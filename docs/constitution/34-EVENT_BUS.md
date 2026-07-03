# 34 — EVENT BUS

## Purpose

This document is the full analysis backing ADR-012 (`31-ADR.md`). It is
written to be honest, not promotional — an event bus is genuinely useful
infrastructure in many systems, and the goal here is to show the actual
trade-off for *this* project rather than assert a conclusion without
showing the reasoning that could, under different conditions, point the
other way.

---

## Section 1 — What an Event Bus Would Provide

If `claude-ytb` adopted a pub/sub event bus (in-process, or a durable
broker like Redis Streams/Kafka), stage and node boundaries would emit
named events instead of calling observers directly:

- **Decoupled communication between pipeline stages.** `VoicePrompt`
  finishing would publish `VoiceSegmentCompleted` without knowing who, if
  anyone, is listening — `Subtitle`'s dependency on voice timing would be
  expressed as "subscribe to `VoiceSegmentCompleted`" rather than a direct
  function call/return value, and a new consumer could be added without
  touching `VoicePrompt`'s code at all.
- **Real-time progress streaming.** A web UI (hypothetical, per
  `01-VISION.md` v5) or a richer Telegram experience could subscribe to a
  live event stream and render true real-time progress (per-segment, even
  per-token) rather than the current call-and-report granularity.
- **Audit log via event stream.** `36-AI_GOVERNANCE.md`'s `AITrace`
  records could, in principle, be a materialized view over an event log
  rather than a separately-written table — "what happened" reconstructed by
  replaying `*Completed`/`*Failed` events in order.
- **Worked examples of event names this project would define:**
  `VoiceSegmentCompleted`, `SceneRendered`, `QualityGatePassed`,
  `PublishSucceeded`, `ProviderFallbackTriggered` (the Pexels/F5-TTS
  fallback path, ADR-003/ADR-004), `CheckpointWritten`.

These are real benefits. The question this document answers is whether they
are worth their cost *for this project, at this stage* — not whether event
buses are a good idea in general.

---

## Section 2 — Why We Do NOT Use a Full Event Bus

### Complexity cost vs what asyncio already gives for free

`claude-ytb` is, today and through the v3 milestone, a **single Python
process**. Within one process, `asyncio` queues and direct `await` chains
already provide ordered, backpressure-aware stage-to-stage signaling with
zero additional infrastructure. A `VoicePrompt` coroutine finishing and a
`Subtitle` coroutine consuming its result is a function call with a return
value — introducing a publish/subscribe layer between them replaces a
direct, statically-checkable call (`mypy` can verify the `Subtitle`
coroutine's argument type matches `VoicePrompt`'s return type) with an
indirect, stringly-typed event name and a runtime-only contract (a
subscriber expecting a `VoiceSegmentCompleted` payload shape that changed is
a runtime surprise, not a type-checker error). For a single-process system,
this trade is a net complexity *increase* with no corresponding decoupling
benefit, because the "decoupling" a bus provides is valuable specifically
when publishers and subscribers live in different processes that cannot
share a type system or a call stack — which is not this project's situation.

### Single-process architecture: in-process events are just function calls

The DAG executor (`05-WORKFLOW.md`, v3 milestone) walks `WorkflowNode`s in
one process. "Stage A's completion triggers Stage B" is already exactly
what the executor's dependency-graph walk does — `WorkflowNode.depends_on`
*is* the event-driven relationship, expressed as data the executor reads,
rather than as a parallel runtime mechanism (a bus) layered on top of a
graph that already encodes the same ordering information. Adding a bus here
would mean maintaining two parallel notions of "what triggers what": the
`WorkflowGraph`'s edges, and the bus's subscription list — a duplication
that is itself a bug surface (the two could disagree).

### Persistence overhead: a durable bus is ops burden for a solo macOS tool

A *durable* event bus (Kafka, Redis Streams) exists to survive consumer
crashes and support multiple independent consumer groups replaying history
at their own pace — properties that matter for distributed, multi-team, or
multi-tenant systems. `claude-ytb` runs as one process on one creator's
MacBook (`PROJECT_VISION.md` §1 offline-first manifesto); introducing Redis
or Kafka would mean running and keeping alive a broker service the project's
own local-first thesis (ADR-010, `31-ADR.md`) argues against — it is exactly
the kind of "rent a tiny piece of distributed infrastructure for a solo
local tool" mistake ADR-009 already rejected for workflow orchestration
(Airflow/Prefect/Temporal) and ADR-005 rejected for the audit trail
(SQLite over a database service). The pattern is consistent: this project
repeatedly chooses embedded/local mechanisms over networked services when
the actual consumer count is one process, one user.

### Observer pattern is sufficient at the current consumer count

Today there are exactly **two** observers of pipeline progress: the
Telegram notifier (`notify/telegram.py`) and the ledger writer
(`31-ADR.md` ADR-005's `ledger.md`). Two observers calling back from a
direct list, or receiving a direct callback invocation, is the textbook
case where the Observer pattern (`02-PRINCIPLES.md` design patterns) is
sufficient and a bus is premature generality (YAGNI) — a bus's value over
a plain observer list scales with the number and independence of
consumers, and two tightly-related, co-deployed consumers in the same
process do not need a message broker to coordinate.

### When a full Event Bus WOULD make sense

This is not a permanent rejection — it is conditional on facts that do not
currently hold:

- **Multi-process architecture.** If the DAG executor and, say, a
  long-running local web UI server become separate OS processes (a real
  possibility at the v5 "Creative OS Surface" milestone per
  `01-VISION.md`), they no longer share a call stack, and an in-process
  observer callback literally cannot reach across the process boundary —
  at that point some message-passing mechanism (even a lightweight one, see
  §3/§4) becomes structurally necessary, not merely nice-to-have.
- **Distributed/cloud scale.** If `claude-ytb` ever runs pipeline stages
  across multiple machines (e.g., offloading video generation to a render
  farm) — explicitly out of scope for the current local-first single-user
  product, per `PROJECT_VISION.md`, but a plausible long-horizon pivot — a
  durable bus becomes the right tool for the same reasons Kafka exists in
  the first place.
- **Team use with multiple concurrent reviewers.** The current solo-creator
  target user (`01-VISION.md`) makes single-observer Telegram approval
  sufficient (ADR-007). A small-team mode with multiple people needing
  independent, replayable visibility into the same project's progress would
  reintroduce the "multiple independent consumer groups" case a durable bus
  is designed for.
- **Real-time UI dashboard requiring sub-second granularity.** The current
  `ProgressEvent` granularity (§3) is per-node-completion. A future
  dashboard wanting per-token LLM streaming or frame-by-frame render
  progress visualization would need a much higher event rate than two
  direct-callback observers comfortably handle inline, which is the point
  at which a queue-based buffer between producer and consumer earns its
  complexity.

---

## Section 3 — Lightweight Alternative We DO Use

### ProgressCallback Protocol

Every engine (`LLMEngine`, `VoiceEngine`, `RenderEngine`, etc., per the
`1X-*_ENGINE.md` documents) accepts an optional `on_progress` callback at
construction or call time:

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Protocol


@dataclass(frozen=True)
class ProgressEvent:
    """The one event-shaped object this project actually needs."""
    stage: str             # e.g. "voiceover", "render"
    node_id: str           # WorkflowNode.id, per 04-DOMAIN.md
    status: str            # "started" | "running" | "done" | "failed" | "skipped"
    pct_complete: float    # 0.0–1.0; coarse-grained, not per-token
    message: str = ""
    timestamp: datetime = None


class ProgressCallback(Protocol):
    def __call__(self, event: ProgressEvent) -> None: ...
```

This gives event-*shaped* data — a typed, immutable event object, the same
naming vocabulary a future bus would use (`stage`, `node_id`, `status`) —
without event-*bus* infrastructure. The callback is invoked synchronously,
in-process, with a statically type-checkable signature; there is no
publish/subscribe registry, no broker, no serialization boundary.

### Two Implementations

```python
class TelegramProgressReporter:
    """Posts ProgressEvents as Telegram messages (debounced per node)."""

    def __init__(self, chat_id: str, telegram_client: "TelegramClient") -> None:
        self._chat_id = chat_id
        self._client = telegram_client

    def __call__(self, event: ProgressEvent) -> None:
        if event.status in ("done", "failed"):
            self._client.send_message(
                self._chat_id,
                f"[{event.stage}] {event.node_id}: {event.status} — {event.message}",
            )


class LogProgressReporter:
    """Writes ProgressEvents to the project's ledger.md (31-ADR.md ADR-005)."""

    def __init__(self, ledger_path: str) -> None:
        self._ledger_path = ledger_path

    def __call__(self, event: ProgressEvent) -> None:
        with open(self._ledger_path, "a", encoding="utf-8") as f:
            f.write(f"{event.timestamp.isoformat()} {event.stage}.{event.node_id} {event.status}\n")
```

These are the project's only two `ProgressCallback` implementations today —
directly matching the "two observers" count referenced in §2.

### Event-Driven UX Without Bus Infrastructure

```python
# pipeline.py — how the DAG executor uses ProgressCallback (illustrative)
async def run_node(
    node: "WorkflowNode",
    on_progress: ProgressCallback,
) -> "Checkpoint":
    on_progress(ProgressEvent(stage=node.name, node_id=node.id, status="started", pct_complete=0.0))
    try:
        output = await execute(node)
    except RetryableError as exc:
        on_progress(ProgressEvent(stage=node.name, node_id=node.id, status="failed", pct_complete=0.0, message=str(exc)))
        raise
    on_progress(ProgressEvent(stage=node.name, node_id=node.id, status="done", pct_complete=1.0))
    return checkpoint_from(node, output)
```

The orchestrator constructs a small list of callbacks
(`[TelegramProgressReporter(...), LogProgressReporter(...)]`) and fans a
single `ProgressEvent` out to each — this *is* the Observer pattern, applied
exactly where it is sufficient (§2), giving the UX benefit of "the creator
gets notified and the ledger records what happened" without paying for a
bus that has no other job to do yet.

---

## Section 4 — Future Path to Event Bus

If/when one of the §2 "would make sense" conditions becomes true — most
plausibly the v5 multi-process Creative OS surface
(`01-VISION.md`) — the migration is designed to be additive, not a rewrite:

1. **Same event schema.** `ProgressEvent` (and any additional event
   dataclasses introduced for `36-AI_GOVERNANCE.md`'s `AITrace`-adjacent
   events) is already the event vocabulary a bus would use — no schema
   redesign is needed, only a new transport.
2. **Replace direct callback invocation with `event.publish(...)`.** The
   call site in `run_node` above changes from `on_progress(event)` to
   `await event_bus.publish("workflow.progress", event)`; `TelegramProgressReporter`
   and `LogProgressReporter` become subscribers registered with the bus
   instead of items in a callback list — their `__call__` bodies are
   unchanged.
3. **Choice of transport at that time:** an in-process `asyncio.Queue`-based
   bus is the minimal step if the only new requirement is "more than two
   decoupled in-process consumers" (still single-process, no broker);
   Redis Streams is the step taken specifically when a second *process*
   (e.g., a local web UI server) needs to consume events that originate in
   the pipeline process — Redis is already a plausible local dependency for
   this project's broader caching needs (`24-CACHE_SYSTEM.md`), so reusing
   it as an event transport avoids introducing a wholly new piece of
   infrastructure.
4. **No retroactive instrumentation needed.** Because every progress-bearing
   call site already goes through `ProgressCallback`/`ProgressEvent` today,
   the migration touches the *transport* (how an event reaches a
   subscriber) without touching the *call sites* (where events are
   produced) — this is the entire reason the lightweight protocol in §3 was
   designed to look like a miniature, schema-compatible bus from day one,
   even though it is not one.
</content>
