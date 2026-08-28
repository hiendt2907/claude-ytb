# Production Readiness Gap Report — 2026-08-28

Status: **read-only audit complete; findings intentionally not implemented**.

This report follows the completed AI-engine feature work through Phase 13. It
audits the repository as it exists on `codex/phase13-operator-disposition` and
is the input to the next **Production Readiness Phase**, not a Phase 14 AI
feature backlog.

## Executive conclusion

The engine has durable planning, visual preparation, semantic QC, bounded
recovery, operator disposition, deterministic timeline/audio/subtitle
composition, render checkpoints and YouTube publishing code. Its automated
suite proves those boundaries mostly with isolated fakes plus real local
FFmpeg. It does **not** yet prove one current production profile can traverse
the entire real Topic -> Long -> derived Short -> providers -> render ->
YouTube journey on a cleanly configured operator machine without code edits.

The principal P0 is therefore validation and configuration closure, not a
missing AI agent. Phase 13 findings below must not be interpreted as authority
to redesign the frozen v1 engine.

## Evidence reviewed

- `Makefile`, `scripts/setup.sh`, `requirements.txt`, `.env.example`,
  `config/settings.py`
- batch CLI, queue/workers, preflight, doctor, checkpoints and WorkflowGraph
- xKiro LLM/TTS/Vision, ComfyUI story generation and provider registry
- story ScenePlan/visual preparation/review/Timeline/render paths
- YouTube OAuth/upload, Drive backup and post-success cleanup
- the Phase 1–13 test and handoff corpus, including the offline FFmpeg E2E
  (`tests/test_e2e_pipeline.py`)

## A. End-to-End workflow

### P0 — No single proven real-provider Long + derived Short journey

The pieces exist, but no checked-in test or durable smoke report demonstrates
one topic traversing real xKiro ideation, real xKiro TTS, Director/ScenePlan,
real ComfyUI candidates, real xKiro Vision, recovery/review, story render,
render quality and YouTube publish as one run. `tests/test_e2e_pipeline.py`
uses real FFmpeg but generated tone audio, a synthetic local B-roll clip,
`DRY_RUN=true`, and forbids all network calls. This blocks an honest v1
production-ready claim.

### P0 — The production admission gate is not a complete provider/profile gate

`preflight_script()` validates script/profile, TTS/render availability, local
assets, thumbnail, duration and disk. It does not preflight the effective
story profile's Vision Judge model capability, all ComfyUI SDXL/IPAdapter
models, Director provider/model, configured local audio files, or YouTube
publish credentials before a long run. Some of these fail later at their
component boundaries, but the stated operator goal is failure before expensive
work.

### P1 — Topic-to-script and pipeline execution remain two operational surfaces

The batch ideation/approval flow creates scripts and the per-project DAG
executes approved scripts. This is deliberate architecture, but the real
operator journey still needs a documented, rehearsed command sequence and a
durable run report tying a Long and its derivative Short together.

## B. External providers

### xKiro LLM — P0 verification gap

The adapter is explicit, bounded and unit-tested with mocked transport. The
default configured model is `deepseek/deepseek-v4-pro`; failures stop rather
than silently switching creative providers. There is no current end-to-end
evidence that the configured credential/model completes both real Long
ideation and optional Director planning within production limits.

### xKiro TTS — P0 verification gap

The adapter has retry/error handling and resumable segment outputs, with
mocked tests. The complete real Long voiceover, concat/loudness path and timing
contract have not been exercised together with the current cloud credential
in the final DAG.

### xKiro Vision — P1 operational dependency

Phase 11 proved a real blue-triangle smoke against an xKiro model advertising
vision capability, and production transport/schema/error mapping are tested.
Vision remains profile opt-in and depends on the live model catalog; the
doctor does not currently report the effective profile's Judge provider/model
and capability. Cached evaluations limit repeated cost but do not remove this
operational dependency.

### ComfyUI — P0 machine-readiness gap

The story adapter checks server/workflow/model requirements at its boundary
and has mocked tests, but repository setup does not install ComfyUI, SDXL,
IPAdapter, CLIP Vision or their model files. A clean machine cannot become a
story-generation worker from `make setup` alone. The exact production
workflow/model inventory must be verified on the target Mac before the first
real run.

### YouTube — P0 live publication proof gap

Upload uses resumable `videos.insert`, thumbnail, playlist and CTA-comment
steps; OAuth refresh and explicit interactive re-auth exist. Automated tests
mock Google APIs. No final-engine-era evidence proves the current OAuth client,
brand-channel token, quota, channel permissions, thumbnail eligibility,
playlist and synthetic-media payload in one live publish. The first production
milestone may use private visibility, but must verify the resulting YouTube ID
through the repository's existing verify command.

## C. Installation

### P0 — Setup contract is stale relative to the current engine

`scripts/setup.sh` still describes Edge as default and requires Claude Code
CLI for ideation, while current settings/policy use xKiro for LLM/TTS. It does
not install or validate the story ComfyUI stack. The script also advertises
`make run`, but the current `Makefile` has no `run` target. These are concrete
clean-machine blockers/confusions.

### P1 — Python dependencies are not reproducibly locked

`requirements.txt` uses broad lower bounds and includes legacy/optional large
dependencies. There is no lock file or exact Python version declaration.
Two clean installs can resolve different dependency sets, so `make test`
success on this machine is not a reproducible release artifact.

## D. Configuration

### P0 — No one-command effective production configuration validation

Pydantic catches field-level settings errors and content profiles have strict
contracts, but relevant values are split across `.env`, profile JSON, project
script, local model inventory and OAuth files. `doctor --local`, normal doctor
and preflight each cover different subsets. None produces one effective
Long/Short readiness result before execution.

### P1 — Documentation/config defaults contain legacy contradictions

Examples include setup comments about Edge/Claude, local doctor labels for
older providers, and older `make run` guidance. These increase operator error
risk even though runtime settings are centralized.

## E. Secrets

### P1 — Storage is safe by convention, not backed by a complete audit command

API keys remain in `.env`; OAuth material is under ignored `secrets/`; project
artifacts and logs do not intentionally persist keys or image base64. This is
sound. The setup script asks for some obsolete/optional providers and does not
guide xKiro configuration consistently. There is no release-time secret scan
or permission check for `.env`/OAuth token files.

## F. Resume / restart

### Proven behavior

- Project nodes, ScenePlan, VisualManifest, candidate slots, evaluations and
  Phase-13 review/manual slots persist.
- A process/provider failure can resume valid completed work; manual generation
  retries only failed slots.
- Review and abandon are explicit checkpoints; changed VisualRequest identity
  makes old decisions stale.

### P1 — Kill/reboot durability is strongly unit-tested but not chaos-tested

Atomic replace and sidecar locks protect individual JSON stores. There is no
real process-kill/Mac-reboot exercise spanning simultaneous registry,
candidate, evaluation, review and project checkpoint writes. A disk-full or
I/O failure between cross-file commits can leave artifacts mutually
incomplete; component validation generally fails closed, but recovery has not
been rehearsed as an operator procedure.

### P1 — Provider outage recovery lacks a full operational drill

Retries and cached checkpoints exist at adapters and visual slots, but no real
outage/restart drill proves batch worker/ledger/project state converge after
xKiro or ComfyUI returns.

## G. Operator experience

### P1 — The visual-review CLI is complete, the overall production journey is not

Phase 13 provides list/show/accept/regenerate/abandon without Python or direct
JSON edits. Elsewhere, profile creation, prompt changes, script diagnosis,
local model installation and some recovery still require filesystem/Python
knowledge. The batch commands are numerous and the canonical first-run/runbook
is not consolidated.

### P1 — State visibility is split

Batch status/logs, `project.json`, quality reports, review CLI, ledger and
provider smoke commands each answer part of “what is running and what does it
need?” A single UI is not required for v1, but a concise operator runbook and
state matrix are.

## H. Storage

### P1 — Unbounded durable visual growth

Candidate rounds (up to eight automated assets per Shot), one manual candidate
set, generation cache, evaluation history, review history, ScenePlans,
manifests, audio and outputs accumulate. AssetRegistry garbage collection was
explicitly deferred. The repository currently contains thousands of files
under `assets`, demonstrating that this is an operational rather than
theoretical concern.

### P2 — Retention/capacity policy

Post-publish cleanup removes selected local audio/thumbnail and one render
workspace after successful Drive backup, but it does not provide retention or
capacity limits for candidates, caches, registry history, abandoned projects
or old outputs. Define thresholds only after measuring the first production
runs; do not delete provenance blindly.

## I. Observability

### P1 — No correlated per-project event record across all stages/providers

There are console logs, batch logs, project/checkpoint states, warnings,
quality reports and explicit Phase-13 states. Candidate/Judge/review logs are
concise and avoid secrets/binary payloads. There is no single structured event
stream correlating provider call, stage, Shot, retry, elapsed time and terminal
operator need.

### P2 — No dashboard is required for the first run

Existing CLI/log artifacts are sufficient to execute a supervised smoke if a
runbook specifies where to look. A dashboard should wait for observed needs.

## J. Cost / usage

### P1 — No durable usage/cost accounting

The engine structurally bounds Director/Judge repair, candidate count,
autonomous recovery and manual regeneration, and caches expensive results.
It does not persist per-project LLM tokens, TTS characters/audio seconds, VLM
calls/image bytes, ComfyUI generations or estimated provider cost. Operators
cannot reconcile actual usage after a batch. Billing integration is not
required; basic counters are a production-readiness concern.

## K. Publishing

### P0 — Current account/quota/private-publish path is unproven end to end

`DRY_RUN=true` is the safe default. Real publish additionally depends on
monetization validation, OAuth scopes/refresh, channel authorization, quota,
playlist configuration, optional thumbnail and Drive backup. Tests prove API
construction and error cases with mocks, not current account readiness.

### P1 — Partial post-upload failure needs a rehearsed reconciliation procedure

A video can upload before thumbnail/playlist/comment/Drive or ledger work
fails. Some operations are best-effort and existing verify/reconciliation
commands help, but the exact “uploaded remotely, local node not DONE” recovery
path should be exercised without producing duplicate uploads.

## L. Release / versioning

### P1 — No explicit v1 release artifact or migration policy

Several domain contracts carry version fields and readers preserve backward
compatibility, but the package itself has no declared release version/lock and
no consolidated migration matrix for `project.json`, ScenePlan, candidates,
evaluations, review and profile schema. Auto-update/rollback exists, but a v1
tag plus compatibility checklist is needed before unattended production.

## M. Test gaps

### P0

- No real-provider full Long + derivative Short + publish acceptance run.
- No current-machine ComfyUI workflow/model acceptance evidence tied to a real
  profile and final visual pipeline.
- No live YouTube private publish/verify evidence for the current OAuth setup.

### P1

- External adapter tests are intentionally mocked in `make test`; xKiro Vision
  has a separate real smoke, but LLM/TTS/full-DAG live smokes are not assembled.
- Process-kill, reboot, disk-full and cross-file interruption behavior lacks a
  fault-injection/operational test.
- The offline E2E covers legacy AI B-roll composition, not the complete
  character-story Director/candidate/Judge/review/prepared-render path.

## N. Exact first real production smoke

Run this in the Production Readiness Phase, not Phase 13:

1. Select one current `character_story` profile with an authorized xKiro LLM,
   xKiro TTS, an xKiro model whose catalog reports `vision=true`, and a verified
   local ComfyUI SDXL/IPAdapter workflow.
2. Configure a private YouTube publish target, validated OAuth/Drive tokens,
   deterministic local audio (or narration-only), and sufficient disk.
3. From one real topic, use normal batch commands to generate and approve one
   Long script plus its repository-defined derivative Short—no source/profile
   edits after execution starts.
4. Run preflight/doctor, then the normal checkpointed DAG. Record provider/model
   identities, project state, calls/generations, review state if any, final
   media probes, subtitle/audio invariants and output paths.
5. If semantic automation stops, resolve it only through
   `ytb batch review ...`, resume, and prove no accepted work regenerates.
6. Publish both videos privately (or, if a genuine operator-resolvable state is
   reached, record that state), verify remote IDs through the existing verify
   command, and confirm no duplicate upload after rerun.

The first success criterion is exactly:

> Starting from one real topic/configuration, produce a real Long video and
> derivative Short using real providers, with no code edits during execution,
> and either publish or reach an explicit operator-resolvable state.

## Prioritized next-work list

### P0 — blocks the first real E2E

1. Reconcile setup/run documentation and make the target Mac's ComfyUI model
   inventory an explicit prerequisite.
2. Add one effective profile/provider preflight result covering xKiro
   LLM/TTS/Vision, ComfyUI assets, local audio and publish credentials.
3. Execute and preserve evidence for the exact real smoke above, fixing only
   concrete production-readiness defects it exposes.

### P1 — required before v1 release

1. Pin a reproducible Python environment and declare supported Python/macOS.
2. Exercise kill/reboot/provider-outage and partial-publish reconciliation.
3. Add a production operator runbook/state matrix and basic durable usage
   counters.
4. Define storage thresholds/retention and a migration/release checklist.

### P2 — may ship after v1

1. Unified observability dashboard.
2. Automated retention/garbage collection after provenance-safe rules exist.
3. Broader platform automation and convenience UX.

## Recommended next workstream

**Production Readiness Phase.** Freeze the v1 AI feature set, close the P0
configuration/install gaps, then run the exact supervised real-provider smoke.
No new agent, model, recovery loop or AI workflow is justified before that
evidence exists.
