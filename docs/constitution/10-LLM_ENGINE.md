# 10 — LLM ENGINE

## Purpose

Provide every Agent (06-AGENTS) with a single, provider-agnostic way to call
an LLM — text completion, structured output, or tool use — so that switching
from Claude CLI subprocess calls to local Ollama/Qwen3 (or any future
provider) is a config change, never a call-site rewrite.

## Provider Interface

```python
from typing import Protocol, TypeVar
from dataclasses import dataclass

T = TypeVar("T")


@dataclass(frozen=True)
class LLMRequest:
    system: str
    user: str
    schema: type | None = None       # if set, response MUST validate against this
    temperature: float = 0.7
    max_tokens: int = 4096
    seed: int | None = None           # determinism where provider supports it


@dataclass(frozen=True)
class LLMResponse[T]:
    text: str
    structured: T | None             # populated only if request.schema was set
    input_tokens: int
    output_tokens: int
    cost_usd: float                   # 0.0 for local providers
    provider: str
    model: str
    latency_ms: int


class LLMProvider(Protocol):
    """Every LLM provider (local or cloud) implements this shape.
    Agents never import a concrete provider — they receive one through
    LLMProviderRegistry.resolve()."""

    name: str
    is_local: bool

    async def complete(self, request: LLMRequest) -> LLMResponse: ...

    async def health_check(self) -> bool:
        """Cheap liveness probe — used by the selection strategy to decide
        local-vs-cloud fallback without waiting for a full request timeout."""
        ...
```

## Supported Providers

| Provider | Type | Notes |
|---|---|---|
| **Ollama** (Qwen3 family) | local | Primary provider. Runs on M4 via Metal/MLX acceleration. No network dependency, no per-token cost. |
| **Anthropic Claude** | cloud | Used for high-stakes reasoning seats (Creative Director, QA Agent semantic checks — see 06-AGENTS) and as the offline-impossible fallback for cloud-only tool use (Research Agent's web search). |
| **OpenAI** | cloud | Secondary cloud fallback / A-B comparison provider. |
| **Gemini** | cloud | Tertiary cloud fallback; useful for its large context window on long-research-brief summarization tasks. |

Each provider is a thin adapter implementing `LLMProvider` — no agent or
engine code branches on provider name; all branching happens inside the
selection strategy below.

## Provider Selection Strategy: Local-First, Cloud Fallback

```python
class LLMProviderRegistry:
    """Resolves a capability ("creative_director", "story_architect", ...)
    to a ranked provider chain, then returns the first healthy one."""

    def __init__(self, chains: dict[str, list[LLMProvider]]):
        self._chains = chains  # capability -> ordered [local, ..., cloud fallback]

    async def resolve(self, capability: str) -> LLMProvider:
        for provider in self._chains[capability]:
            if await provider.health_check():
                return provider
        raise NoProviderAvailable(capability)
```

Default chain shape for most agents: `[ollama_qwen3, claude_sonnet]` — local
is attempted first; cloud is only invoked when `health_check()` fails (Ollama
not running, model not pulled, MPS unavailable) or when the capability is
explicitly pinned to cloud (e.g. QA Agent's semantic judgment seat, Research
Agent's web-search-dependent calls — see 06-AGENTS model recommendations per
agent). This is config-driven (`llm_chains.yaml` or env), never hardcoded
per-agent in Python.

Offline-first mode (`OFFLINE_ONLY=true`) removes cloud providers from every
chain at registry construction time — a capability with no remaining healthy
provider fails fast with a clear error rather than silently blocking on a
network call.

## Prompt Management: Version-Controlled, A/B-Testable

The LLM Engine does not author prompts — it accepts a fully-rendered
`LLMRequest.system`/`user` string produced by the Prompt Engine (11). What
the LLM Engine *does* own is tagging every request/response pair with the
prompt version that produced it (passed through as request metadata) so cost
and quality can be attributed back to a specific prompt version for A/B
comparison — see 11-PROMPT_ENGINE §Prompt testing framework.

## Context Window Management

```python
class ContextManager:
    def count_tokens(self, text: str, model: str) -> int: ...

    def fit(self, system: str, user: str, model: str, reserve_output: int) -> tuple[str, str]:
        """Truncates `user` (never `system` — system carries hard constraints)
        from the least-recent/least-relevant end first, until
        count_tokens(system) + count_tokens(user) + reserve_output <= model context window.
        Truncation point is logged as a warning, never silent."""
        ...
```

Rules:
- `OMNI_LLM_NUM_CTX`-style explicit context-window config (the project's
  existing convention of an explicit ctx-size setting rather than relying on
  provider defaults) carries over here: every provider adapter declares its
  effective context window explicitly rather than trusting a hardcoded
  model default, since local Ollama models are frequently run with a
  smaller-than-max context for memory reasons on M4.
- Truncation always reserves `max_tokens` worth of output budget before
  computing how much input fits — never compute fit on input alone and
  discover output gets clipped.
- Long inputs (a full `KnowledgeGraph` dump, a long `ResearchBrief`) should
  be summarized by a dedicated summarization call **before** hitting context
  limits, not truncated blindly — truncation is the last-resort path, not
  the primary strategy.

## Structured Output Enforcement

```python
class SchemaValidator(Protocol):
    def validate(self, raw_text: str, schema: type) -> tuple[bool, object | None, str]:
        """Returns (is_valid, parsed_object_or_None, error_message)."""
        ...
```

Strategy, in priority order:
1. **Provider-native structured output** when available (Claude/OpenAI tool-
   use / JSON mode; Ollama's `format=json` + grammar-constrained decoding for
   Qwen3) — preferred because it constrains generation, not just validates
   after the fact.
2. **Post-hoc JSON-schema validation** (pydantic model from the agent's
   expected output dataclass) as a universal fallback for providers without
   native structured output, or as a safety net even when native support is
   used (provider bugs happen).
3. **Repair-reprompt loop**: on validation failure, re-issue the request with
   the validator's exact error message appended as correction context (this
   mirrors the project-wide agent retry convention in 06-AGENTS — max 2
   retries, then surface `confidence=0.0`).

`LLMRequest.schema` is the dataclass/pydantic type the caller expects;
`LLMResponse.structured` is `None` until validation succeeds, so callers can
distinguish "provider didn't support structured output and validation hasn't
run yet" from "validation failed" by checking `structured is None` plus the
returned warnings — never assume a non-null `text` implies valid structure.

## Cost Tracking

```python
@dataclass(frozen=True)
class CostRecord:
    run_id: str
    stage: str           # which DAG stage / agent capability issued this call
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: str


class CostTracker(Protocol):
    def record(self, entry: CostRecord) -> None: ...
    def total_for_run(self, run_id: str) -> float: ...
    def total_for_stage(self, stage: str, since: str) -> float: ...
```

Every `LLMResponse` is recorded regardless of provider — local providers
record `cost_usd=0.0` but still record token counts, since token volume is a
useful capacity-planning signal even when it's free. `RunContext.budget`
(06-AGENTS) is checked against `CostTracker.total_for_run()` before each
cloud-bound dispatch; a budget breach blocks further cloud calls for that run
without blocking local calls (local has no budget impact).

## Retry + Fallback Logic

```
LLMProviderRegistry.resolve(capability)
        │
        ▼
provider.complete(request)
        │
   ┌────┴─────┐
   │ success   │ error / timeout
   ▼           ▼
return     exponential backoff (1s, 4s, 9s) on same provider, max 2 retries
            │
            │ still failing
            ▼
   try next provider in chain (e.g. local → cloud)
            │
            │ chain exhausted
            ▼
   raise LLMEngineExhausted — propagated to the calling Agent's own
   retry/escalation logic (06-AGENTS shared failure conventions), never
   silently swallowed
```

This two-level retry (within-provider backoff, then cross-provider fallback)
is distinct from — and sits below — the Agent-level retry strategies in
06-AGENTS (which retry with corrected *prompt content*, not just re-dispatch
the same request).

## Current State

`src/ytb_pipeline/claude_cli.py` is the entire LLM integration today: it
shells out to the `claude` CLI binary as a subprocess (`claude -p "<prompt>"`,
optionally `--continue` for session continuity), invoked from
`listener.py` (Telegram-triggered) and `orchestrator/batch_cli.py`. There is
no provider abstraction, no structured-output validation, no cost tracking,
and no local-model option — every ideation call is a cloud Claude call via
the developer's own `claude` CLI session, with the actual script content
hand-authored by Claude in chat per `CLAUDE.md`'s explicit current-state note
("scaffold khởi đầu... Claude viết tay trong chat").

```python
# current shape, src/ytb_pipeline/claude_cli.py
def build_claude_cmd(prompt: str, *, cont: bool = False) -> list[str]:
    cmd = [settings.claude_bin]
    ...
    cmd += ["-p", prompt]
    return cmd
```

## Migration Path to Direct SDK Usage

1. **Introduce `LLMProvider` + a `ClaudeCLIProvider` adapter first** — wrap
   the existing subprocess call behind the new interface without changing
   its behavior. This makes the migration's first commit a pure refactor
   (behavior-preserving), satisfying the project's TDD-before-rewrite norm.
2. **Add `OllamaProvider`** using the `ollama` Python SDK (or its HTTP API
   directly) against `host.orb.internal:11434`-style local endpoint
   (matching the project's existing convention of an explicit local-host
   Ollama endpoint for its sibling Omni project) — register it ahead of
   `ClaudeCLIProvider` in the default chain once health-checked as stable.
3. **Add `AnthropicSDKProvider`** using the `anthropic` Python SDK directly
   (replacing the CLI-subprocess `ClaudeCLIProvider` for the cloud-fallback
   seat) — direct SDK usage gets proper token accounting, native structured
   output (tool use / JSON mode), and removes the subprocess overhead/
   fragility (`shlex` argument construction, process exit-code parsing) that
   `claude_cli.py` currently carries.
4. **Retire `claude_cli.py`** once `listener.py`/`batch_cli.py` are updated
   to call `LLMProviderRegistry.resolve(...)` instead of
   `build_claude_cmd(...)` directly — the Telegram-driven interactive
   ideation flow can keep using Claude (now via SDK) as its provider; only
   the call mechanism changes, not the choice of model for that particular
   human-in-the-loop seat.
5. **Wire Cost Tracking from day one of `AnthropicSDKProvider`** — the
   subprocess-based CLI today has no token/cost visibility at all; this is a
   pure addition with no current behavior to preserve.
