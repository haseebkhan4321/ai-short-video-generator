# Phase 1 Plan: Generate a Long-Form Narrated Video Locally

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
| Narration | ElevenLabs, synthesized per chapter, concatenated; cost approved per chapter or per batch (behind a provider interface so it can be swapped) |
| Subtitles | Optional and OFF by default in Phase 1 (long-form narration videos rarely burn captions; local Whisper can be enabled later) |

## Hard requirements (unchanged)

1. **Django 5.x** using the **repository pattern**: views/services never touch the ORM directly; all queries go through repository classes.
2. **MySQL** (Laragon's local MySQL).
3. **Local storage only**: every asset lives under the project `media/` folder.
4. **Profiles**: a Profile is a content identity (niche, style/prompt template, default voice). Each Profile owns a list of generated videos.
5. **Lifecycle visibility**: the UI shows videos in process plus full detail per video (title, story text per chapter, images, per-step status, costs).
6. **Approval gate before spending money**: every step that calls a paid API (OpenAI, ElevenLabs) is created as `pending_approval` with an estimated cost and the exact payload. Nothing is sent to a paid API until the user approves. Free/local steps (FFmpeg render, optional local Whisper) run without approval.

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
5. [$] Generate Narration  (ElevenLabs, one synth per part) -> part_XX.mp3
6.      Merge + Measure      (FFmpeg/ffprobe, free) -> concatenate part audio into narration.mp3,
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

- **Batch approval**: because images (step 4) and narration (step 5) each fan out into many per-part calls, the UI offers a single "approve all images" / "approve all narration" action showing the **combined** estimate, in addition to per-part approval. The script step (step 2) also fans into several continuation calls; its estimate covers the whole target length. Nothing runs until approved.
- **Budget cap**: `MAX_COST_PER_VIDEO_USD` in settings. The approval screen warns (and can block) when an approval would push the video's total over the cap. This matters most for narration, since 1-2 hours of ElevenLabs is the dominant cost.

Because every paid step waits on a human click, Phase 1 needs **no background queue**: an approved step runs synchronously (long steps like full narration/render run via a management command or a long-timeout request). Celery arrives in a later phase.

## Cost reality for long-form (why the gate matters)

Rough per-video envelope at 90 minutes (~13,500 words / ~80,000 characters):

| Item | Rough cost |
|------|-----------|
| Full script (OpenAI text, continuation calls) | ~$0.30 - 1.50 depending on model |
| Images (say 12 parts x 4 = ~48 images) | ~$1 - 4 |
| ElevenLabs narration (~80k chars) | **the big one — potentially $10s** depending on plan/tier |
| Whisper subtitles (local, optional) | free |
| FFmpeg render | free |

Narration dominates, so the plan treats it as the step that most needs explicit, budget-aware approval. A local-TTS provider can be dropped in behind the same interface later to cut this dramatically.

## Data model (MySQL via Django ORM)

```
Profile
-------
id
name                 e.g. "Midnight Horror Narrations"
niche                e.g. horror | history | sci-fi | bedtime ...
description
style_prompt         system/style prompt used for story + image generation
elevenlabs_voice_id  default narrator voice
language             default "en"
created_at / updated_at

Video
-----
id
profile_id           FK -> Profile
premise              user-entered premise/topic for the continuous story
target_minutes       requested length (e.g. 90)
title                nullable until script is generated
script               full continuous script text (the whole 1-2 hour story)
description          long-form description (stored for later phases)
hashtags             JSON list
status               draft | script | split | images | narration |
                     rendering | completed | failed
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
narration_audio_path relative path (part_XX.mp3)
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
step_type            script | split | images | narration | render | subtitles
provider             openai | elevenlabs | local
status               pending_approval | approved | running | completed |
                     failed | rejected
request_payload      JSON (model, prompt, params shown pre-approval)
response_metadata    JSON (usage, ids, timings)
estimated_cost_usd   decimal
actual_cost_usd      decimal, nullable
error_message        nullable
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
      narration.mp3        concatenated full track
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
│   └── wsgi.py
├── apps/
│   ├── profiles/
│   │   ├── models.py
│   │   ├── repositories.py     ProfileRepository
│   │   ├── services.py
│   │   ├── views.py            list / create / edit profiles
│   │   ├── urls.py
│   │   └── templates/profiles/
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
│       │   ├── elevenlabs_provider.py
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
- **integrations** are thin clients behind interfaces, so a provider (e.g. local TTS instead of ElevenLabs) can be swapped without touching services.

## Tech / dependencies

- Python 3.12+, Django 5.x
- mysqlclient
- openai (official SDK) — text + images
- elevenlabs (official SDK) — narration
- faster-whisper — optional local subtitles
- ffmpeg + ffprobe on PATH (invoked via subprocess) — concat, timing, render
- python-dotenv or django-environ for `.env`
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
ELEVENLABS_API_KEY=
MAX_COST_PER_VIDEO_USD=25
```

## UI pages (Phase 1, minimal)

1. **Profiles list / form**: create/edit profiles (name, niche, style prompt, narrator voice id).
2. **Profile detail**: that profile's videos with status badges (in process / completed / failed) and total cost each.
3. **New video**: pick profile, enter premise + target minutes; creates a Video in `draft` and the first pending script step.
4. **Video detail** (main screen):
   - Header: title, description, hashtags, target vs actual length, total cost.
   - Full script (expandable) once generated; parts list after the split, each with its text slice, images, and a per-part audio player once narrated.
   - Full narration player and final video player when ready.
   - Steps timeline: each GenerationStep with status, estimated vs actual cost, and Approve / Reject buttons when pending; plus "approve all images" and "approve all narration" batch actions with combined estimates.
   - Regenerate buttons per step/part (creates a new pending step).

## Milestones / build order

| # | Milestone | Contents |
|---|-----------|----------|
| 1 | Skeleton | Django project, MySQL connection, apps, base templates, .env, models + migrations, gitignore, README |
| 2 | Profiles | Model, repository, CRUD views |
| 3 | Video + approval framework | Video/Chapter/ChapterImage/GenerationStep/ApiCallLog, pipeline service, approval + batch-approval UI, cost estimator, budget cap |
| 4 | Script step | OpenAI continuation calls -> full 1-2 hour script + title, description, hashtags; length driven by target minutes; stored on Video |
| 5 | Split step | Split completed script into ordered parts (local, free) by target duration / natural breaks; create Chapter rows |
| 6 | Images step | OpenAI Images, N per part, 16:9, saved to media, shown per part |
| 7 | Narration step | ElevenLabs per part -> part_XX.mp3, merge -> narration.mp3, measure per-part offsets with ffprobe |
| 8 | Render step | FFmpeg: per part, its images Ken-Burns-panned across that part's audio span, crossfades, ambient music ducked under narration, 1920x1080 final.mp4 |
| 9 | Polish | Status badges, error surfacing, regenerate buttons, per-profile cost totals, end-to-end run of one full long-form video |
| 10 | Optional subtitles | Local faster-whisper SRT + optional burned captions (off by default) |

Definition of done for Phase 1: from a premise + target minutes, a user clicks through approvals (script, images, narration), the script is split into parts and the narration is merged into one track, and they end with a watchable 1-2 hour `final.mp4` on disk, with every dollar spent shown and pre-approved.

## Later phases (recorded for direction, not now)

- **Phase 2**: thumbnail generation, YouTube Data API upload with OAuth, Celery + Redis so long narration/render run in the background, full-pipeline budget approval up front.
- **Phase 3**: scheduling, multiple videos per profile, analytics, Docker Compose, object storage (S3/R2), cheaper providers (local Flux images, local/Piper TTS to slash narration cost), optional AI video clips, cross-posting.
