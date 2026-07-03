# 05 — WORKFLOW

## Purpose

This document specifies the full pipeline as a directed acyclic graph (DAG)
of `WorkflowNode`s, the checkpoint/resume contract every node must honor, and
the failure/retry behavior expected at each stage. It is the operational
contract behind `03-ARCHITECTURE.md`'s "Application Layer" box and the
`WorkflowNode`/`Checkpoint` objects defined in `04-DOMAIN.md`.

## DAG Diagram

```
Topic
  │
  ▼
Research ───────────────────────────────────────────┐
  │                                                  │
  ▼                                                  │
KnowledgeGraph  (merge with persisted KnowledgeBase) │
  │                                                  │
  ▼                                                  │
Outline ◄─────────────────────────────────────────── ┘ (KB informs Outline)
  │
  ▼
Narrative
  │
  ▼
Script
  │
  ▼
SentenceSplit
  │
  ▼
ScenePlanning
  │
  ▼
ShotPlanning
  │
  ▼
Storyboard
  │
  ├──────────────────────────────┐
  ▼                              ▼
VisualPlanning              CameraPlanning
  │                              │
  ▼                              │
ImagePrompt ◄────────────────────┘ (camera framing informs ImagePrompt)
  │
  ├──────────────┐
  ▼              ▼
StickmanPrompt  AnimationPrompt
                  │
                  ▼
              VideoPrompt
  │
  ▼ (parallel branch, depends on Script not Storyboard)
VoicePrompt
  │
  ▼
Subtitle  (depends on VoicePrompt output + SentenceSplit timing)
  │
  ▼
Music
  │
  ▼
SFX
  │
  ▼
Timeline   (merges: VideoPrompt-rendered Assets, VoicePrompt audio, Subtitle, Music, SFX)
  │
  ▼
Assets     (resolved/rendered Asset objects backing every Timeline item)
  │
  ▼
Renderer   (RenderJob: composes Timeline + Assets → final video Asset)
  │
  ▼
Publisher  (PublishJob: uploads final Asset to target platform[s])
```

Note: `VoicePrompt` branches off `Script` directly and runs concurrently with
the `ScenePlanning → ... → VideoPrompt` visual branch — both converge at
`Timeline`. The executor must schedule independent branches concurrently
where their `WorkflowNode.depends_on` sets do not intersect.

## Node Specifications

For each node: **Inputs**, **Outputs**, **Failure modes**, **Retry strategy**.

### Research
- **Inputs:** `Project.id`, `topic: str`
- **Outputs:** `Research` (domain object)
- **Failure modes:** no sources found; LLM/search timeout; topic flagged as
  banned/disallowed
- **Retry:** exponential backoff, max 3, on timeout only. A "banned topic"
  result is a quality-gate failure, not retried — escalate to human review.

### KnowledgeGraph
- **Inputs:** `Research`, existing `KnowledgeBase` (if any, by niche)
- **Outputs:** updated `KnowledgeBase`
- **Failure modes:** merge conflict between new findings and existing
  canonical facts
- **Retry:** none on conflict — surface to human approval; safe to retry on
  transient I/O failure only.

### Outline
- **Inputs:** `Research`, `KnowledgeBase`
- **Outputs:** `Outline`
- **Failure modes:** LLM produces beats outside target duration tolerance
- **Retry:** regenerate with adjusted duration constraint, max 3 attempts.

### Narrative
- **Inputs:** `Outline`
- **Outputs:** `Story`, `Narrative`
- **Failure modes:** narrative drifts from niche/KnowledgeBase facts
  (hallucination); length out of bounds
- **Retry:** regenerate with stricter fact-grounding prompt, max 3.

### Script
- **Inputs:** `Narrative`
- **Outputs:** finalized script text (feeds `SentenceSplit` and `VoicePrompt`)
- **Failure modes:** fails length gate (`test_length_gate.py` precedent),
  fails intro gate (`test_intro_gate.py` precedent)
- **Retry:** regenerate targeted section only (not full script), max 3; on
  persistent failure, route to human approval gate.

### SentenceSplit
- **Inputs:** Script text
- **Outputs:** ordered sentence/timing units consumed by `ScenePlanning` and
  later by `Subtitle`
- **Failure modes:** segmentation produces sentences exceeding TTS provider
  max input length
- **Retry:** re-split with smaller max-chunk size, max 2; no LLM call
  involved, so failures here are deterministic bugs, not flaky.

### ScenePlanning
- **Inputs:** sentence units, `Outline` beats
- **Outputs:** `Scene` objects (ordered, linked to narrative beats)
- **Failure modes:** scene count doesn't match expected beat count
- **Retry:** regenerate scene boundaries, max 3.

### ShotPlanning
- **Inputs:** `Scene` objects
- **Outputs:** `Shot` objects per Scene
- **Failure modes:** shot durations don't sum to scene duration
- **Retry:** rebalance shot durations algorithmically (deterministic fix,
  not an LLM retry) before falling back to regeneration.

### Storyboard
- **Inputs:** `Shot` objects
- **Outputs:** `Frame` objects per Shot (the storyboard is the full
  Scene→Shot→Frame tree)
- **Failure modes:** frame count zero for a shot (degenerate shot)
- **Retry:** regenerate frames for the affected shot only, max 3.

### VisualPlanning
- **Inputs:** `Frame` objects, `Character`/`Location` style references
- **Outputs:** draft visual direction per Frame (style, composition intent)
- **Failure modes:** style direction conflicts with `KnowledgeBase` niche
  style guide
- **Retry:** regenerate with explicit style-guide constraint injected, max 3.

### CameraPlanning
- **Inputs:** `Frame` objects, `Shot` description
- **Outputs:** `Camera` object per Shot
- **Failure modes:** camera movement incompatible with chosen render
  strategy (e.g., dolly movement requested but `slide` strategy selected)
- **Retry:** fall back to nearest supported camera directive for the active
  `RenderProvider`, no LLM retry needed (deterministic mapping).

### ImagePrompt
- **Inputs:** `Frame`, `VisualPlanning` output, `CameraPlanning` output,
  `Character`/`Location` style prompts
- **Outputs:** `ImagePrompt` + `PromptVersion`
- **Failure modes:** prompt exceeds `ImageProvider` max token length
- **Retry:** truncate/summarize prompt, max 2; else regenerate, max 3.

### StickmanPrompt
- **Inputs:** `ImagePrompt` (used for low-fidelity pose/composition preview
  before full image generation — supports fast iteration without invoking
  the full local diffusion model)
- **Outputs:** lightweight pose-sketch prompt/asset
- **Failure modes:** none beyond generic provider failure
- **Retry:** exponential backoff, max 3; this node is skippable (config
  flag) without blocking downstream nodes, since it is a preview aid.

### AnimationPrompt
- **Inputs:** `ImagePrompt`-resolved image `Asset`
- **Outputs:** `AnimationPrompt` + `PromptVersion`
- **Failure modes:** source image asset missing/corrupt
- **Retry:** re-fetch/re-render source image once, then regenerate
  AnimationPrompt, max 3.

### VideoPrompt
- **Inputs:** `AnimationPrompt`-resolved animation
- **Outputs:** `VideoPrompt` + `PromptVersion`, eventually a video `Asset`
- **Failure modes:** local `VideoProvider` GPU/NPU resource exhaustion;
  generation exceeds time budget
- **Retry:** exponential backoff with reduced resolution/duration on second
  attempt, max 3; on persistent failure, this is the single sanctioned point
  where an explicit, config-gated fallback to stock B-roll (Pexels) may
  occur — logged clearly as a fallback, never silent.

### VoicePrompt
- **Inputs:** `VoiceScript` (derived from Script + Character voice
  assignment)
- **Outputs:** synthesized audio `Asset`
- **Failure modes:** local `VoiceProvider` (F5-TTS) model not loaded;
  pronunciation errors (`voiceover/pronunciation.py` precedent)
- **Retry:** reload model once, retry synthesis, max 3; pronunciation
  correction is a deterministic pre-processing retry, not a model retry.

### Subtitle
- **Inputs:** synthesized audio `Asset` (for timing), `SentenceSplit` output
- **Outputs:** `Subtitle` with `SubtitleSegment`s
- **Failure modes:** forced-alignment timing drift beyond tolerance
- **Retry:** re-run alignment with relaxed tolerance, max 2; deterministic,
  not an LLM call.

### Music
- **Inputs:** `Narrative` mood/tone, target duration
- **Outputs:** `Music` asset reference
- **Failure modes:** no mood-matching local track found in asset library
- **Retry:** widen mood-matching tolerance, max 2; else proceed without
  music (degraded but non-blocking).

### SFX
- **Inputs:** `Frame`-level trigger annotations
- **Outputs:** `SFX` asset references
- **Failure modes:** no matching SFX asset for a trigger
- **Retry:** skip the individual SFX cue (non-blocking); log as a content
  gap, not a pipeline failure.

### Timeline
- **Inputs:** all of: rendered video `Asset`s, voice audio `Asset`, `Subtitle`,
  `Music`, `SFX`
- **Outputs:** `Timeline` with ordered `TimelineItem`s
- **Failure modes:** track overlap conflicts; total duration mismatch vs.
  target
- **Retry:** deterministic conflict resolution pass, max 2; else escalate to
  human review (this is a structural assembly error, not something an LLM
  retry fixes).

### Assets
- **Inputs:** `Timeline` references
- **Outputs:** verified, resolved `Asset` files on disk (existence + format
  validation pass)
- **Failure modes:** referenced asset file missing or corrupt
- **Retry:** re-resolve/re-render the specific missing asset's originating
  node (not the whole pipeline), max 3.

### Renderer
- **Inputs:** `Timeline`, resolved `Asset`s, render `strategy` (`slide` |
  `ai`)
- **Outputs:** `RenderJob` → final video `Asset`
- **Failure modes:** FFmpeg/Pillow crash; output file fails post-render
  validation (duration, resolution, audio sync)
- **Retry:** retry render once with the same inputs (handles transient
  FFmpeg flakiness), then escalate; this node must always checkpoint
  partial render state if the underlying tool supports resumable encoding.

### Publisher
- **Inputs:** final video `Asset`, target platform metadata
- **Outputs:** `PublishJob` with `remote_url`
- **Failure modes:** OAuth token expired; platform API rate limit; quota
  exceeded; network failure
- **Retry:** exponential backoff for rate limit/network, max 5 (publish is
  the one stage where elevated retry count is justified, since it is the
  inherently networked final step); OAuth failures are not retried — they
  require human re-authentication, surfaced immediately.

## Checkpoint Specification

### When to Checkpoint

A checkpoint is written **immediately after** a `WorkflowNode` produces a
successful output, and **also** on terminal failure (after retries
exhausted), so failure state itself is resumable/inspectable rather than
lost. A checkpoint is never written for a transient in-progress retry
attempt — only for a node's final resolved state (succeeded or
failed-after-retries).

### What to Save

Each `Checkpoint` (per `04-DOMAIN.md`) records:

- `workflow_graph_id`, `node_id` — which DAG and node this belongs to
- `status` — `succeeded` or `failed`
- `output_ref` — a path (for large artifacts: audio/image/video files) or an
  inline id (for small structured objects: `Outline`, `Scene` lists) pointing
  to the persisted node output
- `error` — populated on failure, includes enough context to diagnose
  without re-running (provider name, exception type, truncated message)
- `created_at`

Checkpoints are append-only and keyed by `(workflow_graph_id, node_id)` —
re-running a node after a fix creates a new `Checkpoint` record rather than
overwriting the prior one, preserving run history for debugging.

### Resume Protocol

1. On `Project` run start/resume, the orchestrator loads all existing
   `Checkpoint`s for the `WorkflowGraph.id`.
2. For each `WorkflowNode`, if a `succeeded` checkpoint exists, its
   `output_ref` is loaded and the node is **not** re-executed — its output
   is fed directly to downstream nodes.
3. If a `failed` checkpoint exists and the underlying issue has not been
   addressed (no config/code change since), resume surfaces the failure to
   the human/approval gate rather than blindly retrying — this prevents
   infinite retry loops on a persistent failure (e.g., a banned topic).
4. If a `failed` checkpoint exists and the operator has indicated the
   blocking issue is resolved (explicit resume flag), the node re-executes
   from its original inputs (which are themselves derived from upstream
   checkpoints, so no upstream recomputation occurs).
5. Nodes with no checkpoint execute normally, writing a new checkpoint on
   completion.
6. The DAG executor walks nodes in topological order, respecting
   `WorkflowNode.depends_on`; independent branches (e.g., the
   `VoicePrompt → Subtitle` branch versus the
   `ScenePlanning → ... → VideoPrompt` branch) execute concurrently when
   their dependency sets do not overlap, and resume independently of each
   other's checkpoint state.

This protocol guarantees that an interrupted multi-hour run (e.g., one that
fails during `Renderer` after successfully completing `Research` through
`Assets`) resumes by re-running only `Renderer` onward — never recomputing
LLM calls, TTS synthesis, or image/video generation that already succeeded.
