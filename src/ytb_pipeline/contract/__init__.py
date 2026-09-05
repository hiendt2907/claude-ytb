"""One compiled production contract per run.

Library only for now: Step 3b of
`plans/claude-ytb-production-engine-refactor.md` moves the prompt and gate call
sites onto it. Compiling here without switching those call sites first lets the
shadow comparison prove parity before anything in production changes.
"""

from .capability import ProviderCapabilitySnapshot, capability_for
from .effective import (
    CONTRACT_SCHEMA_VERSION,
    EditorialPolicy,
    EffectiveProductionContract,
    RuntimeBinding,
    SettingsSnapshot,
    VisualPolicy,
    compile_contract,
    snapshot_from_settings,
)
from .fingerprint import creative_policy_fingerprint, runtime_binding_fingerprint
from .invalidation import NODE_FINGERPRINT_DEPS, stale_node_ids

__all__ = [
    "CONTRACT_SCHEMA_VERSION",
    "EditorialPolicy",
    "NODE_FINGERPRINT_DEPS",
    "EffectiveProductionContract",
    "ProviderCapabilitySnapshot",
    "RuntimeBinding",
    "SettingsSnapshot",
    "VisualPolicy",
    "capability_for",
    "compile_contract",
    "creative_policy_fingerprint",
    "runtime_binding_fingerprint",
    "snapshot_from_settings",
    "stale_node_ids",
]
