"""Repeatable local-first AI benchmark runner.

The benchmark records timings and availability for the local stack without hiding
missing services. Each section is independent so a missing ComfyUI/Wan/TTS model
still produces a useful report instead of aborting the whole run.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Awaitable

from ..config.settings import settings
from ..pkg.models import ComplianceCheck, Script, Segment
from ..providers.registry import get_image_provider, get_llm_provider, get_video_provider, get_voice_provider
from ..voiceover.tts import _slugify

BENCH_TEXT = (
    "Đây là đoạn benchmark tiếng Việt ngắn. "
    "Nó đo tốc độ tổng hợp giọng nói local với thanh điệu rõ ràng. "
    "Các cụm kiểm tra gồm quyết định, thói quen, nghịch lý, tập trung và nhận thức. "
    "Khi một người trì hoãn, vấn đề thường không nằm ở ý chí yếu, mà nằm ở cách não "
    "so sánh phần thưởng trước mắt với chi phí mơ hồ ở tương lai. "
    "Nếu phần thưởng đủ gần, não sẽ ưu tiên nó, ngay cả khi ta biết lựa chọn đó làm "
    "ngày mai tệ hơn. "
    "Điều này tạo ra cảm giác rất quen: ta không thật sự muốn bỏ cuộc, nhưng cũng "
    "không thấy đủ lực để bắt đầu. "
    "Một hệ thống tốt không mắng bản thân phải cố hơn, mà làm chi phí bắt đầu nhỏ đi, "
    "làm tín hiệu tiến bộ rõ hơn, và đặt phần thưởng đúng gần hành động cần làm. "
    "Benchmark này cố ý dùng câu dài, câu ngắn, dấu phẩy, dấu chấm, các thanh điệu "
    "khó, và nhịp kể tự nhiên để kiểm tra độ ổn định khi tổng hợp một đoạn gần một phút."
)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


def _entry(ok: bool, start: float, **extra) -> dict:
    return {"ok": ok, "latency_ms": _elapsed_ms(start), **extra}


def _script(title: str = "Local Benchmark") -> Script:
    seg = Segment(caption="Benchmark", narration=BENCH_TEXT, broll="minimal abstract Vietnamese psychology scene")
    compliance = ComplianceCheck(
        passed=True,
        community="benchmark",
        copyright="benchmark",
        accuracy="benchmark",
        advertiser="benchmark",
        coppa="not for kids",
        notes="local benchmark fixture",
    )
    return Script(
        topic="Local benchmark",
        title=title,
        description="Fixed local benchmark fixture.",
        tags=("benchmark",),
        body=BENCH_TEXT,
        segments=(seg,),
        compliance=compliance,
    )


def _run(coro: Awaitable[dict]) -> dict:
    return asyncio.run(coro)


async def _bench_script_generation() -> dict:
    start = time.perf_counter()
    provider = get_llm_provider()
    if not provider.is_available():
        return _entry(False, start, provider=provider.name, error="provider unavailable")
    try:
        await provider.complete(
            "Return one short Vietnamese title for a video about decision fatigue.",
            system="Benchmark only. Return plain text.",
            max_tokens=64,
            temperature=0.1,
        )
        return _entry(True, start, provider=provider.name, model=provider.model_name())
    except Exception as exc:  # noqa: BLE001
        return _entry(False, start, provider=provider.name, error=str(exc))


async def _bench_tts(work_dir: Path) -> dict:
    start = time.perf_counter()
    provider = get_voice_provider(settings.tts_provider)
    if not provider.is_available():
        return _entry(False, start, provider=provider.name, error="provider unavailable")
    try:
        title = f"Local Benchmark {int(time.time() * 1000)}"
        _cleanup_audio_slug(_slugify(title))
        voiceover = await provider.synthesise(_script(title), work_dir / "audio")
        return _entry(
            True,
            start,
            provider=provider.name,
            output=str(voiceover.audio_path),
            duration_sec=voiceover.duration_sec,
        )
    except Exception as exc:  # noqa: BLE001
        return _entry(False, start, provider=provider.name, error=str(exc))


def _cleanup_audio_slug(slug: str) -> None:
    """Remove only files produced by this benchmark slug.

    The legacy F5/edge voice path owns ``assets/audio`` globally and ignores the
    provider ``output_dir`` argument. Cleaning the unique benchmark slug prevents
    resume from reusing a partial file while leaving production audio untouched.
    """
    audio_dir = Path("assets/audio")
    if not audio_dir.exists():
        return
    for path in audio_dir.glob(f"{slug}*"):
        if path.is_file():
            path.unlink(missing_ok=True)


def _bench_image(work_dir: Path) -> dict:
    start = time.perf_counter()
    provider = get_image_provider(settings.image_provider)
    if not provider.is_available():
        return _entry(False, start, provider=provider.name, error="provider unavailable")
    try:
        out = provider.generate(
            "clean cinematic abstract Vietnamese psychology scene",
            512,
            768,
            work_dir / "image" / "flux_benchmark.png",
        )
        return _entry(True, start, provider=provider.name, output=str(out))
    except Exception as exc:  # noqa: BLE001
        return _entry(False, start, provider=provider.name, error=str(exc))


def _bench_video(work_dir: Path) -> dict:
    start = time.perf_counter()
    provider = get_video_provider(settings.video_provider)
    if not provider.is_available():
        return _entry(False, start, provider=provider.name, error="provider unavailable")
    try:
        out = provider.generate(
            "subtle motion abstract brain decision scene",
            5.0,
            512,
            768,
            work_dir / "video" / "wan_benchmark.mp4",
        )
        return _entry(True, start, provider=provider.name, output=str(out))
    except Exception as exc:  # noqa: BLE001
        return _entry(False, start, provider=provider.name, error=str(exc))


def run_local_benchmark(output_path: Path | str = "assets/benchmarks/local_benchmark.json") -> dict:
    output_path = Path(output_path)
    work_dir = output_path.parent / "_work"
    work_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "settings": {
            "llm_provider": settings.llm_provider,
            "tts_provider": settings.tts_provider,
            "image_provider": settings.image_provider,
            "video_provider": settings.video_provider,
            "broll_strategy": settings.broll_strategy,
        },
        "script_generation": _run(_bench_script_generation()),
        "tts": _run(_bench_tts(work_dir)),
        "flux_image": _bench_image(work_dir),
        "local_video": _bench_video(work_dir),
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def format_benchmark_report(report: dict) -> str:
    lines = ["Local benchmark report"]
    for key in ("script_generation", "tts", "flux_image", "local_video"):
        item = report[key]
        status = "OK" if item.get("ok") else "FAIL"
        detail = item.get("error") or item.get("output") or item.get("model") or ""
        lines.append(f"- {key}: {status} ({item.get('latency_ms', 0)} ms) {detail}")
    return "\n".join(lines)
