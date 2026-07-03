# 36 — AI GOVERNANCE

## Purpose

`02-PRINCIPLES.md` and `05-WORKFLOW.md` already establish quality gates and
human-approval checkpoints as part of the pipeline's failure-handling
contract. This document elevates that into a formal governance model:
every AI-generated output in this system must be **traceable** (who/what/
when produced it), **validated** (checked before being trusted downstream),
and **reproducible** (re-derivable for audit or regression purposes), and a
human must always retain override authority. This is the project's answer
to "how do we know the AI didn't quietly make something up, and how would
we prove it if asked" — relevant even for a solo-creator tool, because the
creator is themselves the human who needs to trust what got published under
their name.

---

## Section 1 — Governance Principles

1. **Every AI output must be traceable to its inputs** — the exact prompt
   text, model identity and version, generation parameters, and timestamp
   that produced it. An advisory, a script, or a generated image with no
   recorded provenance is not auditable, and per `02-PRINCIPLES.md`'s
   validate-at-the-boundary stance, an unauditable output should not be
   trusted to flow downstream silently.
2. **Every AI output must be validated before use** — against a schema (it
   parses into the dataclass it claims to be), a quality gate (length,
   pacing, niche relevance per `05-WORKFLOW.md`), and a content policy (no
   banned framing, no unverified factual claims presented as fact). "The
   LLM returned something" is never itself sufficient confirmation that the
   something is usable.
3. **Every AI decision must be reproducible** — given the same prompt,
   model, and generation parameters (including seed where supported), the
   system should be able to re-run the call and get an output within a
   defined tolerance of the original, sufficient for regression testing and
   for post-hoc review of why a particular decision was made.
4. **A human must be able to override any AI decision at any stage.** This
   is not a new rule — it is `05-WORKFLOW.md`'s human-approval gates and
   `32-STATE_MACHINE.md`'s `APPROVED` state restated as a governance
   principle: no AI output's path to publication is unconditional.

---

## Section 2 — Traceability Model

### AITrace Dataclass

```python
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class AITrace:
    """Provenance record for a single LLM (or other generative) call."""
    trace_id: str               # UUID4
    project_id: str
    stage: str                  # e.g. "ideation", "voiceover", "render" — matches WorkflowNode.name scope
    agent_name: str              # e.g. "story_architect", "quality_gate" (06-AGENTS.md)
    model: str                   # e.g. "qwen2.5-coder", "claude" (provider-neutral family name)
    model_version: str           # e.g. "qwen2.5-coder:7b-instruct-q4_K_M" — pinned, not a moving alias
    prompt_id: str               # 11-PROMPT_ENGINE.md registry id, e.g. "story_architect.build_structure"
    prompt_version: str          # semver of the prompt, per 11-PROMPT_ENGINE.md
    prompt_hash: str             # SHA-256 of the fully rendered prompt text
    input_hash: str              # SHA-256 of the variables dict passed to PromptRenderer
    output_hash: str             # SHA-256 of the raw output text/object
    latency_ms: int
    token_cost: int              # 0 for local inference; non-zero for metered cloud calls
    timestamp: datetime
```

Every field above is populated for **every** LLM call without exception —
this is enforced structurally by routing all LLM calls through a single
`LLMEngine.generate()` entrypoint (`10-LLM_ENGINE.md`) that wraps the
provider call and emits the `AITrace` as a side effect, rather than relying
on each call site to remember to log one. This mirrors the single-write-path
discipline `25-CHECKPOINT_SYSTEM.md` applies to checkpoints — one chokepoint
that cannot be bypassed, not a convention every caller must independently
honor.

### Storage: SQLite

```sql
CREATE TABLE ai_traces (
    trace_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    stage TEXT NOT NULL,
    agent_name TEXT NOT NULL,
    model TEXT NOT NULL,
    model_version TEXT NOT NULL,
    prompt_id TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    output_hash TEXT NOT NULL,
    latency_ms INTEGER NOT NULL,
    token_cost INTEGER NOT NULL DEFAULT 0,
    timestamp TEXT NOT NULL
);
CREATE INDEX idx_ai_traces_project ON ai_traces (project_id, stage);
CREATE INDEX idx_ai_traces_output_hash ON ai_traces (output_hash);
```

Path: `assets/traces.db`, the same SQLite store introduced for the Asset
Graph's adjacency list (`33-GRAPH_MODELS.md` §1) — one queryable metadata
database per project rather than a proliferation of single-purpose files,
consistent with ADR-005's reasoning (`31-ADR.md`) for introducing SQLite
only once a query need (not just a log need) exists.

### Example Query

> "Which model generated the script for episode 42?"

```python
traces = trace_store.query(project_id="proj_episode_42", stage="ideation", agent_name="story_architect")
# -> [AITrace(model="qwen2.5-coder", model_version="qwen2.5-coder:7b-instruct-q4_K_M", ...)]
```

### Link to Asset Graph

`AITrace.output_hash` is the same hash family used as `Asset.content_hash`
in the Asset Graph (`33-GRAPH_MODELS.md` §1) — an `Asset` produced by an LLM
call (e.g., a generated script's text, eventually wrapped as an `Asset`) can
be joined back to the exact `AITrace` that produced it via
`output_hash`, making "show me the full provenance chain for this published
script" a two-table join (`ai_traces` ⋈ `asset_edges`/asset metadata), not a
manual reconstruction.

---

## Section 3 — Validation Gates

Three independent validation layers, applied in this order, each a hard gate
(failure stops forward progress, per `05-WORKFLOW.md`'s failure-mode tables
— it does not silently pass through):

1. **Schema validation.** The LLM's raw output must parse into the exact
   dataclass its `output_schema_ref` (`11-PROMPT_ENGINE.md`) declares. This
   is structural correctness only — "is this the right shape" — checked via
   the project's existing dataclass-construction validation
   (`02-PRINCIPLES.md` "validate at the edge"), not Pydantic (per ADR-001,
   `31-ADR.md`).
2. **Quality gate.** `ComplianceChecker` (compliance rules,
   `02-PRINCIPLES.md`/niche policy), `NicheGate` (relevance to the
   `Project.niche`), and `LengthGate` (duration/word-count tolerance,
   `05-WORKFLOW.md`'s Script node precedent) — each is a deterministic,
   non-LLM check over the already-schema-valid output. These three gates
   are the concrete implementation of "quality gate" referenced throughout
   `05-WORKFLOW.md` and `32-STATE_MACHINE.md`'s `SCRIPTED → APPROVED` guard.
3. **Content policy.** No self-help mantras (a documented niche-quality
   anti-pattern per `02-PRINCIPLES.md`), no unverified claims presented as
   settled fact without a `Research.sources` citation backing them, no
   patterns resembling copyrighted text reproduction. This is the layer most
   likely to require human judgment calls the automated checks cannot fully
   resolve — which is precisely why it feeds into, rather than replaces, the
   human approval gate (§4 of `32-STATE_MACHINE.md`'s `SCRIPTED` state).

### Human Approval

The Telegram gate (current, per ADR-007 `31-ADR.md`) remains the final
governance checkpoint at the `SCRIPTED → APPROVED` transition
(`32-STATE_MACHINE.md`). An "auto-approve for trusted templates" mode is an
explicit opt-in configuration, never a default — it exists for a creator who
has, over many episodes, established enough trust in a specific
prompt/template combination's reliability to skip per-episode review, and it
remains fully reversible (a config flag, not a code path deletion) and is
itself recorded as a governance-relevant `AITrace`-adjacent ledger entry
("auto-approved under template X, no human review") so that a published
piece with auto-approval is distinguishable in the audit trail from one a
human explicitly reviewed.

### Failure Protocol

A validation failure (any of the three gates) routes to human review — it
does **not** trigger an automatic retry with the identical prompt. This
mirrors `05-WORKFLOW.md`'s repeated distinction between transient failures
(retry-eligible) and structural failures (route to human, retrying with the
same inputs cannot produce a different structural outcome): a script that
fails the niche-relevance gate did not fail because of a flaky network call,
and resubmitting the same prompt to the same model is overwhelmingly likely
to fail the same gate again, wasting compute while looking productive.

---

## Section 4 — Reproducibility

### Deterministic Seeds

Local inference via Ollama supports an explicit `seed` parameter alongside
`temperature=0.0` (`10-LLM_ENGINE.md`'s `build_llm_options(ctx)` is extended
to accept and pass through a `seed` field). Setting both for any call that
needs reproducibility (regression tests, governance audits) makes "re-run
this exact call" a meaningful operation rather than an approximation —
without `temperature=0.0`, even a fixed seed leaves sampling randomness in
play.

### Prompt Versioning

Every `AITrace.prompt_hash` (§2) is the SHA-256 of the **fully rendered**
prompt text (post-Jinja2, per `35-PROMPT_DSL.md`) — not just the
`prompt_version` string. This distinction matters: two calls with the same
`prompt_id`/`prompt_version` but different `variables` (e.g., different
`topic`) produce different `prompt_hash`es, so reproducibility checks can
distinguish "same prompt template, different input" from "literally
identical request" without ambiguity.

### Model Pinning

Config specifies a fully-qualified model identifier — `qwen2.5-coder:7b-instruct-q4_K_M`,
never a bare `qwen2.5-coder` alias that could silently resolve to a
different quantization or checkpoint after a local Ollama model update.
This is the same reasoning `02-PRINCIPLES.md`'s general pinning guidance
already states for dependencies, applied here to model weights — an
unpinned model reference is a reproducibility hazard exactly like an
unpinned package version is a build hazard.

### Replay for Regression Testing

```python
def test_ideation_output_is_stable_for_pinned_model(trace_store, llm_engine):
    original_trace = trace_store.get(trace_id="...")
    rendered = prompt_renderer.render(original_trace.prompt_id, original_trace_variables)
    new_output = llm_engine.generate(
        rendered, model_version=original_trace.model_version, seed=42, temperature=0.0,
    )
    assert hash_output(new_output) == original_trace.output_hash  # or within defined tolerance
```

Given a `trace_id`, re-rendering the same prompt and re-invoking the same
pinned model with the same seed should reproduce the same (or
tolerance-bounded similar) output — this is the regression-testing
mechanism that lets a prompt or model upgrade be evaluated against prior
behavior rather than trusted blindly.

### Current State

There is no traceability today. `claude_cli.py`'s subprocess output (per
ADR-002, `31-ADR.md`) is ephemeral — consumed in-process and discarded; no
`AITrace` table exists; no prompt hash is computed; no seed is currently
passed to Ollama calls. This section is target-state specification, not a
description of current behavior, consistent with the rest of this
document's forward-looking sections.

---

## Section 5 — Privacy and Data Residency

### Local Inference

Ollama (LLM), F5-TTS (voice), Flux (image) — when these are the active
providers (default per ADR-010, `31-ADR.md`), no project content (script
text, character descriptions, research findings) leaves the machine. This
is the governance-relevant consequence of the local-first architecture
decision, not a separate mechanism — privacy here is a property of where
compute happens, not an additional access-control layer bolted on top.

### Cloud Inference

When Edge-TTS (current default per ADR-003), Claude API/CLI (opt-in per
ADR-002), or any other cloud provider is in use, this document requires
explicit documentation, per provider, of exactly what data crosses the
network boundary: for Edge-TTS, the synthesized text (the script content)
is sent to Microsoft's service; for the Claude CLI path, the full rendered
prompt (which may include research findings, niche details, and prior
series context per `35-PROMPT_DSL.md`'s `series_context` variable) is sent
to Anthropic. This documentation lives alongside each adapter's module
docstring (`21-PROVIDER_SYSTEM.md` convention) so "what does this provider
send off-machine" is answerable by reading the adapter, not by inferring it
from network traffic.

### Vietnamese Content / No PII

This project's content is educational/explainer material (`01-VISION.md`
target niches: Vietnamese self-development, tech-explainer, history) — no
personally identifiable information about real private individuals is a
legitimate input to any prompt. `Research.sources` citing public figures or
publicly published facts is in scope; a prompt that would require
submitting private personal data about a named individual to any provider
(local or cloud) is out of scope for this product and is not a case the
Prompt Engine's templates (`35-PROMPT_DSL.md`) are designed to accept
variables for.

### Secret Management

API keys (`OMNI`-unrelated to this project, but the same discipline
applies: e.g., Anthropic API key for ADR-002's future SDK path, YouTube
OAuth tokens for `publish/uploader.py`) are never embedded in prompt text,
never logged into `AITrace` records, and never written to `ledger.md`.
`AITrace.prompt_hash`/`input_hash` are one-way hashes specifically so that
even if a prompt's *rendered text* incidentally referenced sensitive
config (which it should not, by construction — secrets are not declared as
`PromptRenderer` template variables, per `35-PROMPT_DSL.md`'s variable
schema convention), the stored trace would not leak it.

---

## Section 6 — Governance Checklist

- [ ] Every LLM call produces an `AITrace` (no call site bypasses
  `LLMEngine.generate()`'s tracing side effect).
- [ ] Every trace is stored in `assets/traces.db` and queryable by
  `project_id`, `stage`, `agent_name`, and `output_hash`.
- [ ] Every output is schema-validated against its `output_schema_ref`
  before the pipeline proceeds to the next `WorkflowNode`.
- [ ] Quality gates (`ComplianceChecker`, `NicheGate`, `LengthGate`) are
  non-bypassable — no `--skip-gates` flag exists anywhere in
  `orchestrator/batch_cli.py` or its v3 DAG-executor successor.
- [ ] A human approval gate exists at the `SCRIPTED → APPROVED` transition
  (`32-STATE_MACHINE.md`), with auto-approve as an explicit, logged,
  reversible opt-in only.
- [ ] Model versions are pinned to a fully-qualified identifier in config —
  never a bare alias.
- [ ] Prompt versions are tracked via `prompt_hash` (rendered-text hash) in
  every `AITrace`, in addition to the `prompt_version` semver field.
</content>
