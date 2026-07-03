# 22 — Plugin System

> Status: **NOT IMPLEMENTED.** All providers today are hard-coded Python
> modules inside `src/ytb_pipeline/`. There is no plugin discovery, no
> manifest format, no isolation, no third-party extension point. This
> document specifies the target system that lets capabilities be extended
> *without* forking `claude-ytb` itself — the natural extension of the
> Provider System (`21-PROVIDER_SYSTEM.md`) to code that does not live in
> this repository.

## 1. Purpose

The Provider System (`21-PROVIDER_SYSTEM.md`) makes built-in capabilities
swappable via config. The Plugin System extends that one step further:
letting a third party or the project owner add a **new** provider, render
strategy, quality gate, or publish target without modifying
`src/ytb_pipeline/` at all. This matters once the system has external
users/contributors, or once the project owner wants to experiment with a
provider (e.g. a custom TikTok publisher, a personal Flux LoRA) without
that experiment living in the main codebase's git history.

## 2. Plugin Types

| Type | Extends | Example |
|---|---|---|
| **Provider plugin** | Any `Provider` protocol from `21-PROVIDER_SYSTEM.md` (TTS, LLM, Image, Video, Music, SFX, Subtitle) | Custom Flux image provider, a fine-tuned local TTS voice |
| **Transform plugin** | A pipeline stage that modifies a domain object in place (post-ideation script rewriting, post-render watermarking) | Brand-specific intro/outro injector |
| **Quality-gate plugin** | The `ComplianceCheck` step (`pkg/models.py`) — additional pass/fail checks before a script proceeds | Custom claim-fact-checker against a private knowledge base |
| **Publish plugin** | `PublishProvider` (`20-PUBLISH_ENGINE.md`) | Custom TikTok publisher, a private CDN uploader |

## 3. Plugin Discovery

```python
"""src/ytb_pipeline/plugins/discovery.py (planned)."""

from __future__ import annotations

from pathlib import Path

PLUGINS_DIR = Path("plugins")  # project-root-relative, NOT inside src/ytb_pipeline


def discover_plugins() -> list["PluginManifest"]:
    """Scans PLUGINS_DIR for subdirectories containing a plugin.yaml,
    parses each manifest, and returns them WITHOUT importing any plugin
    code yet — discovery and loading are separate steps so a malformed
    plugin.yaml never crashes startup, only fails to register that one
    plugin (logged, not raised)."""
    manifests = []
    if not PLUGINS_DIR.exists():
        return manifests
    for entry in sorted(PLUGINS_DIR.iterdir()):
        manifest_path = entry / "plugin.yaml"
        if manifest_path.exists():
            manifests.append(_parse_manifest(manifest_path))
    return manifests
```

Discovery runs once at startup (or once per `claude-ytb` CLI invocation,
consistent with the existing listener's "fresh process per command"
philosophy in `listener.py`) — it never re-scans mid-run, keeping plugin
state stable for the duration of a pipeline execution.

## 4. Plugin Interface

```python
"""src/ytb_pipeline/plugins/interface.py (planned)."""

from __future__ import annotations

from typing import Protocol


class Plugin(Protocol):
    """Every plugin module must expose a module-level `PLUGIN` object
    satisfying this protocol — analogous to a Python entry_point, but kept
    as a simple convention (no setuptools entry_points machinery) since
    plugins here are discovered via plugin.yaml + directory scan, not pip
    package metadata."""

    plugin_id: str
    plugin_type: str       # "provider" | "transform" | "quality_gate" | "publish"
    capabilities: tuple[str, ...]   # declared, see §6 (security)

    def register(self, registries: "PluginRegistries") -> None:
        """Called once at load time. Registers this plugin's Provider(s)
        into the relevant capability registry from 21-PROVIDER_SYSTEM.md
        (e.g. TTS_REGISTRY, PUBLISH_REGISTRY) — the plugin never reaches
        into engine internals directly, only through registries."""
        ...
```

## 5. Plugin Manifest

```yaml
# plugins/my-tiktok-publisher/plugin.yaml (example, planned format)
name: my-tiktok-publisher
version: "0.1.0"
type: publish
entry_point: plugin:PLUGIN          # module:attribute, relative to plugin dir
capabilities:
  - network.outbound        # declares it makes external HTTP calls
  - filesystem.read          # declares it reads the rendered video file
dependencies:
  - requests>=2.31
description: >
  Publishes RenderedVideo to TikTok via the Content Posting API.
author: project-owner
```

```python
"""src/ytb_pipeline/plugins/manifest.py (planned)."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    type: str                      # "provider" | "transform" | "quality_gate" | "publish"
    entry_point: str
    capabilities: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    description: str = ""
    author: str = ""
    plugin_dir: "Path | None" = None
```

## 6. Plugin Security

Plugins are project-owner-installed code, not sandboxed against a malicious
author by default — but the manifest format still enforces **declared
capabilities** so a plugin cannot silently do more than its manifest
claims, and so a reviewer (human or automated) can audit what a plugin is
allowed to touch before enabling it:

```python
"""src/ytb_pipeline/plugins/security.py (planned)."""

KNOWN_CAPABILITIES = {
    "network.outbound",     # makes HTTP/API calls
    "filesystem.read",       # reads files outside its own plugin directory
    "filesystem.write",      # writes files outside its own plugin directory
    "subprocess.exec",       # shells out (e.g. to ffmpeg, a local model binary)
}


def validate_manifest(manifest: PluginManifest) -> list[str]:
    """Returns a list of validation errors (empty = valid). Rejects unknown
    capability strings — a plugin must declare from the closed
    KNOWN_CAPABILITIES set, never an arbitrary free-text capability that
    can't be reasoned about."""
    errors = []
    unknown = set(manifest.capabilities) - KNOWN_CAPABILITIES
    if unknown:
        errors.append(f"Capability không hợp lệ: {unknown}")
    if manifest.type not in {"provider", "transform", "quality_gate", "publish"}:
        errors.append(f"Loại plugin không hợp lệ: {manifest.type}")
    return errors
```

**No arbitrary code execution beyond Python import.** There is no remote
plugin-fetch-and-run step — a plugin must already be present on disk under
`plugins/` before discovery runs (the project owner or an explicit `git
clone`/copy step puts it there). The Plugin System does not implement a
plugin marketplace/auto-install mechanism; that is an explicit non-goal to
avoid supply-chain risk inconsistent with the project's local-first,
single-operator nature.

## 7. Plugin Isolation

```python
"""src/ytb_pipeline/plugins/isolation.py (planned)."""

def venv_path_for(manifest: PluginManifest) -> Path:
    """Optional per-plugin venv at plugins/{name}/.venv, used when
    manifest.dependencies conflict with the main pipeline's requirements.txt
    (e.g. a plugin needing a different requests/numpy version). Default:
    NOT isolated — plugin code imports into the main process and uses the
    main .venv, since most plugins (thin API wrappers) have no real
    dependency conflict risk. Isolation is opt-in per plugin, declared via
    `isolated: true` in plugin.yaml, and invoked via subprocess + a small
    JSON-over-stdio protocol when enabled (keeps the registry
    implementation simple — isolated plugins still satisfy the same
    Plugin protocol, just proxied through a subprocess call instead of an
    in-process method call)."""
    ...
```

## 8. Built-in vs User Plugins

| | Built-in capabilities | User/3rd-party plugins |
|---|---|---|
| Location | `src/ytb_pipeline/{voiceover,render,publish,...}/` | `plugins/{name}/` |
| Registration | Hard-registered in each capability's registry module at import time | Discovered + registered at startup via manifest scan |
| Versioning | Tracked with the main repo's git history | Each plugin's own `version` field; no compatibility contract enforced automatically (a future `compatible_with: ">=0.x"` manifest field is a reasonable v2 addition, not required for v1) |
| Trust | Reviewed via the project's normal code-review rules | Project-owner-installed; capabilities declared but not sandboxed (§6) |

A built-in provider never needs a `plugin.yaml` — the distinction exists
precisely so that core capabilities (TTS, render, publish baselines) are
never accidentally treated as "optional, may be absent" the way a
discovered plugin must be handled defensively.

## 9. Plugin Registry (Local JSON)

```python
"""src/ytb_pipeline/plugins/registry_store.py (planned)."""

import json
from pathlib import Path

REGISTRY_FILE = Path("data/plugins_registry.json")


def load_enabled_plugins() -> dict[str, bool]:
    """{plugin_name: enabled} — separate from discovery. A discovered
    plugin is NOT auto-enabled; the project owner must explicitly enable
    it once (recorded here), consistent with config-driven, never-silent
    provider selection (21-PROVIDER_SYSTEM.md §5)."""
    if not REGISTRY_FILE.exists():
        return {}
    return json.loads(REGISTRY_FILE.read_text())


def set_plugin_enabled(name: str, enabled: bool) -> None:
    state = load_enabled_plugins()
    state[name] = enabled
    REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))
```

## 10. Example Plugins

**Custom TikTok publisher** (`plugins/my-tiktok-publisher/`):
```
plugins/my-tiktok-publisher/
├── plugin.yaml
└── plugin.py        # defines PLUGIN: Plugin, registers a TikTokProvider
                      # into the PublishProvider registry from 20-PUBLISH_ENGINE.md
```

**Custom Flux image plugin** (`plugins/my-flux-images/`):
```
plugins/my-flux-images/
├── plugin.yaml       # capabilities: [subprocess.exec] (shells to a local
│                       Flux inference script), dependencies: [pillow]
└── plugin.py         # registers an ImageProvider for the render visual-
                       # source pipeline (19-RENDER_ENGINE.md)
```

Both examples register into existing capability registries from
`21-PROVIDER_SYSTEM.md` — the Plugin System never invents a parallel
registration mechanism; it is purely the discovery/manifest/security layer
that sits in front of the same registries built-in providers use.

## 11. Current State

**NOT IMPLEMENTED.** No `plugins/` directory, no manifest format, no
discovery code, no `Plugin` protocol. All current providers (`edge`, `f5`,
`elevenlabs` for TTS; `slide`, `ai` for render) are hard-coded Python
modules selected by string flag inside `src/ytb_pipeline/`, per
`21-PROVIDER_SYSTEM.md` §2's baseline description.

## 12. Implementation Roadmap

1. **Land the Provider System first** (`21-PROVIDER_SYSTEM.md`'s
   migration steps) — the Plugin System has nothing to register into
   until capability registries exist.
2. **`Plugin` protocol + `PluginManifest` dataclass** — define the
   contract before any discovery code, so the format is fixed and
   testable in isolation.
3. **Discovery + manifest parsing** — `plugins/` directory scan, YAML
   parse, validation (§6), with discovery failures logged and skipped, never
   crashing startup.
4. **Local JSON enable/disable registry** (§9) — plugins are opt-in even
   after being discovered.
5. **Wire one real example plugin** — a TikTok publisher or a custom image
   provider, built end-to-end as the proof that the discovery → manifest →
   registration → registry-lookup chain actually works, before declaring
   the system "done."
6. **Isolation (opt-in venv)** — only after the in-process path is proven;
   isolation adds real complexity (subprocess + JSON-over-stdio proxying)
   that should not block the common case of dependency-light plugins.
</content>
