"""`ytb batch start` — gọi LLM làm phần SÁNG TẠO (ideation + viết kịch bản).

Xem docstring đầu queue_manager.py về việc đọc hằng số/hàm có thể patch qua
`_cli()` tại thời điểm gọi.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from ..claude_cli import build_claude_cmd
from ..agents.base import AgentStatus
from ..agents.qa_agent import QAAgent
from ..ideation.generator import CHARS_PER_MIN, SHORT_MAX_MINUTES, SHORT_MIN_MINUTES, load_script
from ..ideation.series import slugify
from ..providers.registry import get_llm_provider
from .queue_manager import PIPELINE_LOG_DIR

LEDGER_HEADER = "# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"
SHORT_TARGET_CHARS = int(CHARS_PER_MIN * 1.0)
SHORT_MIN_CHARS = int(CHARS_PER_MIN * SHORT_MIN_MINUTES) + 60
SHORT_MAX_CHARS = int(CHARS_PER_MIN * SHORT_MAX_MINUTES) - 60
CLAUDE_HAIKU_MODEL = "haiku"
CLAUDE_SONNET_MODEL = "sonnet"


def _cli():
    from . import batch_cli

    return batch_cli


def _count_pending_ideation(type_of_vid: str, auto_state_path: Path | None = None) -> tuple[int, list[str]]:
    """Đếm scripts ĐÃ viết xong (đã có trong batch nhưng chưa done trong ledger) theo loại video.

    Trả (số lượng, danh sách slug) để prompt resume nói rõ "đừng viết lại cái này".
    """
    cli = _cli()
    auto_state_path = auto_state_path if auto_state_path is not None else cli.AUTO_STATE_PATH
    data = json.loads(Path(auto_state_path).read_text(encoding="utf-8"))
    video_key = "long_videos" if type_of_vid == "long" else "short_videos"

    batch_keys = sorted(k for k in data if k.startswith("shorts_funnel_batch_"))
    if not batch_keys:
        return 0, []
    batch = data[batch_keys[-1]]
    videos = batch.get(video_key, [])

    done = cli.done_slugs()
    pending = [v["slug"] for v in videos if v["slug"] not in done]
    return len(pending), pending


def _build_resume_prompt(remaining: int, type_of_vid: str, type_of_rules: str, existing_slugs: list[str]) -> str:
    """Prompt resume — nói rõ đã có bao nhiêu, cần thêm bao nhiêu, KHÔNG viết lại cũ."""
    vid_label = "Video dài (ngang, 10-30 phút)" if type_of_vid == "long" else "Short (dọc, 1-2 phút)"
    topic_guidance = (
        "TỰ chọn chủ đề hợp ngách kênh (đọc memory dự án + ledger)."
        if type_of_rules == "auto"
        else (
            f"Ý tưởng người dùng đưa là RÀNG BUỘC CHÍNH: {type_of_rules}. "
            "Được chia thành nhiều góc nhìn khác nhau nhưng không được đổi sang chủ đề khác."
        )
    )
    slugs_str = "\n".join(f"  - {s}" for s in existing_slugs)
    return (
        f"RESUME IDEATION — tiếp tục batch bị dừng giữa chừng.\n\n"
        f"Các slug SAU ĐÂY đã có script + đã đăng ký trong auto_state.json, "
        f"TUYỆT ĐỐI KHÔNG viết lại hay đăng ký lại:\n{slugs_str}\n\n"
        f"Cần viết THÊM {remaining} video loại \"{vid_label}\" — dùng skill youtube-ideation, "
        f"tuân thủ ĐẦY ĐỦ .claude/skills/youtube-ideation/video-quality-rules.md "
        f"(cổng verify mục 0, luật series mục 0d, độ dài mục 2a/2b). {topic_guidance}\n\n"
        "Trước khi chọn chủ đề: đọc data/ledger.md, loại bỏ mọi chủ đề trùng/tương tự "
        "(mọi status, không chỉ done).\n\n"
        "QUY TRÌNH BẮT BUỘC — làm TUẦN TỰ từng video, KHÔNG làm batch:\n"
        "  1. Chọn chủ đề + viết scripts/<slug>.json đầy đủ (compliance.passed=true)\n"
        "  2. GHI NGAY vào assets/auto_state.json (append item vào mảng đúng — "
        "long_videos hoặc short_videos trong batch key mới nhất; schema: "
        "slug/topic/orientation/render_provider/dry_run/publish_at/"
        "stage=\"ideation\"/status=\"ok\"/updated)\n"
        "  3. GHI NGAY 1 dòng vào data/ledger.md\n"
        "  4. Chỉ sau khi đã ghi xong cả 2 file mới được bắt đầu video tiếp theo\n\n"
        "Lý do: nếu hết token giữa chừng, `ytb batch start --resume` đọc "
        "auto_state.json để biết đã có bao nhiêu và chỉ viết phần còn thiếu.\n\n"
        "TUYỆT ĐỐI KHÔNG chạy voiceover/render/publish. Khi đủ "
        f"{remaining} video MỚI đã có script + đăng ký xong, DỪNG lại và báo tóm tắt "
        "(slug + chủ đề từng video mới)."
    )


def _build_start_prompt(num_of_vid: int, type_of_vid: str, type_of_rules: str) -> str:
    """Dựng prompt giao việc SÁNG TẠO (ideation + viết kịch bản) cho LLM.

    Đây là phần KHÔNG mô phỏng được bằng code thường — cần LLM chọn chủ đề
    (chống trùng ledger), viết narration, tự chấm cổng compliance. Sau khi LLM
    viết xong scripts/*.json + đăng ký vào auto_state.json, `ytb batch run --loop`
    mới tiếp quản phần sản xuất máy-móc (không cần LLM nữa).
    """
    vid_label = "Video dài (ngang, 10-30 phút)" if type_of_vid == "long" else "Short (dọc, 1-2 phút)"
    topic_guidance = (
        "TỰ chọn chủ đề hợp ngách kênh hiện tại (đọc memory dự án + ledger để biết ngách)."
        if type_of_rules == "auto"
        else (
            f"Ý tưởng người dùng đưa là RÀNG BUỘC CHÍNH: {type_of_rules}. "
            "Được chia thành nhiều góc nhìn khác nhau nhưng không được đổi sang chủ đề khác."
        )
    )
    return (
        f"Làm phần SÁNG TẠO (ideation + viết kịch bản) cho {num_of_vid} video loại "
        f"\"{vid_label}\" — dùng skill youtube-ideation, tuân thủ ĐẦY ĐỦ "
        f".claude/skills/youtube-ideation/video-quality-rules.md (cổng verify mục 0, "
        f"luật series mục 0d, độ dài mục 2a/2b). {topic_guidance}\n\n"
        "Trước khi chọn chủ đề: đọc data/ledger.md, loại bỏ mọi chủ đề trùng/tương tự "
        "(mọi status, không chỉ done).\n\n"
        "QUY TRÌNH BẮT BUỘC — làm TUẦN TỰ từng video, KHÔNG làm batch:\n"
        "  1. Chọn chủ đề + viết scripts/<slug>.json đầy đủ (compliance.passed=true)\n"
        "  2. GHI NGAY vào assets/auto_state.json (append item vào mảng đúng — "
        "long_videos hoặc short_videos trong batch key mới nhất; schema: "
        "slug/topic/orientation/render_provider/dry_run/publish_at/"
        "stage=\"ideation\"/status=\"ok\"/updated)\n"
        "  3. GHI NGAY 1 dòng vào data/ledger.md\n"
        "  4. Chỉ sau khi đã ghi xong cả 2 file mới được bắt đầu video tiếp theo\n\n"
        "Lý do: nếu hết token giữa chừng, `ytb batch start --resume` sẽ đọc "
        "auto_state.json để biết đã có bao nhiêu script và KHÔNG viết lại — "
        "chỉ hoạt động đúng nếu mỗi video được ghi ngay sau khi xong.\n\n"
        "TUYỆT ĐỐI KHÔNG chạy voiceover/render/publish — đó là việc của "
        "`ytb batch run --loop` chạy bằng tay sau, không cần LLM. Khi đủ "
        f"{num_of_vid} video đã có script + đăng ký xong, DỪNG lại và báo tóm tắt "
        "(slug + chủ đề từng video)."
    )


def _prompt_start_interactive(args: argparse.Namespace) -> argparse.Namespace:
    """Hỏi tương tác khi thiếu tham số bắt buộc."""
    ask_all = bool(getattr(args, "ask", False))
    if not sys.stdin.isatty():
        if ask_all:
            print("✗ --ask cần terminal tương tác. Bỏ --ask hoặc chạy lệnh trong terminal thật.")
            sys.exit(1)
        print("✗ Thiếu --num-of-vid (-n). Ví dụ: ytb batch start -n 3 --type-of-vid long")
        sys.exit(1)

    print("╔══════════════════════════════════════════════╗")
    print("║         ytb batch start — thiết lập         ║")
    print("╚══════════════════════════════════════════════╝")

    # Số video
    if ask_all or args.num_of_vid is None:
        while True:
            default_hint = f", Enter = {args.num_of_vid}" if args.num_of_vid else ""
            raw = input(f"\nSố video cần viết kịch bản (ví dụ: 3{default_hint}): ").strip()
            if not raw and args.num_of_vid:
                break
            if raw.isdigit() and int(raw) > 0:
                args = argparse.Namespace(**{**vars(args), "num_of_vid": int(raw)})
                break
            print("  ✗ Nhập số nguyên dương.")

    if ask_all:
        print(f"\nLoại video:")
        print("  1) long  — video dài ngang, 10-30 phút")
        print("  2) short — Short dọc, 1-2 phút")
        current = "2" if args.type_of_vid == "short" else "1"
        raw = input(f"Chọn [1/2, Enter = hiện tại {args.type_of_vid}]: ").strip()
        raw = raw or current
        typ = "short" if raw == "2" else "long"
        args = argparse.Namespace(**{**vars(args), "type_of_vid": typ})

    # Yêu cầu / ý tưởng
    if ask_all or args.type_of_rules == "auto":
        print(f"\nYêu cầu / ý tưởng cho batch này:")
        print("  • Để trống = LLM tự chọn chủ đề theo ngách kênh (auto)")
        print("  • Hoặc mô tả cụ thể, ví dụ: \"chủ đề về thiên kiến nhận thức\"")
        current = "auto" if args.type_of_rules == "auto" else args.type_of_rules
        raw = input(f"Yêu cầu [Enter = {current}]: ").strip()
        if raw:
            args = argparse.Namespace(**{**vars(args), "type_of_rules": raw})

    # Resume
    if ask_all:
        print(f"\nBatch này là tiếp tục batch bị dừng giữa chừng (hết token)?")
        raw = input("Resume [y/N]: ").strip().lower()
        if raw == "y":
            args = argparse.Namespace(**{**vars(args), "resume": True})

    if ask_all:
        print(f"\nClear ledger cũ trước khi chọn ý tưởng mới?")
        raw = input("Clear ledger [y/N]: ").strip().lower()
        if raw == "y":
            args = argparse.Namespace(**{**vars(args), "clear_ledger": True})

    print()
    return args


def _clear_ledger_for_fresh_ideas(ledger_path: Path) -> Path | None:
    """Reset ledger history for fresh ideation, keeping a timestamped backup."""
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    if not ledger_path.exists():
        ledger_path.write_text(LEDGER_HEADER, encoding="utf-8")
        return None

    text = ledger_path.read_text(encoding="utf-8")
    if text.strip():
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = ledger_path.with_name(f"{ledger_path.stem}.backup.{stamp}{ledger_path.suffix}")
        backup_path.write_text(text, encoding="utf-8")
    else:
        backup_path = None
    ledger_path.write_text(LEDGER_HEADER, encoding="utf-8")
    return backup_path


def _json_from_llm(text: str) -> dict:
    """Parse structured LLM output, tolerating fenced JSON wrappers."""
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.strip("`").strip()
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
        raise


def _local_start_log_path() -> Path:
    PIPELINE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PIPELINE_LOG_DIR / f"ideation_{stamp}.log"


def _append_local_start_log(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(f"\n\n===== {title} =====\n")
        f.write(body.rstrip())
        f.write("\n")


class _ClaudeStartProvider:
    name = "claude"

    def __init__(self, model: str):
        self._model = model

    def is_available(self):
        return shutil.which(_cli().settings.claude_bin) is not None

    def model_name(self):
        return self._model

    async def complete(self, prompt: str, **_kwargs) -> str:
        cmd = build_claude_cmd(prompt, model=self._model)
        return await asyncio.to_thread(self._invoke, cmd)

    def _invoke(self, cmd: list[str]) -> str:
        result = subprocess.run(
            cmd,
            cwd=_cli().ROOT,
            capture_output=True,
            text=True,
            timeout=300,
            check=True,
        )
        return result.stdout


def _local_script_prompt(
    index: int,
    total: int,
    type_of_vid: str,
    type_of_rules: str,
    ledger_text: str,
    generated_summaries: list[str] | None = None,
) -> str:
    target = (
        '"video_type": "long", "target_minutes": 10-12 and 20-30 rich sections'
        if type_of_vid == "long"
        else '"video_type": "short", no target_minutes and enough narration for a 1-2 minute Short'
    )
    generated_summaries = generated_summaries or []
    topic = (
        "Pick a non-duplicate topic from the channel niche."
        if type_of_rules == "auto"
        else (
            "User idea is the primary constraint. Build this script around the exact idea, "
            f"without drifting to another topic: {type_of_rules}"
        )
    )
    blocked_titles = "\n".join(f"- {title}" for title in _ledger_topics(ledger_text)[-40:])
    generated = "\n".join(f"- {item}" for item in generated_summaries) or "- none yet"
    custom_rules = "" if type_of_rules == "auto" else (
        "\nCustom idea rules:\n"
        "- The user's idea overrides the default channel niche and old ledger topics.\n"
        "- Use the ledger ONLY as a blacklist of topics/titles to avoid, not as inspiration.\n"
        "- Current channel scope is sharing/knowledge, not entertainment. Do NOT write comedy, "
        "stickman/người que scenes, punchline structure, or gag narration for this channel.\n"
        "- Write a clear Vietnamese knowledge short: concrete everyday example, mechanism, "
        "application step, and grounded Pexels queries for real stock footage.\n"
    )
    return (
        "You are writing a Vietnamese YouTube script JSON for a local-first pipeline.\n"
        f"Video {index}/{total}. Type: {type_of_vid}. Requirement: {topic}\n"
        f"Length contract: {target}.\n"
        "This must be a NEW concept inside the current batch. Do not reuse any slug, title, "
        "topic, scene setup, or punchline already listed below.\n"
        f"{custom_rules}\n"
        "Already generated in this batch:\n"
        f"{generated}\n\n"
        "Blocked historical titles/topics:\n"
        f"{blocked_titles or '- none'}\n\n"
        "Return ONLY one JSON object with keys: slug, topic, title, description, tags, "
        "video_type, voice_profile, sections, compliance. video_type is only long or short. "
        "voice_profile is knowledge or inspiring. Each section needs time_goal, voiceover, "
        "visual_intent, pexels_query, caption, hook, transition, payoff, emphasis. "
        "Keep legacy narration equal to voiceover and broll equal to pexels_query for compatibility.\n"
        "compliance.passed must be true and include community/copyright/accuracy/"
        "advertiser/coppa/notes."
    )


def _repair_prompt(payload: dict, qa_output: dict | None, validation_error: str | None) -> str:
    issues = {
        "validation_error": validation_error,
        "qa": qa_output or {},
    }
    return (
        "Repair this Vietnamese YouTube script JSON for the local-first pipeline.\n"
        "Return ONLY the full corrected JSON object. Do not add markdown.\n"
        "Preserve the topic and core story unless a listed violation requires a narrow fix.\n"
        f"For Shorts without target_minutes, total narration MUST be {SHORT_MIN_CHARS}-{SHORT_MAX_CHARS} "
        "Vietnamese characters. Do not overshoot. Do not add greetings.\n"
        "Current channel scope is sharing/knowledge, not entertainment. Remove comedy, "
        "stickman/người que, punchline, and gag narration if present. Keep a concrete "
        "everyday example, mechanism, application step, and real-stock-footage Pexels queries.\n"
        "Required schema: slug, topic, title, description, tags, video_type, voice_profile, "
        "sections, compliance. video_type is only short or long. voice_profile is knowledge "
        "or inspiring. Each section needs time_goal, voiceover, visual_intent, pexels_query, "
        "caption, hook, transition, payoff, emphasis. Also include legacy narration=voiceover "
        "and broll=pexels_query. compliance.passed must be true.\n\n"
        f"Issues:\n{json.dumps(issues, ensure_ascii=False, indent=2)}\n\n"
        f"Current JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def _strip_short_greeting(text: str) -> str:
    patterns = (
        r"\s*Chào mừng các bạn đến với video mới của chúng tôi\.\s*",
        r"\s*Chào mừng các bạn[^.?!]*[.?!]\s*",
        r"^\s*Hôm nay,\s*chúng ta sẽ\s*",
    )
    cleaned = text.strip()
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def _trim_to_sentence(text: str, limit: int) -> str:
    text = _strip_short_greeting(text)
    if len(text) <= limit:
        return text
    cut = text[:limit].rstrip()
    boundary = max(cut.rfind("."), cut.rfind("!"), cut.rfind("?"))
    if boundary >= max(60, int(limit * 0.55)):
        return cut[: boundary + 1].strip()
    boundary = cut.rfind(" ")
    if boundary >= max(60, int(limit * 0.65)):
        cut = cut[:boundary].rstrip()
    return cut.rstrip(" ,;:") + "."


def _short_narration_chars(payload: dict) -> int:
    return sum(len(section.get("voiceover") or section.get("narration", "") or "")
               for section in payload.get("sections", []) or [])


def _normalize_short_narration(payload: dict) -> tuple[dict, str | None]:
    """Keep local Short scripts inside the hard length gate without another LLM hop."""
    if payload.get("target_minutes") is not None:
        return payload, None
    sections = [s for s in payload.get("sections", []) or [] if isinstance(s, dict)]
    if not sections:
        return payload, None

    changed = False
    for section in sections:
        narration = section.get("voiceover") or section.get("narration", "")
        if isinstance(narration, str):
            cleaned = _strip_short_greeting(narration)
            if cleaned != narration:
                section["voiceover"] = cleaned
                section["narration"] = cleaned
                changed = True

    total = _short_narration_chars(payload)
    if total > SHORT_MAX_CHARS:
        ratio = SHORT_TARGET_CHARS / total
        remaining = SHORT_TARGET_CHARS
        for idx, section in enumerate(sections):
            narration = str(section.get("voiceover") or section.get("narration", ""))
            left = len(sections) - idx
            budget = max(120, min(len(narration), remaining - 80 * (left - 1)))
            proportional = max(120, int(len(narration) * ratio))
            budget = min(budget, proportional)
            section["voiceover"] = _trim_to_sentence(narration, budget)
            section["narration"] = section["voiceover"]
            remaining -= len(section["voiceover"])
        changed = True
    elif total < SHORT_MIN_CHARS:
        needed = min(SHORT_TARGET_CHARS - total, SHORT_MAX_CHARS - total)
        idx = 0
        fillers = (
            " Ví dụ cụ thể: bạn mở laptop để làm việc, nhưng chỉ cần nhìn thấy một nhiệm vụ hơi khó là tay tự động với sang điện thoại.",
            " Cơ chế nằm ở chỗ não không né công việc, nó né cảm giác mơ hồ và nguy cơ làm sai trong vài giây đầu.",
            " Cách áp dụng là thu nhỏ bước đầu tiên đến mức không còn đáng sợ: chỉ mở file, viết một dòng nháp, rồi mới quyết định làm tiếp.",
        )
        while needed > 0 and sections:
            addition = fillers[idx % len(fillers)]
            if len(addition) > needed:
                addition = _trim_to_sentence(addition, needed)
            sections[idx % len(sections)]["voiceover"] = (
                str(sections[idx % len(sections)].get("voiceover") or sections[idx % len(sections)].get("narration", "")).rstrip() + addition
            ).strip()
            sections[idx % len(sections)]["narration"] = sections[idx % len(sections)]["voiceover"]
            needed -= len(addition)
            idx += 1
        changed = True

    if not changed:
        return payload, None
    total = _short_narration_chars(payload)
    return payload, f"normalized short narration to {total} chars"


async def _validate_or_repair_script(
    provider,
    payload: dict,
    script_path: Path,
    ledger_text: str,
    max_attempts: int = 3,
    log_path: Path | None = None,
    console_prefix: str = "",
    strict: bool = True,
) -> dict:
    """Write, validate, QA, and repair a local LLM script JSON with bounded retries."""
    qa = QAAgent()
    done_topics = _ledger_topics(ledger_text)
    current = dict(payload)
    last_validation_error: str | None = None
    last_qa_output: dict | None = None

    for attempt in range(1, max_attempts + 1):
        current, normalized_note = _normalize_short_narration(current)
        if normalized_note:
            if console_prefix:
                print(f"{console_prefix} normalize: {normalized_note}", flush=True)
            if log_path:
                _append_local_start_log(log_path, f"NORMALIZE {attempt}", normalized_note)
        if console_prefix:
            print(f"{console_prefix} validate: attempt {attempt}/{max_attempts}", flush=True)
        if log_path:
            _append_local_start_log(
                log_path,
                f"VALIDATION_ATTEMPT {attempt}",
                json.dumps(current, ensure_ascii=False, indent=2),
            )
        script_path.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            script = load_script(script_path)
            last_validation_error = None
        except Exception as exc:  # noqa: BLE001
            script = None
            last_validation_error = str(exc)
            if log_path:
                _append_local_start_log(log_path, f"VALIDATION_ERROR {attempt}", last_validation_error)

        if script is not None:
            result = await qa.run({"script": script, "done_topics": done_topics, "strict": strict})
            if result.status == AgentStatus.SUCCESS:
                last_qa_output = result.output
                if log_path:
                    _append_local_start_log(
                        log_path,
                        f"QA_RESULT {attempt}",
                        json.dumps(result.output, ensure_ascii=False, indent=2),
                    )
                if result.output and result.output.get("passed"):
                    return current
            else:
                last_qa_output = {"passed": False, "violations": [{"rule": "qa_agent", "detail": result.error}]}
                if log_path:
                    _append_local_start_log(
                        log_path,
                        f"QA_ERROR {attempt}",
                        json.dumps(last_qa_output, ensure_ascii=False, indent=2),
                    )

        if attempt == max_attempts:
            break

        if console_prefix:
            print(f"{console_prefix} repair: asking LLM to fix validation issues", flush=True)
        repair_prompt = _repair_prompt(current, last_qa_output, last_validation_error)
        if log_path:
            _append_local_start_log(log_path, f"REPAIR_PROMPT {attempt}", repair_prompt)
        repaired = await provider.complete(
            repair_prompt,
            system="Return strict JSON only. No markdown.",
            max_tokens=8192,
            temperature=0.2,
            json_output=True,
        )
        if log_path:
            _append_local_start_log(log_path, f"REPAIR_RESPONSE {attempt}", repaired)
        current = _json_from_llm(repaired)
        current["slug"] = script_path.stem

    if log_path:
        _append_local_start_log(
            log_path,
            "FINAL_FAILURE",
            f"validation={last_validation_error!r}\nqa={last_qa_output!r}",
        )
    raise SystemExit(
        "✗ LLM tạo script không qua QA sau "
        f"{max_attempts} lần. validation={last_validation_error!r} qa={last_qa_output!r}"
    )


def _ledger_topics(ledger_text: str) -> list[str]:
    topics: list[str] = []
    for line in ledger_text.splitlines():
        if not line.startswith("|"):
            continue
        cols = [part.strip() for part in line.strip("|").split("|")]
        if len(cols) >= 3 and cols[2] and cols[2].lower() != "tiêu đề":
            topics.append(cols[2])
    return topics


def _existing_queue_slugs(auto_state_path: Path) -> set[str]:
    if not auto_state_path.exists():
        return set()
    try:
        data = json.loads(auto_state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    slugs: set[str] = set()
    for batch in data.values():
        if not isinstance(batch, dict):
            continue
        for key in ("long_videos", "short_videos"):
            for item in batch.get(key, []) or []:
                slug = item.get("slug") if isinstance(item, dict) else None
                if slug:
                    slugs.add(str(slug))
    return slugs


def _ledger_slugs(ledger_text: str) -> set[str]:
    slugs: set[str] = set()
    for line in ledger_text.splitlines():
        if not line.startswith("|"):
            continue
        cols = [part.strip() for part in line.strip("|").split("|")]
        if len(cols) >= 2 and cols[1] and cols[1].lower() != "slug":
            slugs.add(cols[1])
    return slugs


def _unique_slug(base_slug: str, used_slugs: set[str], scripts_dir: Path) -> str:
    base = slugify(base_slug) or "video"
    candidate = base
    index = 2
    while candidate in used_slugs or (scripts_dir / f"{candidate}.json").exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _write_local_batch_item(script_path: Path, payload: dict, args: argparse.Namespace) -> None:
    cli = _cli()
    data = json.loads(cli.AUTO_STATE_PATH.read_text(encoding="utf-8")) if cli.AUTO_STATE_PATH.exists() else {}
    batch_key = sorted([k for k in data if k.startswith("shorts_funnel_batch_")])[-1:] or ["shorts_funnel_batch_local"]
    batch_key = batch_key[0]
    batch = data.setdefault(batch_key, {"long_videos": [], "short_videos": []})
    key = "long_videos" if args.type_of_vid == "long" else "short_videos"
    videos = batch.setdefault(key, [])
    if any(v.get("slug") == script_path.stem for v in videos if isinstance(v, dict)):
        raise SystemExit(f"✗ Trùng slug trong queue: {script_path.stem}. Dừng để tránh overwrite/rerun sai.")
    day = max([int(v.get("day", 0)) for v in videos] or [0]) + 1
    videos.append({
        "day": day,
        "slug": script_path.stem,
        "topic": payload.get("topic", payload.get("title", script_path.stem)),
        "orientation": "landscape" if args.type_of_vid == "long" else "portrait",
        "render_provider": "ai",
        "dry_run": cli.settings.dry_run,
        "publish_at": cli.settings.youtube_publish_at,
        "stage": "ideation",
        "status": "ok",
        "shorts_status": "queued",
    })
    cli.AUTO_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cli.AUTO_STATE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    cli.update_ledger(
        script_path.stem,
        payload.get("title", ""),
        "ideation",
        "ok",
        f"LLM script validated: {script_path}",
    )


async def _cmd_start_local(args: argparse.Namespace) -> None:
    cli = _cli()
    provider = getattr(args, "_provider", None) or get_llm_provider()
    strict_qa = getattr(args, "_strict_qa", getattr(provider, "name", "") == "claude")
    if not provider.is_available():
        raise SystemExit(
            f"✗ LLM provider `{provider.name}` chưa sẵn sàng. "
            f"Chạy `ytb batch doctor --local` hoặc cấu hình {cli.settings.ollama_url}."
        )

    if getattr(args, "clear_ledger", False):
        backup = _clear_ledger_for_fresh_ideas(cli.LEDGER_PATH)
        if backup:
            print(f"✓ Đã clear ledger cũ. Backup: {backup}", flush=True)
        else:
            print(f"✓ Đã tạo ledger sạch: {cli.LEDGER_PATH}", flush=True)

    ledger_text = cli.LEDGER_PATH.read_text(encoding="utf-8") if cli.LEDGER_PATH.exists() else ""
    scripts_dir = cli.ROOT / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    log_path = _local_start_log_path()
    used_slugs = _ledger_slugs(ledger_text) | _existing_queue_slugs(cli.AUTO_STATE_PATH)
    generated_summaries: list[str] = []

    written: list[str] = []
    print(f"▶ Ideation: {args.num_of_vid} video ({args.type_of_vid}) bằng {provider.name}/{provider.model_name()}", flush=True)
    print(f"  ý tưởng: {args.type_of_rules}", flush=True)
    print(f"  log chi tiết: {log_path}", flush=True)
    for i in range(1, args.num_of_vid + 1):
        prefix = f"[{i}/{args.num_of_vid}]"
        prompt = _local_script_prompt(
            i,
            args.num_of_vid,
            args.type_of_vid,
            args.type_of_rules,
            ledger_text,
            generated_summaries,
        )
        print(f"{prefix} prompt: preparing request", flush=True)
        _append_local_start_log(log_path, f"PROMPT {i}", prompt)
        print(f"{prefix} LLM: generating script JSON...", flush=True)
        text = await provider.complete(
            prompt,
            system="Return strict JSON only. No markdown.",
            max_tokens=8192,
            temperature=0.7,
            json_output=True,
        )
        _append_local_start_log(log_path, f"RAW_LLM_RESPONSE {i}", text)
        print(f"{prefix} LLM: response received", flush=True)
        try:
            payload = _json_from_llm(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"✗ LLM không trả JSON hợp lệ: {exc}") from exc
        base_slug = slugify(payload.get("slug") or payload.get("title") or payload.get("topic") or f"video-{i}")
        slug = _unique_slug(base_slug, used_slugs, scripts_dir)
        if slug != base_slug:
            print(f"{prefix} slug: adjusted duplicate `{base_slug}` -> `{slug}`", flush=True)
            _append_local_start_log(log_path, f"SLUG_ADJUSTED {i}", f"{base_slug} -> {slug}")
        payload["slug"] = slug
        script_path = scripts_dir / f"{slug}.json"
        payload = await _validate_or_repair_script(
            provider,
            payload,
            script_path,
            ledger_text,
            log_path=log_path,
            console_prefix=prefix,
            strict=strict_qa,
        )
        _write_local_batch_item(script_path, payload, args)
        ledger_text += f"\n| local | {slug} | {payload.get('title', '')} | ideation | ok | LLM |\n"
        used_slugs.add(slug)
        generated_summaries.append(f"{slug} | {payload.get('title', '')} | {payload.get('topic', '')}")
        written.append(slug)
        print(f"{prefix} queued: {slug}", flush=True)

    print("✓ Ideation xong:")
    for slug in written:
        print(f"  - {slug}")


def cmd_start(args: argparse.Namespace) -> None:
    cli = _cli()
    if getattr(args, "ask", False) or args.num_of_vid is None:
        args = cli._prompt_start_interactive(args)

    if getattr(args, "local", False) and getattr(args, "cloud", False):
        raise SystemExit("✗ Chọn một trong hai: --local hoặc --cloud, không dùng cùng lúc.")
    if getattr(args, "clear_ledger", False):
        if getattr(args, "resume", False):
            raise SystemExit("✗ --clear-ledger không dùng cùng --resume; resume cần ledger cũ để tránh chạy nhầm.")

    if getattr(args, "local", False):
        asyncio.run(_cmd_start_local(args))
        return

    if not getattr(args, "cloud", False):
        configured_provider = get_llm_provider()
        if getattr(configured_provider, "name", "") != "claude":
            setattr(args, "_provider", configured_provider)
            asyncio.run(_cmd_start_local(args))
            return
        try:
            setattr(args, "_provider", _ClaudeStartProvider(CLAUDE_HAIKU_MODEL))
            setattr(args, "_strict_qa", True)
            asyncio.run(_cmd_start_local(args))
            return
        except SystemExit as exc:
            print(f"⚠ Claude Haiku chưa qua QA: {exc}. Thử lại bằng Sonnet...", flush=True)
            setattr(args, "_provider", _ClaudeStartProvider(CLAUDE_SONNET_MODEL))
            setattr(args, "_strict_qa", True)
            asyncio.run(_cmd_start_local(args))
            return

    if args.resume:
        existing_count, existing_slugs = cli._count_pending_ideation(args.type_of_vid)
        remaining = args.num_of_vid - existing_count
        if remaining <= 0:
            print(
                f"✓ Đã có {existing_count} script pending ({args.type_of_vid}) trong queue — "
                f"không cần viết thêm. Chạy `ytb batch run --loop` để sản xuất."
            )
            return
        print(
            f"▶ Resume: đã có {existing_count} script, cần thêm {remaining} "
            f"(tổng mục tiêu {args.num_of_vid})."
        )
        prompt = cli._build_resume_prompt(remaining, args.type_of_vid, args.type_of_rules, existing_slugs)
        action_label = f"viết thêm {remaining} video ({args.type_of_vid})"
    else:
        prompt = cli._build_start_prompt(args.num_of_vid, args.type_of_vid, args.type_of_rules)
        action_label = f"sáng tạo {args.num_of_vid} video ({args.type_of_vid})"

    cmd = cli.build_claude_cmd(prompt) + ["--output-format", "stream-json", "--verbose"]
    print(f"▶️  Gọi Claude {action_label}...")
    if getattr(args, "clear_ledger", False):
        backup = _clear_ledger_for_fresh_ideas(cli.LEDGER_PATH)
        if backup:
            print(f"✓ Đã clear ledger cũ. Backup: {backup}", flush=True)
        else:
            print(f"✓ Đã tạo ledger sạch: {cli.LEDGER_PATH}", flush=True)
    try:
        proc = cli.subprocess.Popen(cmd, cwd=cli.ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        print(f"✗ Không tìm thấy `{cli.settings.claude_bin}`. Đặt CLAUDE_BIN trong .env.")
        sys.exit(1)

    output_lines: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            print(raw, flush=True)
            output_lines.append(raw)
            continue
        # stream-json: assistant text delta
        if obj.get("type") == "assistant":
            for block in obj.get("message", {}).get("content", []):
                if block.get("type") == "text":
                    text = block["text"]
                    print(text, end="", flush=True)
                    output_lines.append(text)
        # kết quả cuối
        elif obj.get("type") == "result":
            result_text = obj.get("result", "")
            if result_text:
                print(result_text, flush=True)
                output_lines.append(result_text)

    proc.wait()
    output = "\n".join(output_lines)
    if proc.returncode != 0:
        stderr = (proc.stderr.read() if proc.stderr else "")[-500:]
        cli.emit_warning(f"ytb batch start lỗi (code {proc.returncode}): {stderr}")
        sys.exit(1)
    print("\n✓ Xong phần sáng tạo — chạy `ytb batch status` để xem queue, rồi "
          "`ytb batch run --loop` để sản xuất.")
