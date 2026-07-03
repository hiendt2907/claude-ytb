# 35 — PROMPT DSL

## Purpose

`11-PROMPT_ENGINE.md` already states "templates use Jinja2... plain
f-string-style substitution is acceptable for single-variable templates" as
a settled implementation detail. This document is the analysis behind that
choice — specifically, why a custom Prompt DSL (a purpose-built templating
or prompt-programming language) is not warranted for this project, why
Jinja2 is the right level of tooling, and the concrete directory/file
architecture that the Prompt Engine's templates live in.

---

## Section 1 — What a Custom Prompt DSL Would Provide

A purpose-built DSL for prompt authoring — rather than a general-purpose
templating engine — could offer:

- **Structured prompt authoring beyond raw strings:** a syntax that
  understands "this block is the persona," "this block is the task," "this
  block is the output contract" as first-class constructs, rather than
  conventionally-named string sections inside a YAML file.
- **Variable injection, conditional blocks, loops:** the same capability
  Jinja2 already provides, but with prompt-domain-specific syntax (e.g., a
  `{% character_voice %}` tag that knows it must resolve to a
  `Character.voice_id`-shaped value, rather than a generic `{{ variable }}`).
- **Type-safe prompt construction:** a DSL could, in principle, be compiled
  with static checking that a referenced variable exists and has the
  expected type before the prompt ever renders, closer to how a typed
  programming language catches undefined-variable errors at compile time
  rather than at render time.
- **Example DSL syntax vs raw string (illustrative, not adopted):**

```
# Hypothetical DSL — NOT what this project uses
persona: story_architect
constraint: no_self_help_framing
task: build_mechanism_structure(topic: $topic, target_minutes: $target_minutes)
output_schema: StoryStructure
```

versus the Jinja2 + YAML this project actually uses (§4) — the DSL example
is more declarative about *intent* (this is a persona block, this is a
schema reference) but requires writing and maintaining a parser/interpreter
for a brand-new mini-language to get there.

---

## Section 2 — Why Jinja2 Is Sufficient

### Already familiar to Python devs

Jinja2 is the de facto standard templating library in the Python ecosystem
(Flask, Ansible, Django-adjacent tooling all use it or something
Jinja2-shaped) — any contributor who has touched Python web tooling already
knows its syntax. A custom DSL has exactly one person who knows its syntax
at any given time: whoever wrote it most recently, until documentation
catches up. For a project explicitly optimizing for solo-maintainer
velocity (`01-VISION.md` target user), this is not a marginal
consideration.

### Handles everything this project's prompts actually need

- **Variable injection:** `{{ topic }}`, `{{ target_minutes }}` — covers
  every `user` prompt's per-call substitution need described in
  `11-PROMPT_ENGINE.md`'s Prompt Types table.
- **Conditionals:** `{% if series_context %}...continuation framing...{% endif %}`
  — covers the "optional series-context blocks" `11-PROMPT_ENGINE.md`
  explicitly calls out.
- **Loops:** `{% for example in few_shot_examples %}...{% endfor %}` —
  covers few-shot example injection without hand-written string
  concatenation.
- **Macros (reusable prompt fragments):** a shared `{% macro niche_guard() %}`
  block defining the "no self-help mantras" compliance constraint
  (`02-PRINCIPLES.md`) can be `{% import %}`-ed into every agent's system
  prompt that needs it, rather than copy-pasted across a dozen YAML files —
  this is DRY (`02-PRINCIPLES.md`) applied to prompt text itself.

### Filters for Vietnamese text

Jinja2's filter syntax composes cleanly with the project's Vietnamese-first
content needs (`04-DOMAIN.md`'s `Narrative.language: str = "vi"` default):

```jinja2
{{ research_findings | truncate(300) }}
{{ character_name | title }}
```

Custom filters (registered on the `Environment`, see §4) can encode
project-specific Vietnamese text handling — e.g., a `vi_sentence_split`
filter wrapping the same segmentation logic `05-WORKFLOW.md`'s
`SentenceSplit` node uses, so a prompt that needs to show "the first three
sentences of the research findings" doesn't reimplement sentence boundary
detection inline in a template expression.

### Version-controllable .j2 template files

Each prompt's `user`/`system` block, when extracted to its own `.j2` file
(§4), is independently diffable in `git log -p` — exactly the property
`11-PROMPT_ENGINE.md` already requires ("Git is the version ledger").
Embedding prompt text inside YAML string blocks (the current interim state)
is still git-diffable, but a `.j2` file gets syntax highlighting and
editor tooling a YAML multi-line string block does not.

### Testing: trivial render-and-compare

```python
def test_ideation_prompt_renders_with_required_variables():
    rendered = prompt_renderer.render(
        "ideation_v2",
        {"topic": "loss aversion", "target_minutes": 5, "niche": "vietnamese-finance"},
    )
    assert "loss aversion" in rendered.user
    assert "self-help" not in rendered.system.lower()
```

Jinja2 renders deterministically to a string; the test is a string
assertion. No DSL compiler/interpreter test harness is needed.

### What Jinja2 Cannot Do — and Why That's Fine

Jinja2 has no concept of:
- **Structured output enforcement** — Jinja2 produces text; it has no idea
  whether that text, once sent to the LLM, will come back as valid JSON
  matching `StoryStructure`'s schema.
- **Schema validation** — Jinja2 cannot check that `{{ topic }}` was passed
  a `str` and not accidentally a `Topic` dataclass instance whose `__str__`
  produces garbage.
- **Semantic versioning of prompt logic** — Jinja2 has no notion that
  `ideation_v2.j2` is a "MINOR" change from `ideation_v1.j2`; it just
  renders whichever file it's given.

These gaps are real, but they are not gaps a templating engine should be
closing — they are the responsibility of the **Prompt Engine**
(`11-PROMPT_ENGINE.md`), which already owns: `output_schema_ref` (schema
validation happens after the LLM responds, against the dataclass the schema
ref points to), the `version` field + git-paired-bump convention (semver
tracking), and the `RenderedPrompt` boundary type that the LLM Engine
(`10-LLM_ENGINE.md`) consumes. A custom DSL solving these problems would be
solving them in the wrong layer — duplicating responsibilities
`11-PROMPT_ENGINE.md` already assigns elsewhere, rather than filling a real
gap in Jinja2 itself.

---

## Section 3 — When a Custom DSL Would Be Warranted

Not a permanent rejection — conditional on needs that don't currently
exist:

- **Multi-agent prompt chaining with typed handoffs.** If an agent's output
  must flow into a second agent's prompt as a *typed* intermediate object
  (not just a rendered string), with the chain itself needing to be
  statically validated (agent A's output schema matches agent B's expected
  input schema before either prompt is rendered), a DSL with real type
  awareness would earn its complexity. Today, each Agent
  (`06-AGENTS.md`) calls the Prompt Engine independently per call; chains
  are orchestrated in Python (the Application layer), not expressed inside
  prompt text.
- **Prompt programs — loops/branches at LLM decision points.** If a single
  prompt needed to express "ask the model to decide X, and based on that
  decision, render a different follow-up sub-prompt, looping until a
  termination condition the model itself signals" as a single declarative
  unit (closer to a ReAct-style agent loop encoded in the prompt artifact
  itself, rather than in surrounding Python control flow), a DSL purpose
  -built for that pattern would be more legible than Jinja2 macros trying
  to fake it.
- **For now: not warranted.** Every current prompt in this project is a
  single render → single LLM call → single structured-output parse,
  orchestrated by Python control flow in the Application layer
  (`03-ARCHITECTURE.md`). Revisit this decision at the **v4.0 full agent
  system** milestone, if/when `06-AGENTS.md`'s agent roster grows
  multi-step decision loops that current Python orchestration plus Jinja2
  templating start to strain against.

---

## Section 4 — Jinja2 Prompt Architecture

### Directory Structure

```
src/ytb_pipeline/prompts/
├── ideation_v1.j2
├── ideation_v2.j2
├── story_architect.build_structure_v1.j2
├── quality_gate_v1.j2
├── creative_director.arbitrate_v1.j2
├── prompt_variables.yaml
└── macros/
    └── niche_guard.j2          # shared compliance-constraint macro, imported by multiple prompts
```

### Naming Convention

`{stage_or_agent}_{version}.j2` — e.g. `ideation_v2.j2`,
`quality_gate_v1.j2`, `story_architect.build_structure_v1.j2` (agent-scoped
prompts use the `{agent}.{capability}` prefix `11-PROMPT_ENGINE.md` already
specifies for the YAML registry, kept consistent here so a prompt's `.j2`
filename and its registry entry id are recognizably the same artifact).
Version is part of the filename, not just an internal field, so multiple
versions coexist on disk simultaneously (`11-PROMPT_ENGINE.md`'s "old
versions are retained" rule) — `ideation_v1.j2` is never deleted or
overwritten when `ideation_v2.j2` is introduced, it simply stops being the
`active` version pointed to by the registry.

### Variables: Adjacent YAML Schema

```yaml
# prompt_variables.yaml (excerpt)
ideation_v2:
  required:
    - topic: str
    - target_minutes: int
    - niche: str
  optional:
    - series_context: str | None
    - few_shot_examples: list[dict]
```

This schema is consulted by `PromptRenderer.render()` (below) to fail fast
with a clear error ("ideation_v2 requires `target_minutes`, got none") if a
caller omits a required variable, rather than letting Jinja2 silently
render an empty string into the gap — Jinja2 itself runs in
`undefined=StrictUndefined` mode for exactly this reason, but the adjacent
YAML schema additionally lets `test_prompts.py` (§ Testing below) enumerate
every prompt's required variables without parsing the template body.

### PromptRenderer

```python
from dataclasses import dataclass
from pathlib import Path

import jinja2
import yaml


@dataclass(frozen=True)
class RenderedPrompt:
    prompt_id: str
    version: str
    system: str
    user: str
    schema: type | None = None


class PromptRenderer:
    """Wraps a Jinja2 Environment; the only object that touches Jinja2 directly."""

    def __init__(self, prompts_dir: Path) -> None:
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(prompts_dir)),
            undefined=jinja2.StrictUndefined,   # missing variable -> render-time error, never silent blank
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._env.filters["vi_sentence_split"] = _vi_sentence_split_filter
        with open(prompts_dir / "prompt_variables.yaml", encoding="utf-8") as f:
            self._variable_schema = yaml.safe_load(f)

    def render(self, prompt_id: str, variables: dict) -> RenderedPrompt:
        self._validate_required_variables(prompt_id, variables)
        template = self._env.get_template(f"{prompt_id}.j2")
        rendered_text = template.render(**variables)
        system, user = _split_system_user(rendered_text)
        return RenderedPrompt(prompt_id=prompt_id, version=prompt_id.rsplit("_v", 1)[-1], system=system, user=user)

    def _validate_required_variables(self, prompt_id: str, variables: dict) -> None:
        schema = self._variable_schema.get(prompt_id, {})
        missing = [v for v in schema.get("required", []) if v not in variables]
        if missing:
            raise ValueError(f"{prompt_id} missing required variables: {missing}")
```

### Caching

Compiled templates are cached in memory via Jinja2's default
`Environment` behavior (the `FileSystemLoader` + `Environment` combination
already caches parsed templates after first load) — no additional caching
layer is built; this is exactly the kind of "don't roll your own cache when
the library already does it" discipline `24-CACHE_SYSTEM.md` applies
elsewhere in the project.

### Testing

```python
# tests/test_prompts.py (excerpt)
import pytest

PROMPT_FIXTURES = {
    "ideation_v2": {"topic": "loss aversion", "target_minutes": 5, "niche": "vietnamese-finance"},
    "quality_gate_v1": {"script_text": "...", "target_minutes": 5},
}


@pytest.mark.parametrize("prompt_id,fixture", PROMPT_FIXTURES.items())
def test_prompt_renders_without_missing_variables(prompt_renderer, prompt_id, fixture):
    rendered = prompt_renderer.render(prompt_id, fixture)
    assert rendered.system
    assert rendered.user
```

Every template in `prompts/` has a corresponding fixture entry; CI fails if
a new `.j2` file is added without a matching fixture (enforced via a test
that diffs `Path("prompts").glob("*.j2")` against `PROMPT_FIXTURES.keys()`),
so a prompt can never silently ship unrendered/untested.

### Migration from Current State

Prompts today are embedded inline inside `SKILL.md`-style markdown files
and as Python string literals scattered across `ideation/generator.py` and
similar modules — not yet extracted to the `prompts/*.j2` structure above.
Migration:

1. For each existing inline prompt, create the corresponding
   `{stage}_{version}.j2` file, copying the prompt text verbatim as
   version `v1` (preserving exact current behavior — this step is pure
   extraction, not a rewrite).
2. Add the matching entry to `prompt_variables.yaml`.
3. Replace the inline string construction call site with
   `prompt_renderer.render(prompt_id, variables)`.
4. Add the fixture to `test_prompts.py`.
5. Only after extraction is complete and tested does any *new* prompt
   iteration (e.g., a `v2` improving few-shot examples) happen — mixing
   "extract" and "improve" in the same change would make it impossible to
   tell whether a behavior change came from the migration or the
   improvement.

### Code Example: Ideation Prompt Template

```jinja2
{# src/ytb_pipeline/prompts/ideation_v2.j2 #}
{% import "macros/niche_guard.j2" as guard %}
---SYSTEM---
You are a story architect for Vietnamese {{ niche }} short-form video content.
{{ guard.niche_guard() }}
Target duration: {{ target_minutes }} minutes. Output must match the
StoryStructure schema exactly.
---USER---
Build a 5-part mechanism structure for topic: {{ topic }}.
{% if series_context %}
This is part of an ongoing series. Prior context: {{ series_context | truncate(300) }}
{% endif %}
{% if few_shot_examples %}
Reference examples of prior approved structures:
{% for example in few_shot_examples %}
- {{ example.topic }}: {{ example.structure_summary }}
{% endfor %}
{% endif %}
```

The `---SYSTEM---`/`---USER---` markers are the convention
`_split_system_user()` (in `PromptRenderer.render`) parses to populate
`RenderedPrompt.system`/`.user` from one rendered file, keeping a single
`.j2` file per prompt id rather than two separate files per
system/user pair — fewer files to keep in sync per prompt revision.
</content>
