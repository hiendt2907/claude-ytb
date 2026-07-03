# 25 — Checkpoint System

> Status: **NOT IMPLEMENTED.** Current state is scattered, stage-local
> resume checks in `voiceover/tts.py`, `render/compose.py`, and
> `publish/uploader.py`, plus the listener daemon's `auto_state.json` queue
> file. This document specifies the unified DAG checkpoint/resume manager
> that supersedes them, required for the `05-WORKFLOW.md` DAG executor
> milestone (`01-VISION.md` v3).

## 1. Purpose

A `Project`'s production run is a DAG of nodes (research → outline →
script → voiceover → render → publish, with sub-nodes per segment), not a
single atomic operation. Any node can fail — a local model crashes, FFmpeg
errors on a malformed clip, the network drops mid-upload. Per
`PROJECT_VISION.md` §5 success metric ("100% of interrupted runs resume from
last checkpoint without recomputation"), the system must never force a full
restart from node 1 because node 14 failed.

The Checkpoint System is what makes "resume" a structural guarantee instead
of a per-stage convention each module author has to remember to implement
correctly.

## 2. Checkpoint Schema

```json
{
  "project_id": "proj_2026_06_29_loss_aversion",
  "node_id": "voiceover.segment_3",
  "status": "done",
  "output_ref": "assets/cache/tts/9f1c2a...e7.wav",
  "started_at": "2026-06-29T08:12:03Z",
  "completed_at": "2026-06-29T08:12:41Z",
  "error": null,
  "attempt": 1
}
```

| Field | Type | Notes |
|---|---|---|
| `project_id` | `str` | Matches the owning `Project.id`. |
| `node_id` | `str` | Stable, hierarchical identifier (`{stage}.{substage}` or `{stage}.segment_{n}`); never a positional index alone, so reordering DAG construction doesn't invalidate prior checkpoints. |
| `status` | `Literal["pending", "running", "done", "failed"]` | See §6 for transitions. |
| `output_ref` | `str \| None` | Path or cache key (per `24-CACHE_SYSTEM.md`) to the node's produced artifact; `None` while `pending`/`running`, or for nodes with no artifact output (e.g., a validation node). |
| `started_at` | `str \| None` | ISO 8601 UTC; `None` until first attempt starts. |
| `completed_at` | `str \| None` | ISO 8601 UTC; set on `done` or final `failed`. |
| `error` | `str \| None` | Last failure's message/traceback summary; cleared (`None`) on success. |
| `attempt` | `int` | Incremented on each retry; supports a `max_attempts` policy without a separate counter. |

`attempt` and `error` are additions to the field list given in this
document's scope, required to satisfy §5 (failure handling needs a retry
counter and a recorded reason) without inventing a second schema.

## 3. Storage

Checkpoint state is embedded directly in `project.json`, under a top-level
`checkpoints` map keyed by `node_id`:

```json
{
  "id": "proj_2026_06_29_loss_aversion",
  "...": "...other project.json fields per 04-DOMAIN.md...",
  "checkpoints": {
    "research": { "status": "done", "...": "..." },
    "outline": { "status": "done", "...": "..." },
    "voiceover.segment_1": { "status": "done", "...": "..." },
    "voiceover.segment_2": { "status": "failed", "error": "F5-TTS OOM", "attempt": 2 },
    "render.segment_2": { "status": "pending" }
  }
}
```

Rationale for embedding rather than a separate database: `project.json` is
already the single portable artifact for a project (per
`PROJECT_VISION.md` §2.5, v5 "diffable, mergeable creative artifact"); a
project's checkpoint state is meaningless without its `project.json`
context (DAG node definitions, inputs) and should never be able to drift out
of sync with it in two separate files. Writing `project.json` is therefore
the **only** write path for checkpoint state — no second sink.

## 4. Resume Protocol

On `ytb project resume <project_id>` (or automatic resume on a re-run of the
same `project_id`):

1. Load `project.json`, including the full `checkpoints` map.
2. Reconstruct the DAG from the project's declared workflow (per
   `05-WORKFLOW.md`).
3. For each node, in topological order:
   - `status == "done"` → **skip**. Do not re-invoke the node's provider
     call. Load `output_ref` for any downstream node that depends on it.
   - `status == "failed"` → **retry**, provided `attempt < max_attempts`
     (default `max_attempts = 3`, configurable per node type). If retries
     are exhausted, halt the resume and surface the failure — do not
     silently skip a failed node and proceed as if it were done.
   - `status in ("pending", "running")` → **run**. A `"running"` status
     found at resume time means the previous process died mid-node (crash,
     kill, power loss) — it is treated identically to `"pending"`, never
     assumed complete. This is why node execution must be idempotent (§7).
4. As each node completes, immediately persist its checkpoint update to
   `project.json` (write-through, not batched at end-of-run) — a crash
   immediately after node completion must never lose that node's `done`
   status.

## 5. Checkpoint Granularity

Checkpoints are **per DAG node**, not per pipeline stage. A stage like
"voiceover" decomposes into one node per segment
(`voiceover.segment_1`, `voiceover.segment_2`, ...), each independently
checkpointed. This is required because:

- A 12-minute episode might have 15+ voiceover segments; re-synthesizing
  all 15 because segment 9 failed wastes the 14 that already succeeded.
- Per-stage granularity would force "voiceover" to be all-or-nothing,
  contradicting the resume reliability success metric in
  `PROJECT_VISION.md` §5.

Coarser stage-level status (e.g., "is voiceover fully done?") is a derived
view — computed by checking that all `voiceover.segment_*` nodes are
`"done"` — never a separately stored checkpoint that could desync from the
per-node truth.

## 6. Failure Handling

State machine per node: `pending → running → done`, or
`pending → running → failed → running (retry) → done | failed (exhausted)`.

On failure:

1. Set `status = "failed"`, populate `error` with a concise message (full
   traceback goes to structured logs per `27-CODING_STANDARD.md`, not into
   `project.json` — keep the artifact human-readable).
2. Increment `attempt`.
3. Persist immediately (per §4 step 4).
4. Surface the failure to the orchestrator, which decides (per configured
   retry policy) whether to retry now, retry on next resume, or halt the
   run and notify (e.g., via the existing Telegram approval channel) that
   manual intervention is needed.

A node is never silently marked `"done"` after a failure without actually
re-running it successfully — there is no "mark as done anyway" path in the
automated resume protocol (§9's manual override exists precisely because
this should be a deliberate, visible human action, not an automatic one).

## 7. Idempotency

Every DAG node **must** be safe to re-run with the same inputs and produce
an equivalent result, because resume re-executes any node not already
`"done"`, including ones that partially ran before a crash. Practical
requirements this places on node implementations:

- Side effects (file writes, API calls) must check-then-act against the
  Cache System (`24-CACHE_SYSTEM.md`) rather than assuming "this is the
  first time this runs" — a node's first action on every invocation is a
  cache lookup keyed on its inputs.
- Publish-stage nodes (the one stage with genuinely non-idempotent external
  effects — uploading a video twice is not a no-op) must additionally guard
  via `settings.dry_run` and an explicit "already published" check against
  `output_ref`/the YouTube video ID before calling the upload API again on
  retry.
- No node may depend on accumulated in-memory state from a previous partial
  run of itself — all state a node needs to resume correctly must be
  derivable from `project.json` and the Cache System, not from a Python
  process that may no longer exist.

## 8. Manual Override

A CLI surface for deliberately resetting one node's checkpoint, for cases
where a human decides a "done" result was actually wrong and must be
regenerated (e.g., a TTS segment that's technically `"done"` but
mispronounces a word and needs a forced re-synthesis):

```bash
ytb checkpoint reset <project_id> <node_id>      # status -> pending, clears output_ref/error/attempt
ytb checkpoint reset <project_id> --stage voiceover  # resets all nodes under that stage prefix
ytb checkpoint show <project_id>                 # prints full checkpoint map, human-readable
```

`reset` only ever mutates the in-memory/`project.json` checkpoint record —
it never deletes the underlying cached artifact from
`24-CACHE_SYSTEM.md`'s registry automatically (the artifact might still be
valid for some other node, or the human might want to inspect it before it's
overwritten). If the human wants the cache entry gone too, that's a
separate, explicit `ytb cache evict <hash>` action.

## 9. Current State

Resume logic is implemented ad-hoc, per-module, with no shared schema:

- `voiceover/tts.py` — checks for existing output files derived from script
  content to decide whether to re-synthesize.
- `render/compose.py` — similar existence-based skip logic for rendered
  clips.
- `publish/uploader.py` — relies on `settings.dry_run` and presumably
  checks for a prior successful upload record before calling the YouTube
  API again, but this is not backed by a structured, queryable checkpoint
  record.
- `auto_state.json` — tracks listener-daemon queue/run state (what's
  queued, what's currently running) but is not a per-DAG-node checkpoint
  record and does not capture node-level `done`/`failed` granularity.

This works for the current linear four-stage pipeline because each stage is
mostly monolithic (one TTS pass, one render pass) — it will not scale to the
explicit per-segment, per-node DAG required by `05-WORKFLOW.md` and v3 of
`01-VISION.md`.

## 10. Migration to Unified Checkpoint Manager

1. **Phase A.** Implement `CheckpointManager` in
   `src/ytb_pipeline/pkg/checkpoint.py` operating purely on a
   `dict[str, CheckpointRecord]` (the `checkpoints` map) plus a
   `project.json` read/write callback — no I/O of its own beyond what's
   handed to it, so it is fully unit-testable without real files.
2. **Phase B.** Wire the still-linear pipeline (`pipeline.py`) to checkpoint
   each of its four existing stages as single nodes (`ideation`,
   `voiceover`, `render`, `publish`) — coarse-grained at first, proving the
   write-through persistence and resume-skip logic work, without yet
   requiring the full DAG executor.
3. **Phase C.** Decompose `voiceover` and `render` stages into per-segment
   nodes once segment-level domain objects exist (per `04-DOMAIN.md`'s
   `Segment`), achieving the granularity required by §5.
4. **Phase D.** Replace `auto_state.json`'s queue-state responsibilities
   with `CheckpointManager` queries (e.g., "which projects have any
   `"running"` node and should be considered in-progress") — collapsing two
   ad-hoc state files into one structured source of truth.
5. **Phase E.** Add the `ytb checkpoint reset`/`show` CLI (§8) once the
   manager is live end-to-end.

Acceptance: `ytb project resume <id>` works correctly after a `kill -9` of
the pipeline process at any point — verified by an integration test that
kills mid-run and asserts the rerun does not regenerate any node already
cached/checkpointed as `"done"`.
