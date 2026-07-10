# AI Story Video Studio

Generates long-form (1 to 2 hour) narrated story videos locally: a full script is
generated, split into parts, each part gets images and ElevenLabs narration, the
narration is merged, and FFmpeg renders one 1920x1080 MP4. Every paid API call is
gated behind an explicit approval with a cost estimate.

See [`docs/phase-1-plan.md`](docs/phase-1-plan.md) for the full plan and
[`docs/chatgpt-conversation-readout.md`](docs/chatgpt-conversation-readout.md) for
the original brief.

## Stack

- Django 5.2 (repository pattern: views -> services -> repositories -> ORM)
- MySQL (Laragon)
- OpenAI (script + images), ElevenLabs (narration), FFmpeg (render, local)
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

# 4. Admin user (optional)
.venv\Scripts\python manage.py createsuperuser

# 5. Run
.venv\Scripts\python manage.py runserver
```

Open http://127.0.0.1:8000/ (redirects to the videos list). Admin at /admin/.

## Layout

```
config/            Django project + split settings (base.py, local.py)
apps/profiles/     Profile model, repository, views
apps/videos/       Video/Chapter/ChapterImage/GenerationStep/ApiCallLog,
                   repositories, services/, integrations/
media/             Generated assets (gitignored)
assets/            Music + fonts (user-supplied)
docs/              Plan + brief
```

## Architecture rules

- **views** call **services** only.
- **services** hold business logic; they use **repositories** for persistence and
  **integrations** for external APIs.
- **repositories** are the only layer that touches the ORM.
- **integrations** are thin provider clients behind interfaces (swappable).

## Build status

- [x] Milestone 1: project skeleton, MySQL, models, migrations, base UI
- [x] Milestone 2: profiles CRUD
- [x] Milestone 3: video + approval framework
- [ ] Milestone 4: script step (OpenAI)
- [ ] Milestone 5: split step
- [ ] Milestone 6: images step (OpenAI)
- [ ] Milestone 7: narration step (ElevenLabs) + merge
- [ ] Milestone 8: render step (FFmpeg)
- [ ] Milestone 9: polish + end-to-end
- [ ] Milestone 10: optional subtitles (local Whisper)
