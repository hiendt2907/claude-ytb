# 04 — DOMAIN

## Purpose

This document defines the full domain model for `claude-ytb` as it evolves
toward the v2/v3 milestones in `01-VISION.md`: a `project.json`-anchored,
DAG-shaped representation of a piece of creative work, independent of
platform. Every object below is a **frozen dataclass** — immutability is
structural (per `PROJECT_VISION.md` §6), not a style choice. Today's
`src/ytb_pipeline/pkg/models.py` implements an early, YouTube-coupled subset
of this model (`VideoIdea → Script → Voiceover → RenderedVideo →
PublishResult`, an inheritance chain). The model below is the target
domain — flatter, composition-based, and platform-agnostic — that the
existing chain migrates into.

## Conventions

- All objects are `@dataclass(frozen=True)`.
- All objects carry an `id: str` (typically a UUID4 string) so they can be
  referenced from `WorkflowNode` inputs/outputs and from `Checkpoint`
  records without embedding full nested copies everywhere.
- Timestamps are `created_at: datetime`; mutation is modeled as producing a
  new object (e.g., `PromptVersion`), never `__setattr__` on an existing one.
- Optional/forward references use `Optional[...]` with default `None`.

## Core Project Container

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


@dataclass(frozen=True)
class Project:
    """Top-level creative work unit. Anchors the project.json artifact."""
    id: str
    title: str
    niche: str                      # e.g. "vietnamese-history", "tech-explainer"
    created_at: datetime
    knowledge_base_id: Optional[str] = None
    research_id: Optional[str] = None
    outline_id: Optional[str] = None
    narrative_id: Optional[str] = None
    timeline_id: Optional[str] = None
    workflow_graph_id: Optional[str] = None
    target_platforms: tuple[str, ...] = ()   # e.g. ("youtube", "shorts")
    status: str = "draft"           # draft | in_progress | review | published | archived
```

## Research & Knowledge

```python
@dataclass(frozen=True)
class Research:
    """Raw research gathered for a Project — trending topics, source facts."""
    id: str
    project_id: str
    topic: str
    sources: tuple[str, ...]        # URLs / citations
    findings: str                   # synthesized research text
    created_at: datetime


@dataclass(frozen=True)
class KnowledgeBase:
    """Durable, reusable knowledge for a niche/channel — outlives one Project."""
    id: str
    niche: str
    facts: tuple[str, ...]
    characters: tuple[str, ...]     # ids of reusable Character objects
    locations: tuple[str, ...]      # ids of reusable Location objects
    updated_at: datetime
```

## Narrative Structure

```python
@dataclass(frozen=True)
class Outline:
    """High-level structure: the beats the narrative must hit."""
    id: str
    project_id: str
    research_id: str
    beats: tuple[str, ...]          # ordered list of beat summaries
    target_duration_seconds: int
    created_at: datetime


@dataclass(frozen=True)
class Story:
    """The narrative arc derived from the Outline — characters + plot."""
    id: str
    outline_id: str
    logline: str
    arc_summary: str
    character_ids: tuple[str, ...]
    created_at: datetime


@dataclass(frozen=True)
class Narrative:
    """Full prose narrative text, sentence-segmentable, pre-script."""
    id: str
    story_id: str
    body_text: str
    language: str = "vi"
    created_at: datetime = None


@dataclass(frozen=True)
class Scene:
    """A narrative segment with a single setting/intent — composed of Shots."""
    id: str
    narrative_id: str
    order: int
    summary: str
    location_id: Optional[str] = None
    shot_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Shot:
    """A single camera take within a Scene — composed of Frames."""
    id: str
    scene_id: str
    order: int
    description: str
    camera_id: Optional[str] = None
    frame_ids: tuple[str, ...] = ()
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class Frame:
    """A single visual moment within a Shot — the unit a render targets."""
    id: str
    shot_id: str
    order: int
    image_prompt_id: Optional[str] = None
    animation_prompt_id: Optional[str] = None
    video_prompt_id: Optional[str] = None
```

## Entities Reused Across Projects

```python
@dataclass(frozen=True)
class Character:
    """A reusable persona — voice, visual style, personality."""
    id: str
    name: str
    description: str
    voice_id: Optional[str] = None          # reference to a VoiceProvider voice/clone
    visual_style_prompt: str = ""
    knowledge_base_id: Optional[str] = None


@dataclass(frozen=True)
class Location:
    """A reusable setting — visual description reused across Scenes."""
    id: str
    name: str
    description: str
    visual_style_prompt: str = ""


@dataclass(frozen=True)
class Camera:
    """Camera framing/movement directive applied to a Shot."""
    id: str
    angle: str           # e.g. "close-up", "wide", "over-the-shoulder"
    movement: str        # e.g. "static", "pan-left", "dolly-in"
    notes: str = ""
```

## Prompts (Versioned)

```python
@dataclass(frozen=True)
class Prompt:
    """Base identity for a prompt used to drive a generative Provider call."""
    id: str
    kind: str            # "image" | "animation" | "video" | "voice" | "stickman"
    current_version_id: str


@dataclass(frozen=True)
class PromptVersion:
    """An immutable version of a Prompt's text — edits create new versions."""
    id: str
    prompt_id: str
    text: str
    version: int
    created_at: datetime


@dataclass(frozen=True)
class ImagePrompt:
    id: str
    frame_id: str
    prompt_version_id: str
    style_reference: Optional[str] = None   # e.g. Character/Location style prompt id


@dataclass(frozen=True)
class AnimationPrompt:
    id: str
    frame_id: str
    prompt_version_id: str
    source_image_asset_id: Optional[str] = None


@dataclass(frozen=True)
class VideoPrompt:
    id: str
    frame_id: str
    prompt_version_id: str
    duration_seconds: float = 0.0


@dataclass(frozen=True)
class VoiceScript:
    """Text plus delivery directives handed to a VoiceProvider."""
    id: str
    narrative_id: str
    text: str
    character_id: Optional[str] = None
    pacing_wpm: Optional[int] = None
    ssml: Optional[str] = None
```

## Audio, Subtitles, Timeline

```python
@dataclass(frozen=True)
class Subtitle:
    id: str
    voice_script_id: str
    segments: tuple["SubtitleSegment", ...]


@dataclass(frozen=True)
class SubtitleSegment:
    start_seconds: float
    end_seconds: float
    text: str


@dataclass(frozen=True)
class Music:
    id: str
    asset_id: str
    mood: str
    bpm: Optional[float] = None


@dataclass(frozen=True)
class SFX:
    id: str
    asset_id: str
    trigger_frame_id: Optional[str] = None
    label: str = ""


@dataclass(frozen=True)
class Timeline:
    """Assembled sequence of Assets with timing — the render's blueprint."""
    id: str
    project_id: str
    track_items: tuple["TimelineItem", ...]
    total_duration_seconds: float


@dataclass(frozen=True)
class TimelineItem:
    asset_id: str
    track: str            # "video" | "audio" | "subtitle" | "music" | "sfx"
    start_seconds: float
    end_seconds: float
```

## Assets and Jobs

```python
@dataclass(frozen=True)
class Asset:
    """Any produced artifact — audio, image, video clip, subtitle file."""
    id: str
    kind: str             # "audio" | "image" | "video" | "subtitle" | "thumbnail"
    file_path: str
    produced_by_provider: str    # adapter name, e.g. "f5_tts", "flux_local"
    created_at: datetime
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class RenderJob:
    id: str
    project_id: str
    timeline_id: str
    strategy: str          # "slide" | "ai"
    status: str = "pending"   # pending | running | succeeded | failed
    output_asset_id: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class PublishJob:
    id: str
    project_id: str
    platform: str           # "youtube" | "shorts" | "tiktok" | "instagram" | "podcast" | "blog"
    asset_id: str
    status: str = "pending"
    remote_url: Optional[str] = None
    error: Optional[str] = None
```

## Workflow, Checkpoint, Memory

```python
@dataclass(frozen=True)
class WorkflowNode:
    """One node in the pipeline DAG. See 05-WORKFLOW.md for the full node list."""
    id: str
    name: str               # e.g. "ScenePlanning", "VoicePrompt"
    depends_on: tuple[str, ...]   # ids of upstream WorkflowNodes
    provider_port: Optional[str] = None   # e.g. "LLMProvider", "VoiceProvider"
    retry_policy: str = "exponential_backoff"
    max_retries: int = 3


@dataclass(frozen=True)
class WorkflowGraph:
    id: str
    project_id: str
    nodes: tuple[WorkflowNode, ...]
    created_at: datetime


@dataclass(frozen=True)
class Checkpoint:
    """Persisted output of a single WorkflowNode run, enabling resume."""
    id: str
    workflow_graph_id: str
    node_id: str
    status: str             # succeeded | failed
    output_ref: Optional[str] = None   # path or id of the persisted node output
    error: Optional[str] = None
    created_at: datetime = None


@dataclass(frozen=True)
class Memory:
    """Long-lived knowledge carried across Projects within a niche/channel."""
    id: str
    niche: str
    summary: str
    related_project_ids: tuple[str, ...] = ()
    updated_at: datetime = None
```

## Providers and Plugins

```python
class ProviderCapability(str, Enum):
    LOCAL = "local"
    CLOUD = "cloud"


@dataclass(frozen=True)
class Provider:
    """Metadata describing a registered Provider adapter (not the adapter code itself)."""
    id: str
    port: str                # "LLMProvider" | "VoiceProvider" | "ImageProvider" | ...
    name: str                 # "ollama_qwen3", "f5_tts", "flux_local", "pexels"
    capability: ProviderCapability
    is_default: bool = False


@dataclass(frozen=True)
class Plugin:
    """A third-party-discoverable bundle of one or more Providers."""
    id: str
    name: str
    version: str
    provider_ids: tuple[str, ...]
    entrypoint: str           # importable module path
```

## Relationship Summary

```
Project ──┬─ Research ── KnowledgeBase
          ├─ Outline ── Story ── Narrative ──┬─ Scene ── Shot ── Frame ──┬─ ImagePrompt
          │                                   │                          ├─ AnimationPrompt
          │                                   │                          └─ VideoPrompt
          │                                   └─ VoiceScript ── Subtitle
          ├─ Timeline ── TimelineItem ── Asset
          ├─ RenderJob ── Asset
          ├─ PublishJob ── Asset
          └─ WorkflowGraph ── WorkflowNode ── Checkpoint

Character / Location / Camera   → referenced by Scene/Shot/Frame/Prompt, reusable across Projects
Prompt ── PromptVersion          → ImagePrompt/AnimationPrompt/VideoPrompt reference a PromptVersion
Provider / Plugin                → resolved by the orchestrator per WorkflowNode.provider_port
Memory                           → persists across Projects within a niche, independent of any single WorkflowGraph
```

## Migration Note (Current Code → This Model)

The current `src/ytb_pipeline/pkg/models.py` chain (`VideoIdea(id, topic,
...) → Script → Voiceover → RenderedVideo → PublishResult`) is a flattened,
single-inheritance approximation of `Project → Narrative → VoiceScript →
RenderJob → PublishJob` above. The migration path (v2 milestone) is:

1. Introduce the new dataclasses above alongside the existing chain.
2. Add an adapter that constructs `Project`/`Narrative`/etc. from an existing
   `RenderedVideo`/`PublishResult` instance (backward-compat read path for
   existing `script.json` files).
3. Switch `orchestrator/batch_cli.py` to construct and pass the new objects.
4. Remove the old inheritance chain once no code path constructs it.
