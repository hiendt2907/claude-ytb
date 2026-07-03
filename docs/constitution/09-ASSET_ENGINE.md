# 09 — ASSET ENGINE

## Purpose

Own the lifecycle of every generated or sourced binary artifact — images,
video clips, audio, subtitles, fonts, templates, overlays. The Asset Engine
is the single chokepoint between "an agent decided we need X" and "X exists
as a cached, addressable file on disk." No other component writes directly
into the asset store.

## Asset Types

| Type | Examples | Producer |
|---|---|---|
| `image` | thumbnail, background frame, character portrait, chart | Image Engine (12) |
| `video_clip` | b-roll clip, animation render, stickman motion | Video Engine (13) |
| `audio` | narration segment, combined voiceover, music/sfx | Voice Engine (14) |
| `subtitle` | SRT/VTT cue track | Subtitle Agent (06-AGENTS) |
| `font` | typeface files used in overlays/captions | Static, version-pinned in repo |
| `template` | ComfyUI workflow JSON, Lottie/animation template | Static, version-pinned in repo |
| `overlay` | caption card PNG, terminal-card PNG, veil/gradient layer | Render Engine (Pillow), may be cached like any generated image |

`font` and `template` are typically static repo assets, not generated — they
still go through the registry (below) so render code never hardcodes a path,
keeping the asset layer the single source of truth for "where is X."

## Asset Lifecycle

```
  generate ──► validate ──► cache (content-hash store) ──► use ──► cleanup
     │             │                                          │
     │             └─ reject (quality gate fail) ──► regenerate (provider retry)
     │
     └─ cache hit short-circuits straight to "use"
```

1. **Generate**: an Engine (Image/Video/Voice) produces a candidate asset
   from a spec (prompt, params, seed).
2. **Validate**: type-specific quality gate runs (blur/NSFW/consistency for
   images — 12-IMAGE_ENGINE; motion blur/artifact/fps for video —
   13-VIDEO_ENGINE; duration/silence detection for audio — 14-VOICE_ENGINE).
   A failed validation triggers a bounded regeneration loop at the Engine
   level, not at the Asset Engine level — the Asset Engine only ever stores
   assets that already passed validation.
3. **Cache**: validated asset is written to `assets/{type}/{content_hash}.{ext}`
   and registered in the SQLite asset registry (below). This step is what
   makes the whole pipeline checkpoint/resume-safe — a re-run with identical
   inputs never regenerates.
4. **Use**: consuming code (Editor Agent's `EditTimeline`, render compositor)
   reads `asset_path` from the registry by hash, never by re-deriving the
   path from the spec itself.
5. **Cleanup**: assets unreferenced by any `used_by` entry past a retention
   window are eligible for garbage collection (see Cache invalidation below).
   Cleanup never deletes an asset still referenced by an active/recent run.

## Asset Addressability — Content-Hash Naming

Every generated asset's identity is `SHA-256(canonical_spec)`, where
`canonical_spec` is a deterministic serialization of every parameter that
affects the output:

```python
import hashlib
import json
from dataclasses import dataclass


@dataclass(frozen=True)
class AssetSpec:
    """Everything that determines the output bytes, and nothing else.
    Two AssetSpecs that are field-equal MUST produce identical assets."""

    asset_type: str           # "image" | "video_clip" | "audio" | ...
    provider: str             # "flux" | "f5-tts" | "wan2.2" | ...
    prompt: str = ""
    negative_prompt: str = ""
    seed: int | None = None
    params: dict = None        # resolution, duration, voice_id, etc. — sorted keys only
    ref_inputs: tuple[str, ...] = ()  # content-hashes of any input assets (e.g. ref audio)

    def content_hash(self) -> str:
        canonical = json.dumps(
            {
                "asset_type": self.asset_type,
                "provider": self.provider,
                "prompt": self.prompt,
                "negative_prompt": self.negative_prompt,
                "seed": self.seed,
                "params": dict(sorted((self.params or {}).items())),
                "ref_inputs": sorted(self.ref_inputs),
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

Rules:
- `provider` is part of the hash — switching from Flux to SDXL for the same
  prompt is a cache miss by design (different model, different output).
  Provider-agnostic caching is a non-goal; provider-fidelity matters more
  than cache hit rate here.
- `ref_inputs` (e.g. the narrator reference audio's own content-hash) must be
  included so that changing the voice-clone reference invalidates all
  downstream cached narration — this is what prevents stale audio after a
  reference-voice update.
- Timestamps, run IDs, and any non-deterministic metadata are **never** part
  of the hash.

## Local Storage Layout

```
assets/
├── image/{content_hash}.png
├── video_clip/{content_hash}.mp4
├── audio/{content_hash}.wav
├── subtitle/{content_hash}.srt
├── overlay/{content_hash}.png
├── font/                    # static, not content-hashed (version-pinned filenames)
├── template/                # static, not content-hashed
└── registry.sqlite3          # the Asset Registry (below)
```

Each generated type gets its own top-level directory rather than one flat
hash-named pool — this keeps the layout debuggable (`ls assets/audio/` is
meaningful) while content-hash naming still guarantees no collisions and no
duplicate generation within a type.

## Cache Invalidation Strategy

Content-hash addressing makes invalidation mostly **structural rather than
time-based**: a changed prompt or seed is automatically a new hash, so there
is no "stale cache" in the traditional sense for asset *content*. What still
needs explicit invalidation:

1. **Provider/model version bumps**: include a `provider_version` field in
   `AssetSpec.params` (e.g. `flux_model="flux-dev-1.0"`) — bumping the
   deployed model version is then automatically a cache miss, not a silent
   reuse of outputs from an old model.
2. **Garbage collection, not correctness invalidation**: periodically
   (`make clean`-equivalent or a scheduled job) delete registry rows (and
   their files) where `used_by` is empty and `created_at` is older than a
   retention window (default 30 days) — frees disk, never affects
   correctness since a future identical spec just regenerates and re-caches.
3. **Manual purge by type**: `assets/{type}/` can be wiped wholesale to force
   full regeneration of one asset class (e.g. after a thumbnail style
   overhaul) — registry rows for that type must be deleted in the same
   transaction to avoid dangling references.

## Asset Registry (SQLite)

```sql
CREATE TABLE asset (
    asset_hash   TEXT PRIMARY KEY,
    asset_type   TEXT NOT NULL,
    path         TEXT NOT NULL,
    provider     TEXT NOT NULL,
    spec_json    TEXT NOT NULL,      -- serialized AssetSpec, for debugging/audit
    created_at   TEXT NOT NULL,      -- ISO8601 UTC
    bytes        INTEGER NOT NULL,
    validated    INTEGER NOT NULL DEFAULT 1  -- 0 only transiently during a future
                                               -- async-validate path; today an asset
                                               -- is only inserted after validation
);

CREATE TABLE asset_usage (
    asset_hash   TEXT NOT NULL REFERENCES asset(asset_hash),
    used_by      TEXT NOT NULL,       -- run_id or video_id
    used_at      TEXT NOT NULL,
    PRIMARY KEY (asset_hash, used_by)
);

CREATE INDEX idx_asset_type ON asset(asset_type);
CREATE INDEX idx_usage_hash ON asset_usage(asset_hash);
```

```python
from typing import Protocol


class AssetRegistry(Protocol):
    def get(self, content_hash: str) -> "Asset | None":
        """Cache lookup — called before any generation request is dispatched."""
        ...

    def put(self, asset: "Asset", spec: AssetSpec) -> None:
        """Called only after validation passes."""
        ...

    def record_usage(self, content_hash: str, used_by: str) -> None: ...

    def garbage_collect(self, retention_days: int = 30) -> int:
        """Returns count of assets purged."""
        ...
```

`asset_usage` is a many-to-many table by design — the same generated
background frame can legitimately be reused across multiple videos in a
series (e.g. a recurring intro card), and GC must respect every reference,
not just the most recent one.

## AI Asset Generation Pipeline

```
AssetSpec
   │
   ▼
AssetRegistry.get(spec.content_hash())  ── HIT ──► return cached Asset
   │ MISS
   ▼
dispatch to Engine by asset_type:
   image      → Image Engine   (Flux/SDXL, 12-IMAGE_ENGINE)
   video_clip → Video Engine   (Wan2.2/CogVideoX, 13-VIDEO_ENGINE)
   audio      → Voice Engine   (F5-TTS, 14-VOICE_ENGINE)
   │
   ▼
Engine-internal quality gate (validate)
   │ PASS                              │ FAIL
   ▼                                    ▼
write file to assets/{type}/{hash}.{ext}   bounded retry (Engine-level,
   │                                        see each Engine's retry strategy)
   ▼                                          │ exhausted
AssetRegistry.put(asset, spec)                ▼
   │                                    return degraded/fallback asset
   ▼                                        (e.g. Ken Burns static fallback
return Asset                                 for video — 13-VIDEO_ENGINE)
```

The Asset Engine itself contains **no model-specific code** — it is a cache
and registry layer. All provider logic lives in the respective Engine
(10/12/13/14), each implementing a shared generation interface so the Asset
Engine's dispatch step is a simple type-keyed lookup, not a growing if/elif
chain.

## Current State

Today there is no Asset Engine, registry, or content-hash addressing:

- `assets/output/` — final rendered videos + thumbnails (`compose.py`/
  `compose_ai.py` write directly here, filenames derived from
  `_slugify(script.title)`, not content-hashed).
- `assets/output/_frames_ai/` — intermediate composited frames for the
  AI-variant renderer.
- `assets/audio/` — per-segment + combined narration audio
  (`{slug}_{i:02d}.mp3`, `{slug}.mp3`), written by `voiceover/tts.py`. The
  *resume* behavior already present here (skip a segment if its audio file
  already exists and has valid duration — see `tts.py::synthesize`) is a
  proto-cache, just keyed by slug+index instead of content hash.
- `assets/ref/` — static reference assets (`narrator.wav`, `narrator.txt`,
  `pronunciation_overrides.json`) — closest existing analog to the `font`/
  `template` static-asset category.
- `assets/broll/`, `assets/music/`, `assets/sfx/`, `assets/branding/` —
  static or Pexels-fetched assets with no registry; B-roll is fetched fresh
  per run via `render/stock.py::fetch_broll`, with no caching at all (a
  re-run with the same `broll` keyword re-fetches from Pexels every time).

## Migration Notes

1. **Add the registry without touching existing producers first**:
   introduce `AssetRegistry`/`AssetSpec`/`assets/registry.sqlite3` as new,
   additive infrastructure. Existing code (`tts.py`, `compose.py`,
   `compose_ai.py`) keeps writing to its current paths unchanged in phase 1.
2. **Wrap, don't rewrite, the TTS resume logic**: `tts.py`'s existing
   "skip segment if valid audio exists" check is functionally a
   content-hash cache with the wrong key (slug+index instead of
   `AssetSpec.content_hash()`). Migrate it by computing the real content
   hash (text + voice + provider + params) and routing the existing
   duration-probe check through `AssetRegistry.get()` instead of a raw
   filesystem `.exists()` check — this also fixes a latent correctness gap:
   today, changing `script.voice` for an already-rendered slug does **not**
   invalidate cached segment audio, because the cache key never included
   voice.
3. **Replace `stock.fetch_broll` caching gap**: wrap Pexels fetches in the
   same `AssetSpec`/registry pattern (`provider="pexels"`, `prompt=keyword`)
   so repeated runs with the same B-roll keyword stop re-fetching — an
   immediate cost/latency win even before any AI-generation migration.
4. **Migrate output paths to content-hash directories last**: once Image/
   Video Engines exist, route their outputs through
   `assets/{image,video_clip}/{hash}.{ext}` per the target layout; final
   assembled video output (`assets/output/*.mp4`) is the one artifact that
   intentionally stays human-readable-named (per video, not content-hashed)
   since it is a terminal deliverable, not a reusable intermediate asset.
5. **`make clean`** (existing Makefile target wiping output/audio/cache)
   becomes a thin wrapper around `AssetRegistry.garbage_collect(0)` (force
   purge everything) once the registry exists, rather than a raw `rm -rf`.
