"""CLI entry point: quét scene folders, sinh N assignment, render N video."""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from ytb_pipeline.assembler.assignment import build_assignments
from ytb_pipeline.assembler.duration import (
    ClipLengthDurationStrategy,
    DurationStrategy,
    VoiceSilenceDurationStrategy,
)
from ytb_pipeline.assembler.manual_plan import parse_manual_plan
from ytb_pipeline.assembler.naming import output_path
from ytb_pipeline.assembler.profiles import resolve_profile
from ytb_pipeline.assembler.render import render_output
from ytb_pipeline.assembler.scanning import scan_scene_folders


def _build_strategy(mode: str) -> DurationStrategy:
    if mode == "clip_length":
        return ClipLengthDurationStrategy()
    if mode == "voice_silence":
        return VoiceSilenceDurationStrategy()
    raise ValueError(f"duration_mode không hợp lệ: {mode!r} (dùng clip_length | voice_silence)")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Dựng N video output từ scene folders")
    parser.add_argument("--scenes-dir", type=Path, required=True)
    parser.add_argument("--voice-track", type=Path, required=True)
    parser.add_argument("--product-name", type=str, required=True)
    parser.add_argument("--n-outputs", type=int, default=1, help="Bỏ qua nếu dùng --manual-plan")
    parser.add_argument("--output-dir", type=Path, default=Path("output"))
    parser.add_argument("--tmp-dir", type=Path, default=Path(".assembler_tmp"))
    parser.add_argument(
        "--duration-mode",
        choices=["clip_length", "voice_silence"],
        default="clip_length",
    )
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument(
        "--aspect-ratio", choices=["16:9", "9:16"], default="16:9",
    )
    parser.add_argument(
        "--fit-mode", choices=["pad", "crop"], default="pad",
        help="pad = giữ nguyên hình + viền đen; crop = lấp đầy khung, mất 2 bên/trên dưới",
    )
    parser.add_argument(
        "--manual-plan",
        type=Path,
        default=None,
        help="Path tới file text plan nhập tay (thay vì random chọn N output)",
    )
    parser.add_argument("--watermark", type=Path, default=None, help="Path tới logo PNG")
    parser.add_argument(
        "--watermark-position",
        choices=["top-left", "top-right", "bottom-left", "bottom-right"],
        default="bottom-right",
    )
    parser.add_argument(
        "--watermark-scale", type=float, default=0.15,
        help="Chiều rộng logo tính theo tỉ lệ %% chiều rộng video (0.15 = 15%%)",
    )
    parser.add_argument("--subtitle", type=Path, default=None, help="Path tới file .srt burn vào video")
    parser.add_argument(
        "--edit-profile",
        type=str,
        default="affiliate_default",
        help="Auto-edit profile, VD affiliate_default | tiktok_shop_fast | product_review_smooth",
    )
    args = parser.parse_args(argv)

    scenes = scan_scene_folders(args.scenes_dir)

    if args.manual_plan is not None:
        assignments = parse_manual_plan(args.manual_plan.read_text(encoding="utf-8"), scenes)
    else:
        rng = random.Random(args.seed)
        assignments = build_assignments(scenes, args.n_outputs, rng)

    strategy = _build_strategy(args.duration_mode)
    total_outputs = len(assignments)
    edit_profile = resolve_profile(args.edit_profile)

    for assignment in assignments:
        durations = strategy.scene_durations(assignment.groups, args.voice_track)
        out_path = output_path(
            args.output_dir, args.product_name, assignment.output_index, total_outputs
        )
        render_output(
            assignment=assignment,
            scene_durations=durations,
            voice_track=args.voice_track,
            out_path=out_path,
            tmp_dir=args.tmp_dir / f"output_{assignment.output_index:03d}",
            aspect_ratio=args.aspect_ratio,
            fit_mode=args.fit_mode,
            watermark_path=args.watermark,
            watermark_position=args.watermark_position,
            watermark_scale=args.watermark_scale,
            subtitle_path=args.subtitle,
            edit_profile=edit_profile,
        )


if __name__ == "__main__":
    main()
