# 26 — Configuration

> Current state: `src/ytb_pipeline/config/settings.py`, 78 lines, a single
> `pydantic_settings.BaseSettings` subclass loaded from `.env`, exposed as
> the module-level singleton `settings`. This document specifies the target
> configuration system that extends it — validators, platform profiles, and
> per-project override — without breaking the existing fail-fast-at-startup
> pattern already established (`CLAUDE.md`: "Config — fail fast tại ranh
> giới").

## 1. Configuration Hierarchy

Precedence, lowest to highest (later overrides earlier):

1. **Defaults** — hardcoded field defaults in the `Settings` class itself
   (e.g., `tts_provider: str = "edge"` today; per `PROJECT_VISION.md`'s
   local-inference-priority decision, target defaults flip to local
   providers — see `29-MIGRATION_PLAN.md` Phase 1).
2. **`.env`** — loaded by `pydantic_settings.SettingsConfigDict(env_file=".env")`,
   already wired. Machine-/operator-level configuration (API keys, paths,
   provider choice for this machine).
3. **CLI args** — explicit flags on a given invocation
   (`ytb run --tts-provider f5`) override `.env` for that run only, never
   persisted back to `.env`.
4. **Runtime override** — programmatic override for the duration of a
   single in-process call (used by tests, by the listener daemon dispatching
   a one-off command with a different flag set than its own `.env`). Highest
   precedence, never persisted anywhere.
5. **Per-project override** (§4) sits conceptually between `.env` and CLI
   args: a `project.json`-declared override beats the machine `.env` default
   but is itself overridable by an explicit CLI flag for a one-off run.

Resolution order in code, therefore: `CLI args > runtime override > project.json override > .env > field defaults`.
(Runtime override is listed above CLI args in capability but in practice is
only used by callers — like tests — that bypass the CLI entirely, so the two
never actually compete within one invocation path.)

## 2. Pydantic-Settings — Current + Validators

Current `Settings` (excerpted, see `src/ytb_pipeline/config/settings.py` for
the authoritative full field list) covers TTS, Telegram, render, YouTube,
paths, Drive, behavior, and listener fields as plain typed fields with
defaults, with no field or model validators today (`extra="ignore"` is the
only configuration knob set beyond `env_file`).

Target additions — validators that turn silent misconfiguration into a
startup failure:

```python
from pydantic import field_validator, model_validator

class Settings(BaseSettings):
    # ...existing fields...

    @field_validator("tts_provider")
    @classmethod
    def _validate_tts_provider(cls, v: str) -> str:
        allowed = {"edge", "elevenlabs", "f5"}
        if v not in allowed:
            raise ValueError(f"tts_provider must be one of {allowed}, got {v!r}")
        return v

    @field_validator("render_provider")
    @classmethod
    def _validate_render_provider(cls, v: str) -> str:
        allowed = {"slide", "ai"}
        if v not in allowed:
            raise ValueError(f"render_provider must be one of {allowed}, got {v!r}")
        return v

    @model_validator(mode="after")
    def _validate_elevenlabs_key_present_if_selected(self) -> "Settings":
        if self.tts_provider == "elevenlabs" and not self.elevenlabs_api_key:
            raise ValueError(
                "tts_provider='elevenlabs' requires elevenlabs_api_key to be set"
            )
        return self

    @model_validator(mode="after")
    def _validate_pexels_key_present_if_ai_render_uses_stock(self) -> "Settings":
        if self.render_provider == "ai" and self.broll_strategy == "pexels" and not self.pexels_api_key:
            raise ValueError(
                "broll_strategy='pexels' requires pexels_api_key to be set"
            )
        return self

    @model_validator(mode="after")
    def _validate_youtube_publish_at_format(self) -> "Settings":
        if self.youtube_publish_at:
            from datetime import datetime
            try:
                datetime.fromisoformat(self.youtube_publish_at)
            except ValueError as exc:
                raise ValueError(
                    f"youtube_publish_at must be RFC3339, got {self.youtube_publish_at!r}"
                ) from exc
        return self
```

Every validator raises `ValueError` (which `pydantic_settings` surfaces as a
`ValidationError` at `Settings()` construction time — i.e., at process
startup, before any pipeline stage runs), preserving the existing fail-fast
contract: a misconfigured `.env` must never be discovered three stages into
a run.

## 3. Config Variable Reference

| Variable | Type | Default | Purpose | Example |
|---|---|---|---|---|
| `tts_provider` | `str` | `"edge"` | Selects voice synthesis adapter. | `f5` |
| `elevenlabs_api_key` | `str` | `""` | ElevenLabs API credential, required iff `tts_provider="elevenlabs"`. | `sk_...` |
| `telegram_bot_token` | `str` | `""` | Bot token for the script-approval gate and listener daemon. | `123456:ABC-DEF...` |
| `telegram_chat_id` | `str` | `""` | Chat ID approvals/commands are sent to/from. | `987654321` |
| `telegram_approval` | `bool` | `True` | Gate ideation output behind a Telegram approval step. | `false` |
| `render_provider` | `str` | `"slide"` | Selects render strategy (`slide` static, `ai` B-roll/generated visuals). | `ai` |
| `orientation` | `str` | `"portrait"` | Output aspect: `portrait` (1080x1920 Short) or `landscape` (1920x1080). | `landscape` |
| `pexels_api_key` | `str` | `""` | Stock B-roll credential; required only when explicitly opted into the Pexels fallback strategy. | `563492...` |
| `show_captions` | `bool` | `False` | Toggle lower-third spoken-word captions. | `true` |
| `pause_comma_ms` | `int` | `250` | Pause inserted after commas/semicolons/colons in TTS. | `300` |
| `pause_sentence_ms` | `int` | `400` | Pause after sentence-ending punctuation. | `450` |
| `pause_segment_ms` | `int` | `500` | Pause between narration segments. | `600` |
| `youtube_api_key` | `str` | `""` | Public read-only key for trending research (`videos.list`). | `AIza...` |
| `youtube_client_secrets` | `str` | `"secrets/client_secret.json"` | OAuth client secrets path for upload. | unchanged |
| `youtube_token_file` | `str` | `"secrets/youtube_token.json"` | Cached OAuth token for YouTube uploads. | unchanged |
| `drive_token_file` | `str` | `"secrets/drive_token.json"` | Cached OAuth token for the separate personal Drive backup account. | unchanged |
| `youtube_privacy` | `str` | `"private"` | Upload visibility: `private`, `unlisted`, `public`. | `unlisted` |
| `youtube_category_id` | `str` | `"28"` | YouTube category (28 = Science & Technology). | `27` |
| `youtube_publish_at` | `str` | `""` | RFC3339 scheduled-publish timestamp; empty = no scheduling. | `2026-07-01T06:00:00+0700` |
| `youtube_contains_synthetic_media` | `bool` | `True` | Declares AI-generated content per YouTube's 2024 transparency policy. | `false` (only if a video genuinely has no AI content) |
| `assets_dir` | `Path` | `Path("assets")` | Root for generated artifacts. | `Path("/Volumes/Fast/assets")` |
| `output_dir` | `Path` | `Path("assets/output")` | Final rendered video output location. | unchanged |
| `drive_backup` | `bool` | `True` | Move uploaded video to Drive then delete local copy. | `false` |
| `drive_folder` | `str` | `"Claude-YTB"` | Target Drive folder name. | `MyChannel` |
| `dry_run` | `bool` | `True` | Master safety switch: render-only, no real publish call. | `false` (production publish) |
| `claude_bin` | `str` | `"claude"` | Binary invoked by the listener daemon per command. | `/usr/local/bin/claude` |
| `listener_claude_args` | `str` | `"--dangerously-skip-permissions"` | Extra flags passed to each `claude -p` session. | `""` |
| `listener_skill` | `str` | `"/youtube-auto"` | Skill prefix wrapping the `/auto` listener command. | unchanged |
| `listener_allow_shell` | `bool` | `True` | Permits the `/sh` listener command to run arbitrary shell. | `false` (hardened deployment) |

## 4. Platform Profiles

A `PlatformProfile` enum (see `04-DOMAIN.md` for the canonical domain
definition once written) selects a coherent bundle of render/publish
defaults rather than requiring six independent settings to be set correctly
together:

| Profile | Orientation | Duration cap | Caption default | Publisher |
|---|---|---|---|---|
| `youtube_short` | portrait | ≤60s | off (per current channel style) | YouTube (Shorts shelf) |
| `youtube_long` | landscape | 8–15 min | off | YouTube (long-form) |
| `tiktok` | portrait | ≤60s | on (platform convention) | TikTok (planned, `29-MIGRATION_PLAN.md` Phase 4) |
| `instagram_reel` | portrait | ≤90s | on | Instagram (planned) |
| `podcast` | n/a (audio-only) | unbounded | n/a | RSS/audio host (planned) |
| `blog` | n/a (text-only) | unbounded | n/a | Static site/CMS export (planned) |

A profile is a named override bundle, resolved at the same precedence layer
as CLI args (`ytb run --platform tiktok` sets `orientation`, caption
defaults, and selects the `Publisher` adapter together, instead of three
separate flags that could be set inconsistently). Profiles never introduce
new fields outside the existing `Settings` schema — they are a convenience
layer that sets existing fields to a known-good combination for that
platform.

## 5. Per-Project Config Override

`project.json` may declare a `config_overrides` object holding any subset of
`Settings` fields, scoped to that project only:

```json
{
  "id": "proj_2026_06_29_loss_aversion",
  "config_overrides": {
    "tts_provider": "f5",
    "pause_sentence_ms": 500
  }
}
```

Resolution: when a pipeline stage needs a setting for a given project, it
resolves `project.config_overrides.<field>` if present, else falls back to
the global `settings.<field>`. This lets one project deliberately use a
different voice or pacing without mutating `.env` (which would affect every
other concurrent/future project) and without a CLI flag (which a resumed run
days later wouldn't remember to repeat). `config_overrides` is validated
against the same `Settings` field types/validators at load time — an invalid
override fails the same way an invalid `.env` value would, at the earliest
point the project is loaded, not mid-pipeline.

## 6. Secrets Management

Current: plaintext files under `secrets/` (`client_secret.json`,
`youtube_token.json`, `drive_token.json`), already `.gitignore`d per
`CLAUDE.md`. API keys (`elevenlabs_api_key`, `pexels_api_key`,
`youtube_api_key`, `telegram_bot_token`) live in `.env`, also gitignored.

This is acceptable for a single-operator local-first tool (no shared
credential store needed when there's one machine and one user) but is the
weakest link if the machine itself is compromised or backed up
unencrypted.

Roadmap:

1. **Now:** keep `secrets/` + `.env`, enforce via `.gitignore` and a
   startup validator (§7) that the directory exists with correct
   permissions (`0700`) rather than silently failing on first real API call.
2. **Near-term:** add a `SecretsProvider` port (mirroring the `Provider`
   pattern from `02-PRINCIPLES.md`) with a `FileSecretsProvider` (today's
   behavior) as the default adapter, so the read path is already abstracted
   before a second adapter exists.
3. **Target:** add a `KeychainSecretsProvider` adapter using macOS Keychain
   Services (via the `keyring` package) as the opt-in, more secure default
   for a single-machine deployment — consistent with "runs primarily on a
   MacBook Pro M4" from `PROJECT_VISION.md`, since Keychain is a local,
   offline-first OS facility, not a cloud vault.
4. **Multi-machine future (not currently planned):** a
   `VaultSecretsProvider` (HashiCorp Vault or 1Password CLI) only becomes
   relevant if the system ever runs across more than one operator-controlled
   machine — explicitly YAGNI today per `02-PRINCIPLES.md`.

## 7. Validation — Startup Checks

Beyond field-level validators (§2), a `validate_environment()` startup
routine runs before the pipeline accepts any work, checking conditions
`pydantic` field validation cannot express alone because they depend on the
external environment, not just the config values themselves:

- **Provider availability.** If `tts_provider="f5"`, confirm the F5-TTS
  model weights/binary are present and loadable. If `render_provider="ai"`
  with a local diffusion provider selected, confirm the local model server
  (e.g., ComfyUI) is reachable. Cloud fallbacks get an equivalent
  reachability check (e.g., a lightweight authenticated ping) rather than
  discovering a bad API key on the first real, expensive call.
- **API keys valid.** Where a cheap validation call exists (e.g., YouTube
  API key against a trivial read endpoint), call it at startup if
  `dry_run=False`, skip it under `dry_run=True` to keep dry runs fully
  offline-capable.
- **Disk space.** Confirm `assets_dir`'s filesystem has at least a
  configurable minimum free space (default 5 GB) before starting a run that
  will write audio/video — failing fast here avoids a multi-minute render
  dying at 90% on `ENOSPC`.
- **Secrets directory permissions.** Confirm `secrets/` exists and is not
  world-readable.

`validate_environment()` runs once per process start (CLI entrypoint and
listener daemon startup both call it) and raises a clear, actionable error
listing every failed check at once — not just the first one — so a
freshly-cloned machine setup surfaces all missing prerequisites in one pass.

## 8. Current State

`src/ytb_pipeline/config/settings.py` — 78 lines, single `Settings` class,
`.env`-backed, `extra="ignore"`, no field/model validators, no platform
profiles, no per-project override, secrets in plaintext files. This is a
correct, simple starting point; the gaps above are additive, not corrective
— nothing in the current file needs to be removed, only extended.

## 9. Migration

1. **Phase A.** Add field/model validators (§2) to existing fields — purely
   additive, no field removed or renamed; verify via a test that
   constructing `Settings` with each known-bad combination raises
   `ValidationError`.
2. **Phase B.** Add `validate_environment()` (§7) and wire it into the CLI
   entrypoint and listener daemon startup.
3. **Phase C.** Add `PlatformProfile` enum and profile-to-settings
   resolution (§4), exposed via `--platform` CLI flag.
4. **Phase D.** Add `config_overrides` support to `project.json` loading
   (§5), once `project.json` itself exists per `04-DOMAIN.md`/
   `29-MIGRATION_PLAN.md` Phase 2.
5. **Phase E.** Introduce `SecretsProvider` abstraction (§6) and the
   Keychain adapter as an opt-in alternative to plaintext `secrets/`.

Acceptance: every `.env` misconfiguration that previously surfaced as a
runtime exception mid-pipeline now surfaces as a `ValidationError` (or a
`validate_environment()` failure) before any provider call is made.
