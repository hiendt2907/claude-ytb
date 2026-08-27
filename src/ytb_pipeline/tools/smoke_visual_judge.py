"""Explicit live smoke for the configured production VisualJudge.

This command is intentionally outside ``make test``.  It performs a real
network request and therefore requires operator-controlled credentials and
provider/model configuration.

Examples::

    python -m ytb_pipeline.tools.smoke_visual_judge --status
    python -m ytb_pipeline.tools.smoke_visual_judge --generate-probe
    python -m ytb_pipeline.tools.smoke_visual_judge \
        --image /path/to/candidate.png --intent "A person at a cafe table"
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw

from ..config.settings import settings
from ..providers.vision import available_visual_judges, get_visual_judge
from ..render.visual_judge import JudgeCandidate, JudgeContext

_PROBE_INTENT = (
    "Operational image-transport probe. Inspect the actual supplied image. "
    "In reasons return exactly the observed facts using these bounded forms: "
    "observed_color=<red|green|blue> and "
    "observed_shape=<circle|square|triangle>. Do not infer from filenames."
)
_EXPECTED_PROBE_FACTS = {"observed_color=blue", "observed_shape=triangle"}


@dataclass(frozen=True)
class _SmokeVisualRequest:
    visual_intent: str
    characters: tuple[str, ...] = ()
    semantic_constraints: tuple[str, ...] = ()
    dimensions: tuple[int, int] = (256, 256)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Send real local image bytes through the configured production VisualJudge."
    )
    parser.add_argument("--provider", help="Override VISUAL_JUDGE_PROVIDER for this smoke only.")
    parser.add_argument("--model", help="Override VISUAL_JUDGE_MODEL for this smoke only.")
    parser.add_argument("--image", action="append", type=Path, default=[], help="Local PNG/JPEG candidate; repeat for a comparative request.")
    parser.add_argument("--intent", help="VisualRequest intent for manually supplied images.")
    parser.add_argument("--generate-probe", action="store_true", help="Generate a temporary blue-triangle fixture and verify facts visible only in its pixels.")
    parser.add_argument("--status", action="store_true", help="Print configuration/registry status without making a provider request.")
    return parser


def _status(provider: str, model: str) -> bool:
    configured = bool(provider and model)
    registered = bool(provider and provider in available_visual_judges())
    credential = bool(settings.xkiro_api_key.strip()) if provider == "xkiro" else False
    print(f"semantic judge configured: {'yes' if configured else 'no'}")
    print(f"vision-capable adapter registered: {'yes' if registered else 'no'}")
    print(f"credential configured: {'yes' if credential else 'no'}")
    print(f"provider: {provider or '(unset)'}")
    print(f"model: {model or '(unset)'}")
    return configured and registered and credential


def _generate_probe(path: Path) -> None:
    image = Image.new("RGB", (256, 256), "white")
    draw = ImageDraw.Draw(image)
    draw.polygon(((128, 32), (32, 224), (224, 224)), fill="blue")
    image.save(path, format="PNG")


def _candidate(path: Path, index: int) -> JudgeCandidate:
    payload = path.read_bytes()
    return JudgeCandidate(
        asset_id=f"smoke-candidate-{index:02d}",
        local_path=str(path),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        candidate_index=index,
    )


def _print_result(result) -> None:  # noqa: ANN001 - provider-neutral result
    for evaluation in result.evaluations:
        reasons = " | ".join(evaluation.reasons) or "(none)"
        failures = ",".join(evaluation.hard_failures) or "none"
        print(
            f"asset_id={evaluation.asset_id} "
            f"aggregate_score={evaluation.aggregate_score():.3f} "
            f"hard_failures={failures} reasons={reasons}"
        )


def _run(
    *,
    provider: str,
    model: str,
    image_paths: tuple[Path, ...],
    intent: str,
    probe: bool,
) -> int:
    judge = get_visual_judge(provider, model)
    candidates = tuple(_candidate(path, index) for index, path in enumerate(image_paths))
    result = judge.evaluate(
        _SmokeVisualRequest(visual_intent=intent),
        candidates,
        JudgeContext(scene_id="smoke-scene", shot_id="smoke-shot", video_slug="visual-judge-smoke"),
    )
    _print_result(result)
    if probe:
        observed = {
            reason.strip().lower()
            for evaluation in result.evaluations
            for reason in evaluation.reasons
        }
        if not _EXPECTED_PROBE_FACTS.issubset(observed):
            print(
                "IMAGE_TRANSPORT_PROBE: FAIL — provider did not report the hidden blue-triangle facts.",
                file=sys.stderr,
            )
            return 1
        print("IMAGE_TRANSPORT_PROBE: PASS")
    else:
        print("VISUAL_JUDGE_SMOKE: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    provider = (args.provider or settings.visual_judge_provider).strip()
    model = (args.model or settings.visual_judge_model).strip()
    if args.status:
        _status(provider, model)
        return 0
    if not provider or not model:
        print(
            "Cấu hình VISUAL_JUDGE_PROVIDER và VISUAL_JUDGE_MODEL trước khi smoke.",
            file=sys.stderr,
        )
        return 2
    if args.generate_probe and args.image:
        print("Chọn --generate-probe hoặc --image, không dùng đồng thời.", file=sys.stderr)
        return 2
    if not args.generate_probe and not args.image:
        print("Cần --generate-probe hoặc ít nhất một --image.", file=sys.stderr)
        return 2
    if args.image and not (args.intent or "").strip():
        print("--intent là bắt buộc khi dùng --image.", file=sys.stderr)
        return 2
    try:
        if args.generate_probe:
            with tempfile.TemporaryDirectory(prefix="ytb-visual-judge-smoke-") as directory:
                path = Path(directory) / "probe.png"
                _generate_probe(path)
                return _run(
                    provider=provider,
                    model=model,
                    image_paths=(path,),
                    intent=_PROBE_INTENT,
                    probe=True,
                )
        return _run(
            provider=provider,
            model=model,
            image_paths=tuple(args.image),
            intent=args.intent.strip(),
            probe=False,
        )
    except Exception as exc:
        print(f"VISUAL_JUDGE_SMOKE: FAIL — {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
