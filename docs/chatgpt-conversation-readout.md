# Readout: ChatGPT Conversation "AI-Generated Short Stories"

Source: https://chatgpt.com/share/6a50caf3-145c-83ee-baa1-b7ad824fbd73
Extracted: 2026-07-10

This is a summary of the reference conversation that shaped this project. Note: several of its recommendations (FastAPI, PostgreSQL, Celery/Redis, Docker, S3/R2, auto-upload) are intentionally NOT followed in Phase 1. See `phase-1-plan.md` for the actual plan.

## Project Idea

Build a fully automated platform that generates faceless AI YouTube Shorts: story-driven vertical videos (30 to 60 seconds, 9:16, 1080x1920) produced with minimal human intervention, eventually across multiple channels/niches.

## The Core Pipeline

```
Topic
  -> Story/Script (GPT, ~120-150 words, strong hook, plot twist)
  -> Split into 8-12 scenes (narration + image prompt per scene)
  -> Generate images (one per scene)
  -> Generate voice narration (single voice track)
  -> Generate subtitles (SRT)
  -> Render video with FFmpeg (Ken Burns zoom/pan, fades, burned captions, background music, voice sync)
  -> Generate thumbnail
  -> Upload to YouTube (title, description, tags, thumbnail)
```

## Recommended AI Services

| Job | Service |
|-----|---------|
| Story, scenes, prompts, titles, hashtags | OpenAI GPT (chat completions) |
| Images | OpenAI Images API (alternatives: Flux, SDXL, Midjourney) |
| AI video clips (later, premium) | Google Veo, Runway, Kling |
| Voice | ElevenLabs |
| Music | Royalty-free (Pixabay, YouTube Audio Library) or Suno/Stable Audio |
| Subtitles | Whisper (API or local) |
| Rendering | FFmpeg (free, local) |
| Upload | YouTube Data API v3 (Google Cloud project, OAuth) |

## Architecture ChatGPT Proposed (for reference, not Phase 1)

- FastAPI backend, PostgreSQL, Celery + Redis workers, Docker Compose
- S3-compatible storage (Cloudflare R2 or MinIO)
- Celery Beat for scheduled daily batch generation (e.g. 10-20 videos/day)
- Separate workers: story, image, voice, render, upload, analytics

## Database Schema Sketch (from the conversation)

- channels: id, name, niche, youtube_channel_id, upload_schedule
- topics: id, title, niche, status
- stories: id, topic_id, title, script, duration
- scenes: id, story_id, scene_number, narration, image_prompt
- images: id, scene_id, image_url
- voices: id, story_id, audio_url
- videos: id, story_id, video_url, youtube_url, views, revenue

## Accounts and Keys Needed

Required: OpenAI Platform (billing added), ElevenLabs, Google Cloud (YouTube Data API v3 + OAuth) for upload phase, YouTube channel, GitHub.
Recommended later: Google AI Studio (Gemini), Cloudflare R2, Docker Hub.

Env vars discussed: OPENAI_API_KEY, ELEVENLABS_API_KEY, YOUTUBE_CLIENT_ID/SECRET/REFRESH_TOKEN, DATABASE_URL, REDIS_URL, R2_* keys.

## Cost Estimates (per 45-second Short)

| Item | Approx. Cost (USD) |
|------|--------------------|
| GPT story + prompts | $0.01 - 0.05 |
| Images (8-10 scenes) | $0.20 - 1.00 |
| ElevenLabs voice | $0.02 - 0.10 |
| Whisper subtitles | < $0.01 (free if local) |
| Music | Free |
| FFmpeg render | Free |
| **Total (image-based)** | **~$0.25 - 1.20** |
| AI video generation route | $2 - 10+ per video |

Recommended starting budget: $20-30 USD. Image-based route strongly recommended for validation; upgrade to AI video clips only after revenue.

## Scaling / Future Ideas (from the conversation)

- Multiple channels, each with its own niche, prompt templates, voice, music, thumbnail style, and upload schedule (horror, mystery, life lessons, history, kids, Islamic stories, etc.)
- Cost optimization: cheaper LLM tiers for drafts, self-hosted Flux for images, Piper open-source TTS, local Whisper
- SaaS direction: multi-channel management, scheduling, analytics dashboard, A/B testing of titles/thumbnails, translations and multi-language voiceovers, cross-posting to TikTok/Instagram Reels/Facebook Reels, character consistency library
- Human approval workflow before publishing was listed as a future feature (in our build it is a Phase 1 core requirement, extended to every paid API call)

## High-RPM Niches Mentioned

Life lessons, business stories, history, AI facts, psychology, finance, mystery, horror.
