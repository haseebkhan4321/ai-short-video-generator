"""Seed data literals. No logic here — the seeders read from this module.

Splitting the data out keeps the seeders readable and makes it obvious what a run
will produce. Everything development-only is suffixed ``@dev.local`` or listed under
``DEMO_*`` so ``seed_development --fresh`` can find and remove exactly what it made.
"""
from apps.accounts.permissions import Perm

# ---------------------------------------------------------------------------
# Starter templates — real content identities, useful in production too.
# ---------------------------------------------------------------------------

STARTER_TEMPLATES = [
    {
        "name": "Midnight Horror Narrations",
        "niche": "horror",
        "description": "Long-form atmospheric horror stories for late-night listening.",
        "style_prompt": (
            "You write slow-burn, atmospheric horror narration for a faceless "
            "long-form YouTube channel. Second-person and third-person mix, dread "
            "that builds gradually, vivid sensory detail, minimal gore, a strong "
            "hook in the first minute and a disturbing twist near the end. Written "
            "to be read aloud calmly by a single narrator."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Sleep & Bedtime Stories",
        "niche": "bedtime",
        "description": "Calm, gentle stories designed to help listeners fall asleep.",
        "style_prompt": (
            "You write soothing, slow-paced bedtime stories for adults. Soft, "
            "meandering narration with warm imagery, no conflict spikes or jump "
            "scares, gentle repetition, and a peaceful, drifting tone. Written to "
            "be read aloud slowly and quietly."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Untold History",
        "niche": "history",
        "description": "Deep-dive historical narratives and forgotten events.",
        "style_prompt": (
            "You write engaging, well-structured long-form history narration. "
            "Clear chronological storytelling, vivid scene-setting, memorable "
            "characters, accurate framing, and smooth transitions between eras. "
            "Authoritative but accessible, written to be narrated as a documentary."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Deep Space Sci-Fi",
        "niche": "sci-fi",
        "description": "Original long-form science fiction stories set in deep space.",
        "style_prompt": (
            "You write cinematic long-form science fiction narration. Grand scale, "
            "cosmic wonder and tension, believable technology, isolated protagonists, "
            "and a slow reveal of the central mystery. Immersive third-person, "
            "written to be narrated over ambient space visuals."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Mind & Motivation",
        "niche": "motivation",
        "description": "Reflective, motivational long-form stories and life lessons.",
        "style_prompt": (
            "You write reflective, uplifting long-form narration built around a "
            "central life lesson. Story-driven rather than preachy, grounded in "
            "relatable human moments, with a clear takeaway and a calm, sincere "
            "tone. Written to be narrated warmly and steadily."
        ),
        "narrator_voice": "",
        "language": "en",
    },
    {
        "name": "Case Files: Fiction",
        "niche": "mystery",
        "description": "Fictional detective and mystery narratives, feature length.",
        "style_prompt": (
            "You write long-form fictional mystery and detective stories. A compelling "
            "case introduced early, escalating clues, red herrings, a methodical "
            "investigator, and a satisfying reveal. Tense, measured pacing written "
            "to be narrated as a serialized case file."
        ),
        "narrator_voice": "",
        "language": "en",
    },
]


# ---------------------------------------------------------------------------
# Development-only: accounts, roles and users
# ---------------------------------------------------------------------------

DEV_PASSWORD = "dev-password-1234"
DEV_EMAIL_DOMAIN = "dev.local"

DEV_SYSTEM_ADMIN = {
    "email": f"admin@{DEV_EMAIL_DOMAIN}",
    "full_name": "Dev Admin",
}

# A role beyond the three defaults, to show that roles are user-defined: it can run
# the free steps (narration, render) but cannot authorize any spend.
NARRATOR_ROLE = {
    "name": "Narrator",
    "description": "Runs the free steps. Cannot approve anything that costs money.",
    "permissions": [
        Perm.TEMPLATE_VIEW,
        Perm.VIDEO_VIEW,
        Perm.STEP_RUN_FREE,
        Perm.STEP_REGENERATE,
    ],
}

# The main demo account gets every starter template plus the seeded videos; the
# second exists so cross-account isolation and the account switcher are visible.
DEMO_ACCOUNTS = [
    {
        "name": "Midnight Studio",
        "owner": {"email": f"owner@{DEV_EMAIL_DOMAIN}", "full_name": "Olive Owner"},
        "templates": "all",
        "extra_roles": [NARRATOR_ROLE],
        "members": [
            {
                "email": f"producer@{DEV_EMAIL_DOMAIN}",
                "full_name": "Pat Producer",
                "role": "Producer",
            },
            {
                "email": f"narrator@{DEV_EMAIL_DOMAIN}",
                "full_name": "Nadia Narrator",
                "role": "Narrator",
            },
            {
                "email": f"viewer@{DEV_EMAIL_DOMAIN}",
                "full_name": "Vic Viewer",
                "role": "Viewer",
            },
        ],
        "with_videos": True,
    },
    {
        "name": "Second Studio",
        "owner": {"email": f"second@{DEV_EMAIL_DOMAIN}", "full_name": "Sam Second"},
        "templates": ["Untold History"],
        "extra_roles": [],
        "members": [
            # Also a member of Midnight Studio, so their account switcher has two
            # entries with different permissions in each.
            {
                "email": f"viewer@{DEV_EMAIL_DOMAIN}",
                "full_name": "Vic Viewer",
                "role": "Viewer",
            },
        ],
        "with_videos": False,
    },
]


# ---------------------------------------------------------------------------
# Development-only: videos, one per pipeline stage
# ---------------------------------------------------------------------------
#
# ``stage`` drives how far the VideoSeeder builds each one. Together they cover the
# whole video-detail UI without a single paid API call:
#
#   draft      pending paid script step — the "Approve the script to begin" state
#   scripted   script written, chapters not yet split
#   split      chapters exist; images pending (paid) and narration pending (free)
#   imaged     images on disk; narration still pending
#   narrated   per-part + merged audio on disk; final render pending
#   completed  everything done, final.mp4 on disk
#   failed     a failed step with an error to surface and retry

_LOREM_PARAGRAPHS = [
    "The house had been empty for eleven years, and in that time the garden had "
    "learned to keep its own counsel. Ivy had found the mortar between the bricks "
    "and worked it patiently, the way water works stone, until the west wall leaned "
    "a little towards the road as though listening for something.",
    "You notice the smell first. Not damp, exactly — damp is honest, damp announces "
    "itself. This is the smell of a room that has been holding its breath. It sits "
    "at the back of the throat and stays there, and you find yourself swallowing "
    "more often than you need to.",
    "The staircase turns twice before it reaches the landing, and on the second turn "
    "there is a window that looks out onto nothing at all: a brick face, eighteen "
    "inches away, mortared shut some time after the house was built. Somebody wanted "
    "that window there. Somebody else wanted it blind.",
    "Marianne had said, in the solicitor's office, that she remembered the upstairs "
    "corridor being shorter. Everyone had smiled at that, the way people smile at a "
    "child's arithmetic. But she had grown up in that corridor, and she had counted "
    "its doors every night of her childhood, and there had been four.",
    "There are five now.",
]

VIDEO_FIXTURES = [
    {
        "key": "draft",
        "stage": "draft",
        "template": "Midnight Horror Narrations",
        "premise": (
            "A family inherits their grandfather's house and finds a corridor with "
            "one more door than anyone remembers."
        ),
        "target_minutes": 30,
    },
    {
        "key": "scripted",
        "stage": "scripted",
        "template": "Untold History",
        "premise": (
            "The forgotten engineers who kept the London Underground running through "
            "the Blitz."
        ),
        "target_minutes": 45,
        "title": "The Night Shift Beneath London",
        "description": (
            "For eight months the deepest stations were a second city. These are the "
            "people who kept its lights on, and the ones who never came back up."
        ),
        "hashtags": ["#History", "#Blitz", "#London", "#Underground", "#WW2"],
    },
    {
        "key": "split",
        "stage": "split",
        "template": "Deep Space Sci-Fi",
        "premise": (
            "A lone maintenance engineer on a generation ship discovers the crew "
            "manifest has been quietly shrinking for decades."
        ),
        "target_minutes": 24,
        "title": "The Shrinking Manifest",
        "description": (
            "Every year the ship's records list a few fewer names, and nobody aboard "
            "finds that strange except her."
        ),
        "hashtags": ["#SciFi", "#DeepSpace", "#Mystery", "#GenerationShip"],
        "chapters": 4,
    },
    {
        "key": "imaged",
        "stage": "imaged",
        "template": "Case Files: Fiction",
        "premise": (
            "A detective reopens a drowning that everyone agreed was an accident, "
            "because the victim could not swim and the lake was fenced."
        ),
        "target_minutes": 18,
        "title": "Case File 41: The Fenced Lake",
        "description": (
            "Three witnesses, one gate, and a body found on the wrong side of it."
        ),
        "hashtags": ["#Mystery", "#Detective", "#CaseFile", "#Fiction"],
        "chapters": 3,
    },
    {
        "key": "narrated",
        "stage": "narrated",
        "template": "Sleep & Bedtime Stories",
        "premise": (
            "A slow walk through a coastal village at dusk, where nothing happens and "
            "nothing needs to."
        ),
        "target_minutes": 12,
        "title": "The Long Dusk at Weatherby Cove",
        "description": (
            "No plot, no tension, no destination. Just the tide going out and the "
            "lamps coming on, one at a time."
        ),
        "hashtags": ["#SleepStory", "#Bedtime", "#Calm", "#Relaxing"],
        "chapters": 3,
    },
    {
        "key": "completed",
        "stage": "completed",
        "template": "Mind & Motivation",
        "premise": (
            "A cabinetmaker who spent forty years making the same chair, and what he "
            "learned about getting better at something."
        ),
        "target_minutes": 15,
        "title": "Forty Years, One Chair",
        "description": (
            "He could have made a thousand different things. He made one thing a "
            "thousand times, and that turned out to be the harder path."
        ),
        "hashtags": ["#LifeLessons", "#Craft", "#Mastery", "#Motivation"],
        "chapters": 3,
    },
    {
        "key": "failed",
        "stage": "failed",
        "template": "Midnight Horror Narrations",
        "premise": (
            "A radio operator at a remote weather station starts receiving her own "
            "voice on a frequency nobody is transmitting on."
        ),
        "target_minutes": 20,
        "error": (
            "openai.RateLimitError: Rate limit reached for gpt-4o-mini in "
            "organization org-demo on tokens per min (TPM): Limit 200000, Used "
            "199712, Requested 1544."
        ),
    },
]


def paragraphs_for(index, count=5):
    """A deterministic slice of the sample prose, so re-runs produce identical text."""
    out = []
    for i in range(count):
        out.append(_LOREM_PARAGRAPHS[(index + i) % len(_LOREM_PARAGRAPHS)])
    return out


CHAPTER_TITLES = [
    "The Inheritance",
    "What the Survey Missed",
    "The Fifth Door",
    "Marianne Counts Again",
    "The Wall Between",
    "What Was Sealed In",
    "The Last Night",
    "Afterwards",
]
