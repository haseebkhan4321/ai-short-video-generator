from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse

from apps.accounts.access import Perm, account_required, has_perm, requires_perm
from apps.accounts.permissions import LABELS as PERM_LABELS

from .forms import VideoCreateForm
from .models import StepStatus, StepType, VideoStatus
from .services.currency import format_usd_as_pkr, pkr_to_usd
from .services.pipeline import (
    BudgetExceededError,
    PipelineError,
    PipelineService,
    QueueUnavailableError,
    StepNotActionableError,
    StepTypeNotImplemented,
)
from .services.video_service import VideoService

ACTIVE_STEP_STATUSES = {StepStatus.APPROVED, StepStatus.RUNNING}


def _get_video_or_404(request, video_id):
    """Account-scoped video lookup.

    A video in another account raises 404 rather than 403, so its existence is not
    observable from outside the account.
    """
    video = VideoService.get_video(video_id, request.account)
    if video is None:
        raise Http404("Video not found")
    return video


def _get_step_or_404(request, video_id, step_id):
    """Resolve a step through both its video and the active account.

    The step id alone is not enough: without the ``video_id`` check the path
    segment would be decorative and any step in any account would resolve.
    """
    video = _get_video_or_404(request, video_id)
    step = VideoService.get_step(step_id, video.pk)
    if step is None:
        raise Http404("Step not found")
    return video, step


def _approval_perm_for(step):
    """Paid steps need the spend permission; free ones only need to be runnable."""
    return Perm.STEP_APPROVE_PAID if step.is_paid else Perm.STEP_RUN_FREE


def _batch_perm(pending_steps):
    """The permission a batch needs: the spend one if any step in it costs money."""
    if any(step.is_paid for step in pending_steps):
        return Perm.STEP_APPROVE_PAID
    return Perm.STEP_RUN_FREE


def _may_approve_paid(request, is_paid):
    return has_perm(request, Perm.STEP_APPROVE_PAID if is_paid
                    else Perm.STEP_RUN_FREE)


def _may_approve(request, pending_steps):
    if not pending_steps:
        return False
    return has_perm(request, _batch_perm(pending_steps))


def _require(request, codename):
    if not has_perm(request, codename):
        raise PermissionDenied(
            f"You do not have permission to do this ({PERM_LABELS.get(codename, codename)})."
        )


def _budget_hint(request, exc, override_label):
    """Only mention the override to someone who actually has it."""
    if has_perm(request, Perm.STEP_OVERRIDE_BUDGET):
        return f"{exc} Use '{override_label}' to override."
    return f"{exc} Ask someone who can override the budget cap."


def _allowed_force(request):
    """Honour ``force=1`` only for someone who may exceed the budget cap.

    The flag arrives in POST data, so it is a request, not a fact. Trusting it
    directly is what let any caller bypass MAX_COST_PER_VIDEO.
    """
    return (
        request.POST.get("force") == "1"
        and has_perm(request, Perm.STEP_OVERRIDE_BUDGET)
    )


@requires_perm(Perm.VIDEO_VIEW)
def video_list(request):
    videos = VideoService.list_videos(request.account)
    return render(request, "videos/list.html", {"videos": videos})


@requires_perm(Perm.VIDEO_CREATE)
def video_create(request):
    if request.method == "POST":
        form = VideoCreateForm(request.POST, account=request.account)
        if form.is_valid():
            data = form.cleaned_data
            video = PipelineService.create_video(
                template=data["template"],
                premise=data["premise"],
                target_minutes=data["target_minutes"],
                actor=request.user,
            )
            messages.success(
                request,
                "Video created. Review the script step and approve it to begin.",
            )
            return redirect(reverse("videos:detail", args=[video.pk]))
    else:
        form = VideoCreateForm(
            account=request.account, default_minutes=settings.DEFAULT_TARGET_MINUTES
        )
    return render(request, "videos/form.html", {"form": form})


def _collapse_latest(raw_steps):
    """Keep only the most recent step per (step_type, chapter) so retries don't
    pile up as extra rows."""
    latest = {}
    for step in raw_steps:
        latest[(step.step_type, step.chapter_id)] = step
    return sorted(latest.values(), key=lambda s: s.created_at)


def _step_label(step):
    """Human label for a step, e.g. 'Images (part 3)' or 'Render'."""
    label = step.get_step_type_display()
    if step.chapter_id and step.chapter:
        label += f" (part {step.chapter.chapter_number})"
    return label


STAGE_DEFS = [
    ("script", "Script"),
    ("split", "Split"),
    ("images", "Images"),
    ("narration", "Narration"),
    ("render", "Render"),
]


def _compute_stages(video, chapters, steps):
    """Build a stepper (Script -> Render) from what the video actually has, so the
    header shows pipeline progress instead of one verbose status label."""
    image_steps = [s for s in steps if s.step_type == StepType.IMAGES]
    narration_steps = [s for s in steps if s.step_type == StepType.NARRATION]

    done_flags = {
        "script": bool(video.script),
        "split": len(chapters) > 0,
        "images": bool(image_steps)
        and all(s.status == StepStatus.COMPLETED for s in image_steps),
        "narration": bool(narration_steps)
        and all(s.status == StepStatus.COMPLETED for s in narration_steps),
        "render": bool(video.final_video_path),
    }

    # First stage that isn't done is the "current" one.
    current_key = next((k for k, _ in STAGE_DEFS if not done_flags[k]), None)
    is_failed = video.status == "failed"

    stages = []
    for key, label in STAGE_DEFS:
        if done_flags[key]:
            state = "done"
        elif key == current_key:
            state = "failed" if is_failed else "current"
        else:
            state = "todo"
        stages.append({"label": label, "state": state})
    return stages


def _pending_actions(parts):
    """Batch actions the user can take right now, each tagged free/paid + cost.
    Images are paid; narration is free (local)."""
    img = [p for p in parts if p["image_step"]
           and p["image_step"].status == StepStatus.PENDING_APPROVAL]
    narr = [p for p in parts if p["narration_step"]
            and p["narration_step"].status == StepStatus.PENDING_APPROVAL]
    actions = []
    if img:
        actions.append({
            "step_type": StepType.IMAGES,
            "label": f"Generate all images ({len(img)} part{'s' if len(img) != 1 else ''})",
            "paid": True,
            "cost": sum((Decimal(p["image_step"].estimated_cost_usd) for p in img), Decimal("0")),
        })
    if narr:
        actions.append({
            "step_type": StepType.NARRATION,
            "label": f"Generate all narration ({len(narr)} part{'s' if len(narr) != 1 else ''})",
            "paid": False,
            "cost": Decimal("0"),
        })
    return actions


def _compute_next_step(video, parts, steps, has_active, actions):
    """A single, plain-language 'what to do next' for the top of the page."""
    if video.status == VideoStatus.FAILED:
        return {"tone": "error", "title": "A step failed",
                "detail": video.error_message
                or "Retry the failed step from its part below, or in Technical details."}
    if video.status == VideoStatus.COMPLETED and video.final_video_path:
        return {"tone": "done", "title": "Your video is ready",
                "detail": "The full video has finished rendering — it's at the top of the page."}

    script_step = next((s for s in steps if s.step_type == StepType.SCRIPT), None)
    if script_step and script_step.status == StepStatus.PENDING_APPROVAL:
        return {"tone": "action", "title": "Approve the script to begin",
                "detail": "This writes the full narration script from your premise. Paid step.",
                "primary": {"url": reverse("videos:step_approve", args=[video.pk, script_step.pk]),
                            "label": "Approve script", "paid": True,
                            "cost": script_step.estimated_cost_usd}}
    if not video.script:
        return {"tone": "wait", "title": "Writing the script…",
                "detail": "This runs automatically and updates live below."}

    paid = [a for a in actions if a["paid"]]
    if paid:
        n = f"{len([p for p in parts if p['image_step'] and p['image_step'].status == StepStatus.PENDING_APPROVAL])}"
        return {"tone": "action", "title": f"Generate images for {n} part(s)",
                "detail": "Images are the only paid step here — narration and all rendering are free. "
                          "Use the buttons below, or do one part at a time in its card."}
    if actions:  # only free narration left
        return {"tone": "action", "title": "Generate narration",
                "detail": "Narration is free (runs locally). Use the button below, or do one part at a time."}
    if has_active:
        return {"tone": "wait", "title": "Working…",
                "detail": "A step is running automatically. Progress shows live below."}
    return {"tone": "wait", "title": "Finishing up…",
            "detail": "All parts are done. Merging and the final render run automatically."}


@requires_perm(Perm.VIDEO_VIEW)
def video_detail(request, video_id):
    video = _get_video_or_404(request, video_id)

    # These mutate state and can start work in a background thread, so they are
    # gated: opening the page as a read-only viewer must not run the pipeline.
    if has_perm(request, Perm.STEP_RUN_FREE):
        # Backfill any missing per-part steps (old splits / part-by-part flow), then
        # kick any step left waiting (e.g. a free step whose executor now exists).
        PipelineService.ensure_asset_steps(video)
        # Create any missing part-preview steps first, then let resume_waiting_steps
        # be the single runner that claims and executes all APPROVED steps.
        PipelineService.backfill_part_videos(video)
        PipelineService.resume_waiting_steps(video)

    chapters = VideoService.chapters_for(video_id)
    steps = _collapse_latest(list(VideoService.steps_for(video_id)))
    for step in steps:
        # Annotated for the technical-details table: which permission a step needs
        # depends on whether it is paid, so resolve it here rather than in HTML.
        step.may_approve = _may_approve_paid(request, step.is_paid)

    # Per-part step map for the Parts UI (images + narration live under a part).
    steps_by_chapter = {}
    for s in steps:
        if s.chapter_id:
            steps_by_chapter.setdefault(s.chapter_id, {})[s.step_type] = s
    parts = []
    for ch in chapters:
        cs = steps_by_chapter.get(ch.pk, {})
        image_step = cs.get(StepType.IMAGES)
        narration_step = cs.get(StepType.NARRATION)
        pending = [
            x for x in (image_step, narration_step)
            if x and x.status == StepStatus.PENDING_APPROVAL
        ]
        parts.append({
            "chapter": ch,
            "image_step": image_step,
            "narration_step": narration_step,
            "render_step": cs.get(StepType.RENDER_PART),
            "pending_estimate": sum(float(x.estimated_cost_usd) for x in pending),
            "pending_count": len(pending),
            # A part's button spends money if any of its pending steps is paid.
            "may_approve": _may_approve(request, pending),
        })

    has_active = any(s.status in ACTIVE_STEP_STATUSES for s in steps)
    actions = _pending_actions(parts)
    next_step = _compute_next_step(video, parts, steps, has_active, actions)
    # Decide button visibility here rather than in the template: whether an action
    # is allowed depends on whether it is paid, which the template shouldn't reason
    # about.
    for action in actions:
        action["allowed"] = _may_approve_paid(request, action["paid"])
    if next_step.get("primary"):
        next_step["primary"]["allowed"] = _may_approve_paid(
            request, next_step["primary"]["paid"]
        )
    signature = "|".join(f"{s.pk}:{s.status}" for s in steps)

    return render(
        request,
        "videos/detail.html",
        {
            "video": video,
            "chapters": chapters,
            "steps": steps,
            "actions": actions,
            "next_step": next_step,
            "budget_cap": PipelineService.budget_cap(),
            "projection": PipelineService.project_cost(video),
            "budget_headroom": PipelineService.budget_headroom(video),
            "budget_committed": PipelineService.budget_committed(video),
            "has_active": has_active,
            "initial_signature": signature,
            "stages": _compute_stages(video, list(chapters), steps),
            "parts": parts,
        },
    )


@requires_perm(Perm.VIDEO_VIEW)
def video_status(request, video_id):
    """Lightweight JSON for the detail page to poll while steps run."""
    video = _get_video_or_404(request, video_id)
    steps = _collapse_latest(list(VideoService.steps_for(video_id)))
    payload = {
        "video_status": video.status,
        "video_status_display": video.get_status_display(),
        "active": any(s.status in ACTIVE_STEP_STATUSES for s in steps),
        # signature changes whenever a status changes or a step is added/removed
        "signature": "|".join(f"{s.pk}:{s.status}" for s in steps),
        "steps": [
            {
                "id": s.pk,
                "label": _step_label(s),
                "status": s.status,
                "status_display": s.get_status_display(),
                "progress_current": s.progress_current,
                "progress_total": s.progress_total,
                "progress_message": s.progress_message,
            }
            for s in steps
        ],
    }
    return JsonResponse(payload)


@account_required
def step_approve(request, video_id, step_id):
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    video, step = _get_step_or_404(request, video_id, step_id)
    _require(request, _approval_perm_for(step))
    try:
        PipelineService.approve_step_background(
            step, force=_allowed_force(request), actor=request.user
        )
        messages.success(
            request, f"Approved: {step.get_step_type_display()} — queued."
        )
    except BudgetExceededError as exc:
        messages.warning(request, _budget_hint(request, exc, "Approve anyway"))
    except QueueUnavailableError as exc:
        # The step stays approved, so it starts on its own once the queue is back.
        messages.error(request, f"{exc} It stays approved and will start once it is.")
    except StepTypeNotImplemented as exc:
        messages.error(request, str(exc))
    except StepNotActionableError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("videos:detail", args=[video_id]))


@requires_perm(Perm.STEP_REJECT)
def step_reject(request, video_id, step_id):
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    video, step = _get_step_or_404(request, video_id, step_id)
    try:
        PipelineService.reject_step(step)
        messages.success(request, f"Rejected: {step.get_step_type_display()}.")
    except StepNotActionableError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("videos:detail", args=[video_id]))


@requires_perm(Perm.STEP_REGENERATE)
def step_regenerate(request, video_id, step_id):
    """Regenerate a step. A failed/rejected step is reset in place; a completed one
    gets a fresh pending copy (so the finished output stays until re-approved)."""
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    video, step = _get_step_or_404(request, video_id, step_id)
    try:
        if step.status == StepStatus.COMPLETED:
            PipelineService.regenerate_step(step)
        else:
            PipelineService.retry_step(step)
        messages.success(
            request,
            f"{step.get_step_type_display()} reset to pending — review and approve.",
        )
    except StepNotActionableError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("videos:detail", args=[video_id]))


@account_required
def part_approve(request, video_id, chapter_id):
    """Approve + run all pending steps for one part (its images and narration)."""
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    video = _get_video_or_404(request, video_id)
    _require(
        request,
        _batch_perm(VideoService.pending_steps(video.pk, chapter_id=chapter_id)),
    )
    try:
        approved = PipelineService.approve_chapter_background(
            video, chapter_id, force=_allowed_force(request), actor=request.user
        )
        if approved:
            messages.success(
                request, f"Queued this part ({len(approved)} step(s))."
            )
        else:
            messages.info(request, "Nothing pending for this part.")
    except BudgetExceededError as exc:
        messages.warning(request, _budget_hint(request, exc, "Generate anyway"))
    except QueueUnavailableError as exc:
        messages.error(request, f"{exc} They stay approved and will start once it is.")
    except StepTypeNotImplemented as exc:
        messages.error(request, str(exc))
    return redirect(reverse("videos:detail", args=[video_id]))


@account_required
def step_batch_approve(request, video_id):
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    video = _get_video_or_404(request, video_id)
    step_type = request.POST.get("step_type")
    if step_type not in StepType.values:
        messages.error(request, "Unknown step type.")
        return redirect(reverse("videos:detail", args=[video_id]))
    _require(
        request,
        _batch_perm(VideoService.pending_steps(video.pk, step_type=step_type)),
    )
    try:
        approved = PipelineService.batch_approve_background(
            video, step_type, force=_allowed_force(request), actor=request.user
        )
        messages.success(request, f"Approved and queued {len(approved)} step(s).")
    except BudgetExceededError as exc:
        messages.warning(request, _budget_hint(request, exc, "Approve all anyway"))
    except QueueUnavailableError as exc:
        messages.error(request, f"{exc} They stay approved and will start once it is.")
    except StepTypeNotImplemented as exc:
        messages.error(request, str(exc))
    return redirect(reverse("videos:detail", args=[video_id]))


@requires_perm(Perm.STEP_APPROVE_BUDGET)
def budget_approve(request, video_id):
    """Authorize a whole video's projected spend at once, then start what fits.

    Its own permission rather than reusing ``step.approve_paid``: approving one step
    whose cost is on screen and pre-authorizing everything are different levels of
    trust, the same way overriding the cap is.
    """
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    video = _get_video_or_404(request, video_id)

    projection = PipelineService.project_cost(video)
    amount = _submitted_amount(request) or projection["total_usd"]
    try:
        released = PipelineService.approve_budget(
            video, amount, actor=request.user, force=_allowed_force(request)
        )
        messages.success(
            request,
            f"Authorized {format_usd_as_pkr(amount)} for this video"
            + (f" — started {len(released)} step(s)." if released
               else " — nothing was waiting to start."),
        )
    except BudgetExceededError as exc:
        messages.warning(request, _budget_hint(request, exc, "Approve anyway"))
    except QueueUnavailableError as exc:
        messages.error(request, f"{exc} The steps stay approved and will start once it is.")
    except PipelineError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("videos:detail", args=[video_id]))


@requires_perm(Perm.STEP_APPROVE_BUDGET)
def budget_revoke(request, video_id):
    """Withdraw the up-front approval. Anything already queued stays queued."""
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    video = _get_video_or_404(request, video_id)
    PipelineService.revoke_budget(video)
    messages.success(
        request,
        "Up-front approval withdrawn. Steps that have not started will wait for "
        "approval again; anything already queued keeps running.",
    )
    return redirect(reverse("videos:detail", args=[video_id]))


def _submitted_amount(request):
    """A PKR amount typed into the form, converted to USD. None when left blank."""
    raw = (request.POST.get("amount_pkr") or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        return pkr_to_usd(Decimal(raw))
    except (InvalidOperation, ValueError):
        return None


@requires_perm(Perm.VIDEO_DELETE)
def video_delete(request, video_id):
    video = _get_video_or_404(request, video_id)
    if request.method == "POST":
        VideoService.delete_video(video)
        messages.success(request, "Video deleted.")
        return redirect(reverse("videos:list"))
    return render(request, "videos/confirm_delete.html", {"video": video})
