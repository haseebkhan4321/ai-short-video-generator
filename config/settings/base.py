"""Base Django settings shared across environments."""
import os
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

# BASE_DIR points at the project root (two levels up from this file).
BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")


def _get(key, default=None):
    return os.getenv(key, default)


def _get_bool(key, default=False):
    val = os.getenv(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def _get_int(key, default):
    val = os.getenv(key)
    return int(val) if val not in (None, "") else default


def _get_decimal(key, default):
    val = os.getenv(key)
    return Decimal(val) if val not in (None, "") else Decimal(str(default))


def _get_list(key, default):
    val = os.getenv(key)
    if not val:
        return default
    return [item.strip() for item in val.split(",") if item.strip()]


SECRET_KEY = _get("SECRET_KEY", "dev-insecure-change-me")
DEBUG = _get_bool("DEBUG", True)
ALLOWED_HOSTS = _get_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1"])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Local apps
    "apps.profiles",
    "apps.videos",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": _get("DB_NAME", "ai_shorts"),
        "USER": _get("DB_USER", "root"),
        "PASSWORD": _get("DB_PASSWORD", ""),
        "HOST": _get("DB_HOST", "127.0.0.1"),
        "PORT": _get("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
            "init_command": "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---- Application-specific settings ----

# Provider API keys (empty until the user adds them; approval gate guards spend).
OPENAI_API_KEY = _get("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = _get("ELEVENLABS_API_KEY", "")

# Model + generation defaults.
OPENAI_TEXT_MODEL = _get("OPENAI_TEXT_MODEL", "gpt-4o-mini")
OPENAI_IMAGE_MODEL = _get("OPENAI_IMAGE_MODEL", "gpt-image-1")

# ---- Text-to-speech (narration): Kokoro, local and free ----
TTS_PROVIDER = _get("TTS_PROVIDER", "kokoro")
TTS_SAMPLE_RATE = _get_int("TTS_SAMPLE_RATE", 24000)
# Max characters sent to the TTS engine per request (long parts are chunked).
MAX_TTS_CHARS = _get_int("MAX_TTS_CHARS", 2000)

# Kokoro (local). Model + voices files live under assets/kokoro/ (see README).
DEFAULT_KOKORO_VOICE = _get("DEFAULT_KOKORO_VOICE", "af_heart")
KOKORO_MODEL_PATH = _get("KOKORO_MODEL_PATH", str(BASE_DIR / "assets" / "kokoro" / "kokoro-v1.0.onnx"))
KOKORO_VOICES_PATH = _get("KOKORO_VOICES_PATH", str(BASE_DIR / "assets" / "kokoro" / "voices-v1.0.bin"))
KOKORO_LANG = _get("KOKORO_LANG", "en-us")

# Currency: providers bill in USD; costs are stored in USD and displayed in PKR.
USD_TO_PKR = _get_decimal("USD_TO_PKR", "280")

# Cost guardrail (set in PKR): warn/block when a video's spend would exceed this.
MAX_COST_PER_VIDEO_PKR = _get_decimal("MAX_COST_PER_VIDEO_PKR", "7000")
MAX_COST_PER_VIDEO_USD = MAX_COST_PER_VIDEO_PKR / USD_TO_PKR

# Long-form generation tuning.
WORDS_PER_MINUTE = _get_int("WORDS_PER_MINUTE", 150)
DEFAULT_TARGET_MINUTES = _get_int("DEFAULT_TARGET_MINUTES", 90)
TARGET_MINUTES_PER_PART = _get_int("TARGET_MINUTES_PER_PART", 6)
IMAGES_PER_PART = _get_int("IMAGES_PER_PART", 4)
VIDEO_WIDTH = _get_int("VIDEO_WIDTH", 1920)
VIDEO_HEIGHT = _get_int("VIDEO_HEIGHT", 1080)

# ---- Render (ffmpeg) ----
# Binaries: "ffmpeg"/"ffprobe" if on PATH, or absolute paths via .env.
FFMPEG_BINARY = _get("FFMPEG_BINARY", "ffmpeg")
FFPROBE_BINARY = _get("FFPROBE_BINARY", "ffprobe")
RENDER_FPS = _get_int("RENDER_FPS", 24)
RENDER_PRESET = _get("RENDER_PRESET", "veryfast")  # x264 speed/size tradeoff
RENDER_CRF = _get_int("RENDER_CRF", 23)
# Background music: a file placed in assets/music/ (optional). Empty = no music.
BACKGROUND_MUSIC = _get("BACKGROUND_MUSIC", "")
BACKGROUND_MUSIC_VOLUME = _get("BACKGROUND_MUSIC_VOLUME", "0.08")
