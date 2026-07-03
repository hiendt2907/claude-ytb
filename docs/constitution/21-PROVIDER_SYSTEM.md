# 21 — Provider System

> Status: **AD HOC (string-flag if/else, no registry).** `settings.py`
> already has the *config surface* of a provider system
> (`tts_provider`, `render_provider`) but no actual `Provider` protocol,
> registry, or dependency-injection mechanism exists — call sites branch
> directly on the setting string. This document specifies the target system
> that every other engine in this constitution (`16`–`20`, `22`) is written
> against.

## 1. Purpose

Per `PROJECT_VISION.md` non-negotiable #4 ("Plugin providers for every
external capability... A provider is a plugin: discoverable, replaceable,
independently testable"), every external capability — LLM, TTS, image
generation, video generation, music, SFX, subtitles, publish targets — must
be selectable, swappable, and testable without touching the engine that
consumes it. The Provider System is the shared mechanism all of those
engines rely on, so it is specified once here rather than reinvented per
engine.

## 2. Current Implementation (Baseline)

```python
# config/settings.py
tts_provider: str = "edge"        # edge | elevenlabs | f5
render_provider: str = "slide"    # slide | ai
```

```python
# voiceover/tts.py
if settings.tts_provider == "f5":
    voiced = _synth_all_f5(script, slug)
else:
    voiced = []
    for i, seg in enumerate(script.segments):
        ...  # inline edge-tts call
```

This is a working but non-generalizable pattern: each call site that cares
about provider choice has its own `if settings.X_provider == "..."` branch.
Adding a third TTS provider means editing `tts.py`'s branching logic
directly; there is no shared registration mechanism, no `is_available()`
health check (today, picking `"f5"` when the F5 model isn't downloaded
fails deep inside `_synth_all_f5`, not at a clean boundary), and no way to
A/B two providers without writing a one-off script.

## 3. Provider Protocol Template

```python
"""src/ytb_pipeline/pkg/provider.py (planned) — shared base, all engine-
specific provider protocols (MusicProvider, SFXProvider, etc.) follow this
same shape, documented per-engine in files 16/17/18/20/22."""

from __future__ import annotations

from typing import Protocol, TypeVar

RequestT = TypeVar("RequestT")
ResultT = TypeVar("ResultT")


class Provider(Protocol[RequestT, ResultT]):
    """Generic shape every concrete provider protocol specializes.

    name        — stable identifier, matches the config string (e.g. "f5",
                  "edge", "musicgen") so registry lookup is a literal dict
                  key, not string-matching logic scattered per call site.
    is_local    — True if this provider runs fully offline. Used by the
                  local-first selection strategy (§7) — never inferred from
                  the name string.
    """

    name: str
    is_local: bool

    def is_available(self) -> bool:
        """Cheap, side-effect-free check: model file present, binary on
        PATH, API key set. MUST NOT raise — returns False on any doubt, so
        callers can iterate a fallback chain safely."""
        ...

    def run(self, request: RequestT) -> ResultT:
        """Do the work. MAY raise typed, specific exceptions (e.g.
        ProviderUnavailableError, ProviderQuotaError) — callers distinguish
        'this provider can't do this' from 'this provider broke' to decide
        whether to fall back or surface the error."""
        ...
```

## 4. Provider Registry

```python
"""src/ytb_pipeline/pkg/registry.py (planned)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProviderRegistry:
    """One registry per capability (TTS, LLM, Image, Video, Music, SFX,
    Subtitle, Publish) — never one global registry mixing capabilities,
    since a "tts_provider=f5" string must never collide with a
    "publish_provider=f5"-shaped typo. Each engine module owns its own
    registry instance."""

    _providers: dict[str, "Provider"] = field(default_factory=dict)

    def register(self, provider: "Provider") -> None:
        if provider.name in self._providers:
            raise ValueError(f"Provider đã đăng ký: {provider.name}")
        self._providers[provider.name] = provider

    def get(self, name: str) -> "Provider":
        try:
            return self._providers[name]
        except KeyError:
            raise KeyError(
                f"Provider '{name}' chưa đăng ký. Có: {list(self._providers)}"
            ) from None

    def available(self) -> list["Provider"]:
        """Providers that pass is_available() right now — used by the
        local-first selection strategy."""
        return [p for p in self._providers.values() if p.is_available()]
```

Example registration (TTS, mapping today's `tts.py` branch onto the
registry):

```python
"""src/ytb_pipeline/voiceover/registry.py (planned)."""

TTS_REGISTRY = ProviderRegistry()
TTS_REGISTRY.register(EdgeTTSProvider())
TTS_REGISTRY.register(F5TTSProvider())
TTS_REGISTRY.register(ElevenLabsProvider())
# Kokoro provider added here when implemented, per PROJECT_VISION.md target stack
```

## 5. Provider Selection (Config-Driven)

```python
"""src/ytb_pipeline/voiceover/tts.py (target shape, post-migration)."""

def synthesize(script: Script) -> Voiceover:
    provider = TTS_REGISTRY.get(settings.tts_provider)
    if not provider.is_available():
        raise ProviderUnavailableError(
            f"TTS provider '{provider.name}' không sẵn sàng "
            f"(model thiếu / API key trống / binary không có trên PATH)"
        )
    ...  # provider.run(request) per segment, identical shape regardless of provider
```

Selection is **always** explicit via settings — `settings.tts_provider`
remains the single source of truth for which provider runs, exactly as
today. The registry changes *how* that string resolves to working code
(dict lookup against registered providers) — it does not change *who*
decides (config, not runtime heuristics), preserving non-negotiable #2's
requirement that providers are "selected explicitly by config, never
silently substituted."

## 6. Dependency Injection

Providers are injected into engine functions as parameters, not imported
and resolved deep inside engine internals — this is what makes engines
independently testable with a fake provider:

```python
"""voiceover/tts.py — injected shape."""

def synthesize(script: Script, *, provider: "TTSProvider | None" = None) -> Voiceover:
    provider = provider or TTS_REGISTRY.get(settings.tts_provider)
    ...
```

```python
"""tests/voiceover/test_tts.py — example test enabled by injection."""

def test_synthesize_uses_injected_provider():
    fake = FakeTTSProvider(fixed_duration_sec=3.0)
    result = synthesize(some_script, provider=fake)
    assert result.duration_sec == 3.0 * len(some_script.segments)
```

This is the concrete mechanism that satisfies the Testing rule's
requirement for unit tests of individual functions without invoking real
edge-tts/F5/Ollama calls in CI.

## 7. Local-First Selection Strategy

```python
"""src/ytb_pipeline/pkg/local_first.py (planned)."""

def select_with_fallback(
    registry: ProviderRegistry, preferred: str, *, allow_cloud_fallback: bool = False,
) -> "Provider":
    """Resolves `preferred` from config. If unavailable AND
    allow_cloud_fallback is explicitly True, tries other registered
    providers in registration order, preferring is_local=True candidates
    first. Raises if nothing is available — never silently does nothing.

    allow_cloud_fallback defaults to False: per non-negotiable #2, cloud
    fallback is opt-in, not automatic. A caller that wants "try local,
    then cloud if local is down" must say so explicitly."""
    provider = registry.get(preferred)
    if provider.is_available():
        return provider
    if not allow_cloud_fallback:
        raise ProviderUnavailableError(
            f"'{preferred}' không sẵn sàng và allow_cloud_fallback=False"
        )
    candidates = sorted(registry.available(), key=lambda p: not p.is_local)
    if not candidates:
        raise ProviderUnavailableError("Không có provider nào sẵn sàng")
    return candidates[0]
```

## 8. Provider Health Check

`is_available()` is the contract every provider must implement honestly —
it is called before every `run()`, never assumed. Examples per capability:

| Provider | `is_available()` check |
|---|---|
| F5-TTS | Model checkpoint file exists under `models/vi-f5-tts/` and `.venv-tts` interpreter is reachable |
| Ollama/Qwen3 | `GET {OMNI_OLLAMA_BASE_URL}/api/tags`-equivalent ping succeeds, model name present in list |
| ElevenLabs | `elevenlabs_api_key` non-empty (cheap check; does not call the API just to check availability — that would burn quota) |
| MusicGen/AudioCraft | Local model weights present, MPS/CPU backend importable |
| YouTube publish | OAuth token file exists and is non-expired (or refreshable) |

## 9. Multi-Provider / A-B Testing

```python
"""src/ytb_pipeline/pkg/ab_test.py (planned)."""

def run_ab(request, providers: list["Provider"], judge) -> "Provider":
    """Runs `request` through each provider, scores results with `judge`
    (e.g. an LLM-as-judge call, or a deterministic metric like audio
    duration accuracy), returns the winning provider's result. Used for
    one-off comparison runs (e.g. "is F5 or Kokoro better for this voice
    style"), not wired into the default pipeline path — A/B is an
    explicit opt-in operator action, never automatic per-render behavior
    (that would make renders non-deterministic, violating the DAG/
    checkpoint contract)."""
    ...
```

## 10. Example Provider Protocols Per Capability

Each engine document specializes the generic `Provider` protocol for its
own request/result types — listed here for cross-reference:

| Capability | Protocol | Defined in |
|---|---|---|
| LLM | `LLMProvider` | (ideation stage; planned alongside Ollama/Qwen3 migration) |
| Image | `ImageProvider` | (planned, Flux/SDXL migration) |
| Video | `VideoProvider` | (planned, Wan2.2 migration) |
| Voice | `TTSProvider` | `voiceover/provider.py` (planned) |
| Music | `MusicProvider` | `16-MUSIC_ENGINE.md` §3 |
| SFX | `SFXProvider` | `17-SFX_ENGINE.md` §4 |
| Subtitle | `SubtitleProvider` | `18-SUBTITLE_ENGINE.md` §4 |
| Render visual source | (no separate protocol; a `Clip` producer feeding `19-RENDER_ENGINE.md`) | — |
| Publish | `PublishProvider` | `20-PUBLISH_ENGINE.md` §3 |

## 11. Current State

- `tts_provider`/`render_provider` settings exist; no `Provider` protocol,
  no registry, no `is_available()` checks anywhere in the codebase.
- Provider selection is inline `if`/`else` in `tts.py`; render strategy
  selection is inline in whatever orchestrates `compose.py` vs
  `compose_ai.py` (not shown above, but same pattern).
- No dependency injection — engine functions call provider-specific
  internals directly rather than accepting an injected provider parameter.
- No A/B testing mechanism.

## 12. Migration Notes

1. **Define `Provider` base protocol** in `pkg/provider.py` — generic,
   capability-agnostic.
2. **Wrap existing TTS branch** as `EdgeTTSProvider`/`F5TTSProvider` behind
   `TTSProvider`, register in `TTS_REGISTRY`, replace `tts.py`'s `if/else`
   with a registry lookup. Zero behavior change at this step.
3. **Wrap existing render-strategy branch** similarly (`SlideRenderProvider`
   / `BrollRenderProvider`), feeding into the Timeline model from
   `19-RENDER_ENGINE.md`.
4. **Add `is_available()` to each wrapped provider** — surfaces config
   errors (missing F5 model, missing Pexels key) at the registry boundary
   instead of deep inside `_synth_all_f5`/`stock.fetch_broll`.
5. **Add dependency injection parameters** to `synthesize()`/render
   functions so unit tests can pass fakes — required to meet the 80%
   coverage bar without invoking real external models in every test run.
6. **Build out registries for Music/SFX/Subtitle/Publish** as those
   engines are implemented (`16`, `17`, `18`, `20`).
7. **Local-first fallback wiring** — apply `select_with_fallback` once
   ≥2 providers per capability exist (today only TTS has 2+: edge/f5/
   elevenlabs).
</content>
