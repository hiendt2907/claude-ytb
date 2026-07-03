# 37 — CREATIVE COMPILER

## Purpose

This document specifies the Creative Compiler — the architectural
centerpiece that transforms a high-level creative intent (a `Topic` plus
constraints) into a fully-specified, executable `WorkflowGraph`
(`04-DOMAIN.md`, `05-WORKFLOW.md`). It is the component that makes
`01-VISION.md`'s "AI models are orchestrated tools the system calls at
well-defined DAG nodes, not an opaque black box" literal: the Creative
Compiler is what produces those well-defined DAG nodes from a creative idea
*before* any expensive generation work begins.

---

## Section 1 — What Is the Creative Compiler?

The analogy is deliberate and load-bearing: like a programming-language
compiler, the Creative Compiler has a **source** (creative intent), an
**AST** (the narrative's intermediate structure), an **IR** (a
platform-agnostic but execution-aware intermediate representation), and a
**codegen** phase (the executable artifact).

| Compiler concept | This project's equivalent |
|---|---|
| Source | Creative intent: topic, platform, duration, style, audience (`CreativeIntent`) |
| AST | `Outline → Story → Narrative` (the parsed, structured creative idea) |
| IR | `Scene Graph + Shot List + Storyboard` (`33-GRAPH_MODELS.md` §2) |
| Codegen | `WorkflowGraph` (`04-DOMAIN.md`) — a DAG of executable `WorkflowNode`s |
| Output | `project.json`, fully specified, ready to execute |

The compiler makes **all** creative decisions upfront, before the first
unit of expensive generation compute is spent:

- Which scenes to generate (derived from the Outline's beats and the
  Narrative's scene boundaries).
- Which agents to invoke at each stage (`06-AGENTS.md`'s registry, resolved
  per capability needed).
- Which providers to use, based on `target_platforms` and
  `config/settings.py` (`21-PROVIDER_SYSTEM.md`'s resolver, consulted at
  compile time rather than improvised at each node's execution time).
- Which assets need to be generated fresh versus reused from cache
  (`24-CACHE_SYSTEM.md`, cross-referenced against the Asset Graph,
  `33-GRAPH_MODELS.md` §1).

This is the structural difference between a **planner** (which proposes a
plan that may still be revised mid-execution) and a **compiler** (which
fully resolves every decision before execution starts, so the executor's
job is purely mechanical). §7 expands on why this distinction is named
deliberately.

---

## Section 2 — Compiler Stages

```
Stage 1: PARSE
  Input: Topic + Platform + Duration + Style + Audience
  Output: CreativeIntent (structured)
  Agent: Creative Director

Stage 2: RESEARCH
  Input: CreativeIntent
  Output: ResearchReport (facts, sources, knowledge graph)
  Agent: Research Agent

Stage 3: OUTLINE
  Input: CreativeIntent + ResearchReport
  Output: Outline (acts, beats, mechanisms)
  Agent: Story Architect

Stage 4: NARRATIVE
  Input: Outline
  Output: Narrative (scene-by-scene plan, emotional arc)
  Agent: Narrative Planner

Stage 5: STORYBOARD
  Input: Narrative
  Output: Storyboard (shots, frames, camera, visual notes)
  Agent: Storyboard Agent + Visual Director

Stage 6: ASSET PLANNING
  Input: Storyboard
  Output: AssetManifest (list of all assets needed, with cache hits flagged)
  Agent: Creative Compiler (deterministic, no LLM)

Stage 7: CODEGEN
  Input: AssetManifest + Platform Profile
  Output: WorkflowGraph (DAG of nodes)
  Agent: Creative Compiler (deterministic, no LLM)
```

Stages 1–5 correspond directly to existing `05-WORKFLOW.md` DAG nodes
(`Research`, `Outline`, `Narrative`, ... `Storyboard`) — the Creative
Compiler does not replace those nodes' LLM-driven work, it is the component
that *sequences and packages* their outputs into something execution-ready.
Stages 6–7 are new: today, nothing in the codebase explicitly separates "plan
what assets are needed" from "actually generate them" — asset generation
calls are interleaved with planning inside `ideation/generator.py` and
`render/compose_ai.py`. The Creative Compiler's contribution is making
stages 6–7 their own explicit, deterministic, no-LLM phase.

---

## Section 3 — Asset Planning (Deterministic)

For each `Scene`/`Shot`/`Frame` in the Storyboard, the compiler determines
exactly which `Asset`s must exist for that node to be renderable: a scene
image, a voice segment, an animation/video clip, a subtitle segment.

```python
@dataclass(frozen=True)
class AssetPlanItem:
    frame_id: str
    asset_kind: str            # "image" | "audio" | "video" | "subtitle"
    content_hash: str          # computed from the Frame's prompt + style refs, per 24-CACHE_SYSTEM.md
    decision: str              # "GENERATE" | "CACHE_HIT"
    cached_asset_id: str | None = None


@dataclass(frozen=True)
class AssetManifest:
    project_id: str
    items: tuple[AssetPlanItem, ...]
    estimated_generation_count: int   # len(items where decision == "GENERATE")
```

For each `AssetPlanItem`, the compiler checks `AssetCache`
(`24-CACHE_SYSTEM.md`) by `content_hash`: a hit marks the item
`CACHE_HIT`, referencing the existing `Asset.id` — no `WorkflowNode` is
generated for it (§4); a miss marks it `GENERATE`, and a node is generated.
This is a pure function of the Storyboard plus the current cache state — no
LLM call is involved, which is why this stage and Stage 7 are explicitly
"Agent: Creative Compiler (deterministic, no LLM)" rather than attributed to
any of the LLM-backed agents in Stages 1–5.

**Optimization:** the compiler orders generation so that maximum cache
reuse is achieved — if `Character.visual_style_prompt`'s reference image is
unchanged since a prior project, every `Frame` referencing that `Character`
(`33-GRAPH_MODELS.md` §2's `REFERENCES_CHARACTER` edge) is a candidate for
generating fewer unique style-reference renders, reusing the existing one
across scenes rather than regenerating a near-duplicate per scene.

---

## Section 4 — Code Generation (Deterministic)

The `AssetManifest` plus the resolved `PlatformProfile`
(`target_platforms`-driven render preset and `Publisher` selection, per
`03-ARCHITECTURE.md`'s extension-points guidance) compiles into a
`WorkflowGraph`:

- One `WorkflowNode` per `AssetPlanItem` marked `GENERATE` — no node is
  created for `CACHE_HIT` items, since there is nothing to execute for them
  (their `output_ref` is already known and is wired directly to whatever
  downstream node consumes them).
- Dependencies between nodes are encoded as `WorkflowNode.depends_on` edges,
  derived directly from the Scene Graph's structure
  (`33-GRAPH_MODELS.md` §2) and the Asset Graph's `DERIVED_FROM`/
  `COMPOSED_WITH` edges (`33-GRAPH_MODELS.md` §1) — the compiler is, in this
  step, literally translating one graph (creative structure) plus another
  graph (asset dependency) into a third graph (execution order), which is
  why `33-GRAPH_MODELS.md`'s explicit distinction between Scene Graph and
  WorkflowGraph matters: this translation step is where one becomes the
  other.
- Independent branches are preserved as parallel-eligible subgraphs — e.g.,
  per-frame image generation nodes with no edges between them are
  independently schedulable by the v3 DAG executor
  (`05-WORKFLOW.md`'s "independent branches execute concurrently" rule),
  exactly as `VoicePrompt` and `ScenePlanning→VideoPrompt` already do.
- Output: a fully populated `project.json`, including the `WorkflowGraph`,
  an empty `checkpoints` map (per `25-CHECKPOINT_SYSTEM.md`), and the
  `lifecycle` record initialized to `ProjectState.APPROVED`
  (`32-STATE_MACHINE.md`) — compilation happens *after* script approval,
  never before, since asset planning depends on a Storyboard that itself
  depends on an approved Narrative.

---

## Section 5 — Python Implementation

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class CreativeCompiler:
    llm_engine: "LLMEngine"
    agent_registry: "AgentRegistry"
    asset_cache: "CacheManager"
    platform_profile: "PlatformProfile"

    async def compile(self, intent: "CreativeIntent") -> "WorkflowGraph":
        # Stage 1-5: LLM-driven (creative decisions)
        research = await self._research(intent)
        outline = await self._outline(intent, research)
        narrative = await self._plan_narrative(outline)
        storyboard = await self._storyboard(narrative)
        # Stage 6-7: Deterministic (compiler decisions)
        manifest = self._plan_assets(storyboard)
        graph = self._codegen(manifest, self.platform_profile)
        return graph

    async def _research(self, intent: "CreativeIntent") -> "Research":
        agent = self.agent_registry.get("research_agent")
        return await agent.run(intent)

    async def _outline(self, intent: "CreativeIntent", research: "Research") -> "Outline":
        agent = self.agent_registry.get("story_architect")
        return await agent.run(intent, research)

    async def _plan_narrative(self, outline: "Outline") -> "Narrative":
        agent = self.agent_registry.get("narrative_planner")
        return await agent.run(outline)

    async def _storyboard(self, narrative: "Narrative") -> "Storyboard":
        agent = self.agent_registry.get("storyboard_agent")
        return await agent.run(narrative)

    def _plan_assets(self, storyboard: "Storyboard") -> "AssetManifest":
        items = tuple(
            self._plan_one_asset(frame) for scene in storyboard.scenes for frame in scene.frames
        )
        generate_count = sum(1 for item in items if item.decision == "GENERATE")
        return AssetManifest(project_id=storyboard.project_id, items=items, estimated_generation_count=generate_count)

    def _plan_one_asset(self, frame: "Frame") -> "AssetPlanItem":
        content_hash = self.asset_cache.compute_hash(frame)
        cached = self.asset_cache.lookup(content_hash)
        if cached is not None:
            return AssetPlanItem(frame.id, "image", content_hash, "CACHE_HIT", cached.id)
        return AssetPlanItem(frame.id, "image", content_hash, "GENERATE")

    def _codegen(self, manifest: "AssetManifest", profile: "PlatformProfile") -> "WorkflowGraph":
        nodes = tuple(
            self._node_for(item, profile) for item in manifest.items if item.decision == "GENERATE"
        )
        return WorkflowGraph(id=new_id(), project_id=manifest.project_id, nodes=nodes, created_at=now())
```

`CreativeCompiler` is itself a frozen dataclass (per ADR-001,
`31-ADR.md`) — its fields are its dependencies (the `LLMEngine`,
`AgentRegistry`, `CacheManager`, `PlatformProfile`), injected once and never
mutated; `compile()` is a pure async method with no hidden instance state
beyond those injected collaborators, keeping the compiler itself trivially
testable with fake/stub collaborators per the Provider Pattern's general
testability argument (ADR-008, `31-ADR.md`).

---

## Section 6 — Relationship to Existing Code

Today, `pipeline.py` runs four stages sequentially with no explicit planning
phase — ideation directly produces a script, voiceover/render/publish run in
sequence, and "what assets are needed" is decided implicitly, call by call,
inside `ideation/generator.py` and `ideation/series.py` as the pipeline
progresses, rather than upfront.

The `CreativeCompiler` **replaces** the current ideation stage's "decide as
you go" structure and **adds** an explicit planning phase (Stages 6–7)
before any render-phase execution begins. `batch_cli.py` continues to
orchestrate the overall run (it remains the Application-layer entrypoint,
per `03-ARCHITECTURE.md`), but its role narrows: it now calls
`CreativeCompiler.compile()` to obtain a `WorkflowGraph`, then hands that
graph to the DAG executor (`05-WORKFLOW.md`, v3 milestone) — `batch_cli.py`
no longer needs to know *what* to generate, only *that* a graph exists and
must be executed/resumed.

**Migration path:** wrap the current `ideation/generator.py` +
`ideation/series.py` logic as a stub `CreativeCompiler` whose `_research`/
`_outline`/`_plan_narrative`/`_storyboard` methods call into the existing
code paths unchanged, while `_plan_assets`/`_codegen` (Stages 6–7) are new
code introduced for the first time — this isolates "new behavior" (explicit
asset planning) from "relocated behavior" (existing ideation logic moved
behind a new interface), so a regression introduced during migration is
attributable to one or the other, not both at once.

---

## Section 7 — Why "Compiler" Not "Planner"

The naming is a substantive distinction, not a stylistic preference:

- A **Planner** proposes a plan that may be revised at runtime — if a node
  fails mid-execution, a planner-based system might re-plan downstream
  steps in response, meaning "what will run" is not fully knowable until
  execution is well underway.
- A **Compiler** fully resolves all decisions upfront; the executor's only
  job is to run the DAG it was handed, retry per `32-STATE_MACHINE.md`'s
  `WorkflowNode` retry policy, and checkpoint per
  `25-CHECKPOINT_SYSTEM.md` — it does not improvise new nodes or change the
  graph's shape mid-run.

This separation is what enables three properties this project specifically
needs:

1. **Dry-run (compile without executing).** A creator can ask "show me what
   this topic would compile into" — the `AssetManifest`'s
   `estimated_generation_count` and the `WorkflowGraph`'s node list —
   without spending a single second of render compute, because compilation
   and execution are separate calls.
2. **Plan review before execution.** The Telegram approval gate
   (`32-STATE_MACHINE.md`'s `SCRIPTED → APPROVED` transition) reviews the
   compiled plan's *script and structure*, with the confidence that what
   gets approved is what will execute — there is no "the plan changed after
   I approved it" risk, because nothing re-plans mid-run.
3. **Deterministic replays.** Given the same `CreativeIntent` and the same
   cache state, `compile()` produces the same `WorkflowGraph` — this is the
   same reproducibility property `36-AI_GOVERNANCE.md` §4 requires of
   individual LLM calls, extended to the whole-project planning level.

A planner-shaped system could not offer any of these three without
additional machinery to "freeze" a plan at approval time — which would just
be reinventing the Compiler's upfront-resolution property under a different
name. Calling it a Compiler from the start keeps the architecture honest
about what guarantee it is actually providing.

---

## Section 8 — Error Handling

Two distinct error categories, handled differently, mirroring the
transient-vs-structural distinction `05-WORKFLOW.md` and
`32-STATE_MACHINE.md`'s retry policy already establish for `WorkflowNode`
execution:

- **Compile errors** — missing research (Stage 2 produced zero usable
  sources), a quality-gate failure detected during Stages 3–5 (e.g., the
  Outline's beats don't fit the target duration after the configured
  regeneration attempts), or an Asset Planning inconsistency (Stage 6 finds
  a `Frame` with no resolvable style reference). These raise a
  `CompileError` and **halt before any `WorkflowNode` is created** — no
  render compute is ever spent reacting to a compile-time problem, which is
  the entire point of separating planning from execution.

```python
class CompileError(Exception):
    """Raised when the Creative Compiler cannot produce a valid WorkflowGraph.

    Always raised before any WorkflowNode is constructed — compilation
    fails cheap, never mid-render.
    """
```

- **Runtime errors** — a TTS provider crash, an FFmpeg render crash, a local
  diffusion model OOM. These occur *after* compilation succeeded and the
  `WorkflowGraph` is executing; they are handled by the existing
  `WorkflowNode` retry/checkpoint machinery
  (`32-STATE_MACHINE.md` §2, `25-CHECKPOINT_SYSTEM.md`) — the Creative
  Compiler has no further role once `compile()` has returned a graph; it
  does not intervene in runtime failures, and it is never re-invoked
  mid-execution to "fix" a failing node (that would reintroduce the
  planner-style re-planning behavior §7 explicitly rejects).

**Philosophy: fail cheap, not expensive.** A `CompileError` surfaces before
a single second of GPU/NPU time is spent — the cost of catching a bad
Outline at Stage 3 is one more LLM call's worth of latency. A failure
discovered mid-`Renderer` after Storyboard, ImagePrompt, AnimationPrompt,
VideoPrompt, and VoicePrompt have all already run successfully is the
expensive failure this architecture is designed to make rare: the Creative
Compiler's entire reason for existing is to move as many possible failure
points as possible from "after expensive compute" to "before any compute,"
consistent with the testing-pyramid intuition that cheap checks should run
before expensive ones, applied here to a creative-generation pipeline
instead of a test suite.
</content>
