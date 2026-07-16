"""`ytb batch start` — gọi LLM làm phần SÁNG TẠO (ideation + viết kịch bản).

File này chỉ giữ entrypoint `cmd_start` + luồng điều phối; logic cụ thể đã tách:
  - ideation_prompts.py    — prompt templates (versioned artifact)
  - ideation_script_fix.py — normalize/validate/QA-repair script JSON
  - ideation_state.py      — ledger/auto_state.json/slug I/O
Mọi tên cũ (`_build_start_prompt`, `_normalize_short_narration`, ...) được
re-export bên dưới để interface `ideation_cmd.<tên>`/`batch_cli.<tên>` (kể cả
monkeypatch trong test) không đổi.

Xem docstring đầu queue_manager.py về việc đọc hằng số/hàm có thể patch qua
`_cli()` tại thời điểm gọi.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from ..claude_cli import build_claude_cmd
from ..ideation.series import slugify
from ..providers.registry import get_llm_provider
from .ideation_prompts import (
    SCRIPT_GENERATION_SYSTEM_PROMPT,
    SHORT_MAX_CHARS,
    SHORT_MIN_CHARS,
    SHORT_TARGET_CHARS,
    build_resume_prompt,
    build_start_prompt,
    ledger_topics,
    local_script_prompt,
    repair_prompt,
)
from .ideation_script_fix import (
    append_local_start_log,
    json_from_llm,
    normalize_short_narration,
    short_narration_chars,
    strip_short_greeting,
    trim_to_sentence,
    validate_or_repair_script,
)
from .ideation_state import (
    LEDGER_HEADER,
    clear_ledger_for_fresh_ideas,
    count_pending_ideation,
    existing_queue_slugs,
    ledger_slugs,
    unique_slug,
    write_local_batch_item,
)
from .queue_manager import PIPELINE_LOG_DIR

# Re-export tên cũ — giữ backward compat cho test/caller ngoài.
_build_resume_prompt = build_resume_prompt
_build_start_prompt = build_start_prompt
_local_script_prompt = local_script_prompt
_repair_prompt = repair_prompt
_ledger_topics = ledger_topics
_json_from_llm = json_from_llm
_append_local_start_log = append_local_start_log
_strip_short_greeting = strip_short_greeting
_trim_to_sentence = trim_to_sentence
_short_narration_chars = short_narration_chars
_normalize_short_narration = normalize_short_narration
_validate_or_repair_script = validate_or_repair_script
_count_pending_ideation = count_pending_ideation
_clear_ledger_for_fresh_ideas = clear_ledger_for_fresh_ideas
_ledger_slugs = ledger_slugs
_existing_queue_slugs = existing_queue_slugs
_unique_slug = unique_slug
_write_local_batch_item = write_local_batch_item


def _cli():
    from . import batch_cli

    return batch_cli


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
        print("  1) long  — video dài ngang, 12-15 phút")
        print("  2) short — Short dọc, 1-1.5 phút")
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


def _local_start_log_path() -> Path:
    PIPELINE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return PIPELINE_LOG_DIR / f"ideation_{stamp}.log"


def _with_system_contract(prompt: str, system: str | None) -> str:
    """Serialize a system contract into CLI-only providers' single prompt slot."""
    contract = (system or "").strip()
    return f"{contract}\n\nUser task:\n{prompt}" if contract else prompt


class _ClaudeStartProvider:
    name = "claude"

    def __init__(self, model: str | None = None):
        self._model = model

    def is_available(self):
        return shutil.which(_cli().settings.claude_bin) is not None

    def model_name(self):
        return self._model or "default"

    async def complete(self, prompt: str, **kwargs) -> str:
        full_prompt = _with_system_contract(prompt, kwargs.get("system"))
        cmd = build_claude_cmd(full_prompt, **({"model": self._model} if self._model else {}))
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


class _CodexStartProvider:
    """Codex CLI provider cho structured script generation."""

    name = "codex"

    def __init__(self, model: str | None = None):
        self._model = model

    def is_available(self):
        return shutil.which(_cli().settings.codex_bin) is not None

    def model_name(self):
        return self._model or "default"

    async def complete(self, prompt: str, **kwargs) -> str:
        full_prompt = _with_system_contract(prompt, kwargs.get("system"))
        cmd = [
            _cli().settings.codex_bin,
            "exec",
            "--full-auto",
        ]
        if self._model:
            cmd += ["--model", self._model]
        cmd.append(full_prompt)
        return await asyncio.to_thread(self._invoke, cmd)

    def _invoke(self, cmd: list[str]) -> str:
        with tempfile.NamedTemporaryFile(prefix="ytb-codex-", suffix=".json", delete=False) as tmp:
            output_path = Path(tmp.name)
        command = [*cmd[:-1], "--output-last-message", str(output_path), cmd[-1]]
        try:
            result = subprocess.run(
                command,
                cwd=_cli().ROOT,
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
            response = output_path.read_text(encoding="utf-8").strip()
            return response or result.stdout
        finally:
            output_path.unlink(missing_ok=True)


def _configured_script_provider(name: str):
    if name == "claude":
        return _ClaudeStartProvider()
    if name == "codex":
        return _CodexStartProvider()
    return get_llm_provider(name)


async def _cmd_start_local(args: argparse.Namespace) -> None:
    from ..analytics.feedback import AnalyticsStore
    cli = _cli()
    provider = getattr(args, "_provider", None) or get_llm_provider()
    # Quality gates are provider-independent: a valid script must meet the
    # same channel standard whether it was drafted by Claude or Codex.
    strict_qa = getattr(args, "_strict_qa", True)
    if not provider.is_available():
        raise SystemExit(
            f"✗ LLM provider `{provider.name}` chưa sẵn sàng. "
            f"Chạy `ytb batch doctor --local` hoặc cấu hình {cli.settings.ollama_url}."
        )

    if getattr(args, "clear_ledger", False):
        backup = clear_ledger_for_fresh_ideas(cli.LEDGER_PATH)
        if backup:
            print(f"✓ Đã clear ledger cũ. Backup: {backup}", flush=True)
        else:
            print(f"✓ Đã tạo ledger sạch: {cli.LEDGER_PATH}", flush=True)

    ledger_text = cli.LEDGER_PATH.read_text(encoding="utf-8") if cli.LEDGER_PATH.exists() else ""
    scripts_dir = cli.ROOT / "scripts"
    scripts_dir.mkdir(parents=True, exist_ok=True)
    log_path = _local_start_log_path()
    used_slugs = ledger_slugs(ledger_text) | existing_queue_slugs(cli.AUTO_STATE_PATH)
    generated_summaries: list[str] = []
    analytics_feedback = AnalyticsStore().feedback_summary()
    funnel = {
        "long_form_slug": str(getattr(args, "long_form_slug", "") or "").strip(),
        "playlist": str(getattr(args, "playlist", "") or "").strip(),
        "cta_target": str(getattr(args, "cta_target", "") or "").strip(),
    }

    written: list[str] = []
    print(f"▶ Ideation: {args.num_of_vid} video ({args.type_of_vid}) bằng {provider.name}/{provider.model_name()}", flush=True)
    print(f"  ý tưởng: {args.type_of_rules}", flush=True)
    print(f"  log chi tiết: {log_path}", flush=True)
    for i in range(1, args.num_of_vid + 1):
        prefix = f"[{i}/{args.num_of_vid}]"
        prompt = local_script_prompt(
            i,
            args.num_of_vid,
            args.type_of_vid,
            args.type_of_rules,
            ledger_text,
            generated_summaries,
            analytics_feedback,
            funnel,
        )
        print(f"{prefix} prompt: preparing request", flush=True)
        append_local_start_log(log_path, f"PROMPT {i}", prompt)
        print(f"{prefix} LLM: generating script JSON...", flush=True)
        text = await provider.complete(
            prompt,
            system=SCRIPT_GENERATION_SYSTEM_PROMPT,
            max_tokens=8192,
            temperature=0.7,
            json_output=True,
        )
        append_local_start_log(log_path, f"RAW_LLM_RESPONSE {i}", text)
        print(f"{prefix} LLM: response received", flush=True)
        try:
            payload = json_from_llm(text)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"✗ LLM không trả JSON hợp lệ: {exc}") from exc
        base_slug = slugify(payload.get("slug") or payload.get("title") or payload.get("topic") or f"video-{i}")
        slug = unique_slug(base_slug, used_slugs, scripts_dir)
        if slug != base_slug:
            print(f"{prefix} slug: adjusted duplicate `{base_slug}` -> `{slug}`", flush=True)
            append_local_start_log(log_path, f"SLUG_ADJUSTED {i}", f"{base_slug} -> {slug}")
        payload["slug"] = slug
        script_path = scripts_dir / f"{slug}.json"
        payload = await validate_or_repair_script(
            provider,
            payload,
            script_path,
            ledger_text,
            log_path=log_path,
            console_prefix=prefix,
            strict=strict_qa,
            semantic_history=generated_summaries,
        )
        write_local_batch_item(script_path, payload, args)
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
        raise SystemExit(
            "✗ Luồng Ollama sinh kịch bản đã bị xoá. Dùng `--llm claude` hoặc `--llm codex`."
        )

    if not getattr(args, "cloud", False):
        requested_provider = getattr(args, "llm_provider", None)
        if requested_provider in {"claude", "codex"}:
            setattr(args, "_provider", _configured_script_provider(requested_provider))
            setattr(args, "_strict_qa", True)
            asyncio.run(_cmd_start_local(args))
            return
        if _cli().settings.llm_provider == "codex":
            setattr(args, "_provider", _CodexStartProvider())
            setattr(args, "_strict_qa", True)
            asyncio.run(_cmd_start_local(args))
            return
        if _cli().settings.llm_provider == "ollama":
            raise SystemExit("✗ Chỉ hỗ trợ Claude hoặc Codex để sinh kịch bản; Ollama đã bị xoá.")
        configured_provider = get_llm_provider()
        if getattr(configured_provider, "name", "") != "claude":
            setattr(args, "_provider", configured_provider)
            asyncio.run(_cmd_start_local(args))
            return
        # Không ép Haiku/Sonnet: để CLI dùng model mặc định đã cấu hình trong
        # Claude Code. Lỗi QA phải được báo nguyên nhân thật, không bị che bởi
        # một lần gọi model thứ hai với tiêu chí khác.
        setattr(args, "_provider", _ClaudeStartProvider())
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
        backup = clear_ledger_for_fresh_ideas(cli.LEDGER_PATH)
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
