# 06 — AGENTS

## Purpose

Define the contract for every AI Agent in the Creative OS: what each agent is
responsible for, what it consumes and produces, how it fails, and which model
class (local vs cloud) it should run on. Agents are **pure orchestration units**
— they call into Engines (LLM/Image/Video/Voice/Asset, see 09–14) but never talk
to a model provider directly. This keeps agents swappable, testable in
isolation (mock the engine), and replaceable without touching provider code.

## Architectural Position

```
                 ┌─────────────────────┐
                 │   Creative Director  │  orchestrates, decides, gates
                 └──────────┬──────────┘
        ┌───────────────────┼───────────────────────┐
        ▼                   ▼                       ▼
  Research Agent     Story Architect          QA Agent (gate)
        │                   │
        ▼                   ▼
  (knowledge graph)   Narrative Planner
                            │
                            ▼
                      Storyboard Agent ──► Visual Director
                            │                    │
                            ▼                    ▼
                     Camera Director      Image Planner / Animation Planner
                            │
                            ▼
                      Voice Director ──► Subtitle Agent
                            │
                            ▼
                       Editor Agent ──► Continuity Agent
                            │
                            ▼
                 SEO Agent / Thumbnail Agent
```

Every agent is a **Protocol implementation** registered in an `AgentRegistry`.
The Creative Director resolves agents by capability name, never by import path
— this is what lets a future `StoryArchitectV2` replace `StoryArchitect` with
zero call-site changes.

## Shared Agent Contract

```python
from typing import Protocol, TypeVar
from dataclasses import dataclass

TIn = TypeVar("TIn")
TOut = TypeVar("TOut")


@dataclass(frozen=True)
class AgentResult[TOut]:
    """Uniform envelope every agent returns — never a bare model object."""

    output: TOut
    confidence: float          # 0.0-1.0, self-reported
    cost_usd: float            # 0.0 for local inference
    model_used: str            # e.g. "ollama/qwen3:14b" or "claude-opus-4-6"
    retries: int
    warnings: tuple[str, ...] = ()


class Agent(Protocol[TIn, TOut]):
    """Every agent in the OS implements this shape."""

    name: str

    async def run(self, input: TIn, *, ctx: "RunContext") -> AgentResult[TOut]:
        """Execute the agent's single responsibility. MUST be idempotent
        given the same (input, ctx.seed) — required for checkpoint/resume."""
        ...

    def validate_output(self, output: TOut) -> tuple[bool, str]:
        """Schema + domain validation. Called by the agent itself before
        returning AND by QA Agent independently. Returns (is_valid, reason)."""
        ...
```

`RunContext` carries `run_id`, `checkpoint_dir`, `tenant_config`, `budget`
(token/cost ceiling), and `seed` (determinism for retries/tests). It is
**read-only** to agents — agents propose, the Creative Director commits state.

## Failure & Retry Conventions (apply to every agent below)

| Failure mode | Detection | Retry strategy |
|---|---|---|
| Schema violation (malformed JSON/struct) | `validate_output()` fails | Re-prompt with the validation error appended as correction context, max 2 retries |
| Hallucinated reference (fact, asset, character not in context) | Cross-check against `RunContext` knowledge graph / asset registry | Re-prompt with explicit "only use provided facts/assets" constraint, max 2 retries |
| Timeout (model unresponsive) | Engine-level timeout (default 60s local / 30s cloud) | Exponential backoff (1s, 4s, 9s), then fallback provider per Engine's fallback chain |
| Budget exceeded | `ctx.budget` check before dispatch | Hard stop, escalate to Creative Director, no silent downgrade |
| Empty/degenerate output | Length + diversity heuristics | 1 retry with temperature bump (+0.2), then flag for human review |

All retries are logged to the run's checkpoint as `AgentResult.retries` — never
silently swallowed. After exhausting retries, the agent returns a result with
`confidence=0.0` and a `warnings` entry; it never raises past the Creative
Director boundary so a single agent failure cannot crash the DAG (see 02-DAG
checkpoint/resume).

---

## Creative Director

**Purpose**: Top-level orchestrator. Owns the DAG execution order, resolves
conflicts between agents (e.g. Story Architect wants a 12-min runtime, Voice
Director's pacing implies 14-min), and makes the final go/no-go call before
handing off to rendering.

**Inputs**: `VideoBrief` (topic, platform, target length, niche constraints,
series context), prior run history (for series continuity).

**Outputs**: `ProductionPlan` — resolved Storyboard + Scene list + agent
assignment + budget allocation, ready for the Asset/Render Engines.

**Responsibilities**:
- Sequence agent calls per the DAG (Research → Story → Narrative → Storyboard
  → Visual/Camera → Image/Animation → Voice → Subtitle → Editor → Continuity
  → SEO/Thumbnail → QA gate).
- Arbitrate conflicting constraints (length, tone, budget) by priority order
  defined in `VideoBrief.constraints`.
- Own the final accept/reject decision after QA Agent reports.
- Persist `ProductionPlan` as the DAG checkpoint boundary after each major
  phase (research, story, storyboard, render-ready).

**Interface**:

```python
class CreativeDirector(Protocol):
    async def plan(self, brief: VideoBrief, ctx: RunContext) -> AgentResult[ProductionPlan]: ...
    async def resolve_conflict(
        self, conflicts: tuple["AgentConflict", ...], ctx: RunContext
    ) -> "Resolution": ...
    async def finalize(self, plan: ProductionPlan, qa: "QAReport", ctx: RunContext) -> AgentResult[ProductionPlan]: ...
```

**Failure modes**: deadlock between agents with contradictory hard constraints
(e.g. Story Architect minimum 3 acts vs platform max 60s) → escalate to human
via Telegram approval gate rather than silently picking a side.

**Retry strategy**: re-invoke the conflicting agents with the resolved
constraint injected as a hard system constraint; max 1 re-plan cycle before
human escalation.

**Model recommendation**: cloud (Claude Sonnet/Opus class) — this is the
highest-stakes reasoning seat (multi-constraint arbitration); local Qwen3 is
the fallback when offline-only mode is forced.

---

## Research Agent

**Purpose**: Web research, fact verification, and incremental knowledge graph
construction for a topic/niche so downstream agents write claims that are
sourced and accurate (`ERR_REA_NO_PHYSICAL_PROOF`-equivalent guard for content).

**Inputs**: `topic: str`, `niche_constraints`, existing `KnowledgeGraph` (if
series — accumulate, don't restart).

**Outputs**: `ResearchBrief` (claims with source URLs + confidence, mechanism
explanations, contradictions found), updated `KnowledgeGraph` delta.

**Responsibilities**:
- Issue targeted search queries, fetch and extract primary sources.
- Tag every claim with a source; reject unsourced claims rather than inventing
  citations.
- Detect contradictions between sources and surface them instead of picking
  silently.
- Merge findings into the running `KnowledgeGraph` (entities + relations), not
  a flat list — enables Continuity Agent and series cross-referencing later.

**Interface**:

```python
class ResearchAgent(Protocol):
    async def research(self, topic: str, ctx: RunContext) -> AgentResult[ResearchBrief]: ...
    async def verify_claim(self, claim: str, ctx: RunContext) -> AgentResult["VerifiedClaim"]: ...
```

**Failure modes**: search returns no authoritative sources (saturated/niche
topic); contradicting sources of equal authority.

**Retry strategy**: broaden query (drop most restrictive filter term) once;
if still empty, return brief with `confidence<0.4` and flag for Creative
Director to either narrow topic or proceed with explicit "unverified" labeling.

**Model recommendation**: cloud (needs live web tools — Claude with web
search/browsing tool use, or a dedicated search API agent). Not suitable for
fully offline-first mode; degrade gracefully to "use existing KnowledgeGraph
only" when offline.

---

## Story Architect

**Purpose**: Define the narrative skeleton — act structure (3-act, or
problem→mechanism→solution for the channel's mechanism-explainer format).

**Inputs**: `ResearchBrief`, `VideoBrief` (target length, platform, niche
voice rules), series context (prior episode hooks/bridges).

**Outputs**: `StoryStructure` — ordered `Act` list, each with purpose,
target duration share, and the core claim/mechanism it carries.

**Responsibilities**:
- Choose structure template (3-act vs 5-part mechanism format) based on
  `VideoBrief.format`.
- Allocate runtime budget per act proportionally to target length.
- Ensure the structure ends with a series bridge when `series_context` is set
  (per the channel's "no Tập n badge, but link forward" rule).
- Reject structures that violate niche gates (no self-help framing, etc.) by
  delegating the check to QA Agent's rule set — Story Architect itself stays
  generative, QA enforces.

**Interface**:

```python
class StoryArchitect(Protocol):
    async def build_structure(
        self, research: ResearchBrief, brief: VideoBrief, ctx: RunContext
    ) -> AgentResult[StoryStructure]: ...
```

**Failure modes**: research too thin to support a full structure (one
mechanism, not enough supporting detail) → structure degenerates to filler.

**Retry strategy**: request Research Agent for a targeted follow-up on the
thin act before re-running structure generation; max 1 round-trip.

**Model recommendation**: local-first (Ollama/Qwen3:14b+) — structural
reasoning over already-researched material is well within local model
capability; escalate to cloud only if local output fails QA twice.

---

## Narrative Planner

**Purpose**: Break each `Act` into scenes with pacing and emotional-arc
targets — the bridge between story structure and the Scene Engine (08).

**Inputs**: `StoryStructure`, target total duration, platform pacing norms
(Shorts need higher beat density than 12-min long-form).

**Outputs**: `ScenePlan` — ordered list of `SceneSpec` (purpose, target
duration, emotional beat: tension/release/curiosity/payoff, dialogue/voice
intent).

**Responsibilities**:
- Convert each act's abstract purpose into 2-6 concrete scene specs.
- Assign an emotional-arc value per scene so Voice Director and Editor Agent
  have a shared pacing signal (rising tension → faster cuts + tighter VO).
- Respect platform duration ceilings (Scene Engine §"Scene duration
  constraints").

**Interface**:

```python
class NarrativePlanner(Protocol):
    async def plan_scenes(
        self, structure: StoryStructure, brief: VideoBrief, ctx: RunContext
    ) -> AgentResult[ScenePlan]: ...
```

**Failure modes**: total scene duration drifts from target (LLM scene-length
estimates are unreliable) — detected by summing `SceneSpec.target_duration`.

**Retry strategy**: if drift > 15%, re-prompt with the numeric delta and ask
for explicit rebalancing across scenes (never silently truncate — that's the
Editor Agent's job at assembly time, not the planner's).

**Model recommendation**: local-first (Qwen3:14b).

---

## Storyboard Agent

**Purpose**: Expand each `SceneSpec` into a visual plan — what is on screen,
shot by shot, before any image generation happens. See 07-STORYBOARD.md for
the full data model.

**Inputs**: `ScenePlan`, `VisualStyleGuide` (from Visual Director, if already
set for series), `KnowledgeGraph` (for consistent character/location
depiction).

**Outputs**: `Storyboard` (Scene → Shot → Frame hierarchy, see 07).

**Responsibilities**:
- For each scene, decide shot count and shot purpose (establish, reaction,
  detail, transition).
- Attach a draft visual description per shot (refined later by Image Planner
  into an actual generation prompt).
- Flag shots that require continuity tracking (recurring character/location)
  for the Continuity Agent.

**Interface**:

```python
class StoryboardAgent(Protocol):
    async def build_storyboard(
        self, scenes: ScenePlan, style: "VisualStyleGuide", ctx: RunContext
    ) -> AgentResult[Storyboard]: ...
```

**Failure modes**: shot descriptions too abstract for Image Planner to turn
into a concrete prompt (e.g. "show the concept visually").

**Retry strategy**: Image Planner validation rejects under-specified shots
back to Storyboard Agent with the specific missing attribute (subject,
setting, or composition); max 2 rounds.

**Model recommendation**: local-first (Qwen3:14b); cloud fallback for complex
multi-character continuity scenes.

---

## Visual Director

**Purpose**: Own the global visual identity for a video/series — style,
color palette, composition rules — so every generated frame is coherent.

**Inputs**: `VideoBrief` (niche, tone), prior series `VisualStyleGuide` (if
continuing a series), reference images (optional).

**Outputs**: `VisualStyleGuide` (art style, palette tokens, lighting
direction, composition rules, negative-prompt baseline).

**Responsibilities**:
- Define a single style guide reused across the whole video (and series, when
  applicable) to prevent frame-to-frame drift.
- Translate abstract tone ("serious, mechanism-explainer") into concrete
  generation constraints (palette hex values, lighting adjectives, lens
  language) consumable by Image Planner.
- Version the style guide so series episodes can intentionally evolve while
  staying traceable.

**Interface**:

```python
class VisualDirector(Protocol):
    async def define_style(
        self, brief: VideoBrief, prior: "VisualStyleGuide | None", ctx: RunContext
    ) -> AgentResult["VisualStyleGuide"]: ...
```

**Failure modes**: style guide too vague to prevent drift (common LLM
failure: restates tone words instead of concrete visual tokens).

**Retry strategy**: validate output contains at least N concrete tokens
(palette hex codes, named lighting style, named composition rule); re-prompt
once requesting concrete substitutions for any abstract term found.

**Model recommendation**: local-first (Qwen3:14b); this is low-frequency
(once per video/series), so cost is not the constraint — correctness is.

---

## Camera Director

**Purpose**: Assign shot type, camera movement, and angle per shot —
vocabulary defined in 07-STORYBOARD.md §"Camera movement vocabulary".

**Inputs**: `Storyboard` (shot list), `VisualStyleGuide`, scene emotional beat
from `ScenePlan`.

**Outputs**: enriched `Storyboard` where every `Shot` has `shot_type`,
`movement`, `angle` populated.

**Responsibilities**:
- Map emotional beat to camera language (tension → tighter framing/push-in;
  release → wide/static).
- Avoid repeating the same shot type back-to-back beyond a configurable
  threshold (visual monotony guard).
- Respect platform aspect ratio constraints when choosing movement (vertical
  Shorts limit horizontal pan usefulness).

**Interface**:

```python
class CameraDirector(Protocol):
    async def assign_camera(
        self, storyboard: Storyboard, ctx: RunContext
    ) -> AgentResult[Storyboard]: ...
```

**Failure modes**: monotonous shot sequencing (LLM default bias toward
"medium shot, static" repeated).

**Retry strategy**: post-hoc monotony check (same `shot_type` for >3
consecutive shots) triggers a targeted re-prompt for just the offending shots.

**Model recommendation**: local-first (Qwen3:14b) — this is rule-applicable
and doesn't need deep reasoning once the vocabulary is in the prompt.

---

## Image Planner

**Purpose**: Turn each `Frame`/`Shot` into a concrete, generation-ready image
prompt for Flux/SDXL (see 12-IMAGE_ENGINE.md).

**Inputs**: `Storyboard` (with camera assigned), `VisualStyleGuide`,
character/location reference descriptions from `KnowledgeGraph`.

**Outputs**: `ImagePromptSet` — one structured prompt (positive + negative +
resolution profile) per frame.

**Responsibilities**:
- Compose style guide + shot description + camera language into a single
  coherent prompt string per the target provider's prompt grammar.
- Select resolution profile per frame purpose (thumbnail vs background vs
  square frame — see 12-IMAGE_ENGINE.md).
- Attach a deterministic seed strategy when frame-to-frame consistency is
  required (recurring character across shots).

**Interface**:

```python
class ImagePlanner(Protocol):
    async def plan_prompts(
        self, storyboard: Storyboard, style: "VisualStyleGuide", ctx: RunContext
    ) -> AgentResult["ImagePromptSet"]: ...
```

**Failure modes**: prompt too long/contradictory for provider token limit;
character drift across shots due to inconsistent descriptive language.

**Retry strategy**: enforce prompt length budget at construction time (hard
truncate lowest-priority style tokens first, never the subject); character
drift caught by Continuity Agent post-generation, not here.

**Model recommendation**: local-first (Qwen3:14b) — deterministic templating
task once style guide exists; cloud not justified.

---

## Animation Planner

**Purpose**: Produce motion/animation specs for non-photoreal scenes
(stickman explainers, simple motion graphics) distinct from full AI video
generation.

**Inputs**: `Storyboard` shots flagged `scene_type=animation`, mechanism
description from `StoryStructure` (what is being explained).

**Outputs**: `AnimationSpec` per shot — keyframe list, motion type (translate/
rotate/scale/path), duration, easing, and any on-screen label text.

**Responsibilities**:
- Translate an abstract mechanism ("habit loop: cue → routine → reward") into
  a keyframe sequence a renderer (Pillow/SVG/Lottie-style engine) can execute
  deterministically — no model call needed at render time.
- Keep animation specs declarative (data, not code) so they can be cached and
  replayed without re-invoking the LLM.

**Interface**:

```python
class AnimationPlanner(Protocol):
    async def plan_animation(
        self, shot: "Shot", mechanism: str, ctx: RunContext
    ) -> AgentResult["AnimationSpec"]: ...
```

**Failure modes**: keyframe spec produces visually broken motion (overlapping
elements, off-canvas positions) — only detectable post-render.

**Retry strategy**: schema validation catches malformed specs pre-render;
visual sanity (bounding box checks) catches off-canvas issues; one re-prompt
with the specific violated constraint.

**Model recommendation**: local-first (Qwen3:14b) — structured spec
generation, no need for cloud-grade reasoning.

---

## Voice Director

**Purpose**: Select TTS provider per-line/per-scene and control prosody so
narration matches the emotional arc. See 14-VOICE_ENGINE.md for provider
details.

**Inputs**: `Script`/`Segment` narration text, `ScenePlan` emotional beats,
available voice profiles (narrator clone, multi-voice roster).

**Outputs**: `VoiceDirection` per segment — provider choice, pause durations
(`pause_comma_ms`, `pause_sentence_ms`, `pause_segment_ms`), emphasis word
list, speaking-rate adjustment.

**Responsibilities**:
- Map emotional beat → prosody (tension: faster rate, shorter pauses; payoff:
  slower rate, longer pause before the line).
- Select provider per the Voice Engine's local-first selection policy, only
  overriding it for explicit creative needs (e.g. a multi-character scene
  needing a second voice).
- Pass emphasis keywords through unchanged from `Segment.emphasis` — Voice
  Director must not invent new emphasis the script didn't intend.

**Interface**:

```python
class VoiceDirector(Protocol):
    async def direct(
        self, segments: tuple["Segment", ...], plan: ScenePlan, ctx: RunContext
    ) -> AgentResult["VoiceDirection"]: ...
```

**Failure modes**: requested prosody unsupported by chosen provider (e.g.
edge-tts has coarser pause control than F5-TTS SSML-like markers).

**Retry strategy**: degrade prosody precision to the provider's actual
capability rather than failing; log a warning so QA can flag a provider
mismatch for review.

**Model recommendation**: local-first (Qwen3:14b for the directive reasoning
— the actual synthesis is the Voice Engine's job, not this agent's).

---

## Subtitle Agent

**Purpose**: Generate auto-captions, sync timing to audio, and apply caption
styling per platform conventions.

**Inputs**: final audio file + per-segment timing (from Voiceover model),
narration text (ground truth — preferred over ASR transcript when available).

**Outputs**: `SubtitleTrack` (SRT/VTT-equivalent structured cues with start/
end timestamps), style spec (font, position, highlight-on-emphasis).

**Responsibilities**:
- Prefer forced-alignment against the known narration text over blind ASR
  (Whisper) when the script text is already known — far more accurate.
- Fall back to Whisper transcription only for scenes without a known script
  (e.g. ad-libbed B-roll commentary).
- Apply emphasis-word highlighting using `Segment.emphasis` so caption style
  matches Voice Director's prosody emphasis.

**Interface**:

```python
class SubtitleAgent(Protocol):
    async def generate(
        self, audio_path: Path, segments: tuple["Segment", ...], ctx: RunContext
    ) -> AgentResult["SubtitleTrack"]: ...
```

**Failure modes**: forced alignment drifts on heavily-edited audio (pitch/
speed altered post-TTS); Whisper mis-transcribes domain jargon.

**Retry strategy**: drift detected via word-count mismatch between aligned
cues and source text triggers fallback to Whisper for just the drifted
segment, then a final consistency pass.

**Model recommendation**: local (Whisper running on MPS) for ASR; no LLM
reasoning required for the alignment path.

---

## SEO Agent

**Purpose**: Optimize title, description, tags, and hashtags for discovery —
platform-aware (YouTube tag conventions differ from TikTok hashtag norms).

**Inputs**: final `Script`/`StoryStructure` summary, `ResearchBrief` (for
accurate claims in description), platform target, niche keyword history
(`data/ledger.md`-equivalent — avoid keyword cannibalization across series
episodes).

**Outputs**: `SEOPackage` (title variants ranked, description, tag list,
hashtag list, platform-specific metadata).

**Responsibilities**:
- Generate multiple title variants and rank by predicted CTR heuristics
  (curiosity gap, specificity, length-per-platform).
- Ensure description claims trace back to `ResearchBrief` sources — no
  invented statistics for SEO benefit.
- Cross-check against series ledger to avoid duplicate primary keyword usage
  across recent episodes.

**Interface**:

```python
class SEOAgent(Protocol):
    async def optimize(
        self, summary: "ContentSummary", platform: str, ctx: RunContext
    ) -> AgentResult["SEOPackage"]: ...
```

**Failure modes**: keyword stuffing degrading description readability;
duplicate title against a recent series entry.

**Retry strategy**: ledger collision triggers automatic re-generation with
the colliding keyword excluded; readability check (sentence-length heuristic)
triggers one rewrite pass.

**Model recommendation**: local-first (Qwen3:14b); cloud fallback when A/B
testing against a cloud model for higher-stakes flagship videos.

---

## Thumbnail Agent

**Purpose**: Design a CTR-optimized thumbnail concept and hand off the
concrete generation prompt to the Image Engine.

**Inputs**: `Storyboard` (candidate high-impact frames), `SEOPackage` (title,
for text-overlay coherence), `VisualStyleGuide`.

**Outputs**: `ThumbnailConcept` (composition description, text overlay
content + placement, candidate source frame or fresh-generation prompt,
contrast/readability requirements).

**Responsibilities**:
- Select or generate a high-contrast, legible-at-small-size composition.
- Keep text overlay short (platform-tested character ceiling) and
  high-contrast against the chosen background.
- Produce at least 2 concept variants for A/B consideration when budget
  allows.

**Interface**:

```python
class ThumbnailAgent(Protocol):
    async def design(
        self, storyboard: Storyboard, seo: "SEOPackage", ctx: RunContext
    ) -> AgentResult["ThumbnailConcept"]: ...
```

**Failure modes**: text overlay illegible at thumbnail scale (low contrast
or too much text) — only verifiable via a render-and-check pass.

**Retry strategy**: automated legibility check (contrast ratio + text length)
post-render triggers regeneration with simplified text and higher contrast
constraint; max 2 iterations before falling back to the highest-scoring
variant regardless.

**Model recommendation**: local-first for concept (Qwen3:14b); the actual
image generation is delegated to Image Engine (Flux/SDXL).

---

## Editor Agent

**Purpose**: Assemble the final timeline — cut rhythm, transitions, and
overall pacing — from the rendered shots/scenes.

**Inputs**: `Storyboard` (with all media assets attached), `ScenePlan`
emotional-arc targets, audio track with timing.

**Outputs**: `EditTimeline` — ordered clip list with in/out points,
transition type per cut, and final duration.

**Responsibilities**:
- Match cut rhythm to the emotional-arc beat density set in 08-SCENE_ENGINE.
- Select transition types per `Transitions` vocabulary (hard cut, whoosh,
  crossfade) based on narrative function (hard cut within a beat, whoosh at
  problem→solution pivots — matching the channel's existing `transitions.py`
  convention).
- Enforce final duration against the platform ceiling, trimming lowest-
  priority filler shots first if over budget.

**Interface**:

```python
class EditorAgent(Protocol):
    async def assemble(
        self, storyboard: Storyboard, plan: ScenePlan, ctx: RunContext
    ) -> AgentResult["EditTimeline"]: ...
```

**Failure modes**: assembled duration overshoots platform ceiling; transition
choice clashes with adjacent scene's visual style (e.g. whoosh between two
static talking-head shots reads as jarring).

**Retry strategy**: duration overshoot triggers automatic trim pass (cut
lowest-narrative-priority shots, flagged by Narrative Planner); transition
clash caught by a rule-based compatibility matrix, not re-prompted — fixed in
code, not LLM-negotiated.

**Model recommendation**: local-first (Qwen3:14b) for rhythm decisions;
the trim/compatibility enforcement is deterministic code, not LLM.

---

## Continuity Agent

**Purpose**: Guarantee visual and narrative consistency across scenes —
recurring characters look the same, locations stay coherent, established
facts aren't contradicted later in the same video or across series episodes.

**Inputs**: full `Storyboard`, `KnowledgeGraph` (characters/locations/facts),
generated image assets (post Image Engine).

**Outputs**: `ContinuityReport` (violations found, severity, suggested fix —
e.g. "Scene 4 character description doesn't match Scene 1 reference").

**Responsibilities**:
- Cross-check every character/location appearance against the canonical
  `KnowledgeGraph` entry, not against the immediately preceding scene only.
- Run both at planning time (text-level check on `Storyboard` descriptions)
  and post-generation time (visual similarity check on actual generated
  frames, via embedding similarity against reference images).
- Flag narrative contradictions (a fact stated in Scene 2 contradicted in
  Scene 8) using the same `KnowledgeGraph` cross-reference.

**Interface**:

```python
class ContinuityAgent(Protocol):
    async def check(
        self, storyboard: Storyboard, graph: "KnowledgeGraph", ctx: RunContext
    ) -> AgentResult["ContinuityReport"]: ...
```

**Failure modes**: false positives on intentional stylistic variation
(deliberate scene-to-scene mood shift misflagged as inconsistency).

**Retry strategy**: violations above a severity threshold block the QA gate
and route back to the originating agent (Image Planner for visual drift,
Story Architect for factual contradiction) with the specific violation as
correction context; below-threshold issues are logged as warnings only.

**Model recommendation**: local-first for text-level checks (Qwen3:14b);
embedding-based visual similarity runs on a local vision-embedding model
(CLIP-class, MPS-accelerated), not an LLM call.

---

## QA Agent

**Purpose**: Final quality gate before a `ProductionPlan` is released to
render/publish. Enforces the niche compliance rules
(`.claude/skills/youtube-ideation/video-quality-rules.md` §0c/§0d today,
generalized into a rule engine going forward) plus structural/continuity
checks aggregated from other agents.

**Inputs**: full `ProductionPlan`, `ComplianceCheck` rule set, all upstream
`AgentResult.warnings`, `ContinuityReport`.

**Outputs**: `QAReport` — pass/fail per rule, aggregate `passed: bool`
(mirrors the existing `ComplianceCheck.passed` semantics in `pkg/models.py`),
human-readable notes.

**Responsibilities**:
- Run every compliance gate (niche fit, community guidelines, copyright,
  accuracy/sourcing, advertiser-friendliness, COPPA) as discrete, individually
  loggable checks — never a single opaque pass/fail.
- Aggregate warnings surfaced by every other agent in the run rather than
  re-deriving them.
- Block the pipeline (`passed=False`) on any CRITICAL rule violation; warn-
  only on MEDIUM/LOW per the project's review-severity conventions.

**Interface**:

```python
class QAAgent(Protocol):
    async def evaluate(
        self, plan: "ProductionPlan", rules: "RuleSet", ctx: RunContext
    ) -> AgentResult["QAReport"]: ...
```

**Failure modes**: rule false-negative (content that should fail passes
because phrasing dodges a keyword-based rule) — mitigated by combining
keyword rules with LLM-judged semantic checks, not keyword matching alone.

**Retry strategy**: QA Agent does not retry itself — a fail result is
authoritative and routes back to Creative Director, who decides whether to
re-invoke upstream agents with the specific violated rule as context, or
escalate to human review (Telegram approval gate, matching the existing
`ideation/approval.py` pattern).

**Model recommendation**: cloud (Claude Sonnet/Opus class) for the semantic
judgment checks — this is the integrity backstop for the whole pipeline and
should not be the place cost-optimization happens; local Qwen3 may run a
cheap pre-filter pass to short-circuit obvious failures before the cloud call.

---

## Agent Registry & Resolution

```python
class AgentRegistry:
    """Resolves capability name -> concrete Agent implementation.
    Swapping StoryArchitect for StoryArchitectV2 is a registry edit,
    never a call-site change."""

    def register(self, capability: str, agent: Agent) -> None: ...
    def resolve(self, capability: str) -> Agent: ...
```

Capabilities are registered at process start from config (`AGENT_<NAME>_IMPL`
env vars or a `agents.yaml` manifest), keeping the Creative Director's code
free of concrete agent imports — the same plugin discipline applied to
Engines in 10–14.

## Migration Notes

The current codebase has **no agent layer** — `ideation/generator.py` and
`ideation/research.py` are direct LLM-script-writing stubs driven by
hand-authored Claude chat sessions (per `CLAUDE.md`: "Claude viết tay trong
chat"). Migration path:

1. Extract the existing niche/compliance rules from
   `.claude/skills/youtube-ideation/video-quality-rules.md` into the `RuleSet`
   consumed by QA Agent (§"QA Agent" above) — do not re-author them.
2. Wrap `ideation/research.py` behavior as the first concrete
   `ResearchAgent` implementation; it already does web research today.
3. Introduce `ComplianceCheck` (already exists in `pkg/models.py`) as the
   literal output shape QA Agent populates — no new model needed, just a new
   producer.
4. Build agents incrementally in DAG order (Research → Story → Narrative →
   Storyboard → ...); each new agent slots into the existing
   `dataclasses.replace()`-based enrichment chain rather than replacing it.
