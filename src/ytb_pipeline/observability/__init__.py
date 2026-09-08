"""Observability records for a production run.

Library only: nothing here is wired into the pipeline yet. Step 2c of
`plans/claude-ytb-production-engine-refactor.md` owns the call site, so that
wiring lands as its own reviewable change rather than as a side effect of
defining the record.
"""

from .run_manifest import NodeOutcome, RunManifest

__all__ = ["NodeOutcome", "RunManifest"]
