# Access control (RBAC)

Nothing in this app is reachable without signing in, and every query is scoped to
the caller's **active account**. Spending money requires an explicit permission,
and exceeding the budget cap requires a *second*, separate one.

## The pieces

```
User ──────< Membership >────── Account ──< Template ──< Video ──< Chapter ──< ChapterImage
              │                    │                       │
              └── Role             └── Role                └──< GenerationStep ──< ApiCallLog
                  (per account,        (its own roles,
                   permission list)     cloned from the defaults)

AccountRequest ── a visitor asking for an account; approved by a system admin
```

- **Account** is a workspace. It owns templates, and through them every video,
  chapter, image, step and API log. It is the unit of isolation.
- **Membership** grants one user one role in one account. A user with several
  memberships switches between accounts; the active one is held in
  `session["active_account_id"]`.
- **Role** is a named list of permission codenames, scoped to an account and freely
  editable by anyone there with `account.manage_roles`. A role with
  `account=None` is a **system default**, cloned into each new account.
- **User** logs in with an email (there is no username). `is_system_admin` is the
  app-level administrator who approves account requests and runs `/console/`; it is
  separate from `is_staff`/`is_superuser`, which only govern Django's `/admin/`.

`Template` used to be called `Profile`. It was never a user profile — it is a
content identity (niche, style prompt, narrator voice).

## The permission catalog

Codenames are defined **in code**, in
[`apps/accounts/permissions.py`](../apps/accounts/permissions.py). Roles are
defined by users. So the set of possible actions is fixed by the developer while
the set of roles is open-ended.

| Group | Codename | What it allows |
|---|---|---|
| Templates | `template.view` | See templates and their videos |
| | `template.manage` | Create, edit, delete templates (including the style prompt used in paid calls) |
| Videos | `video.view` | Open videos, read scripts, play narration, watch renders |
| | `video.create` | Start a video from a premise (this also queues the first paid script step) |
| | `video.delete` | Delete a video and everything under it |
| Pipeline | `step.run_free` | Run the steps that cost nothing: split, narration, merge, render |
| | `step.approve_paid` | **Authorize real spend** on OpenAI (script, images) |
| | `step.override_budget` | **Exceed `MAX_COST_PER_VIDEO`** |
| | `step.reject` | Reject a step waiting for approval |
| | `step.regenerate` | Retry a failed step, or queue a fresh copy of a completed one |
| Account | `account.manage_users` | Add users to the account, change their role, remove them |
| | `account.manage_roles` | Create roles and choose their permissions |
| | `account.manage_settings` | Rename the account |

Role permissions are stored as a JSON list, so a codename can outlive its removal
from the catalog. `Role.codenames` filters against the catalog on every read, which
means a stale entry grants nothing.

### Seeded default roles

Cloned into every new account, then editable there.

| Role | Permissions |
|---|---|
| **Owner** | Everything |
| **Producer** | Everything except `account.*` and `step.override_budget` — makes videos and approves spend, but cannot exceed the cap or administer the account |
| **Viewer** | `template.view` + `video.view` only |

Edit the defaults at `/console/default-roles/`. Existing accounts keep the copy
they were given; editing only changes what *future* accounts start with.

## Where decisions are made

Every authorization decision funnels through
[`apps/accounts/access.py`](../apps/accounts/access.py):

- `AccountMiddleware` resolves the active account and permission set once per
  request and attaches `request.access`, `request.account`, `request.membership`.
  A missing account is `None`, never an error.
- Views declare what they need: `@requires_perm(Perm.VIDEO_CREATE)`.
  `@account_required` is login + an active account. `@system_admin_required` is for
  `/console/`, which is outside account scope.
- The `access_context` context processor exposes `can` to templates, keyed by
  **underscored** codename (`{% if can.step_approve_paid %}`) because Django
  templates cannot resolve a dotted dictionary key.
- A system admin resolves to the whole catalog and may enter any account.

**Row scoping lives in the repositories**, per the project's layering rule:
`TemplateRepository.for_account`, `VideoRepository.for_account` (which filters
`template__account`, since videos have no account column of their own), and
`StepRepository.get_in_video`. Services take an `account` and return `None` for
anything outside it, so views raise 404. A row in another account is never
distinguishable from one that does not exist.

## The two spend gates

The approval framework was a *cost* gate; RBAC makes it an *authorization* gate
too.

1. `step.approve_paid` is required to approve any step whose provider is not
   `local`. A batch counts as paid if **any** pending step in it is paid.
2. `step.override_budget` is required for `force=1`, which bypasses
   `MAX_COST_PER_VIDEO`. The view never trusts the POST flag on its own:

   ```python
   force = request.POST.get("force") == "1" and has_perm(request, Perm.STEP_OVERRIDE_BUDGET)
   ```

   The "Approve anyway" button only renders when `can.step_override_budget`, and a
   hand-crafted POST from someone without it still hits `BudgetExceededError`.

Who authorized what is recorded: `GenerationStep.approved_by` and
`Video.created_by`. Pipeline steps run in daemon threads with no request, so the
actor is captured at approve time and passed to the service as `actor=`.

Two related hardenings came with this:

- `video_detail` mutates state and can start a background thread
  (`ensure_asset_steps`, `backfill_part_videos`, `resume_waiting_steps`). Those
  calls are gated on `step.run_free`, so a read-only Viewer opening the page cannot
  start the pipeline.
- `GenerationStep.status` is read-only in Django admin. Flipping it there would
  approve a paid step while skipping the budget cap entirely.

## Media is access-controlled

Generated scripts, images, narration and final renders all live under
`media/videos/<video_id>/`, so a plain static handler makes every account's output
readable by anyone who can guess a path. `guarded_serve` in
[`config/media_serve.py`](../config/media_serve.py) requires a login, resolves the
video id out of the path, and 404s anything outside the active account. It stays
range-aware so seeking in long audio and video still works.

The media route is registered **unconditionally**, not under `if DEBUG` — it is no
longer a static file server, and handing media to a web server that skips the check
would undo all of this.

## Getting in

After a fresh `migrate` there is no way in: every page needs a login and every
account is created by an administrator.

```bash
python manage.py seed_production --email you@example.com --account "My Studio"
python manage.py seed_templates --account my-studio
```

`seed_production` is idempotent. It seeds the three default roles, creates the first
system administrator, and gives them an account with an Owner membership.
`--roles-only` seeds just the roles.

For local work, `python manage.py seed_development` does all that plus demo accounts,
a user per role, and a video at every pipeline stage. See
[`seeders.md`](seeders.md).

## Route map

| Route | Gate |
|---|---|
| `/` | public landing page (signed-in users are sent to `/videos/`) |
| `/accounts/login/`, `/accounts/logout/` | public |
| `/accounts/request/` | public — creates an inactive user plus a pending `AccountRequest` |
| `/accounts/me/` | login — own name, password, and the account switcher |
| `/accounts/switch/<id>/` | login, POST only, membership checked |
| `/templates/…` | `template.view` / `template.manage` |
| `/videos/…` | `video.view` / `video.create` / `video.delete` |
| `/videos/<id>/steps/<id>/approve/` | `step.approve_paid` if paid, else `step.run_free` |
| `/videos/<id>/steps/<id>/reject/` | `step.reject` |
| `/videos/<id>/steps/<id>/regenerate/` | `step.regenerate` |
| `/accounts/users/…` | `account.manage_users` |
| `/accounts/roles/…` | `account.manage_roles` |
| `/accounts/settings/` | `account.manage_settings` |
| `/console/…` | `is_system_admin` |
| `/media/…` | login + `video.view` + the video must be in the active account |
| `/admin/` | `is_staff` (Django's own) |

## Invariants

Permission checks say who *may* act. These say what the result may not be, and they
live in the services so they hold whichever view is calling:

- **No privilege escalation** — nobody can grant a permission they do not hold
  themselves. The role form only offers what the editor has, and
  `RoleService._assert_no_escalation` enforces it regardless.
- **Never lock out an account** — the last active user who can manage users cannot
  be removed, deactivated, or moved to a role without that permission; the last
  role holding it cannot have it taken away.
- **The account owner** cannot be removed or deactivated, and must keep a role that
  can manage users.
- **A role in use** cannot be deleted (`Membership.role` is `PROTECT`).
- **The last system administrator** cannot be demoted, and no system admin can
  deactivate themselves.
- **Removing someone** deletes their membership, never their user — they may belong
  to other accounts.

## Account requests

There is no email backend, so the request form collects the password up front:

1. A visitor submits `/accounts/request/`. This creates
   `User(is_active=False)` with the password already hashed, plus a pending
   `AccountRequest`. They cannot sign in yet.
2. A system administrator approves at `/console/requests/`. That flips
   `is_active=True`, creates the account, clones the default roles into it, and adds
   an Owner membership.
3. They sign in with the password they chose. Nothing is handed over out of band.

Rejecting deletes the placeholder user, freeing the email for a future request.

A user created by an account administrator at `/accounts/users/new/` is active
immediately — only public self-service requests need approval. They are flagged
`must_change_password`, which shows a banner until they change it.

## Tests

124 tests, `python manage.py test`, plain `django.test.TestCase` and
`django.test.Client` — no extra dependency.

| Module | Covers |
|---|---|
| `seeders/tests/test_seeders.py` | both seeders: idempotency, the DEBUG guard, `--fresh` scope, fixture invariants |
| `apps/accounts/tests/test_access.py` | permission resolution, system-admin bypass, switching, inactive users and memberships |
| `apps/accounts/tests/test_requests.py` | request → cannot sign in → approve → Owner; rejection; double review |
| `apps/accounts/tests/test_user_management.py` | privilege escalation, last administrator, owner protection, role lifecycle |
| `apps/videos/tests/test_scoping.py` | cross-account 404s on videos, templates, the status endpoint, steps and media files |
| `apps/videos/tests/test_permissions.py` | per-role gating, the two spend gates, `force=1` from an unprivileged caller, viewer-does-not-run-pipeline, `approved_by` audit |

`apps/accounts/tests/factories.py` holds the shared helpers.
