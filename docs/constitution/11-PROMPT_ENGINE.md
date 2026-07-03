# 11 — PROMPT ENGINE

## Purpose

Treat prompts as first-class, versioned artifacts — not strings embedded in
Python or scattered across markdown skill files. The Prompt Engine is what
every Agent (06-AGENTS) calls to obtain a fully-rendered, schema-aware,
compliance-constrained prompt before handing it to the LLM Engine (10).

## Prompt as a First-Class Artifact

A prompt is data, checked into version control, independently testable, and
independently auditable — the same discipline the project already applies to
`pkg/models.py` dataclasses and `video-quality-rules.md`. Concretely: a
prompt change is a diff reviewable on its own, a prompt has a version number
referenced in cost/quality tracking (10-LLM_ENGINE §Cost Tracking), and a
prompt can be benchmarked against expected output before being promoted to
production use.

## Prompt Types

| Type | Purpose | Example |
|---|---|---|
| `system` | Stable role + constraint definition for an agent capability | Story Architect's "you are a narrative structure expert; never use self-help framing" |
| `user` | Per-call task content, templated with run-specific variables | "Build a 5-part mechanism structure for topic: {{ topic }}, target length: {{ target_minutes }} min" |
| `few_shot` | Worked examples appended to steer format/quality | 2-3 prior `ResearchBrief` → `StoryStructure` pairs that passed QA |
| `chain_of_thought` | Explicit reasoning-step scaffolding for harder structural/arbitration tasks | Creative Director's conflict-resolution prompt, which requires enumerating each constraint before deciding |

## Prompt Templates

Templates use Jinja2 for anything with conditionals/loops (few-shot example
injection, optional series-context blocks); plain f-string-style `{{ var }}`
substitution is acceptable for single-variable templates to avoid Jinja
overhead on the hot path. Both are declared explicitly in the YAML registry
entry (`engine: jinja2` vs `engine: fstring`) so the renderer never has to
guess.

```python
from typing import Protocol


class PromptTemplate(Protocol):
    id: str                 # e.g. "story_architect.build_structure"
    version: str             # semver, e.g. "1.3.0"
    engine: str               # "jinja2" | "fstring"
    system: str
    user: str
    few_shot: tuple[dict, ...] = ()
    output_schema_ref: str = ""   # dotted path to the dataclass/pydantic schema

    def render(self, variables: dict) -> "RenderedPrompt": ...
```

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class RenderedPrompt:
    prompt_id: str
    version: str
    system: str
    user: str
    schema: type | None
```

`RenderedPrompt` is what gets handed to `LLMRequest` (10-LLM_ENGINE) —
the Prompt Engine's only output type, keeping a clean boundary: Prompt
Engine renders text, LLM Engine dispatches it.

## Prompt Versioning

- **Semver per prompt** (`MAJOR.MINOR.PATCH`), independent of the
  application's own version: `MAJOR` bump = output schema changed (breaking
  for any consumer parsing structured output); `MINOR` = meaningfully
  different instructions/behavior, same schema; `PATCH` = wording/clarity
  fix, same behavior intent.
- **Git is the version ledger.** Each prompt is one YAML file
  (`prompts/{agent}.{capability}.yaml`); `git log -p` on that file is the
  changelog. The `version` field inside the YAML must be bumped in the same
  commit that changes `system`/`user`/`few_shot` content — a CI check (or
  pre-commit hook, per the project's PostToolUse hook conventions) verifies
  this pairing.
- **Old versions are retained**, not overwritten — a prompt registry entry
  is `prompts/story_architect.build_structure.yaml` containing a list of
  versions, not a single current version, so a production run can pin to a
  specific version for reproducibility while development iterates on a new
  one (`status: draft` vs `status: active`).

## Quality Rules as Prompt Constraints

Compliance/niche rules are not purely a post-hoc QA Agent check — the
relevant subset is **embedded directly into the generating prompt's system
block** so the LLM is constrained at generation time, with QA Agent as the
backstop that catches what slipped through:

```yaml
# excerpt from prompts/story_architect.build_structure.yaml
system: |
  You are a narrative structure expert for a Vietnamese self-development
  channel. HARD CONSTRAINTS (violating any of these makes your output
  unusable, regenerate internally before responding):
  - Never frame content as "self-help" — explain the underlying mechanism
    (psychology/behavioral science), not advice-giving.
  - Every claim must be traceable to a provided ResearchBrief source; never
    invent statistics or studies.
  - Idea density: minimum 1 concrete mechanism explained per act, no filler
    acts.
```

This pattern generalizes the project's existing
`.claude/skills/youtube-ideation/video-quality-rules.md` §0c (niche gates)
and §0d (series constraints) — those rules become the canonical source text
that the Prompt Engine's constraint blocks are generated/synced from, so the
rules are authored once and fan out into every relevant prompt rather than
copy-pasted by hand into each one.

## Prompt Testing Framework

```python
@dataclass(frozen=True)
class PromptBenchmarkCase:
    name: str
    variables: dict                  # rendered into the template
    expected_schema: type             # output must validate against this
    quality_rubric: tuple[str, ...]   # human/LLM-judge rubric items
    min_quality_score: float = 0.7


class PromptBenchmark(Protocol):
    async def run(
        self, template: PromptTemplate, cases: tuple[PromptBenchmarkCase, ...]
    ) -> "BenchmarkReport": ...
```

`BenchmarkReport` aggregates per-case: schema pass/fail, a quality score
(LLM-judge against the rubric, using a cloud model as the judge regardless of
which model the prompt targets, to avoid a model grading its own homework),
and cost. A prompt version is only promoted from `status: draft` to
`status: active` after its benchmark report clears the project's coverage-
equivalent bar — this is the prompt-layer analog of the 80% test-coverage
gate already mandatory for code (`testing.md`).

A regression suite (`tests/prompts/`) re-runs the full benchmark set whenever
an `active` prompt's YAML changes, the same way `pytest` re-runs unit tests
on code changes — prompt changes go through the same CI gate as code changes,
not a separate, looser process.

## Prompt Registry

```
prompts/
├── creative_director.plan.yaml
├── creative_director.resolve_conflict.yaml
├── research_agent.research.yaml
├── story_architect.build_structure.yaml
├── narrative_planner.plan_scenes.yaml
├── storyboard_agent.build_storyboard.yaml
├── visual_director.define_style.yaml
├── camera_director.assign_camera.yaml
├── image_planner.plan_prompts.yaml
├── animation_planner.plan_animation.yaml
├── voice_director.direct.yaml
├── seo_agent.optimize.yaml
├── thumbnail_agent.design.yaml
├── editor_agent.assemble.yaml
├── continuity_agent.check.yaml
├── qa_agent.evaluate.yaml
└── _shared/
    ├── niche_constraints.yaml        # synced from video-quality-rules.md
    └── series_constraints.yaml
```

One YAML file per agent capability — matching 06-AGENTS' one-capability-per-
method interfaces 1:1, so finding "the prompt that produced this output" is
always a direct filename lookup from the agent/method name, never a search.
`_shared/` holds constraint fragments referenced (via Jinja `{% include %}`
or a pre-render merge step) by multiple prompts, so the niche-gate rules are
edited in exactly one place.

```yaml
# prompts/story_architect.build_structure.yaml
id: story_architect.build_structure
status: active
versions:
  - version: "1.3.0"
    engine: jinja2
    output_schema_ref: "ytb_pipeline.pkg.models.StoryStructure"
    system: |
      {% include "_shared/niche_constraints.yaml" %}
      You are a narrative structure expert...
    user: |
      Topic research: {{ research_brief }}
      Target length: {{ target_minutes }} minutes
      Format: {{ format }}
    few_shot: []
  - version: "1.2.0"
    status: deprecated
    ...
```

## Current State

Prompts today live embedded inside Claude Code skill markdown
(`.claude/skills/youtube-ideation/SKILL.md` and its co-located
`video-quality-rules.md`), authored for and consumed by a human-in-the-loop
Claude chat session — not rendered programmatically, not versioned
independently of the skill file, not benchmarked, and not reusable by any
non-Claude-chat agent. There is no `prompts/` directory and no programmatic
prompt rendering anywhere in `src/ytb_pipeline/`.

## Migration: Extract to `prompts/*.yaml`

1. **Inventory first**: read every instruction block in
   `youtube-ideation/SKILL.md` and `video-quality-rules.md`, and classify each
   as either (a) a durable constraint that belongs in `_shared/` (niche
   gates, series rules) or (b) a capability-specific instruction that maps to
   a specific future agent (e.g. "write the hook with a paradox" maps to
   Story Architect's hook-scene framing, per 08-SCENE_ENGINE §Scene
   Composition Rules).
2. **Author the first YAML files for capabilities that already have a code
   equivalent** — `research_agent.research.yaml` from `ideation/research.py`'s
   existing prompting logic, since that module already issues LLM-directed
   research today and is the lowest-risk extraction.
3. **Do not delete the skill markdown immediately.** Keep
   `youtube-ideation/SKILL.md` as the human-facing chat-session entry point
   (it still serves interactive/manual runs via Telegram-triggered
   `listener.py`) while `prompts/*.yaml` becomes the programmatic-agent-path
   source of truth — the two converge once the agent layer (06-AGENTS) fully
   replaces the hand-authored-in-chat ideation flow, at which point the skill
   markdown is reduced to a thin pointer at the YAML registry instead of
   containing duplicated rule text.
4. **Add the benchmark suite (`tests/prompts/`) before promoting any prompt
   to `status: active`** — every extracted prompt starts at `status: draft`
   until it has at least 3 benchmark cases covering the QA-relevant
   constraints (niche gate compliance, schema validity, idea-density
   minimum) and clears the quality bar, per the project's TDD-first
   discipline applied to the prompt layer.
