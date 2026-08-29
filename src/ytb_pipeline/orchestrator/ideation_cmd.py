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
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

# A 12-minute Vietnamese Long needs materially more than 8k output tokens.
# One sufficiently-sized first response is cheaper and more reliable than a
# truncated draft followed by repair calls. Operators may lower this in tests.
SCRIPT_LLM_MAX_TOKENS = int(os.environ.get("IDEATION_LLM_MAX_TOKENS", "14000"))

from ..ideation.series import slugify
from ..content_profiles import load_content_profile
from ..providers.registry import get_llm_provider
from .ideation_prompts import (
    SHORT_MAX_CHARS,
    SHORT_MIN_CHARS,
    SHORT_TARGET_CHARS,
    build_resume_prompt,
    build_start_prompt,
    ledger_topics,
    is_personal_finance_psychology_request,
    local_script_prompt,
    repair_prompt,
    script_generation_system_prompt,
)
from .ideation_script_fix import (
    IdeationQualityFailure,
    append_local_start_log,
    json_from_llm,
    normalize_short_narration,
    short_narration_chars,
    strip_short_greeting,
    trim_to_sentence,
    validate_or_repair_script,
)
from ..ideation.wording_engine import process_and_sanitize
from ..ideation.generation_schema import script_generation_schema
from .ideation_error_engine import record_ideation_failure
from .external_long import completed_external_long_source
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


def load_short_source_long_context(script_path: Path, long_slug: str) -> dict:
    """Build a compact, traceable bank of useful open-loop segments from a Long."""
    try:
        payload = json.loads(script_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Không đọc được kịch bản Long nguồn {long_slug}: {exc}") from exc
    sections = payload.get("sections")
    if not isinstance(sections, list):
        raise ValueError(f"Kịch bản Long nguồn {long_slug} không có sections hợp lệ.")

    candidates: list[dict] = []
    for index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        excerpt = str(section.get("voiceover") or section.get("narration") or "").strip()
        if not excerpt:
            continue
        purpose = str(section.get("purpose", "")).strip()
        normalized_purpose = purpose.casefold()
        if any(word in normalized_purpose for word in ("mở đầu", "hook", "retention", "kết thúc", "cầu nối")):
            continue
        score = sum(weight for word, weight in (
            ("giải thích", 3), ("explanation", 3), ("dấu hiệu", 3), ("cạm bẫy", 3),
            ("khác biệt", 2), ("bằng chứng", 2), ("evidence", 2), ("nguồn gốc", 2),
            ("thực hành", 2), ("application", 2), ("ví dụ", 1), ("example", 1),
        ) if word in normalized_purpose)
        candidates.append({"section_index": index, "purpose": purpose, "excerpt": excerpt, "score": score})
    candidates.sort(key=lambda item: (-item["score"], item["section_index"]))
    selected = [{key: item[key] for key in ("section_index", "purpose", "excerpt")} for item in candidates[:3]]
    if not selected:
        raise ValueError(f"Kịch bản Long nguồn {long_slug} không có đoạn phù hợp để làm Short.")
    evidence_register = payload.get("evidence_register")
    return {
        "slug": long_slug,
        "title": str(payload.get("title", "")).strip(),
        "topic": str(payload.get("topic", "")).strip(),
        "candidates": selected,
        "evidence_register": evidence_register if isinstance(evidence_register, list) else [],
    }


def short_source_dedup_exemptions(
    *, replacement_slug: str = "", source_long_context: dict | None = None,
) -> tuple[str, ...]:
    """Exclude only the verified derivative source from self-dedup.

    A Short is intentionally semantically close to its Long source.  The
    source context is loaded from that concrete Long script before generation,
    so its slug/title/topic are safe exemptions; unrelated ledger entries keep
    the normal exact and semantic duplicate checks.
    """
    values = [replacement_slug]
    if source_long_context is not None:
        values.extend(
            str(source_long_context.get(field) or "").strip()
            for field in ("slug", "title", "topic")
        )
    return tuple(dict.fromkeys(value for value in values if value))


def resolve_short_source_long_path(
    scripts_dir: Path, long_slug: str, *, allow_external_long: bool = False
) -> Path:
    """Resolve an active Long, or an explicitly allowed archived completed Long."""
    active_path = scripts_dir / f"{long_slug}.json"
    if active_path.exists():
        return active_path
    if allow_external_long:
        archived_path = completed_external_long_source(
            scripts_dir / "archive", long_slug, _cli().done_slugs()
        )
        if archived_path is not None:
            return archived_path
        raise SystemExit(f"✗ Long external '{long_slug}' cần done|ok và source archive Long hợp lệ.")
    raise SystemExit("✗ --long-form-slug phải trỏ tới Long đã có trong cùng --batch-key.")


def available_short_source_context(source_long_context: dict, used_section_indexes: set[int]) -> dict:
    """Return only source segments not already assigned to another Short."""
    candidates = [
        item for item in source_long_context.get("candidates", [])
        if item.get("section_index") not in used_section_indexes
    ]
    if not candidates:
        raise ValueError(
            f"Long nguồn {source_long_context.get('slug', '')} không còn phân đoạn khác cho Short tiếp theo."
        )
    return {**source_long_context, "candidates": candidates}


def used_short_source_section_indexes(
    batch: dict, *, long_slug: str, replacement_slugs: set[str] | None = None,
) -> set[int]:
    """Reserve sources used by other Shorts, not the slot being replaced."""
    replaced = replacement_slugs or set()
    return {
        item["source_section_index"]
        for item in batch.get("short_videos", [])
        if isinstance(item, dict)
        and item.get("slug") not in replaced
        and item.get("long_form_slug") == long_slug
        and isinstance(item.get("source_section_index"), int)
    }


def preassign_short_source_context(source_long_context: dict) -> dict:
    """Limit one generation to one auditable Long excerpt.

    A source choice is workflow input, not model-authored metadata.  Giving
    the model one candidate removes ambiguous provenance while preserving the
    existing no-reuse rule in ``available_short_source_context``.
    """
    candidates = source_long_context.get("candidates", [])
    if not candidates:
        raise ValueError("Long nguồn không còn candidate hợp lệ cho Short.")
    return {**source_long_context, "candidates": [candidates[0]]}


def attach_preassigned_short_source_provenance(payload: dict, source_long_context: dict) -> dict:
    """Attach only the provenance selected before the LLM request.

    Missing metadata can be completed from the declared candidate; conflicting
    metadata is a hard failure so a model can never silently point a Short at
    another Long section.
    """
    candidates = source_long_context.get("candidates", [])
    if len(candidates) != 1 or not isinstance(candidates[0], dict):
        raise ValueError("Source provenance cần đúng một candidate đã chọn.")
    strategy_raw = payload.get("strategy")
    if not isinstance(strategy_raw, dict):
        return dict(payload)
    candidate = candidates[0]
    expected = {
        "source_long_slug": source_long_context.get("slug", ""),
        "source_section_index": candidate.get("section_index"),
        "source_excerpt": candidate.get("excerpt", ""),
    }
    strategy = dict(strategy_raw)
    for field, value in expected.items():
        supplied = strategy.get(field)
        if supplied not in (None, "", value):
            raise ValueError(f"Source provenance mâu thuẫn ở {field}.")
        strategy[field] = value
    return {**payload, "strategy": strategy}


def reserve_invalid_json_regeneration(attempts: dict[int, int], candidate_index: int) -> bool:
    """Spend the one allowed fresh generation for this candidate, if unused."""
    used = attempts.get(candidate_index, 0)
    if used >= 1:
        return False
    attempts[candidate_index] = used + 1
    return True

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


def _validate_short_generation_request(args: argparse.Namespace) -> None:
    """Fail before an LLM call when a new Short cannot enter the v1 funnel."""
    if getattr(args, "type_of_vid", "") != "short":
        return
    profile = getattr(args, "_content_profile", None)
    if profile is not None and not profile.content_rules.require_short_source_trace:
        return
    required = {
        "batch-key": str(getattr(args, "batch_key", "") or "").strip(),
        "long-form-slug": str(getattr(args, "long_form_slug", "") or "").strip(),
        "playlist": str(getattr(args, "playlist", "") or "").strip(),
        "cta-target": str(getattr(args, "cta_target", "") or "").strip(),
    }
    if any(not value for value in required.values()):
        raise SystemExit(
            "✗ Short strategy-v1 cần --batch-key, --long-form-slug, --playlist và --cta-target "
            "trước khi gọi LLM."
        )
    if not required["batch-key"].startswith("shorts_funnel_batch_"):
        raise SystemExit("✗ --batch-key của Short phải bắt đầu bằng 'shorts_funnel_batch_'.")
    if required["cta-target"] != required["long-form-slug"]:
        raise SystemExit("✗ --cta-target của Short phải khớp --long-form-slug.")
    state_path = _cli().AUTO_STATE_PATH
    try:
        batch = json.loads(state_path.read_text(encoding="utf-8")).get(required["batch-key"], {})
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"✗ Không đọc được batch Short strategy-v1: {exc}") from exc
    long_slugs = {
        str(item.get("slug", ""))
        for item in batch.get("long_videos", [])
        if isinstance(item, dict)
    }
    external_completed_long = False
    if bool(getattr(args, "allow_external_long", False)):
        external_completed_long = completed_external_long_source(
            _cli().ROOT / "scripts" / "archive",
            required["long-form-slug"],
            _cli().done_slugs(),
        ) is not None
    if required["long-form-slug"] not in long_slugs and not external_completed_long:
        raise SystemExit("✗ --long-form-slug phải trỏ tới Long đã có trong cùng --batch-key.")


def _configured_script_provider(name: str):
    if name != "xkiro":
        raise ValueError(
            "Ideation chỉ hỗ trợ xkiro/DeepSeek V4 Pro; "
            "không có fallback sang Codex hoặc Claude."
        )
    return get_llm_provider("xkiro")


async def _cmd_start_local(args: argparse.Namespace) -> None:
    from ..analytics.feedback import AnalyticsStore
    cli = _cli()
    provider = getattr(args, "_provider", None) or get_llm_provider()
    content_profile = getattr(args, "_content_profile", None) or load_content_profile(
        getattr(args, "profile_id", None)
    )
    if not content_profile.supports_generation(args.type_of_vid):
        raise SystemExit(
            f"✗ Profile '{content_profile.profile_id}' không cho sinh {args.type_of_vid} mới."
        )
    generation_profile = (
        content_profile if getattr(args, "_profile_scoped", False) else None
    )
    # Quality gates are provider-independent: a valid script must meet the
    # same channel standard whether it was drafted by Claude or Codex.
    strict_qa = getattr(args, "_strict_qa", True)
    if not provider.is_available():
        raise SystemExit(
            f"✗ LLM provider `{provider.name}` chưa sẵn sàng. "
            "Chạy `ytb batch doctor --local` hoặc kiểm tra XKIRO_API_KEY/"
            "`claude`/`codex` CLI trong PATH."
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
    replacement_slugs = [str(slug).strip() for slug in getattr(args, "replace_slug", []) or []]
    source_long_context = None
    used_source_section_indexes: set[int] = set()
    if args.type_of_vid == "short" and content_profile.content_rules.require_short_source_trace:
        source_long_context = load_short_source_long_context(
            resolve_short_source_long_path(
                scripts_dir, funnel["long_form_slug"],
                allow_external_long=bool(getattr(args, "allow_external_long", False)),
            ),
            funnel["long_form_slug"],
        )
        state = json.loads(cli.AUTO_STATE_PATH.read_text(encoding="utf-8"))
        batch = state.get(str(getattr(args, "batch_key", "")), {})
        used_source_section_indexes = used_short_source_section_indexes(
            batch,
            long_slug=funnel["long_form_slug"],
            replacement_slugs=set(replacement_slugs),
        )

    if replacement_slugs and (len(replacement_slugs) != args.num_of_vid or not getattr(args, "batch_key", "")):
        raise SystemExit("✗ --replace-slug cần đúng một slug cho mỗi video và bắt buộc có --batch-key.")
    requested_count = args.num_of_vid
    if getattr(args, "resume", False):
        existing_count, existing_slugs = count_pending_ideation(
            args.type_of_vid,
            cli.AUTO_STATE_PATH,
            batch_key=str(getattr(args, "batch_key", "") or ""),
        )
        requested_count = max(0, args.num_of_vid - existing_count)
        if requested_count == 0:
            print(f"✓ Batch đã có {existing_count}/{args.num_of_vid} script {args.type_of_vid}; không cần sinh thêm.")
            return
        print(f"▶ Resume: đã có {existing_count}/{args.num_of_vid}, sinh thêm {requested_count}.", flush=True)
        generated_summaries.extend(existing_slugs)
    written: list[str] = []
    print(f"▶ Ideation: {requested_count} video ({args.type_of_vid}) bằng {provider.name}/{provider.model_name()}", flush=True)
    print(f"  ý tưởng: {args.type_of_rules}", flush=True)
    print(f"  log chi tiết: {log_path}", flush=True)
    rejected_candidates = 0
    invalid_json_regenerations: dict[int, int] = {}
    # The generator must satisfy deterministic contracts in its first response.
    # Do not spend cloud tokens in automatic repair/candidate loops; preserve
    # the rejection evidence for an intentional editorial retry instead.
    max_rejected_candidates = 1
    i = 1
    while i <= requested_count:
        prefix = f"[{i}/{requested_count}]"
        available_source_long_context = (
            available_short_source_context(source_long_context, used_source_section_indexes)
            if source_long_context is not None else None
        )
        if available_source_long_context is not None:
            available_source_long_context = preassign_short_source_context(
                available_source_long_context
            )
        prompt = local_script_prompt(
            i,
            requested_count,
            args.type_of_vid,
            args.type_of_rules,
            ledger_text,
            generated_summaries,
            analytics_feedback,
            funnel,
            available_source_long_context,
            content_profile=generation_profile,
        )
        print(f"{prefix} prompt: preparing request", flush=True)
        append_local_start_log(log_path, f"PROMPT {i}", prompt)
        print(f"{prefix} LLM: generating script JSON...", flush=True)
        text = await provider.complete(
            prompt,
            system=script_generation_system_prompt(
                generation_profile, video_type=args.type_of_vid
            ),
            max_tokens=SCRIPT_LLM_MAX_TOKENS,
            temperature=0.2,
            json_output=True,
            response_schema=script_generation_schema(
                args.type_of_vid, content_profile=generation_profile
            ),
        )
        append_local_start_log(log_path, f"RAW_LLM_RESPONSE {i}", text)
        print(f"{prefix} LLM: response received", flush=True)
        try:
            # Layer 2: deterministic wording/JSON/slug sanitizer runs directly
            # after Qwen and before validate_or_repair_script/QA.  It never
            # spends an additional LLM call.
            payload = process_and_sanitize(text)
            if generation_profile is not None:
                payload["profile_id"] = generation_profile.profile_id
                payload["profile_version"] = generation_profile.version
            if available_source_long_context is not None:
                payload = attach_preassigned_short_source_provenance(
                    payload, available_source_long_context
                )
        except (ValueError, json.JSONDecodeError) as exc:
            # A truncated/malformed object cannot be repaired deterministically.
            # Preserve the exact response and allow one full fresh generation;
            # this is cheaper than a repair conversation and never promotes a
            # partial narration into the queue.
            archive_dir = cli.ROOT / "assets" / "script_revisions" / "failed_ideation"
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = archive_dir / f"candidate_{i}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.raw.txt"
            archive_path.write_text(text, encoding="utf-8")
            error_text = f"LLM không trả JSON hợp lệ: {exc}"
            record_ideation_failure(
                cli.ROOT / "assets" / "quality_reports" / "ideation_errors.jsonl",
                script_name=f"candidate_{i}.json",
                attempt=invalid_json_regenerations.get(i, 0) + 1,
                validation_error=error_text,
                qa=None,
            )
            append_local_start_log(
                log_path, "INVALID_JSON_ARCHIVED",
                f"archive={archive_path}; error={error_text}",
            )
            if not reserve_invalid_json_regeneration(invalid_json_regenerations, i):
                raise SystemExit(
                    f"✗ LLM không trả JSON hợp lệ sau 1 lần sinh lại. Bản lỗi: {archive_path}"
                ) from exc
            print(f"{prefix} JSON lỗi; đã lưu bản lỗi và sinh lại đúng 1 lần.", flush=True)
            continue
        replacement_slug = replacement_slugs[i - 1] if replacement_slugs else ""
        base_slug = slugify(payload.get("slug") or payload.get("title") or payload.get("topic") or f"video-{i}")
        slug = replacement_slug or unique_slug(base_slug, used_slugs, scripts_dir)
        if not replacement_slug and slug != base_slug:
            print(f"{prefix} slug: adjusted duplicate `{base_slug}` -> `{slug}`", flush=True)
            append_local_start_log(log_path, f"SLUG_ADJUSTED {i}", f"{base_slug} -> {slug}")
        payload["slug"] = slug
        script_path = scripts_dir / f"{slug}.json"
        if replacement_slug and script_path.exists():
            archive_dir = cli.ROOT / "assets" / "script_revisions" / slug
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = archive_dir / f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            shutil.copy2(script_path, archive_path)
            setattr(args, "_replacement_archive", str(archive_path))
        else:
            setattr(args, "_replacement_archive", "")
        setattr(args, "replace_slug", replacement_slug)
        try:
            payload = await validate_or_repair_script(
                provider,
                payload,
                script_path,
                ledger_text,
                log_path=log_path,
                console_prefix=prefix,
                strict=strict_qa,
                semantic_history=generated_summaries,
                expected_video_type=args.type_of_vid,
                requires_financial_evidence=is_personal_finance_psychology_request(
                    args.type_of_rules
                ),
                source_long_context=available_source_long_context,
                exempt_slugs=short_source_dedup_exemptions(
                    replacement_slug=replacement_slug,
                    source_long_context=available_source_long_context,
                ),
            )
        except IdeationQualityFailure as exc:
            rejected_candidates += 1
            archive_dir = cli.ROOT / "assets" / "script_revisions" / "failed_ideation"
            archive_dir.mkdir(parents=True, exist_ok=True)
            archive_path = archive_dir / f"{slug}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.json"
            if script_path.exists():
                shutil.move(str(script_path), archive_path)
            rejected_title = str(exc.payload.get("title", "")).strip()
            rejected_topic = str(exc.payload.get("topic", "")).strip()
            generated_summaries.append(f"REJECTED — do not reuse | {slug} | {rejected_title} | {rejected_topic}")
            used_slugs.add(slug)
            detail = f"candidate={slug}; archive={archive_path}; reason={exc}"
            append_local_start_log(log_path, "CANDIDATE_REJECTED", detail)
            if rejected_candidates >= max_rejected_candidates:
                raise SystemExit(
                    f"✗ Không thể tạo đủ {requested_count} script sau {rejected_candidates} candidate bị QA từ chối."
                ) from exc
            print(f"{prefix} rejected: QA terminal failure; generating a replacement candidate", flush=True)
            continue
        write_local_batch_item(script_path, payload, args)
        if args.type_of_vid == "short" and content_profile.content_rules.require_short_source_trace:
            used_source_section_indexes.add(payload["strategy"]["source_section_index"])
        ledger_text += f"\n| local | {slug} | {payload.get('title', '')} | ideation | ok | LLM |\n"
        used_slugs.add(slug)
        generated_summaries.append(f"{slug} | {payload.get('title', '')} | {payload.get('topic', '')}")
        written.append(slug)
        print(f"{prefix} queued: {slug}", flush=True)
        i += 1

    print("✓ Ideation xong:")
    for slug in written:
        print(f"  - {slug}")


def cmd_start(args: argparse.Namespace) -> None:
    cli = _cli()
    if getattr(args, "ask", False) or args.num_of_vid is None:
        args = cli._prompt_start_interactive(args)

    if getattr(args, "local", False):
        raise SystemExit(
            "✗ --local đã bị gỡ cùng Ollama/MLX-LM (amendment 2026-08-24, "
            "PROJECT_VISION.md Amendment Log). Ideation chỉ dùng xKiro/DeepSeek V4 Pro."
        )
    if getattr(args, "clear_ledger", False):
        if getattr(args, "resume", False):
            raise SystemExit("✗ --clear-ledger không dùng cùng --resume; resume cần ledger cũ để tránh chạy nhầm.")

    if getattr(args, "cloud", False):
        raise SystemExit(
            "✗ --cloud đã bị gỡ vì bỏ qua system prompt và strategy-v1. "
            "Ideation chỉ dùng xKiro/DeepSeek V4 Pro."
        )

    profile_scoped = hasattr(args, "profile_id")
    content_profile = load_content_profile(getattr(args, "profile_id", None))
    setattr(args, "_content_profile", content_profile)
    setattr(args, "_profile_scoped", profile_scoped)
    if profile_scoped:
        setattr(args, "profile_id", content_profile.profile_id)
    _validate_short_generation_request(args)

    # Ideation có một provider duy nhất để nội dung luôn nhất quán.
    requested_provider = (
        getattr(args, "llm_provider", None)
        or (content_profile.providers.llm if profile_scoped else _cli().settings.llm_provider)
    )
    if requested_provider != "xkiro":
        raise SystemExit(
            "✗ Ideation chỉ dùng xkiro/DeepSeek V4 Pro. "
            "Cập nhật providers.llm của content profile thành `xkiro`."
        )
    setattr(args, "_provider", _configured_script_provider("xkiro"))
    setattr(args, "_strict_qa", True)
    asyncio.run(_cmd_start_local(args))
