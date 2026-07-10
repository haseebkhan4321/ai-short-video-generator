from django.conf import settings
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse

from .forms import VideoCreateForm
from .models import StepStatus, StepType
from .services.pipeline import (
    BudgetExceededError,
    PipelineService,
    StepNotActionableError,
    StepTypeNotImplemented,
)
from .services.video_service import VideoService


def video_list(request):
    videos = VideoService.list_videos()
    return render(request, "videos/list.html", {"videos": videos})


def video_create(request):
    if request.method == "POST":
        form = VideoCreateForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            video = PipelineService.create_video(
                profile=data["profile"],
                premise=data["premise"],
                target_minutes=data["target_minutes"],
            )
            messages.success(
                request,
                "Video created. Review the script step and approve it to begin.",
            )
            return redirect(reverse("videos:detail", args=[video.pk]))
    else:
        form = VideoCreateForm(default_minutes=settings.DEFAULT_TARGET_MINUTES)
    return render(request, "videos/form.html", {"form": form})


def video_detail(request, video_id):
    video = VideoService.get_video(video_id)
    if video is None:
        raise Http404("Video not found")

    chapters = VideoService.chapters_for(video_id)
    steps = VideoService.steps_for(video_id)

    # Group pending paid steps by type so batch approvals can show a combined
    # estimate for fan-out stages (images, narration).
    pending_by_type = {}
    for step in steps:
        if step.status == StepStatus.PENDING_APPROVAL and step.provider != "local":
            bucket = pending_by_type.setdefault(
                step.step_type,
                {"label": step.get_step_type_display(), "count": 0, "estimate": 0},
            )
            bucket["count"] += 1
            bucket["estimate"] += float(step.estimated_cost_usd)

    batchable = {
        k: v for k, v in pending_by_type.items() if v["count"] > 1
    }

    return render(
        request,
        "videos/detail.html",
        {
            "video": video,
            "chapters": chapters,
            "steps": steps,
            "batchable": batchable,
            "budget_cap": PipelineService.budget_cap(),
        },
    )


def _get_step_or_404(step_id):
    try:
        return VideoService.get_step(step_id)
    except Exception:
        raise Http404("Step not found")


def step_approve(request, video_id, step_id):
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    step = _get_step_or_404(step_id)
    force = request.POST.get("force") == "1"
    try:
        PipelineService.approve_step(step, force=force)
        messages.success(request, f"Approved: {step.get_step_type_display()}.")
    except BudgetExceededError as exc:
        messages.warning(request, str(exc) + " Use 'Approve anyway' to override.")
    except StepTypeNotImplemented as exc:
        messages.error(request, str(exc))
    except StepNotActionableError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("videos:detail", args=[video_id]))


def step_reject(request, video_id, step_id):
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    step = _get_step_or_404(step_id)
    try:
        PipelineService.reject_step(step)
        messages.success(request, f"Rejected: {step.get_step_type_display()}.")
    except StepNotActionableError as exc:
        messages.error(request, str(exc))
    return redirect(reverse("videos:detail", args=[video_id]))


def step_regenerate(request, video_id, step_id):
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    step = _get_step_or_404(step_id)
    PipelineService.regenerate_step(step)
    messages.success(
        request, f"New pending {step.get_step_type_display()} created for approval."
    )
    return redirect(reverse("videos:detail", args=[video_id]))


def step_batch_approve(request, video_id):
    if request.method != "POST":
        return redirect(reverse("videos:detail", args=[video_id]))
    video = VideoService.get_video(video_id)
    if video is None:
        raise Http404("Video not found")
    step_type = request.POST.get("step_type")
    force = request.POST.get("force") == "1"
    if step_type not in StepType.values:
        messages.error(request, "Unknown step type.")
        return redirect(reverse("videos:detail", args=[video_id]))
    try:
        approved = PipelineService.batch_approve(video, step_type, force=force)
        messages.success(request, f"Approved {len(approved)} step(s).")
    except BudgetExceededError as exc:
        messages.warning(request, str(exc) + " Use 'Approve all anyway' to override.")
    except StepTypeNotImplemented as exc:
        messages.error(request, str(exc))
    return redirect(reverse("videos:detail", args=[video_id]))


def video_delete(request, video_id):
    video = VideoService.get_video(video_id)
    if video is None:
        raise Http404("Video not found")
    if request.method == "POST":
        VideoService.delete_video(video)
        messages.success(request, "Video deleted.")
        return redirect(reverse("videos:list"))
    return render(request, "videos/confirm_delete.html", {"video": video})
