# Phase 1 Plan: Generate a Long-Form Narrated Video Locally

> **Superseded in two places.** Phase 1 assumed a single anonymous local operator
> and called the content identity a **Profile**. Since then:
>
> - `Profile` is now **`Template`** (`apps/templates`, URLs at `/templates/`). It was
>   never a user profile — it is a content identity.
> - Authentication and multi-tenant RBAC were added on top: **accounts** own
>   templates, roles are defined per account from a fixed permission catalog, and
>   approving spend (`step.approve_paid`) is separate from exceeding the budget cap
>   (`step.override_budget`). See [`rbac.md`](rbac.md).
>
> Read `Profile` as `Template` below, and assume every page requires a login and is
> scoped to the caller's active account.

## What we are building

A **Video** in this system is one **long-form, continuous story (1 to 2 hours)**. The full flow for a single video:

1. Generate the **full 1-2 hour script** (the entire continuous story text).
2. **Split the completed script into parts** (ordered chapters).
3. Generate a few images per part.
4. Generate the narration (TTS) part by part.
5. When the script is fully narrated, **merge the narration parts into one** long audio track and render one full 16:9 video on top of it.

This is the audiobook / "sleep story" / faceless long-form style, **not** 30-60 second Shorts.

Goal of Phase 1: produce one complete long-form MP4 on local disk. Nothing else. **No Docker, no S3/R2, no Redis/Celery, no YouTube upload, no scheduling.**

## Confirmed decisions

| Decision | Choice |
|----------|--------|
| Final format | 16:9 landscape, 1920x1080 |
| Target length | 1 to 2 hours of narration (configurable per video) |
| Story structure | One continuous story split into ordered chapters/parts |
| Visuals | A few images per chapter (default 3-6), each shown for minutes with a slow Ken Burns pan/zoom, crossfaded |
| Narration | Kokoro TTS (local, free), synthesized per part and concatenated. Behind a provider interface. Steps still need a manual start (long job) but cost Rs 0 |
| Subtitles | Optional and OFF by default in Phase 1 (long-form narration videos rarely burn captions; local Whisper can be enabled later) |

## Hard requirements (unchanged)

1. **Django 5.x** using the **repository pattern**: views/services never touch the ORM directly; all queries go through repository classes.
2. **MySQL** (Laragon's local MySQL).
3. **Local storage only**: every asset lives under the project `media/` folder.
4. **Templates**: a Template is a content identity (niche, style/prompt template, default voice). Each Template owns a list of generated videos, and belongs to an Account.
5. **Lifecycle visibility**: the UI shows videos in process plus full detail per video (title, story text per chapter, images, per-step status, costs).
6. **Approval gate before spending money**: every step that calls a paid API (OpenAI script + images) is created as `pending_approval` with an estimated cost and the exact payload. Nothing is sent to a paid API until the user approves. Narration (Kokoro, local) and render (FFmpeg) are free; narration still waits for a manual start because it is a long job, but its estimate is Rs 0.

## Script first, then split

The user's flow is: **write the full script, then split it into parts.** A continuous 1-2 hour story (~9,000 words for 1 hour, ~18,000 for 2 hours at ≈150 words/minute) exceeds a single model response, so the script step generates it in **sequential continuation calls** until the target length is reached, appending each chunk to one growing script. The result is treated as a single completed script.

- **Script step**: repeatedly call OpenAI, each call continuing from where the last left off (passing the running tail for continuity) plus the target word budget, until `total_words` reaches the target. Also produces the title, description, and hashtags. The full text is stored on the Video.
- **Split step**: once the script is complete, split it into ordered parts (chapters) by target duration / natural paragraph breaks (default ~5-8 minutes of narration each). Each part becomes a Chapter row with its slice of the script. This split is a local operation (free) with no external call, though a paid OpenAI pass can optionally refine part boundaries and titles.

Splitting after the script is written keeps the story coherent as one piece, while still giving per-part units for images, narration, and regeneration. The narration parts are later **merged into one** track before rendering.

## Pipeline (Phase 1)

Paid steps marked [$].

```
1. Create Video            user picks a profile, enters a premise/topic and target minutes (e.g. 90)
2. [$] Generate Script     (OpenAI, sequential continuation calls) -> full 1-2 hour script + title,
                           description, hashtags; appended until target word count is reached
3.      Split Into Parts    (local, free) -> ordered chapters, each a slice of the completed script
                           (optional paid OpenAI pass to refine boundaries/titles)
4. [$] Generate Images     (OpenAI Images) -> N images per part (default 3-6), 16:9
5.      Generate Narration  (Kokoro, local/free, one synth per part) -> part_XX.wav
6.      Merge + Measure      (numpy/soundfile, free) -> concatenate part audio into narration.wav,
                            record per-part offsets and total duration
7.      Render Video        (FFmpeg, free) -> final.mp4: per part, its images Ken-Burns-panned across that
                            part's audio span, crossfades between images and parts, ambient background
                            music ducked under narration, 1920x1080
```

Optional (off by default): a subtitles step using local `faster-whisper` producing an SRT and optional burned captions.

## Approval flow

For every paid step:

1. The pipeline service creates a `GenerationStep` row with `status=pending_approval`, the provider, the exact payload (model, prompt, image count, character count), and an **estimated cost in USD**.
2. The video detail page shows the pending step with its estimate and Approve / Reject buttons.
3. On approve, the step runs, moving `approved -> running -> completed` (or `failed`, error stored). Actual usage/cost from the API response is recorded.
4. On reject, the step is `rejected`; the user can edit inputs and create a new step.
5. Every outbound call is also logged to `ApiCallLog` (provider, endpoint, tokens/characters/images, actual cost) so spend per video and per profile is always queryable.

Long-form specifics:

- **Batch approval**: images and narration each fan out per part. The UI offers "approve all images" / "approve all narration" (combined estimate) plus per-part approval, and a per-part "Generate this part" that runs that part's images + narration together. The script step also fans into several continuation calls; its estimate covers the whole target length.
- **Part-by-part or stage-by-stage**: images and narration are both created right after the split (they only depend on the part text), so you can finish one part fully before the next, or run a whole stage at once. Merge + render fire automatically once every part has both.
- **Budget cap**: `MAX_COST_PER_VIDEO_PKR` in settings (shown/added in PKR). Since narration is now local/free, the dominant cost is images; the cap mainly guards the image stage.

Because every paid step waits on a human click, Phase 1 needed **no background queue**: an approved step ran in a daemon thread inside the web process.

> **Superseded.** That thread is gone: approved steps are Celery tasks now, so a
> 40-minute render survives a server restart instead of dying with it. See
> [`queue.md`](queue.md).

## Cost reality for long-form (why the gate matters)

Rough per-video envelope at 90 minutes (~13,500 words / ~80,000 characters):

| Item | Rough cost |
|------|-----------|
| Full script (OpenAI text, continuation calls) | ~$0.30 - 1.50 depending on model |
| Images (say 12 parts x 4 = ~48 images) | ~$1 - 4 (**the dominant cost**) |
| Kokoro narration (local) | free |
| Whisper subtitles (local, optional) | free |
| FFmpeg render | free |

With Kokoro narration and local render, the only paid steps are the OpenAI script and images, so images are the dominant cost and what the budget cap mainly guards.

## Data model (MySQL via Django ORM)

Since RBAC landed, `Template` also has an `account_id` FK, `Video` has `created_by`,
and `GenerationStep` has `approved_by` — see [`rbac.md`](rbac.md) for the
`User` / `Account` / `Role` / `Membership` / `AccountRequest` tables.

```
Template  (was: Profile)
-------
id
account_id           FK -> Account   (added with RBAC; the ownership anchor)
name                 e.g. "Midnight Horror Narrations"
niche                e.g. horror | history | sci-fi | bedtime ...
description
style_prompt         system/style prompt used for story + image generation
narrator_voice       default narrator voice (Kokoro voice, e.g. af_heart)
language             default "en"
created_at / updated_at

Video
-----
id
template_id          FK -> Template  (was profile_id)
created_by_id        FK -> User, nullable (added with RBAC)
premise              user-entered premise/topic for the continuous story
target_minutes       requested length (e.g. 90)
title                nullable until script is generated
script               full continuous script text (the whole 1-2 hour story)
description          long-form description (stored for later phases)
hashtags             JSON list
status               draft | script | split | images | narration |
                     rendering | completed | failed
                     (furthest stage reached)
                     (furthest pipeline stage reached / in progress)
total_words          nullable, filled as the script grows
duration_seconds     nullable, measured after narration concat
narration_audio_path relative path under media/ (concatenated full track)
final_video_path     relative path under media/
total_cost_usd       decimal, sum of actual costs
error_message        nullable
created_at / updated_at

Chapter
-------
id
video_id             FK -> Video
chapter_number       1..N (ordered)
title                short part title (from split step)
body                 this part's slice of the full script (narrated text)
word_count           words in this part
narration_audio_path relative path (part_XX.wav)
audio_start_seconds  offset within the full track (filled after concat)
audio_end_seconds
created_at / updated_at

ChapterImage
------------
id
chapter_id           FK -> Chapter
order                display order within the chapter
image_prompt         full prompt sent to the image model
image_path           relative path under media/
created_at / updated_at

GenerationStep
--------------
id
video_id             FK -> Video
chapter_id           FK -> Chapter, nullable (null = video-level step)
step_type            script | split | images | narration | merge | render | subtitles
provider             openai | local
status               pending_approval | approved | running | completed |
                     failed | rejected
request_payload      JSON (model, prompt, params shown pre-approval)
response_metadata    JSON (usage, ids, timings)
estimated_cost_usd   decimal
actual_cost_usd      decimal, nullable
error_message        nullable
approved_by_id       FK -> User, nullable (added with RBAC; spend audit trail)
approved_at / started_at / finished_at
created_at

ApiCallLog
----------
id
step_id              FK -> GenerationStep
provider / endpoint / model
units                JSON (input_tokens, output_tokens, images, characters)
cost_usd             decimal
duration_ms
created_at
```

## Local storage layout

```
media/
  videos/
    {video_id}/
      parts/
        01/ img_1.png img_2.png ...   part_01.mp3
        02/ img_1.png img_2.png ...   part_02.mp3
        ...
      narration.wav        concatenated full track
      subtitles.srt        optional
      final.mp4
assets/
  music/                   royalty-free ambient tracks (added manually)
  fonts/
```

## Project structure (repository pattern)

```
ai-generated-short-videos/
├── config/                     Django project
│   ├── settings/ base.py, local.py
│   ├── urls.py
│   ├── media_serve.py          login- and account-checked media (added with RBAC)
│   └── wsgi.py
├── apps/
│   ├── accounts/               added with RBAC — see docs/rbac.md
│   │   ├── models.py           User, Account, Role, Membership, AccountRequest
│   │   ├── permissions.py      the fixed permission catalog + default roles
│   │   ├── access.py           middleware, decorators, context processor
│   │   ├── repositories.py / services.py
│   │   ├── views.py            home, login, request, profile, users, roles, settings
│   │   ├── console_views.py    system admin: requests, users, accounts
│   │   └── templates/accounts/
│   ├── templates/              (was: profiles/)
│   │   ├── models.py           Template
│   │   ├── repositories.py     TemplateRepository
│   │   ├── services.py
│   │   ├── views.py            list / create / edit templates
│   │   ├── urls.py
│   │   └── templates/templates/
│   └── videos/
│       ├── models.py           Video, Chapter, ChapterImage, GenerationStep, ApiCallLog
│       ├── repositories.py     VideoRepository, ChapterRepository, StepRepository, ApiCallLogRepository
│       ├── services/
│       │   ├── pipeline.py         orchestrates steps, creates approval requests, advances status
│       │   ├── script_service.py       full-script generation via continuation calls
│       │   ├── split_service.py        split completed script into ordered parts
│       │   ├── image_service.py
│       │   ├── narration_service.py    per-part synth + merge
│       │   ├── render_service.py       FFmpeg timeline builder
│       │   ├── subtitle_service.py     optional, local
│       │   └── cost_estimator.py
│       ├── integrations/
│       │   ├── base.py         LLMProvider / ImageProvider / TTSProvider interfaces
│       │   ├── openai_provider.py
│       │   ├── kokoro_provider.py
│       │   ├── whisper_local.py
│       │   └── ffmpeg_renderer.py
│       ├── views.py            video list, detail, create, approve/reject step, batch approve
│       ├── urls.py
│       └── templates/videos/
├── media/                      generated assets (gitignored)
├── assets/                     music, fonts
├── docs/
├── .env / .env.example
├── requirements.txt
└── manage.py
```

Layering rules:

- **views** call **services** only.
- **services** hold business logic and pipeline orchestration; they talk to **repositories** for persistence and **integrations** for external APIs.
- **repositories** are the only layer that runs ORM queries.
- **integrations** are thin clients behind interfaces, so a TTS provider can be swapped without touching services (Kokoro is used now).

## Tech / dependencies

- Python 3.10+, Django 5.2
- mysqlclient
- openai (official SDK) — text + images
- kokoro-onnx — local narration (bundles espeak-ng via espeakng-loader; no system install)
- numpy + soundfile — audio synth output, part merge, duration measurement
- ffmpeg + ffprobe (invoked via subprocess; path set in .env) — render
- faster-whisper — optional local subtitles (later)
- python-dotenv for `.env`
- Frontend: plain Django templates + light CSS (no SPA in Phase 1)

`.env` keys:

```
SECRET_KEY=
DEBUG=True
DB_NAME=ai_shorts
DB_USER=root
DB_PASSWORD=
DB_HOST=127.0.0.1
DB_PORT=3306
OPENAI_API_KEY=
TTS_PROVIDER=kokoro
DEFAULT_KOKORO_VOICE=af_heart
USD_TO_PKR=280
MAX_COST_PER_VIDEO_PKR=7000
FFMPEG_BINARY=ffmpeg
FFPROBE_BINARY=ffprobe
```

Kokoro model files (`kokoro-v1.0.onnx`, `voices-v1.0.bin`) live under `assets/kokoro/`.

## UI pages (Phase 1, minimal)

All of these now require a login and show only the active account's rows. Action
buttons render only when the caller's role permits them. RBAC also added a public
home page, login and account-request pages, an account switcher, per-account user
and role management, and a system console — see [`rbac.md`](rbac.md).

1. **Templates list / form**: create/edit templates (name, niche, style prompt, narrator voice id).
2. **Template detail**: that template's videos with status badges (in process / completed / failed) and total cost each.
3. **New video**: pick template, enter premise + target minutes; creates a Video in `draft` and the first pending script step.
4. **Video detail** (main screen), top to bottom:
   - Header: title, the template it came from, and a Script -> Render stepper.
   - Target vs actual length, words, total spent and budget cap, plus the premise.
   - Full script (expandable) once generated, with description and hashtags.
   - "Next step": one plain-language instruction plus the action that follows from it.
   - Full narration player and final video player when ready.
   - Parts list after the split, each with its text slice, images, a per-part preview video and audio player, and a per-part "Generate this part" button.
   - Technical details (collapsed): each GenerationStep with status, estimated vs actual cost, who approved it, and Approve / Reject / Regenerate when applicable; plus "approve all images" and "approve all narration" batch actions with combined estimates.

   The spend numbers and the script sit *above* the action panel deliberately: what a
   video has already cost and what it says are what you need before approving more.

## Milestones / build order

| # | Milestone | Contents |
|---|-----------|----------|
| 1 | Skeleton | Django project, MySQL connection, apps, base templates, .env, models + migrations, gitignore, README |
| 2 | Profiles | Model, repository, CRUD views |
| 3 | Video + approval framework | Video/Chapter/ChapterImage/GenerationStep/ApiCallLog, pipeline service, approval + batch-approval UI, cost estimator, budget cap |
| 4 | Script step | OpenAI continuation calls -> full 1-2 hour script + title, description, hashtags; length driven by target minutes; stored on Video |
| 5 | Split step | Split completed script into ordered parts (local, free) by target duration / natural breaks; create Chapter rows |
| 6 | Images step | OpenAI Images, N per part, 16:9, saved to media, shown per part |
| 7 | Narration step | Kokoro (local) per part -> part_XX.wav, merge -> narration.wav, per-part offsets via sample counts |
| 8 | Render step | FFmpeg: per part, its images Ken-Burns-panned across that part's audio span, crossfades, ambient music ducked under narration, 1920x1080 final.mp4 |
| 9 | Polish | Status badges, error surfacing, regenerate buttons, per-template cost totals, end-to-end run of one full long-form video |
| 10 | Optional subtitles | Local faster-whisper SRT + optional burned captions (off by default) |

Milestone 10 as built: a free `subtitles` step between merge and render, transcribing
the merged narration with faster-whisper and writing `media/videos/<id>/subtitles.srt`.
`SUBTITLES_ENABLED` inserts the step; `BURN_SUBTITLES` additionally draws the captions
into the video, which costs one extra re-encode of the silent cut. Transcribed rather
than derived from the script, because only the audio carries timings — a caption track
built from the script would drift wherever the TTS chunked a sentence differently.

Definition of done for Phase 1: from a premise + target minutes, a user approves the paid steps (script, images), generates narration (free, Kokoro) part-by-part or in batch, and the narration is merged and rendered into a watchable 1-2 hour `final.mp4` on disk, with every paid step pre-approved and costs shown in PKR.

## Later phases (recorded for direction, not now)

- **Phase 2**: thumbnail generation, YouTube Data API upload with OAuth, ~~Celery + Redis so long narration/render run in a real queue~~ (**done** — see [`queue.md`](queue.md)), ~~full-pipeline budget approval up front~~ (**done** — see [`budget.md`](budget.md)).
- **Phase 3**: scheduling, multiple videos per profile, analytics, Docker Compose, object storage (S3/R2), cheaper/local image models (e.g. Flux), optional premium TTS or AI video clips, cross-posting.
