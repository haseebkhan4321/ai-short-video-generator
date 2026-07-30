# Seeders

Two entry points, one per environment. Both are idempotent — re-running creates
nothing new.

```bash
# Production: the minimum a live install needs
python manage.py seed_production --email you@example.com --account "My Studio"

# Development: everything, including videos at every pipeline stage
python manage.py seed_development
```

`seeders/` is a Django app only so its management commands are discovered; it has no
models and no migrations.

```
seeders/
├── base.py          Seeder base class: per-run tally, output helpers
├── data.py          every literal — templates, demo users, video fixtures
├── media.py         placeholder PNG / WAV / MP4 writers
├── lorem.py         deterministic lorem ipsum
├── roles.py         RoleSeeder       (both environments)
├── accounts.py      UserSeeder, AccountSeeder, FirstAdminSeeder
├── templates.py     TemplateSeeder   (both environments)
├── videos.py        VideoSeeder      (development only)
├── test_videos.py   TestVideoSeeder  (lorem ipsum, any stage and size)
├── production.py    ProductionSeeder
├── development.py   DevelopmentSeeder
└── management/commands/
    ├── seed_production.py
    ├── seed_development.py
    ├── seed_test_video.py   lorem ipsum videos on demand
    └── seed_templates.py    per-account starter templates
```

Two rules hold for every seeder:

- **Idempotent.** Each row is looked up before it is created, and the run reports
  `created` / `existed` / `updated` / `skipped`.
- **Repositories only.** Seeders go through the repositories like the rest of the
  app, so account scoping and model defaults are never bypassed. They skip the
  *services* for the RBAC invariants on purpose — a fixture that had to satisfy "you
  cannot grant what you do not hold" would need a fake actor to grant from.

## `seed_production`

Deliberately boring: no demo content, no invented credentials, and it never resets an
existing user's password.

1. The **system default roles** (Owner, Producer, Viewer). Without them a new account
   has no roles at all, because account creation clones these.
2. The **first system administrator** and their account. After a fresh `migrate`
   nothing is reachable anonymously and accounts are created by an administrator, so
   this is the only way in.

| Flag | Effect |
|---|---|
| `--email` | The administrator to create or promote. Without it, only the roles are seeded. |
| `--password` | Prompted for if omitted. Ignored for an existing user. |
| `--name` | Their full name. |
| `--account` | Name of the account to create and make them Owner of. |
| `--with-templates` | Also add the starter content templates to that account. |
| `--roles-only` | Seed the roles and stop. Creates no user. |
| `--refresh-roles` | Re-apply the permission catalog to the default roles, discarding edits made at `/console/default-roles/`. |

Starter templates are real content rather than demo data, so they are available but
off by default: what a live account should contain is the operator's decision. Add
them later with `seed_templates --account <slug>`.

The password is prompted for rather than defaulted. A seeder that invents a
production password is a seeder that ships a known credential.

## `seed_development`

Runs the production seed first, then adds demo data: two accounts, a user per role
including one custom role, every starter template, and **a video at each pipeline
stage** with real placeholder assets on disk.

| Flag | Effect |
|---|---|
| `--fresh` | Delete this seeder's previous output first (see below). |
| `--password` | Password for every seeded user. Defaults to `dev-password-1234`. |
| `--no-media` | Skip writing images and audio. Faster; thumbnails and players stay empty. |
| `--no-video-files` | Write images and audio but skip the ffmpeg renders. |
| `--audio-seconds N` | Length of each placeholder narration clip (default 8). |
| `--force` | Run even when `DEBUG` is off. |

It **refuses to run with `DEBUG` off** unless `--force` is passed, because it creates
users with a well-known password.

### Who it creates

All with the same password.

| Email | Role |
|---|---|
| `admin@dev.local` | system administrator — every account, `/console/` |
| `owner@dev.local` | Owner of Midnight Studio |
| `producer@dev.local` | Producer in Midnight Studio — approves spend, cannot exceed the cap |
| `narrator@dev.local` | Narrator in Midnight Studio — a custom role: runs free steps, approves nothing paid |
| `viewer@dev.local` | Viewer in **both** accounts — so the account switcher has two entries |
| `second@dev.local` | Owner of Second Studio |

Second Studio exists so cross-account isolation and account switching are visible
rather than theoretical. `viewer@dev.local` belongs to both, with the same role in
each; switch at `/accounts/me/` or from the nav.

The custom **Narrator** role is the interesting one: it holds `step.run_free` but not
`step.approve_paid`, so signing in as them shows "Generate all narration" and *not*
"Generate all images" on the same video.

### The video fixtures

Seven videos in Midnight Studio, one per stage, covering the whole detail page
without a single paid API call.

| Stage | State |
|---|---|
| `draft` | Pending paid script step — the "Approve the script to begin" screen |
| `scripted` | Script written, chapters not yet split |
| `split` | Chapters exist; images pending (paid) and narration pending (free) |
| `imaged` | Images on disk and paid for; narration still pending |
| `narrated` | Per-part and merged audio on disk; final render queued |
| `completed` | Fully rendered, `final.mp4` on disk |
| `failed` | A failed step with a real-looking error to surface and retry |

Three things the fixtures are careful about:

**Placeholder assets, real files.** A path on a model is not enough — the detail page
renders image thumbnails, an audio player and a video element, all of which break if
the file is missing. `seeders/media.py` writes small PNGs (by hand, no Pillow), quiet
WAVs (via soundfile, already a dependency) and MP4s (via ffmpeg, skipped with a
warning when it is unavailable). Chapter and video durations are read back *from those
files* rather than derived from word counts, so the part offsets, the audio player and
`duration_seconds` all agree. Seeded audio is a few seconds of quiet tone, not
synthesized narration — `target_minutes` stays realistic because that is the request,
not a measurement.

**A split script really is its parts.** `Video.script` is exactly
`"\n\n".join(chapter.body)`, so the split relationship holds the way it would after a
real run.

**Nothing is left approved, with one exception.** `resume_waiting_steps` claims
approved steps and runs them, so an approved-but-unfinished step means real work
starts the first time anyone opens the page. Seeded steps are pending, completed or
failed — except the `narrated` fixture's final render, which is left `approved`
because that is genuinely where the pipeline leaves it once a merge finishes. Opening
that video runs the part and final renders for real, which is the point: it
demonstrates the live progress UI for free. That step has to be created by the seeder,
because `_advance` only queues the video-level render when a merge step *completes at
runtime*, and the fixture seeds merge as already done.

`--no-media` cannot reach `completed`: with no assets to render from, that fixture
stops at `narration` rather than claiming a finished render it has no file for. Image
rows are still created for their prompts, but with a blank `image_path`.

### `--fresh`

Removes only what this seeder creates — its two named accounts and every
`@dev.local` user — then re-seeds. Cascades do the work: dropping an account takes its
templates, and a template takes its videos, chapters, images, steps and API logs.

Files under `media/` are left alone. A seeder that deleted directories there could
take a real render with it.

## `seed_test_video`

Throwaway videos filled with lorem ipsum, at any stage and any size. The development
fixtures are hand-written and deliberately small; this is the other thing you want
when checking how the UI behaves — a 14-part script reads nothing like a three-part
one.

```bash
python manage.py seed_test_video --account midnight-studio
python manage.py seed_test_video --account midnight-studio --count 3 --stage completed
python manage.py seed_test_video --account midnight-studio --parts 14 --words 950
python manage.py seed_test_video --account midnight-studio --purge
```

| Flag | Effect |
|---|---|
| `--account` | Required. Slug of the target account. |
| `--count N` | How many to create (default 1). |
| `--stage` | `draft`, `scripted`, `split`, `imaged`, `narrated`, `completed`, `failed` (default `split`). |
| `--parts N` | Parts per video (default 4). |
| `--words N` | Words per part (default 300). `--parts 14 --words 950` is about the size of a real 90-minute script. |
| `--template` | Pin one template. Default spreads a batch across all of the account's templates. |
| `--start N` | First index to number from (default 1). Re-running the same index is a no-op, so raise it to add more. |
| `--no-media`, `--no-video-files`, `--audio-seconds` | As `seed_development`. |
| `--purge` | Delete every lorem ipsum test video in the account. Leaves the hand-written fixtures alone. |

It reuses `VideoSeeder`, so a generated video gets the same steps, costs, API call
logs and placeholder assets as the demo ones — only the text differs.

Two things worth knowing:

**The text is deterministic.** Every `lorem.*` function takes a seed derived from the
video's own index, so re-running the same command produces byte-identical text. That
is what keeps the seeder idempotent (it matches an existing video by its premise) and
makes a bug reproducible from the same command. Sentence and paragraph lengths still
vary, because uniform paragraphs do not exercise the layout the way real prose does.

**Everything it makes is marked.** Premises start with `[lorem]`, which is both how
`--start` stays idempotent and how `--purge` finds its own output and nothing else.

## `seed_templates`

The targeted tool, for when an account already exists and just needs the starter set.

```bash
python manage.py seed_templates --account my-studio
python manage.py seed_templates --account my-studio --only "Untold History"
python manage.py seed_templates --account my-studio --update
```

The slug is shown at `/accounts/settings/`.

## From nothing to a working install

```bash
mysql -u root -e "CREATE DATABASE ai_shorts CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
python manage.py migrate
python manage.py seed_development      # or seed_production for a real install
python manage.py runserver
```

## Tests

`python manage.py test seeders` — 36 tests. The two properties worth protecting are
idempotency and the fixture invariants: that no step is left approved-but-unrun
(except the documented one), that a split script equals its parts, that every recorded
media path has a file behind it, that part offsets are contiguous and sum to the
duration, that a video's cost equals the sum of its API call logs, and that `--fresh`
removes its own output and nothing else.
