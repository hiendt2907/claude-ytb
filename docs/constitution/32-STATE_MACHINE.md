# 32 — STATE MACHINE

## Purpose

`04-DOMAIN.md`'s `Project.status` field is currently a loosely-typed
`str` (`"draft" | "in_progress" | "review" | "published" | "archived"`) and
`auto_state.json` (the listener daemon's current resume-queue file) tracks
ad-hoc string status with no formal transition validation anywhere in the
codebase. This document specifies the formal state machines for `Project`
and `WorkflowNode` that supersede that ad-hoc string field — the contract
that makes "what can happen next" a checkable invariant instead of whatever
the next line of code happens to do.

This is the lifecycle layer sitting directly on top of
`05-WORKFLOW.md` (the DAG shape) and `25-CHECKPOINT_SYSTEM.md` (the
per-node persistence contract) — those documents say *what* runs and *how
it resumes*; this document says *what state the Project and each node are
allowed to be in, and what is a legal transition between them*.

---

## Section 1 — Project State Machine

### States

| State | Meaning |
|---|---|
| `DRAFT` | `Project` created; topic/niche/target_platforms set; no research yet. |
| `RESEARCHED` | `Research` + `KnowledgeBase` merge complete (`05-WORKFLOW.md` Research/KnowledgeGraph nodes done). |
| `OUTLINED` | `Outline` produced and passes duration-tolerance gate. |
| `SCRIPTED` | `Story → Narrative → Script` chain complete; Script passes length/intro gates. |
| `APPROVED` | A human has explicitly approved the Script via the Telegram gate (`07-X`/listener). Required before any render compute is spent. |
| `RENDERING` | `WorkflowGraph` execution is in progress across Storyboard → Timeline → Renderer nodes. |
| `RENDERED` | `RenderJob.status == "succeeded"`; final video `Asset` exists and has passed post-render validation (duration, resolution, audio sync). |
| `PUBLISHING` | `PublishJob` dispatched to one or more target platforms; awaiting platform confirmation. |
| `PUBLISHED` | All target `PublishJob`s reached `status == "succeeded"`; `remote_url` recorded on each. |
| `ARCHIVED` | Terminal success state. Project's compute/storage footprint may be reduced (e.g., large intermediate assets pruned per `24-CACHE_SYSTEM.md` retention policy) without losing `project.json` itself. |
| `FAILED` | Terminal failure state. Reached only after retries are exhausted on the WorkflowNode currently blocking progress, with the triggering `Checkpoint.error` preserved for diagnosis. |

### Valid Transitions

```
DRAFT        -> RESEARCHED   | FAILED
RESEARCHED   -> OUTLINED     | FAILED
OUTLINED     -> SCRIPTED     | FAILED
SCRIPTED     -> APPROVED     | FAILED        (guard: quality gate, see below)
APPROVED     -> RENDERING    | FAILED
RENDERING    -> RENDERED     | FAILED
RENDERED     -> PUBLISHING   | ARCHIVED      (creator may archive without publishing)
PUBLISHING   -> PUBLISHED    | FAILED
PUBLISHED    -> ARCHIVED
FAILED       -> (state the failure occurred in)   (resume re-enters the same state on retry)
```

No state may be skipped — `RENDERING` cannot be entered directly from
`SCRIPTED`; `APPROVED` is mandatory because it is the human gate. No
backward transition exists except via `FAILED`'s resume re-entry, which is
not a regression — it is retrying the same state, not undoing a prior one.
This mirrors `25-CHECKPOINT_SYSTEM.md`'s resume protocol: a `Project` does
not "go back" to `DRAFT` because `RENDERING` failed; it resumes `RENDERING`.

### ASCII State Diagram

```
 ┌───────┐
 │ DRAFT │
 └───┬───┘
     │ research + KB merge done
     ▼
┌────────────┐
│ RESEARCHED │
└─────┬──────┘
      │ outline passes duration gate
      ▼
┌──────────┐
│ OUTLINED │
└────┬─────┘
     │ script passes length + intro gates
     ▼
┌──────────┐
│ SCRIPTED │──────────────┐ (quality gate FAIL)
└────┬─────┘              │
     │ human approves      │
     │ (Telegram gate)     ▼
     ▼                 ┌────────┐
┌──────────┐           │ FAILED │◄────────────────────────┐
│ APPROVED │           └────────┘                         │
└────┬─────┘                ▲                              │
     │ DAG executor starts  │ retries exhausted             │
     ▼                      │ at any state                   │
┌───────────┐               │                                 │
│ RENDERING │───────────────┘                                 │
└────┬──────┘                                                 │
     │ RenderJob succeeded + post-render validation passes    │
     ▼                                                         │
┌──────────┐                                                   │
│ RENDERED │──────────────┐ (creator archives without publish) │
└────┬─────┘              ▼                                    │
     │ publish dispatched ┌──────────┐                          │
     ▼                    │ ARCHIVED │◄─────────────┐           │
┌────────────┐            └──────────┘               │           │
│ PUBLISHING │────────────────────────────────────────┼───────────┘
└────┬───────┘                                        │
     │ all PublishJobs succeeded                       │
     ▼                                                  │
┌───────────┐                                            │
│ PUBLISHED │────────────────────────────────────────────┘
└───────────┘
```

### Per-State Detail

#### DRAFT
- **Entry actions:** allocate `Project.id` (UUID4); persist initial
  `project.json` with `niche`, `target_platforms`, empty checkpoint map.
- **Exit actions:** none beyond the transition itself — `DRAFT` has no
  cleanup obligation.
- **Invariants:** `Project.research_id` is `None`; no `WorkflowGraph` exists
  yet.

#### RESEARCHED
- **Entry actions:** set `Project.research_id`, `knowledge_base_id`;
  write `Checkpoint`s for `Research` and `KnowledgeGraph` nodes.
- **Exit actions:** none.
- **Invariants:** `Research.sources` is non-empty (a Research result with
  zero sources is a quality-gate failure per `05-WORKFLOW.md`, not a valid
  `RESEARCHED` state — it routes to `FAILED` instead).

#### OUTLINED
- **Entry actions:** set `Project.outline_id`.
- **Exit actions:** none.
- **Invariants:** `Outline.target_duration_seconds` is within the
  configured tolerance band of the platform's target duration
  (`05-WORKFLOW.md` Outline node failure mode).

#### SCRIPTED
- **Entry actions:** set `Project.narrative_id`; the finalized script text
  is attached to the `WorkflowGraph` as the `Script` node's checkpointed
  output.
- **Exit actions:** none until the `APPROVED` guard passes.
- **Invariants:** Script has passed the length gate and intro gate
  (`05-WORKFLOW.md` Script node precedents `test_length_gate.py`,
  `test_intro_gate.py`) — these are preconditions for *entering* `SCRIPTED`,
  not optional checks performed later.

**Guard condition — `SCRIPTED` → `APPROVED`:** the transition is blocked
until both of the following hold:
1. The Script's quality gate result (length + intro + niche-compliance, per
   `05-WORKFLOW.md` and `02-PRINCIPLES.md`'s compliance rules) is `PASS`.
2. A human has responded `approve` to the Telegram approval prompt for this
   `Project.id` (`listener.py`). A `reject` response does not transition to
   `FAILED` directly — it re-enters `OUTLINED` or `SCRIPTED` with a
   revision request, handled as a new attempt at the same node, consistent
   with `25-CHECKPOINT_SYSTEM.md`'s append-only checkpoint history.

This guard is the literal implementation of the example given in this
document's own task description: "cannot transition SCRIPTED→APPROVED
without passing quality gate" — encoded here as a two-part guard (automated
gate AND human sign-off), not either alone.

#### APPROVED
- **Entry actions:** record approval timestamp and approver identity (the
  Telegram user/chat id) into the ledger (`31-ADR.md` ADR-005) for audit.
- **Exit actions:** construct the `WorkflowGraph` for render execution
  (Storyboard onward) if not already constructed during `SCRIPTED`.
- **Invariants:** no render compute (image/video/voice generation) has
  occurred prior to this state — `APPROVED` is the gate that protects local
  GPU/NPU cycles from being spent on a script the human has not signed off
  on.

#### RENDERING
- **Entry actions:** DAG executor begins walking `WorkflowNode`s from
  Storyboard through Renderer (`05-WORKFLOW.md`); per-node `Checkpoint`s
  begin accumulating.
- **Exit actions:** none until `RenderJob.status` resolves.
- **Invariants:** `Project` may remain in `RENDERING` across process
  restarts — this state is resumable by definition (`25-CHECKPOINT_SYSTEM.md`
  §4 Resume Protocol); a crashed process does not imply a `FAILED` Project,
  only nodes left in `"running"` status which resume treats as `"pending"`.

#### RENDERED
- **Entry actions:** set `RenderJob.output_asset_id`; run post-render
  validation (duration, resolution, audio sync per `05-WORKFLOW.md`
  Renderer node).
- **Exit actions:** none.
- **Invariants:** the final video `Asset` file exists on disk and passes
  validation — a `RenderJob.status == "succeeded"` with a validation failure
  is not `RENDERED`; it is `FAILED` with the validation error attached.

#### PUBLISHING
- **Entry actions:** create one `PublishJob` per entry in
  `Project.target_platforms`.
- **Exit actions:** none until all `PublishJob`s resolve.
- **Invariants:** at least one `PublishJob` exists; `PUBLISHING` is never
  entered for a `Project` with empty `target_platforms` (such a Project
  transitions `RENDERED → ARCHIVED` directly).

#### PUBLISHED
- **Entry actions:** record all `remote_url`s into `project.json` and the
  ledger.
- **Exit actions:** none until archival.
- **Invariants:** every `PublishJob.status == "succeeded"` — a Project with
  one platform published and another still retrying remains in `PUBLISHING`,
  not `PUBLISHED`, until all resolve (success or terminal failure).

#### ARCHIVED
- **Entry actions:** optional cache pruning of large intermediate assets per
  `24-CACHE_SYSTEM.md` retention policy; `project.json` itself is never
  pruned.
- **Exit actions:** none — `ARCHIVED` is terminal.
- **Invariants:** none beyond `project.json` remaining readable indefinitely
  (the v5 "diffable, mergeable creative artifact" property,
  `01-VISION.md`).

#### FAILED
- **Entry actions:** preserve the triggering `Checkpoint.error` and the
  state the `Project` was in when the failure occurred (`failed_in_state`
  field, see §3).
- **Exit actions:** on operator-confirmed resume (per
  `25-CHECKPOINT_SYSTEM.md` §4 step 4), re-enter `failed_in_state` and
  resume node execution from there.
- **Invariants:** `FAILED` always carries a non-`None` error reference —
  there is no such thing as an unexplained `FAILED` state.

---

## Section 2 — WorkflowNode State Machine

### States

| State | Meaning |
|---|---|
| `PENDING` | Node declared in the `WorkflowGraph`; not yet started; either no checkpoint exists or the checkpoint matches `25-CHECKPOINT_SYSTEM.md`'s `"pending"`. |
| `QUEUED` | Node's `depends_on` set is fully satisfied (all upstream nodes `DONE`); the executor has scheduled it for execution but the underlying provider call has not yet started. |
| `RUNNING` | The node's provider call (or deterministic computation) is in flight. |
| `RETRYING` | The most recent attempt failed with a retryable error; the node is waiting out its backoff interval before the next attempt. |
| `DONE` | The node produced a successful output; a `Checkpoint` with `status == "succeeded"` is persisted. |
| `FAILED` | All retries exhausted (`attempt >= max_retries`) without success; a `Checkpoint` with `status == "failed"` is persisted. |
| `SKIPPED` | The node was deliberately bypassed — either a config flag marks it optional (e.g., `StickmanPrompt`, per `05-WORKFLOW.md`) or a non-blocking failure mode degrades gracefully (e.g., `Music`/`SFX` proceeding without a match). |

### Valid Transitions

```
PENDING   -> QUEUED
QUEUED    -> RUNNING
RUNNING   -> DONE | RETRYING | FAILED | SKIPPED
RETRYING  -> RUNNING | FAILED
FAILED    -> RUNNING        (only on explicit operator-confirmed resume)
```

`SKIPPED` is reachable only from `RUNNING` evaluating a non-blocking
failure mode, or directly from `PENDING` when a config flag marks the node
optional before it ever runs (e.g., `StickmanPrompt` disabled entirely).
`DONE` and `SKIPPED` are both terminal-success states for the purpose of
downstream dependency satisfaction — a node depending on a `SKIPPED`
upstream node treats it as satisfied with a `None`/default output, per the
node's own contract (e.g., `Timeline` assembling without `Music` if `Music`
was `SKIPPED`).

### ASCII State Diagram

```
┌─────────┐
│ PENDING │
└────┬────┘
     │ depends_on satisfied
     ▼
┌────────┐
│ QUEUED │
└───┬────┘
    │ executor dispatches
    ▼
┌─────────┐     non-blocking failure mode      ┌─────────┐
│ RUNNING │────────────────────────────────────►│ SKIPPED │ (terminal)
└──┬───┬──┘                                      └─────────┘
   │   │
   │   │ retryable error, attempt < max_retries
   │   ▼
   │ ┌──────────┐  backoff elapsed   ┌─────────┐
   │ │ RETRYING │───────────────────►│ RUNNING │ (loop back up)
   │ └────┬─────┘                    └─────────┘
   │      │ attempt >= max_retries
   │      ▼
   │  ┌────────┐  operator confirms resume   ┌─────────┐
   │  │ FAILED │────────────────────────────►│ RUNNING │ (loop back up)
   │  └────────┘ (terminal until resume)
   │
   │ success
   ▼
┌──────┐
│ DONE │ (terminal)
└──────┘
```

### Timeout Handling

A node in `RUNNING` is subject to a per-node-type timeout
(`27-CODING_STANDARD.md` configuration conventions apply: timeout is a
named constant per node type, never a magic number inline). A timeout
firing while `RUNNING` is treated identically to a retryable provider
exception — it transitions to `RETRYING` (if `attempt < max_retries`) or
`FAILED` (if exhausted), with the `Checkpoint.error` recording
`"timeout after Ns"` rather than a provider-specific exception string, so
timeout failures are distinguishable from genuine provider errors when
reviewing the ledger.

### Retry Policy

| Field | Type | Default | Notes |
|---|---|---|---|
| `max_retries` | `int` | `3` | Per `WorkflowNode.max_retries` (`04-DOMAIN.md`); `Publisher` overrides to `5` per `05-WORKFLOW.md`'s justification (networked final step). |
| `backoff_seconds` | `tuple[float, ...]` | `(2.0, 8.0, 30.0)` | Exponential backoff schedule indexed by `attempt`; not a formula computed at runtime, so the schedule is itself reviewable/testable as data. |
| `retry_on` | `tuple[type[Exception], ...]` | provider-specific | Only exceptions explicitly classified as transient (timeout, connection error, provider rate limit) trigger `RETRYING`. Exceptions classified as structural (schema validation failure, banned-topic gate failure, OAuth re-auth required) route directly to `FAILED` regardless of remaining `attempt` budget — retrying a structural failure with identical inputs cannot succeed, per the failure-mode tables in `05-WORKFLOW.md`. |

`retry_on` classification lives alongside each `Provider` adapter
(`21-PROVIDER_SYSTEM.md`), since only the adapter knows which of its own
exception types are transient versus structural — the DAG executor consults
this classification rather than hard-coding a global exception list.

---

## Section 3 — Python Implementation

### Enum + Dataclass Definition

```python
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum


class ProjectState(str, Enum):
    DRAFT = "draft"
    RESEARCHED = "researched"
    OUTLINED = "outlined"
    SCRIPTED = "scripted"
    APPROVED = "approved"
    RENDERING = "rendering"
    RENDERED = "rendered"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    FAILED = "failed"


class NodeState(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    RETRYING = "retrying"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


# Adjacency map of legal transitions — the single source of truth the
# validator below consults. Defined as data, not as a chain of `if`
# statements, so the full transition table is reviewable in one place.
_PROJECT_TRANSITIONS: dict[ProjectState, frozenset[ProjectState]] = {
    ProjectState.DRAFT: frozenset({ProjectState.RESEARCHED, ProjectState.FAILED}),
    ProjectState.RESEARCHED: frozenset({ProjectState.OUTLINED, ProjectState.FAILED}),
    ProjectState.OUTLINED: frozenset({ProjectState.SCRIPTED, ProjectState.FAILED}),
    ProjectState.SCRIPTED: frozenset({ProjectState.APPROVED, ProjectState.FAILED}),
    ProjectState.APPROVED: frozenset({ProjectState.RENDERING, ProjectState.FAILED}),
    ProjectState.RENDERING: frozenset({ProjectState.RENDERED, ProjectState.FAILED}),
    ProjectState.RENDERED: frozenset({ProjectState.PUBLISHING, ProjectState.ARCHIVED}),
    ProjectState.PUBLISHING: frozenset({ProjectState.PUBLISHED, ProjectState.FAILED}),
    ProjectState.PUBLISHED: frozenset({ProjectState.ARCHIVED}),
    ProjectState.ARCHIVED: frozenset(),
    ProjectState.FAILED: frozenset(),  # resume re-enters failed_in_state explicitly, not via this table
}


class InvalidTransitionError(Exception):
    """Raised when a Project or WorkflowNode attempts an illegal state transition."""

    def __init__(self, from_state: Enum, to_state: Enum) -> None:
        super().__init__(f"Illegal transition: {from_state.value} -> {to_state.value}")
        self.from_state = from_state
        self.to_state = to_state


@dataclass(frozen=True)
class ProjectStateRecord:
    """Immutable record of a Project's current lifecycle state."""
    project_id: str
    state: ProjectState
    failed_in_state: ProjectState | None = None
    entered_at: datetime = None

    def transition(self, to_state: ProjectState, *, now: datetime) -> "ProjectStateRecord":
        if to_state not in _PROJECT_TRANSITIONS.get(self.state, frozenset()):
            raise InvalidTransitionError(self.state, to_state)
        failed_in = self.state if to_state == ProjectState.FAILED else None
        return replace(self, state=to_state, failed_in_state=failed_in, entered_at=now)

    def resume(self, *, now: datetime) -> "ProjectStateRecord":
        """Resume from FAILED back into the state the failure occurred in."""
        if self.state != ProjectState.FAILED or self.failed_in_state is None:
            raise InvalidTransitionError(self.state, self.state)
        return replace(self, state=self.failed_in_state, failed_in_state=None, entered_at=now)
```

### State Transition Validation

`ProjectStateRecord.transition()` is the **only** sanctioned way to change
`state` — there is no setter, and `frozen=True` makes direct mutation a
`dataclasses.FrozenInstanceError` at the language level, not a code-review
convention. Any orchestrator code (`pipeline.py`, the future v3 DAG
executor) calls `.transition(...)` and replaces its in-memory reference with
the returned new record; persisting that record to `project.json` is a
separate, explicit step (see Persistence below), keeping "state changed" and
"state change observed/persisted" as distinct, ordered actions.

### Persistence in project.json

`ProjectStateRecord` serializes into `project.json` as a top-level
`lifecycle` object, alongside the existing `checkpoints` map
(`25-CHECKPOINT_SYSTEM.md` §3):

```json
{
  "id": "proj_2026_06_29_loss_aversion",
  "lifecycle": {
    "state": "rendering",
    "failed_in_state": null,
    "entered_at": "2026-06-29T09:03:11Z"
  },
  "checkpoints": { "...": "..." }
}
```

Writing `lifecycle` follows the same single-write-path rule
`25-CHECKPOINT_SYSTEM.md` §3 establishes for checkpoints: `project.json` is
the only sink, so lifecycle state can never drift out of sync with
checkpoint state in two separate files.

### Integration with CheckpointManager

The relationship between `ProjectState` and `WorkflowNode`/`NodeState` is
one of aggregation, not duplication: `ProjectState.RENDERING` is "true" for
exactly as long as the `CheckpointManager` (`25-CHECKPOINT_SYSTEM.md`)
reports at least one node in `RUNNING`/`RETRYING`/`QUEUED` and none yet
terminally failed for the render-phase subgraph. The `Project`-level state
machine does not duplicate per-node bookkeeping — it derives its
`RENDERING → RENDERED` transition from the `CheckpointManager` reporting all
render-phase nodes `DONE`, and its `RENDERING → FAILED` transition from any
render-phase node reporting `FAILED` with retries exhausted. Concretely:

```python
def derive_project_transition(
    checkpoint_manager: "CheckpointManager", render_phase_node_ids: tuple[str, ...]
) -> ProjectState | None:
    statuses = [checkpoint_manager.node_state(nid) for nid in render_phase_node_ids]
    if any(s == NodeState.FAILED for s in statuses):
        return ProjectState.FAILED
    if all(s in (NodeState.DONE, NodeState.SKIPPED) for s in statuses):
        return ProjectState.RENDERED
    return None  # still RENDERING, no transition yet
```

### Current State vs Migration

Today, `Project.status` (`04-DOMAIN.md`) is an unvalidated `str` default
`"draft"`, and the listener daemon's `auto_state.json` tracks its own
separate, informal status string with no shared vocabulary with
`Project.status` — the two can disagree with nothing to notice. There is no
`InvalidTransitionError` anywhere in the current codebase; any code path can
set any status string at any time.

**Migration notes:**
1. Introduce `ProjectState`/`NodeState` enums and `ProjectStateRecord` as
   above, alongside the existing `status: str` field — do not remove the
   string field yet (backward-compat read path for existing `project.json`
   files written before this migration, same pattern as `04-DOMAIN.md`'s
   own migration note for the `Project` model itself).
2. Add a one-time loader that maps every legacy `status` string value to
   its corresponding `ProjectState` (`"draft"` → `ProjectState.DRAFT`,
   `"in_progress"` → `ProjectState.RENDERING` as the closest approximation,
   `"review"` → `ProjectState.SCRIPTED`, `"published"` →
   `ProjectState.PUBLISHED`, `"archived"` → `ProjectState.ARCHIVED`) —
   this mapping is lossy (the legacy model has no `APPROVED`/`RESEARCHED`/
   `OUTLINED`/`RENDERED`/`PUBLISHING` distinction) and is documented as
   best-effort for old artifacts only, never used for new `Project` runs.
3. Retarget `listener.py`'s `auto_state.json` queue to read
   `ProjectStateRecord.state` directly from `project.json` instead of
   maintaining its own parallel status string — eliminating the
   two-sources-of-truth problem.
4. Once no code path constructs the legacy string-only status, remove the
   string field, following the same "introduce alongside, then remove once
   unused" discipline `04-DOMAIN.md` already prescribes for the broader
   domain model migration.
</content>
