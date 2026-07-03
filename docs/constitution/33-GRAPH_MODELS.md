# 33 — GRAPH MODELS

## Purpose

`04-DOMAIN.md` defines `Project`'s constituent objects (`Research`,
`Outline`, `Scene`, `Shot`, `Frame`, `Asset`, ...) and their pairwise
relationships in a flat "Relationship Summary" tree. That tree is sufficient
to understand containment, but it does not answer two operational questions
this project needs answered structurally rather than by ad-hoc code each
time: "if I regenerate this one asset, what downstream output is now stale?"
and "what is the render order / continuity structure of this project's
narrative?" This document specifies two graphs that answer those questions —
the **Asset Graph** (dependency/invalidation) and the **Scene Graph**
(creative structure) — and how each differs from the `WorkflowGraph`
(`05-WORKFLOW.md`, execution structure).

---

## Section 1 — Asset Graph

### Purpose

A directed acyclic graph over `Asset` objects (`04-DOMAIN.md`), capturing
*derivation* relationships: which assets were produced from which other
assets. This is distinct from the `WorkflowGraph`, which captures *which
node produced* an asset — the Asset Graph captures *which assets an asset's
content depends on*, which is the question that matters when deciding what
must be regenerated after an edit.

### Nodes

An `AssetGraphNode` wraps an `Asset.id` plus its `kind`
(`"image" | "audio" | "video" | "subtitle" | "thumbnail" | "font" |
"template"`) and `content_hash` (per `24-CACHE_SYSTEM.md`'s cache-key
convention) — the hash is what makes invalidation a content comparison, not
a timestamp guess.

### Edge Types

| Edge | Meaning | Example |
|---|---|---|
| `DERIVED_FROM` | Target asset's content was generated using source asset as direct input | A `thumbnail` Asset is `DERIVED_FROM` the `scene_image` Asset it was cropped/upscaled from |
| `COMPOSED_WITH` | Target asset is an assembly that incorporates source asset as one of several inputs, none of which alone determines the output | The final video `Asset` is `COMPOSED_WITH` the voice audio `Asset`, the per-shot video `Asset`s, the `Subtitle` burn-in, `Music`, and `SFX` — `Timeline` assembly per `05-WORKFLOW.md` |
| `DEPENDS_ON` | Target asset's generation required source asset as a non-content prompt input (style reference, voice clone reference) rather than literal pixel/sample derivation | An `ImagePrompt`-generated frame `DEPENDS_ON` the `Character.visual_style_prompt`'s backing reference image asset |

`DERIVED_FROM` and `COMPOSED_WITH` both imply invalidation propagation
(§ Invalidation Propagation below); `DEPENDS_ON` implies invalidation only
when the *referenced* style/voice asset itself changes, not on every
regeneration of assets that merely cite it.

### Use Case: Targeted Invalidation

> "If `voice_segment_03` is regenerated, which render outputs are
> invalidated?"

This is answered by a forward graph traversal from the changed asset:

```
voice_segment_03 (regenerated)
  └─ COMPOSED_WITH → subtitle_03 (timing depends on voice_segment_03's actual duration)
  └─ COMPOSED_WITH → timeline (assembly references voice_segment_03 directly)
       └─ COMPOSED_WITH → final_render (Renderer composes the whole Timeline)
```

All three downstream assets (`subtitle_03`, `timeline`, `final_render`) are
marked stale; everything *not* reachable from `voice_segment_03` in this
traversal (e.g., `scene_image_03`, every other voice segment) is
unaffected and is **not** regenerated — this is the entire point of
modeling the graph explicitly rather than re-rendering the whole project on
any single change, and it is what makes a corrected mispronunciation in one
segment a cheap, localized fix instead of a full re-render.

### Graph Operations

- **Topological sort (render order):** assets with no incoming
  `DERIVED_FROM`/`COMPOSED_WITH` edges (raw generated assets: a scene image,
  a voice segment) sort first; assets are generated/assembled only after
  every asset they depend on already exists. This sort order is what the
  `WorkflowGraph`'s `depends_on` edges are ultimately compiled from at the
  asset-resolution level (`05-WORKFLOW.md` "Assets" node).
- **Invalidation propagation:** given a changed/regenerated asset, compute
  the forward-reachable set in the `DERIVED_FROM`/`COMPOSED_WITH` subgraph;
  mark every reached asset's cache entry stale (`24-CACHE_SYSTEM.md`). This
  is a standard graph reachability/BFS problem, not a bespoke algorithm.
- **Cache coherence:** before generating any asset, check whether its
  `content_hash` (computed from its direct inputs' hashes, per
  `24-CACHE_SYSTEM.md`) already exists in the cache; if so, reuse rather
  than regenerate, and add the existing asset as a node with edges to its
  recorded inputs rather than recomputing the graph from scratch. This
  ties the Asset Graph directly to the cache-key derivation scheme — the
  graph *is* the dependency chain the cache key is computed over.

### Storage: SQLite Adjacency List

```sql
CREATE TABLE asset_edges (
    asset_id TEXT NOT NULL,             -- the dependent (downstream) asset
    depends_on_asset_id TEXT NOT NULL,  -- the dependency (upstream) asset
    edge_type TEXT NOT NULL CHECK (edge_type IN ('DERIVED_FROM', 'COMPOSED_WITH', 'DEPENDS_ON')),
    PRIMARY KEY (asset_id, depends_on_asset_id)
);
CREATE INDEX idx_asset_edges_dependency ON asset_edges (depends_on_asset_id);
```

The reverse index (`idx_asset_edges_dependency`) is what makes "what depends
on asset X" (the invalidation-propagation query) an indexed lookup rather
than a full-table scan — this is the query pattern that runs on every
regeneration, so it is the one explicitly indexed for. This table lives in
the same SQLite store introduced for `AITrace` records
(`36-AI_GOVERNANCE.md` §2, `assets/traces.db`) rather than a third database
file — both are per-project queryable metadata stores with the same
operational footprint.

### Python Implementation

A hand-rolled adjacency-list wrapper is used rather than `networkx` — the
operations needed (forward reachability, topological sort) are a few dozen
lines each over a plain `dict[str, set[str]]`, and adding `networkx` as a
dependency for two graph algorithms this small would be exactly the kind of
speculative-generality dependency `02-PRINCIPLES.md`'s YAGNI guidance warns
against, especially for a project that already keeps its dependency surface
deliberately small (`PROJECT_VISION.md` §6 local-first, minimal-surface
ethos).

```python
from dataclasses import dataclass
from enum import Enum


class AssetEdgeType(str, Enum):
    DERIVED_FROM = "DERIVED_FROM"
    COMPOSED_WITH = "COMPOSED_WITH"
    DEPENDS_ON = "DEPENDS_ON"


@dataclass(frozen=True)
class AssetEdge:
    asset_id: str
    depends_on_asset_id: str
    edge_type: AssetEdgeType


class AssetGraph:
    """In-memory adjacency-list view, loaded from the asset_edges table."""

    def __init__(self, edges: tuple[AssetEdge, ...]) -> None:
        self._forward: dict[str, set[str]] = {}    # asset -> assets that depend on it
        self._backward: dict[str, set[str]] = {}   # asset -> assets it depends on
        for edge in edges:
            self._forward.setdefault(edge.depends_on_asset_id, set()).add(edge.asset_id)
            self._backward.setdefault(edge.asset_id, set()).add(edge.depends_on_asset_id)

    def invalidated_by(self, changed_asset_id: str) -> set[str]:
        """Forward-reachable set: everything that must be regenerated."""
        seen: set[str] = set()
        frontier = [changed_asset_id]
        while frontier:
            current = frontier.pop()
            for dependent in self._forward.get(current, set()):
                if dependent not in seen:
                    seen.add(dependent)
                    frontier.append(dependent)
        return seen

    def topological_order(self) -> list[str]:
        """Render order: dependencies before dependents (Kahn's algorithm)."""
        in_degree = {node: len(deps) for node, deps in self._backward.items()}
        for node in self._forward:
            in_degree.setdefault(node, 0)
        ready = [n for n, deg in in_degree.items() if deg == 0]
        order: list[str] = []
        while ready:
            node = ready.pop()
            order.append(node)
            for dependent in self._forward.get(node, set()):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)
        return order
```

### Example: Full Asset Graph for a Typical Short

```
scene_image_01 ──DERIVED_FROM──► thumbnail
scene_image_01 ──COMPOSED_WITH──► animation_01 ──COMPOSED_WITH──► video_clip_01
voice_segment_01 ──COMPOSED_WITH──► subtitle_01
character_ref_image ──DEPENDS_ON (referenced by)──► scene_image_01
character_ref_image ──DEPENDS_ON (referenced by)──► scene_image_02
video_clip_01 ──COMPOSED_WITH──► timeline
voice_segment_01 ──COMPOSED_WITH──► timeline
subtitle_01 ──COMPOSED_WITH──► timeline
music_track ──COMPOSED_WITH──► timeline
timeline ──COMPOSED_WITH──► final_render
```

Note `character_ref_image` fanning out to multiple scenes via `DEPENDS_ON`
— this is the edge type that makes "the creator updated this Character's
reference image" a computable invalidation across every scene that uses
that Character, without needing to know in advance which scenes those are.

---

## Section 2 — Scene Graph

### Purpose

A hierarchical graph of the *creative* structure of a `Project` — the
narrative shape a human author would recognize, independent of which
provider rendered which pixel. This is the structural backbone the
Creative Compiler (`37-CREATIVE_COMPILER.md`) walks when planning what to
generate, and the structure a human reviews when approving an outline or
storyboard before committing render compute.

### Nodes

```
Project → Story → Act → Scene → Shot → Frame
```

`Act` is a grouping level not currently present as its own dataclass in
`04-DOMAIN.md` — today, `Scene.order` provides a flat ordering directly
under `Narrative`. The Scene Graph formalizes an optional `Act` grouping
layer (a contiguous run of `Scene`s sharing a narrative beat from
`Outline.beats`) for projects long/complex enough to benefit from it; for a
typical short-form video, `Act` may be a single implicit act containing all
`Scene`s, and the Scene Graph degrades gracefully to the existing flat
`Scene → Shot → Frame` chain with no structural change required.

### Edge Types

| Edge | Meaning |
|---|---|
| `CONTAINS` | Parent-child structural containment (`Project CONTAINS Story`, `Scene CONTAINS Shot`, `Shot CONTAINS Frame`) |
| `FOLLOWS` | Sequential ordering between siblings at the same level (`Scene N FOLLOWS Scene N-1`) — redundant with `Scene.order`/`Shot.order` today, made explicit here because graph traversal for continuity checks needs an edge to walk, not a field to sort by |
| `REFERENCES_ASSET` | A node's content depends on a specific `Asset` (`Frame REFERENCES_ASSET <scene_image>`) — this is the join point to the Asset Graph (§1) |
| `REFERENCES_CHARACTER` | A node involves a specific reusable `Character` (`Scene REFERENCES_CHARACTER <character_id>`) — enables the "all scenes with character X" query directly |

### Operations

- **Traverse (render order):** depth-first walk from `Project` down through
  `Story → Act → Scene → Shot → Frame`, respecting `FOLLOWS` ordering at
  each sibling level — this produces the canonical creative sequence, which
  the render stage (`19-RENDER_ENGINE.md`) consumes to assemble the
  `Timeline` in the correct narrative order.
- **Validate (continuity):** walk all `Scene`s in `FOLLOWS` order and check
  for continuity violations the domain can express structurally — e.g., a
  `Character` referenced in `Scene N` via `REFERENCES_CHARACTER` whose
  `visual_style_prompt` changed between `Scene N` and `Scene N+2` without an
  intentional costume/aging beat in `Outline.beats` is a flaggable
  continuity risk, not silently rendered. This validation is the structural
  backbone for any future automated continuity-checking Agent
  (`06-AGENTS.md`).
- **Query ("all scenes with character X"):** a single filter over
  `REFERENCES_CHARACTER` edges where `character_id == X` — answerable in
  one pass without walking unrelated subtrees, which matters once a
  `KnowledgeBase`/`Memory` (`04-DOMAIN.md`) is being used to maintain
  consistency for a recurring Character across many `Project`s.

### Relationship to WorkflowGraph

The Scene Graph and the `WorkflowGraph` (`05-WORKFLOW.md`,
`04-DOMAIN.md`) are deliberately separate graphs over related but distinct
concerns:

| | Scene Graph | WorkflowGraph |
|---|---|---|
| Represents | Creative structure — what the story *is* | Execution structure — what work must *run*, in what order, on what provider |
| Nodes | `Story`, `Act`, `Scene`, `Shot`, `Frame` | `WorkflowNode` (`Research`, `ScenePlanning`, `ImagePrompt`, ...) |
| Changes when | The narrative changes (re-outline, re-plot a scene) | The pipeline's execution plan changes (a node retries, a node is skipped) |
| Owned by | Creative Compiler (`37-CREATIVE_COMPILER.md`) during planning | DAG executor (`05-WORKFLOW.md`) during execution |
| Persists across | Re-renders with the same narrative (stable across resume) | A single `WorkflowGraph.id`'s execution lifetime |

Concretely: one `Frame` in the Scene Graph is the *input* to exactly one
`ImagePrompt` `WorkflowNode` in the `WorkflowGraph` — the Scene Graph node
says "this moment in the story needs a visual"; the `WorkflowNode` says "go
call the `ImageProvider` to produce it, with this retry policy." Re-running
the `ImagePrompt` node (a `WorkflowGraph` concern, e.g., after a transient
provider failure) never changes the Scene Graph; editing the `Frame`'s
description (a Scene Graph / creative concern) is what invalidates and
re-triggers the corresponding `WorkflowNode`.

### Python Implementation

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ActNode:
    id: str
    story_id: str
    order: int
    beat_summary: str            # corresponds to one Outline.beats entry
    scene_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class SceneGraphEdge:
    from_id: str
    to_id: str
    edge_type: str   # "CONTAINS" | "FOLLOWS" | "REFERENCES_ASSET" | "REFERENCES_CHARACTER"


class SceneGraph:
    """Read-only traversal view over a Project's narrative structure.

    Built from existing Scene/Shot/Frame dataclasses (04-DOMAIN.md) plus
    the optional ActNode grouping layer; does not replace those dataclasses,
    only adds traversal/query operations over their relationships.
    """

    def __init__(self, edges: tuple[SceneGraphEdge, ...]) -> None:
        self._edges = edges

    def scenes_referencing_character(self, character_id: str) -> tuple[str, ...]:
        return tuple(
            e.from_id for e in self._edges
            if e.edge_type == "REFERENCES_CHARACTER" and e.to_id == character_id
        )

    def render_order(self, root_id: str) -> list[str]:
        """Depth-first traversal respecting CONTAINS then FOLLOWS order."""
        children = sorted(
            (e for e in self._edges if e.edge_type == "CONTAINS" and e.from_id == root_id),
            key=lambda e: e.to_id,  # actual implementation sorts by sibling .order field
        )
        order: list[str] = [root_id]
        for edge in children:
            order.extend(self.render_order(edge.to_id))
        return order
```

### Example: Scene Graph for a 5-Scene Educational Short

```
Project (proj_loss_aversion)
  └─ Story (logline: "Why losing $20 hurts more than finding $20 feels good")
       └─ Act 1 (beat: "hook + mechanism setup")
            ├─ Scene 1 (REFERENCES_CHARACTER: narrator) FOLLOWS → Scene 2
            │    └─ Shot 1.1 → Frame 1.1.1 (REFERENCES_ASSET: scene_image_01)
            └─ Scene 2 FOLLOWS → Scene 3
                 └─ Shot 2.1 → Frame 2.1.1
       └─ Act 2 (beat: "real-world example")
            ├─ Scene 3 (REFERENCES_CHARACTER: narrator) FOLLOWS → Scene 4
            │    └─ Shot 3.1 → Frame 3.1.1
            └─ Scene 4 FOLLOWS → Scene 5
                 └─ Shot 4.1 → Frame 4.1.1
       └─ Act 3 (beat: "actionable takeaway")
            └─ Scene 5 (REFERENCES_CHARACTER: narrator)
                 └─ Shot 5.1 → Frame 5.1.1
```

---

## Section 3 — Graph Serialization

### JSON Schema

Both graphs serialize as an edge list plus a node-metadata map — chosen over
a nested-object representation because edge lists are what the traversal
algorithms in §1/§2 consume directly, and because a flat edge list is
trivially diffable in `git diff` (consistent with `project.json`'s overall
diffability goal, `01-VISION.md` v5).

```json
{
  "asset_graph": {
    "nodes": {
      "voice_segment_03": { "kind": "audio", "content_hash": "9f1c2a..." },
      "subtitle_03": { "kind": "subtitle", "content_hash": "ab44ef..." }
    },
    "edges": [
      { "asset_id": "subtitle_03", "depends_on_asset_id": "voice_segment_03", "edge_type": "COMPOSED_WITH" }
    ]
  },
  "scene_graph": {
    "nodes": {
      "scene_1": { "kind": "Scene", "order": 1, "summary": "..." }
    },
    "edges": [
      { "from_id": "act_1", "to_id": "scene_1", "edge_type": "CONTAINS" },
      { "from_id": "scene_1", "to_id": "scene_2", "edge_type": "FOLLOWS" }
    ]
  }
}
```

### Embedding Strategy: project.json vs graph.json

| | Embed in `project.json` | Separate `graph.json` |
|---|---|---|
| When | Scene Graph (small: tens of nodes for a Short) and small Asset Graphs | Large projects (long-form, many scenes/assets) where the edge list would dominate `project.json`'s size and slow down every read of project metadata that doesn't need graph detail |
| Rationale | Keeps the single-portable-artifact property (`25-CHECKPOINT_SYSTEM.md` §3's reasoning for embedding checkpoints) for the common case | Avoids forcing every `project.json` read (e.g., the listener checking `Project.status`) to parse a potentially large edge list it doesn't need |

Default for v1–v3: embed both graphs directly in `project.json` under
`asset_graph` and `scene_graph` top-level keys, matching the `checkpoints`
and `lifecycle` embedding pattern (`25-CHECKPOINT_SYSTEM.md`,
`32-STATE_MACHINE.md`). The separate-file split is deferred until a real
project's `project.json` is observed to grow large enough to matter —
introducing the split preemptively for projects that don't need it would be
the same premature-infrastructure mistake ADR-005 (`31-ADR.md`) explicitly
avoided for the audit ledger.
</content>
