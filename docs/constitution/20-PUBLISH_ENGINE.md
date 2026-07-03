# 20 — Publish Engine

> Status: **YOUTUBE-ONLY (no provider abstraction).** `publish/uploader.py`
> and `publish/drive.py` implement YouTube + Drive directly, with no
> `PublishProvider` interface. This document specifies the platform-
> independent target per `PROJECT_VISION.md` §3 (Platform Targets) and
> non-negotiable #7 (Platform independence).

## 1. Purpose

The Publish Engine is the final pipeline stage: it takes a finished
`RenderedVideo` and delivers it to one or more target platforms, each with
its own metadata shape, scheduling semantics, and retry behavior. Per
non-negotiable #7, adding a new platform must mean writing one new
`Publisher` adapter — never touching ideation, voiceover, or render code.

## 2. Current Implementation (Baseline)

`publish/uploader.py::publish()` does YouTube upload directly:

- Honors `settings.dry_run` (no real upload when true — logs intent only).
- Builds `snippet`/`status` body inline, including Short-vs-clip
  classification (`_is_short`, threshold `SHORT_MAX_SEC = 180`), hashtag
  construction (`_build_hashtags`, max 3, `#Shorts` first), and the
  mandatory `containsSyntheticMedia` AI-disclosure flag
  (`settings.youtube_contains_synthetic_media`, default `True`).
- Resumable upload via `MediaFileUpload(resumable=True)` + manual
  `next_chunk()` polling loop — this part is already correctly
  platform-idiomatic (YouTube's own resumable upload protocol) and should
  be preserved as-is inside the YouTube adapter.
- Scheduling via `youtube_publish_at` (RFC3339), forcing
  `privacyStatus=private` until the scheduled time, per YouTube's API
  contract.

`publish/drive.py::backup_to_drive()` is a secondary, YouTube-coupled step:
uploads the rendered file to Drive *after* YouTube upload succeeds, then
optionally deletes the local copy (`move=True`) — but only once Drive
confirms receipt (has an `id`). This is not itself a "publish" target in the
platform sense; it is a storage backup hook tied to the YouTube path today.

## 3. Provider Interface

```python
"""src/ytb_pipeline/publish/provider.py (planned)."""

from __future__ import annotations

from typing import Protocol

from ..pkg.models import PublishResult, RenderedVideo
from .models import PublishMetadata


class PublishProvider(Protocol):
    """Port for any publish target. The render-side domain model
    (RenderedVideo) carries no platform assumptions — each provider is
    responsible for translating it into its platform's metadata shape."""

    name: str  # "youtube" | "tiktok" | "instagram_reels" | "podcast_rss" | "blog" | "drive"

    def is_available(self) -> bool:
        """Credentials/config present. Used by retry/fallback selection,
        never to silently swap the target platform."""
        ...

    def build_metadata(self, video: RenderedVideo) -> PublishMetadata:
        """Translate the platform-neutral RenderedVideo into this
        platform's metadata shape (tags vs hashtags vs episode fields)."""
        ...

    def publish(self, video: RenderedVideo, metadata: PublishMetadata) -> PublishResult:
        """Upload/schedule. Must respect settings.dry_run identically to
        the current uploader.py contract — dry_run is a global behavior,
        not a per-provider opt-in."""
        ...
```

## 4. Data Model

```python
"""src/ytb_pipeline/publish/models.py (planned)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PublishMetadata:
    """Platform-specific metadata, built fresh per provider from the same
    RenderedVideo — never shared/mutated across providers."""

    title: str
    description: str
    tags_or_hashtags: tuple[str, ...] = ()
    category: str = ""
    privacy: str = "private"
    publish_at: str = ""          # RFC3339, empty = publish immediately
    extra: dict = field(default_factory=dict)  # platform-specific fields
                                                 # (e.g. podcast episode_number,
                                                 #  YouTube categoryId, IG
                                                 #  collaborator tags)
```

## 5. Providers

| Provider | Status | Notes |
|---|---|---|
| **YouTube** | Implemented (to be migrated) | `uploader.py` becomes `publish/providers/youtube.py`, wrapped to satisfy `PublishProvider`. Resumable upload, thumbnail set, synthetic-media disclosure, Short classification, hashtag building all carry over unchanged. |
| **TikTok** | Future | New adapter; TikTok's content-posting API uses different metadata (no `categoryId`, different privacy enum, native hashtag-in-caption convention rather than YouTube's tag list). |
| **Instagram Reels** | Future | Graph API publishing; metadata includes collaborator tags, cover image selection — distinct from both YouTube and TikTok. |
| **Podcast RSS** | Future | Not an upload API at all — generates/updates an RSS feed XML with episode metadata (episode number, season, duration, enclosure URL pointing at a hosted audio file). Fundamentally different shape: no video, audio-only artifact from the Podcast `OutputProfile` (`19-RENDER_ENGINE.md`). |
| **Blog (MDX)** | Future | Writes an MDX file (frontmatter + embedded video/audio + transcript pulled from `SubtitleTrack`) into a content repo; "publish" here means a git commit/PR, not an API call. |
| **Google Drive** | Implemented (to be reframed) | Currently a YouTube-path backup hook (`drive.py`); should be modeled as its own `PublishProvider` (`name="drive"`) so it can run independently of YouTube — e.g. backing up content destined only for Blog/Podcast. |

## 6. Publish Metadata Differences (Why One Shape Doesn't Fit All)

| Field | YouTube | TikTok | Instagram Reels | Podcast | Blog |
|---|---|---|---|---|---|
| Discoverability tags | SEO `tags` list (up to 500 chars) + up to 3 hashtags surfaced from description | Hashtags embedded in caption text, platform-driven trends matter more | Hashtags in caption, collaborator/location tags | None — RSS categories instead | Frontmatter tags for site search/SEO |
| Privacy model | `private`/`unlisted`/`public` + scheduled `publishAt` | Public/private/friends, no granular schedule API parity | Public/private, Stories cross-post option | Feed is always public once episode is in the RSS; "private" = don't publish | Draft vs published flag in the content repo |
| AI-disclosure | `containsSyntheticMedia` (mandatory per current settings) | TikTok AI-generated content label (different mechanism) | Meta AI content label | N/A (audio-only, no platform-level AI flag yet) | Can self-disclose in post body |
| Category | `categoryId` (e.g. `"28"` Science & Technology) | No category field | No category field | Apple Podcasts category taxonomy | Blog category/tag taxonomy |

This table is the concrete justification for `PublishMetadata.extra: dict`
— forcing every platform's idiosyncratic fields into a fixed dataclass
schema would either bloat the dataclass with mostly-unused optional fields
or silently drop platform capabilities. `extra` is filled by
`build_metadata()` per provider and consumed only by that same provider's
`publish()`.

## 7. Scheduling

All providers that support scheduling accept `publish_at` as RFC3339,
matching the existing `youtube_publish_at` convention:

```python
"""src/ytb_pipeline/publish/scheduling.py (planned)."""

def normalize_publish_at(raw: str) -> str:
    """Validates `raw` is RFC3339 (e.g. '2026-06-17T06:00:00+0700') or
    raises — never silently passes through a malformed timestamp to a
    platform API that will reject it with a less debuggable error."""
    ...
```

- **YouTube**: native `status.publishAt`, requires `privacyStatus=private`
  until the scheduled moment (current behavior, preserved).
- **TikTok/Instagram**: scheduling support varies and is often
  platform-app-side rather than API-side; the engine queues the publish
  job and a scheduler component triggers it at `publish_at`, rather than
  relying on the platform API itself to hold the schedule.
- **Podcast/Blog**: scheduling means delaying the RSS/MDX commit, handled
  entirely client-side (no remote schedule needed).

## 8. Retry

```python
"""src/ytb_pipeline/publish/retry.py (planned)."""

def with_backoff(fn, *, max_attempts: int = 5, base_delay_sec: float = 2.0):
    """Exponential backoff wrapper for non-resumable providers (most cloud
    REST APIs). YouTube does NOT use this — it has its own resumable upload
    protocol (next_chunk() retry-on-chunk semantics), which must be
    preserved as-is rather than wrapped in a generic retry loop that would
    restart the whole upload on failure."""
    ...
```

- **YouTube**: resumable upload (existing `next_chunk()` loop) — chunk-level
  retry, not whole-file retry.
- **TikTok/Instagram/Podcast/Blog**: generic exponential backoff for
  transient API failures (rate limits, 5xx), since these are typically
  single-request or small-multipart uploads where restarting the whole
  request on failure is acceptable.

## 9. Audit

Current: `ledger.md` — presumably an append-only markdown log of publish
events (one line per upload, referenced in scripts but not part of the
`ytb_pipeline` package itself).

Future: SQLite ledger (`publish/ledger.py`, planned) — one row per
`(video_slug, provider, status, timestamp, url, error)`. Migrating off
markdown is needed once multi-platform publishing makes a single video
correspond to N publish events instead of 1, which a flat markdown log
does not query well (e.g. "show all videos NOT yet published to TikTok").

## 10. Current State

- YouTube: fully implemented in `uploader.py`, including dry-run, Short
  classification, hashtag building, scheduling, synthetic-media disclosure,
  thumbnail set.
- Drive backup: implemented in `drive.py`, coupled to the YouTube path
  (called as a post-upload step, not an independent publish target).
- TikTok, Instagram Reels, Podcast RSS, Blog: **not implemented**.
- No `PublishProvider` interface exists; `RenderedVideo` → YouTube body dict
  translation is inline in `uploader.py::publish()`.

## 11. Migration Notes

1. **Extract `PublishProvider` protocol** and wrap `uploader.py`'s existing
   logic as `providers/youtube.py::YouTubeProvider`, with zero behavior
   change — `_is_short`, `_build_hashtags`, `_to_hashtag`,
   `_set_thumbnail`, scheduling, dry-run, and resumable upload all move
   as-is.
2. **Reframe `drive.py` as `providers/drive.py::DriveProvider`** —
   decouple the "upload to Drive then delete local" sequencing from being
   a YouTube-only post-step; make it an independent provider any pipeline
   run can select.
3. **Introduce `PublishMetadata`/`build_metadata()`** per provider,
   replacing the inline `body = {...}` dict construction in `uploader.py`.
4. **Add Podcast RSS provider** — likely the next-easiest new target since
   it requires no new OAuth flow, just XML generation + static file
   hosting, and pairs naturally with the Podcast `OutputProfile`
   (`19-RENDER_ENGINE.md`).
5. **Add Blog (MDX) provider** — second-easiest; no external API at all,
   just file generation + git commit, reusing `SubtitleTrack` for embedded
   transcript text.
6. **TikTok / Instagram Reels providers** — require new OAuth/API
   integration work; sequenced last since they need the most net-new
   external-API code and the least overlap with already-built pieces.
7. **SQLite ledger** — once 2+ providers exist concurrently, replace
   `ledger.md` with the SQLite schema described in §9.
</content>
