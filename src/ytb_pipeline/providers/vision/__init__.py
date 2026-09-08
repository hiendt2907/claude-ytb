"""Registry for image-understanding providers used by ``VisualJudge``.

This is deliberately separate from ``image_registry``: image providers create
media, while vision-Judge providers inspect existing media.  A provider must
be registered here explicitly before production ``vlm_ranked`` selection may
resolve it.
"""
from __future__ import annotations

from collections.abc import Callable

from ...render.visual_judge import VisualJudge
from .xkiro_provider import XkiroVisualJudge

_JudgeFactory = Callable[[str], VisualJudge]
_VISUAL_JUDGE_FACTORIES: dict[str, _JudgeFactory] = {
    "xkiro": XkiroVisualJudge,
}


def available_visual_judges() -> tuple[str, ...]:
    """Return the explicitly registered image-understanding capabilities."""
    return tuple(sorted(_VISUAL_JUDGE_FACTORIES))


def get_visual_judge(provider: str, model: str) -> VisualJudge:
    """Construct the configured production Judge adapter.

    Model capability is verified against the provider catalog by the adapter
    before it transmits candidate images.  Registry presence therefore means
    an image-capable transport exists, not that every model name is visual.
    """
    try:
        factory = _VISUAL_JUDGE_FACTORIES[provider]
    except KeyError as exc:
        raise ValueError(
            f"Không có vision judge provider tên {provider!r}. "
            f"Các provider khả dụng: {list(available_visual_judges())}"
        ) from exc
    return factory(model)


__all__ = ["XkiroVisualJudge", "available_visual_judges", "get_visual_judge"]
