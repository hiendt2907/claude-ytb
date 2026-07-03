# 24 — Cache System

> Status: **NOT IMPLEMENTED.** Current state is ad-hoc `if path.exists():
> skip` checks scattered across `voiceover/tts.py`, `render/compose.py`, and
> related modules. This document specifies the unified content-hash cache
> manager that replaces them.

## 1. Purpose

Every AI-assisted production step in `claude-ytb` — an LLM call, a TTS
synthesis, an image generation, a video clip render — is expensive in one or
more of: wall-clock time, local compute/battery on the M4, or (for opt-in
cloud fallbacks) money. Per `PROJECT_VISION.md` §2 local-inference-priority,
local generation is the default, which makes wasted recomputation a direct
hit to creative iteration speed, not just a cost line item.

The Cache System exists so that **the same input always produces the same
cached output without regenerating it** — a pure content-addressable cache,
not a TTL-based web cache. If the prompt, model, and parameters are
identical, the result is identical (for deterministic providers) or
acceptable-to-reuse (for the few providers where outputs vary run-to-run but
re-running adds no value, e.g., re-fetching a stock asset by the same query).

## 2. Cache Keys

Cache keys are computed as:

```text
cache_key = sha256(
    canonical_json({
        "type": "llm" | "tts" | "image" | "video_clip",
        "provider": provider_name,        # e.g. "f5", "edge", "flux", "ollama-qwen3"
        "model": model_identifier,        # e.g. "qwen3:8b", "flux-dev-fp8"
        "params": sorted_params_dict,     # voice id, sample rate, resolution, seed, etc.
        "prompt": prompt_text_or_hash,    # full text, or its own hash if very large
    })
).hexdigest()
```

`canonical_json` means keys sorted, no whitespace variance, floats
normalized to a fixed precision — two logically identical requests must
never produce different keys due to dict ordering or float formatting.

This makes the key **deterministic by construction**: same prompt + same
model + same params ⇒ same key, every time, on every machine, forever. No
key ever depends on wall-clock time, machine identity, or random seed unless
`seed` is itself a parameter explicitly included in `params` (in which case
varying the seed is a deliberate cache miss, not a bug).

## 3. Cache Types

| Type | Producer | Typical params in key |
|---|---|---|
| LLM response cache | Ideation/research LLM calls (Ollama/Qwen3 default, Claude API fallback) | `temperature`, `max_tokens`, `system_prompt_hash` |
| TTS audio cache | Voiceover stage (F5-TTS default, Edge-TTS/ElevenLabs fallback) | `voice_id`, `speed`, `pitch`, pause settings (`pause_comma_ms` etc. from `settings.py`) |
| Image cache | Render stage AI image path (Flux default) | `width`, `height`, `steps`, `seed`, `style_lora` |
| Video clip cache | Render stage AI video path / B-roll fetch | `duration_sec`, `resolution`, `motion_strength`, or stock query string for the explicit Pexels fallback |

Each type gets its own subtree under `assets/` (§4) so that cache eviction
(§8) and disk-quota accounting can be scoped per type if needed (e.g., never
evict TTS cache before image cache, since TTS reruns are more expensive
relative to disk cost).

## 4. Storage Layout

```text
assets/
├── cache/
│   ├── llm/{hash}.json          # cached LLM response + metadata
│   ├── tts/{hash}.wav           # cached synthesized audio
│   ├── image/{hash}.png         # cached generated/fetched image
│   └── video_clip/{hash}.mp4    # cached generated/fetched video clip
```

`{hash}` is the full `cache_key` from §2 (hex string). File extension is
fixed per type (`.json`, `.wav`, `.png`, `.mp4`) — never inferred from
provider response metadata, so a cache lookup is a pure path construction
from the hash, no directory scan required.

This generalizes the existing `assets/{audio,output}/` convention already
established in `CLAUDE.md`/`settings.py` (`assets_dir`, `output_dir`) rather
than introducing a parallel directory scheme; `assets/cache/` sits alongside
them as a new, clearly-scoped subtree.

## 5. Cache Registry

A SQLite registry (`data/cache_registry.db`) tracks metadata the filesystem
alone cannot answer efficiently (total size, LRU order, hit rates):

```sql
CREATE TABLE cache_entries (
    hash        TEXT PRIMARY KEY,       -- sha256 hex digest, matches filename
    type        TEXT NOT NULL,          -- 'llm' | 'tts' | 'image' | 'video_clip'
    path        TEXT NOT NULL,          -- relative path under assets/cache/
    size_bytes  INTEGER NOT NULL,
    created_at  TEXT NOT NULL,          -- ISO 8601 UTC
    last_used   TEXT NOT NULL,          -- ISO 8601 UTC, updated on every cache hit
    hit_count   INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_cache_type ON cache_entries(type);
CREATE INDEX idx_cache_last_used ON cache_entries(last_used);
```

Every cache write inserts a row; every cache hit updates `last_used` and
increments `hit_count` (used by §8 eviction and by future cache-warming
prioritization in §7). The registry is rebuildable from the filesystem alone
(scan `assets/cache/`, recompute `size_bytes`, default `last_used` to file
mtime) — it is an index/accelerator, never a second source of truth that can
desync the system if lost.

## 6. Cache Invalidation

- **Deterministic outputs (LLM with `temperature=0` and fixed seed, TTS,
  image, video clip generation): never expire on TTL.** A given hash either
  exists (reuse forever) or doesn't (generate once). `expires_at` for these
  types is always `NULL`.
- **API-sourced, non-deterministic-by-nature data only** (e.g., a stock
  B-roll search result from the explicit Pexels fallback, where the same
  query might return a refreshed catalog over time, or a YouTube trending
  research fetch) gets a TTL, because the *correctness* of reuse degrades
  with time even though the request itself didn't change.
  - Stock B-roll search cache: TTL 7 days.
  - Trending/research API cache: TTL 24 hours.
- TTL is enforced lazily: a cache lookup that finds an entry past
  `expires_at` treats it as a miss, regenerates, and overwrites the entry
  (same hash, refreshed `created_at`/`last_used`) rather than running a
  separate cleanup sweep.

## 7. Cache Warming

For frequently-needed, low-variability assets — e.g., a fixed set of
intro/outro stingers, a small library of channel-branding image prompts, a
standard set of pause/breath SFX — a `warm_cache()` entrypoint pre-generates
and registers them ahead of any pipeline run, so the first real production
run never pays the cold-generation cost for assets the channel reuses every
episode.

Warming targets are declared in a project-level or channel-level config list
(`cache_warm_targets: list[CacheWarmTarget]`, each holding the same
`type`/`provider`/`model`/`params`/`prompt` shape used to compute a cache
key), run via `ytb cache warm` (see `27-CODING_STANDARD.md` / future CLI
surface), and are safe to re-run idempotently — a warm target whose hash
already exists in the registry is a no-op.

## 8. Cache Eviction

Disk is finite; the cache is not allowed to grow unbounded. Eviction policy:

- Configurable `MAX_CACHE_GB` (new `Settings` field, default `20`).
- On every cache write, if total `size_bytes` across `cache_entries` exceeds
  `MAX_CACHE_GB`, evict entries in **LRU order** (`ORDER BY last_used ASC`)
  until under budget, deleting both the registry row and the file.
- Eviction is type-agnostic by default (oldest-used entry of any type goes
  first), but `MAX_CACHE_GB` may optionally be split per type
  (`max_cache_gb_by_type: dict[str, float]`) if one type (e.g., video clips)
  threatens to starve the others of cache headroom in practice.
- Eviction never runs synchronously inside a hot request path that's
  waiting on a cache write to complete the *current* operation — it runs as
  a post-write housekeeping step so a slow eviction pass never blocks
  pipeline progress.
- Eviction is logged via structured logging (`27-CODING_STANDARD.md`) with
  the evicted hash, type, size, and resulting total cache size, so eviction
  pressure is visible without manually inspecting the registry.

## 9. Current State

Ad-hoc existence checks, one per stage, with no shared key derivation, no
registry, no eviction, and no TTL distinction between deterministic and
API-sourced data:

- `voiceover/tts.py` — checks for an existing audio file at a path derived
  from script content before resynthesizing.
- `render/compose.py` — checks for an existing rendered clip before
  re-rendering.

These checks are correct in spirit (avoid redundant work) but fragile in
practice: path derivation is ad-hoc per module (not a shared, tested hash
function), there's no eviction (disk grows unbounded), and there's no
registry to answer "how much cache do we have, by type, and is it healthy?"
without a manual filesystem walk.

## 10. Migration to Unified Cache Manager

1. **Phase A.** Implement `CacheManager` in `src/ytb_pipeline/pkg/cache.py`
   exposing `get(type, provider, model, params, prompt) -> Path | None` and
   `put(type, provider, model, params, prompt, data: bytes) -> Path`, backed
   by the key derivation in §2, storage layout in §4, and registry in §5.
   Pure, fully unit-testable (no real provider calls needed — tests pass
   raw bytes through `put`/`get`).
2. **Phase B.** Migrate `voiceover/tts.py`'s existence check to
   `CacheManager.get(type="tts", ...)`, replacing the path-existence
   `if`/`skip` with a cache lookup; on miss, synthesize then `put`.
3. **Phase C.** Migrate `render/compose.py` equivalently for `image` and
   `video_clip` types.
4. **Phase D.** Add the LLM response cache to the ideation/research call
   sites, gated behind a config flag (`llm_cache_enabled: bool = True`) so
   it can be disabled for explicitly-non-deterministic exploratory runs
   (e.g., deliberately wanting fresh ideation variety) without code changes.
5. **Phase E.** Add eviction (§8) and cache warming (§7) once the manager is
   live across all four types and real disk usage data exists to tune
   `MAX_CACHE_GB` defaults sensibly.

Acceptance for this migration: zero remaining `if path.exists(): skip`
patterns in stage modules; all cache reads/writes go through `CacheManager`;
`data/cache_registry.db` total size matches `du -sh assets/cache/` within
rounding.
