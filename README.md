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
[`docs/rbac.md`](docs/rbac.md) for the access-control model,
[`docs/seeders.md`](docs/seeders.md) for the seeders, and
[`docs/chatgpt-conversation-readout.md`](docs/chatgpt-conversation-readout.md) for
the original brief.

## Stack

- Django 5.2 (repository pattern: views -> services -> repositories -> ORM)
- MySQL (Laragon)
- OpenAI (script + images), Kokoro TTS (narration, local/free), FFmpeg (render, local)
- faster-whisper for optional subtitles (local/free, `SUBTITLES_ENABLED=False` by default)
- Custom `accounts.User` (email login), account-scoped roles, no third-party auth package
- Celery + Redis: approved steps run in a worker, not the web process
- Local storage only (no Docker, S3, or YouTube upload yet)

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

# 4. Seed. Required — every page needs a login, so this is the only way in.
#    Development: demo accounts, a user per role, and a video at every pipeline stage
.venv\Scripts\python manage.py seed_development
#    Production: default roles + the first system administrator, no demo data
.venv\Scripts\python manage.py seed_production --email you@example.com --account "My Studio"

# 5. Run. Three processes: Redis, a Celery worker, and the site.
#    Approved steps run in the worker, so without it they queue and sit there.
redis-server
.venv\Scripts\celery -A config worker -l info --pool=threads --concurrency=4
.venv\Scripts\python manage.py runserver

#    Whether the queue is actually working:
.venv\Scripts\python manage.py queue_status
```

Open http://127.0.0.1:8000/ for the public landing page, then sign in at
`/accounts/login/`. System console at `/console/`, Django admin at `/admin/`.

On Windows the default Celery prefork pool does not work — use `--pool=threads`.
See [`docs/queue.md`](docs/queue.md).

`seed_development` prints the accounts it created and their shared password. Both
seeders are idempotent; `seed_development --fresh` rebuilds its own demo data. Add
throwaway videos of any size with
`seed_test_video --account <slug> --parts 14 --words 950`. See
[`docs/seeders.md`](docs/seeders.md) and [`docs/rbac.md`](docs/rbac.md).

For local work, set `DEV_LOGIN_ENABLED=True` in `.env` to get one-click sign-in
buttons for the seeded `@dev.local` users on the sign-in page. It is ignored unless
`DEBUG` is also true, and can only ever sign you in as a user at that throwaway
domain.

## Layout

```
config/            Django project + split settings (base.py, local.py),
                   celery.py (the task queue),
                   media_serve.py (login- and account-checked media)
apps/accounts/     User/Account/Role/Membership/AccountRequest, the permission
                   catalog, access.py (middleware, decorators, context), console
apps/templates/    Template model (the content identity, formerly Profile)
apps/videos/       Video/Chapter/ChapterImage/GenerationStep/ApiCallLog,
                   repositories, services/, integrations/
seeders/           Production + development seeders and their commands
media/             Generated assets (gitignored)
assets/            Music + fonts (user-supplied)
docs/              Plan, RBAC model, seeders, brief
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

246 tests covering permission resolution, account isolation, the two spend gates, the
account-request flow, the seeders, the development sign-in guards, subtitles, the
task queue, and up-front budget approval. Plain `django.test.TestCase` — no extra dependency.

## Build status

- [x] Milestone 1: project skeleton, MySQL, models, migrations, base UI
- [x] Milestone 2: templates CRUD (formerly "profiles")
- [x] Milestone 3: video + approval framework
- [x] Milestone 4: script step (OpenAI)
- [x] Milestone 5: split step
- [x] Milestone 6: images step (OpenAI)
- [x] Milestone 7: narration step (Kokoro, local/free) + merge
- [x] Milestone 8: render step (FFmpeg)
- [x] Milestone 9: polish + end-to-end
- [x] Milestone 10: optional subtitles (local Whisper, off by default)

Added after Phase 1: authentication and multi-tenant RBAC — accounts, custom roles,
account switching, account requests with system-admin approval, and access-controlled
media. See [`docs/rbac.md`](docs/rbac.md).

Phase 2 progress:

- [x] Celery + Redis: approved steps run in a worker ([`docs/queue.md`](docs/queue.md))
- [x] Up-front budget approval for a whole video ([`docs/budget.md`](docs/budget.md))
- [ ] Thumbnail generation
- [ ] YouTube Data API upload with OAuth
