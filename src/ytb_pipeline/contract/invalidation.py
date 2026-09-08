"""Which nodes a contract change actually invalidates.

`pipeline._reset_stale_nodes` answers "is the output still on disk" and "did
publish really upload". It cannot answer "were the rules different when this
was made", so a rule change either silently reuses stale work or — when the
profile version happens to sit in a cache key — discards every asset at once.
Neither is proportional.

Splitting the question by fingerprint makes it proportional:

  creative  — the story rules. Anything written or planned under them is stale
              when they move: the script, the scene plan, and everything
              downstream of them.
  runtime   — the provider, model and sampler settings. Generated media is
              stale when they move; the script is not, because no model that
              changed had a hand in writing it.

A node depending on both is stale when either moves.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..project.models import Project

# Every pipeline node, and what a change to each fingerprint means for it.
# A node absent from this table is never invalidated, which is why the test
# suite asserts the pipeline's own node set is covered.
NODE_FINGERPRINT_DEPS: dict[str, tuple[str, ...]] = {
    # The script was written under the story rules; no provider binding
    # survives in it beyond the words themselves.
    "input": ("creative",),
    # Narration audio is the script read by a specific voice at a specific
    # pace. Rewriting the rules changes the words; swapping the voice changes
    # the reading.
    "voiceover": ("creative", "runtime"),
    # Validates measured audio against contract bounds, which are creative,
    # using a rate that is runtime.
    "audio_quality": ("creative", "runtime"),
    # Derived from segments plus the profile's scene-planning mode, both of
    # which are authored decisions.
    "scene_plan": ("creative",),
    # Art direction is authored; the checkpoint, sampler and judge are not.
    "visual_assets": ("creative", "runtime"),
    "render": ("creative", "runtime"),
    "render_quality": ("creative", "runtime"),
    # Upload metadata follows the render. It carries no rule of its own, but a
    # re-render must be re-published rather than reusing the old upload.
    "publish": ("creative", "runtime"),
}


def stale_node_ids(
    project: "Project", *, creative: str, runtime: str
) -> tuple[str, ...]:
    """Completed nodes whose recorded fingerprints no longer match the contract.

    A node that recorded no fingerprint is left alone. Every `project.json`
    written before this shipped is in that state, and treating "absent" as
    "different" would reset every node of every project on disk the first time
    this runs.
    """
    from ..project.models import NodeStatus

    stale: list[str] = []
    for node_id, node in sorted(project.nodes.items()):
        if node.status != NodeStatus.DONE:
            continue
        recorded = {
            "creative": node.creative_fingerprint,
            "runtime": node.runtime_fingerprint,
        }
        current = {"creative": creative, "runtime": runtime}
        for kind in NODE_FINGERPRINT_DEPS.get(node_id, ()):
            if recorded[kind] and recorded[kind] != current[kind]:
                stale.append(node_id)
                break
    return tuple(stale)
