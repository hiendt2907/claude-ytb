"""One record answering: what did this run decide, and under which contract?

Today that answer is scattered across `project.json`, the candidate store, the
evaluation store, structured logs and ad-hoc scratch scripts, so reconstructing
a past run means joining five sources by hand. A manifest is the single place a
later reader — or a shadow evaluation — can start from.

Two fingerprints are recorded separately on purpose. `creative_policy` covers
the storytelling rules; `runtime_binding` covers which provider and model
actually served the request. Swapping a model must move the second and leave
the first alone, so an artifact is only invalidated by the change that really
affects it. Freezing them together is what once made a provider outage
permanently unproducible for every script pinned to that profile version.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILENAME = "run_manifest.json"


@dataclass(frozen=True)
class NodeOutcome:
    """What one DAG node did, and what it left behind."""

    node_id: str
    status: str
    started_at: str
    finished_at: str
    attempts: int = 1
    detail: str = ""
    artifact_hashes: Mapping[str, str] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "attempts": self.attempts,
            "detail": self.detail,
            "artifact_hashes": dict(sorted(self.artifact_hashes.items())),
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "NodeOutcome":
        raw = data.get("artifact_hashes") or {}
        hashes = {str(k): str(v) for k, v in dict(raw).items()}
        return cls(
            node_id=str(data["node_id"]),
            status=str(data["status"]),
            started_at=str(data.get("started_at", "")),
            finished_at=str(data.get("finished_at", "")),
            attempts=int(data.get("attempts", 1)),
            detail=str(data.get("detail", "")),
            artifact_hashes=hashes,
        )


@dataclass(frozen=True)
class RunManifest:
    """Immutable. Enrich with `record_node`, which returns a new manifest."""

    run_id: str
    started_at: str
    profile_id: str
    profile_version: str
    creative_policy_fingerprint: str = ""
    runtime_binding_fingerprint: str = ""
    provider_bindings: Mapping[str, str] = field(default_factory=dict)
    node_outcomes: tuple[NodeOutcome, ...] = ()

    def record_node(self, outcome: NodeOutcome) -> "RunManifest":
        """Append or replace one node's outcome, never mutating this manifest.

        Replacing rather than appending on re-run keeps a resumed run's manifest
        describing the run's final state instead of accumulating one row per
        retry, which would make `node_outcomes` ambiguous to read back.
        """
        kept = tuple(o for o in self.node_outcomes if o.node_id != outcome.node_id)
        previous = next(
            (o for o in self.node_outcomes if o.node_id == outcome.node_id), None
        )
        if previous is not None and outcome.attempts <= previous.attempts:
            outcome = replace(outcome, attempts=previous.attempts + 1)
        return replace(self, node_outcomes=kept + (outcome,))

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "run_id": self.run_id,
            "started_at": self.started_at,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "fingerprints": {
                "creative_policy": self.creative_policy_fingerprint,
                "runtime_binding": self.runtime_binding_fingerprint,
            },
            "provider_bindings": dict(sorted(self.provider_bindings.items())),
            "node_outcomes": [o.to_json() for o in self.node_outcomes],
        }

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "RunManifest":
        version = int(data.get("schema_version", 0))
        if version != MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"run_manifest schema_version={version!r} không đọc được "
                f"(hỗ trợ {MANIFEST_SCHEMA_VERSION})."
            )
        fingerprints = dict(data.get("fingerprints") or {})
        bindings_raw = data.get("provider_bindings") or {}
        bindings = {str(k): str(v) for k, v in dict(bindings_raw).items()}
        return cls(
            run_id=str(data["run_id"]),
            started_at=str(data.get("started_at", "")),
            profile_id=str(data.get("profile_id", "")),
            profile_version=str(data.get("profile_version", "")),
            creative_policy_fingerprint=str(fingerprints.get("creative_policy", "")),
            runtime_binding_fingerprint=str(fingerprints.get("runtime_binding", "")),
            provider_bindings=bindings,
            node_outcomes=tuple(
                NodeOutcome.from_json(o) for o in data.get("node_outcomes", [])
            ),
        )

    def write(self, project_dir: Path) -> Path:
        """Write beside `project.json`. Atomic: a killed run leaves no half file."""
        project_dir.mkdir(parents=True, exist_ok=True)
        path = project_dir / MANIFEST_FILENAME
        temp = path.with_suffix(".json.tmp")
        temp.write_text(
            json.dumps(self.to_json(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)
        return path

    @classmethod
    def read(cls, project_dir: Path) -> "RunManifest | None":
        path = project_dir / MANIFEST_FILENAME
        if not path.is_file():
            return None
        return cls.from_json(json.loads(path.read_text(encoding="utf-8")))


def new_run_id(now: datetime) -> str:
    """Sortable and readable; the caller supplies the clock so tests stay exact."""
    return now.strftime("%Y%m%dT%H%M%SZ")
