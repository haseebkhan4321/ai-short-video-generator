# AI Story Video Studio

Generates long-form (1 to 2 hour) narrated story videos locally: a full script is
generated, split into parts, each part gets images and Kokoro narration, the
narration is merged, and FFmpeg renders one 1920x1080 MP4. Every paid API call is
gated behind an explicit approval with a cost estimate.

Multi-tenant with role-based access control: **accounts** own the content, each
account defines its own **roles** from a fixed permission catalog, and users switch
between the accounts they hold a role in. Approving spend and exceeding the budget
cap are separate permissions.

See [`docs/phase-1-plan.md`](docs/phase-1-plan.md) for the full plan,
[`docs/rbac.md`](docs/rbac.md) for the access-control model, and
[`docs/chatgpt-conversation-readout.md`](docs/chatgpt-conversation-readout.md) for
the original brief.

## Stack

- Django 5.2 (repository pattern: views -> services -> repositories -> ORM)
- MySQL (Laragon)
- OpenAI (script + images), Kokoro TTS (narration, local/free), FFmpeg (render, local)
- Custom `accounts.User` (email login), account-scoped roles, no third-party auth package
- Local storage only in Phase 1 (no Docker, S3, Celery, or YouTube upload)

## Setup

```bash
# 1. Virtual env + deps
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 2. Config
copy .env.example .env       # then edit values (API keys optional until you generate)

# 3. Database (MySQL must be running)
#    Create the database once:
#    mysql -u root -e "CREATE DATABASE ai_shorts CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
.venv\Scripts\python manage.py migrate

# 4. First system administrator + their account (required — every page needs a login)
.venv\Scripts\python manage.py bootstrap_rbac --email you@example.com --account "My Studio"

# 5. Starter templates for that account (optional)
.venv\Scripts\python manage.py seed_templates --account my-studio

# 6. Run
.venv\Scripts\python manage.py runserver
```

Open http://127.0.0.1:8000/ for the public landing page, then sign in at
`/accounts/login/`. System console at `/console/`, Django admin at `/admin/`.

`bootstrap_rbac` is idempotent and is the only way in after a fresh `migrate`:
nothing is reachable anonymously and accounts are created by an administrator. See
[`docs/rbac.md`](docs/rbac.md).

## Layout

```
config/            Django project + split settings (base.py, local.py),
                   media_serve.py (login- and account-checked media)
apps/accounts/     User/Account/Role/Membership/AccountRequest, the permission
                   catalog, access.py (middleware, decorators, context), console
apps/templates/    Template model (the content identity, formerly Profile)
apps/videos/       Video/Chapter/ChapterImage/GenerationStep/ApiCallLog,
                   repositories, services/, integrations/
media/             Generated assets (gitignored)
assets/            Music + fonts (user-supplied)
docs/              Plan, RBAC model, brief
```

## Architecture rules

- **views** call **services** only, and declare what they need with
  `@requires_perm(Perm.X)`.
- **services** hold business logic and the RBAC invariants; they use
  **repositories** for persistence and **integrations** for external APIs.
- **repositories** are the only layer that touches the ORM, and therefore the only
  place account scoping is applied (`for_account`, `get_in_account`).
- **integrations** are thin provider clients behind interfaces (swappable).
- Authorization decisions happen in one place: `apps/accounts/access.py`.

## Tests

```bash
.venv\Scripts\python manage.py test
```

88 tests covering permission resolution, account isolation, the two spend gates, and
the account-request flow. Plain `django.test.TestCase` — no extra dependency.

## Build status

- [x] Milestone 1: project skeleton, MySQL, models, migrations, base UI
- [x] Milestone 2: templates CRUD (formerly "profiles")
- [x] Milestone 3: video + approval framework
- [x] Milestone 4: script step (OpenAI)
- [x] Milestone 5: split step
- [x] Milestone 6: images step (OpenAI)
- [x] Milestone 7: narration step (Kokoro, local/free) + merge
- [x] Milestone 8: render step (FFmpeg)
- [ ] Milestone 9: polish + end-to-end
- [ ] Milestone 10: optional subtitles (local Whisper)

Added after Phase 1: authentication and multi-tenant RBAC — accounts, custom roles,
account switching, account requests with system-admin approval, and access-controlled
media. See [`docs/rbac.md`](docs/rbac.md).
