"""Deterministic, local-first quality reports for the pre-publish gate.

The module intentionally consumes evidence collected by earlier stages instead
of invoking those stages (or an LLM) itself.  It can therefore be used by a
publish gate without producing media, touching a queue, or making network calls.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Iterable, Literal, Mapping, Sequence
import unicodedata


Severity = Literal["error", "warning", "info"]
ReportStatus = Literal["pass", "needs_review", "blocked"]

_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}
# Subsets of `SECTION_PURPOSES`, the closed enum the generation schema enforces.
# Keeping both sides in one vocabulary is what stops the gate from demanding a
# purpose the model was never allowed to emit.
REQUIRED_PURPOSES_BY_VIDEO_TYPE = {
    "short": ("situation", "core_answer", "application", "payoff"),
    "long": ("situation", "core_answer", "evidence", "application", "payoff"),
}
# Kept as the module-private alias the existing call sites use.
_REQUIRED_PURPOSES = REQUIRED_PURPOSES_BY_VIDEO_TYPE
_PURPOSE_ALIASES = {
    "payoff/cta": "payoff", "payoff_cta": "payoff",
    "intro": "situation", "hook": "situation",
    "definition": "core_answer", "mechanism_explanation": "evidence",
    "neuroscience_detail": "evidence", "energy_conservation": "evidence",
    "freeze_response": "evidence", "everyday_example_setup": "evidence",
    "example_analysis": "evidence", "misinterpretation": "evidence",
    "cognitive_load_theory": "evidence", "dopamine_mismatch": "evidence",
    "actionable_strategy_intro": "application", "strategy_detail": "application",
    "implementation_example": "application", "momentum_effect": "application",
    "environmental_design": "application", "practical_routine": "application",
    "summary": "payoff", "bridge_to_next": "payoff", "cta": "payoff",
}


def normalise_purpose(purpose: str) -> str:
    """Map a section purpose onto the closed release-gate vocabulary."""
    normalised = (purpose or "").strip().lower()
    return _PURPOSE_ALIASES.get(normalised, normalised)


def missing_required_purposes(
    video_type: str,
    purposes: Iterable[str],
    *,
    required_purposes: Mapping[str, Sequence[str]] | None = None,
) -> tuple[str, ...]:
    """Required purposes absent from `purposes`; empty when the script is complete.

    Exposed so admission (`preflight`) can reject offline exactly what the
    release gate rejects after render.  Discovering a missing `payoff` only at
    the pre-publish gate means the TTS and render bill has already been paid.

    `required_purposes` lets a caller pass a content profile's own declared
    policy (`profile.editorial_contract.purpose_policy.required`) instead of
    the legacy explainer vocabulary below.  Omitted, this falls back to that
    legacy vocabulary so a profile predating `editorial_contract` is unaffected.
    """
    lookup = required_purposes if required_purposes is not None else _REQUIRED_PURPOSES
    required = lookup.get((video_type or "").strip().lower())
    if required is None:
        return ()
    present = {normalise_purpose(item) for item in purposes}
    return tuple(item for item in required if item not in present)


_STOP_WORDS = frozenset({
    "a", "an", "ban", "bi", "cua", "co", "cho", "da", "dang", "de", "do", "duoc",
    "hay", "khi", "la", "lam", "ma", "mot", "nao", "nhung", "o", "roi", "sao", "su",
    "tai", "the", "thi", "va", "vi", "vay", "voi", "why", "how", "the", "and", "for",
})


@dataclass(frozen=True)
class ScriptSection:
    """Minimal script evidence needed by the deterministic completeness rubric."""

    caption: str
    narration: str
    purpose: str = ""


@dataclass(frozen=True)
class RenderEvidence:
    """Dimensions supplied by render validation or ffprobe; no media is opened here."""

    width: int
    height: int
    duration_sec: float | None = None


@dataclass(frozen=True)
class QualityFinding:
    """One portable finding produced locally or passed in by an upstream gate."""

    source: str
    rule: str
    severity: Severity
    message: str
    excerpt: str = ""
    section_index: int | None = None


@dataclass(frozen=True)
class QualityReportInput:
    """All evidence required to make a pre-publish report, without side effects."""

    slug: str
    video_type: str
    title: str
    thumbnail_text: str
    hook_text: str
    sections: tuple[ScriptSection, ...] = ()
    render: RenderEvidence | None = None
    upstream_findings: Sequence[QualityFinding | Mapping[str, Any]] = ()


@dataclass(frozen=True)
class PrePublishQualityReport:
    """Versioned, JSON-serializable local assessment of publication readiness."""

    schema_version: int
    slug: str
    video_type: str
    status: ReportStatus
    findings: tuple[QualityFinding, ...]

    @property
    def counts(self) -> dict[str, int]:
        return {
            severity: sum(finding.severity == severity for finding in self.findings)
            for severity in ("error", "warning", "info")
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "slug": self.slug,
            "video_type": self.video_type,
            "status": self.status,
            "counts": self.counts,
            "findings": [asdict(finding) for finding in self.findings],
        }


@dataclass(frozen=True)
class QualityReportArtifacts:
    json_path: Path
    markdown_path: Path


def evaluate_pre_publish_quality(data: QualityReportInput) -> PrePublishQualityReport:
    """Evaluate supplied evidence only; errors block and warnings need review."""
    findings = [
        *_packaging_findings(data),
        *_script_findings(data),
        *_render_findings(data),
        *(_coerce_finding(item) for item in data.upstream_findings),
    ]
    severities = {finding.severity for finding in findings}
    status: ReportStatus = (
        "blocked" if "error" in severities else "needs_review" if "warning" in severities else "pass"
    )
    return PrePublishQualityReport(
        schema_version=1,
        slug=data.slug.strip(),
        video_type=data.video_type.strip().lower(),
        status=status,
        findings=tuple(findings),
    )


def write_quality_report(report: PrePublishQualityReport, output_dir: Path) -> QualityReportArtifacts:
    """Write deterministic JSON and readable Markdown to a caller-selected local directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_filename(report.slug)
    json_path = output_dir / f"{stem}.quality.json"
    markdown_path = output_dir / f"{stem}.quality.md"
    _write_text(json_path, json.dumps(report.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    _write_text(markdown_path, report_to_markdown(report))
    return QualityReportArtifacts(json_path=json_path, markdown_path=markdown_path)


def report_to_markdown(report: PrePublishQualityReport) -> str:
    """Render the complete report without hidden scoring or model-generated prose."""
    lines = [
        f"# Pre-publish quality report: {report.slug or 'unnamed'}",
        "",
        f"- Schema: {report.schema_version}",
        f"- Video type: {report.video_type or 'unknown'}",
        f"- Status: {report.status}",
        f"- Findings: {report.counts['error']} error, {report.counts['warning']} warning, {report.counts['info']} info",
        "",
        "## Findings",
        "",
    ]
    if not report.findings:
        lines.append("No findings.")
    else:
        for finding in report.findings:
            location = f" (section {finding.section_index + 1})" if finding.section_index is not None else ""
            lines.extend([
                f"### {finding.severity.upper()} · {finding.rule}{location}",
                "",
                f"Source: {finding.source}",
                "",
                finding.message,
            ])
            if finding.excerpt:
                lines.extend(["", f"> {_bound_excerpt(finding.excerpt, 240)}"])
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_repair_brief(
    report: PrePublishQualityReport,
    *,
    max_items: int = 3,
    max_excerpt_chars: int = 160,
) -> str:
    """Return a bounded, actionable brief for a human or a separate repair workflow."""
    if max_items < 1:
        raise ValueError("max_items phải lớn hơn 0.")
    if max_excerpt_chars < 1:
        raise ValueError("max_excerpt_chars phải lớn hơn 0.")
    actionable = [finding for finding in report.findings if finding.severity != "info"]
    actionable.sort(key=lambda finding: _SEVERITY_ORDER[finding.severity])
    if not actionable:
        return "# Repair brief\n\nNo repair is required.\n"

    lines = ["# Repair brief", "", f"Status: {report.status}", ""]
    for finding in actionable[:max_items]:
        lines.extend([
            f"### {finding.rule}",
            "",
            f"- Priority: {finding.severity}",
            f"- Requested repair: {finding.message}",
        ])
        if finding.excerpt:
            lines.append(f"- Evidence: {_bound_excerpt(finding.excerpt, max_excerpt_chars)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _packaging_findings(data: QualityReportInput) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    title_words = _keywords(data.title)
    thumbnail_words = _keywords(data.thumbnail_text)
    hook_words = _keywords(data.hook_text)
    if not title_words:
        findings.append(_finding("script", "packaging.title.present", "error", "Tiêu đề phải có nội dung mô tả."))
    if not thumbnail_words:
        findings.append(_finding("script", "packaging.thumbnail_text.present", "error", "Cần khai báo chữ hoặc thông điệp thumbnail để kiểm tra alignment."))
    if not hook_words:
        findings.append(_finding("script", "packaging.hook.present", "error", "Cần khai báo hook mở đầu để kiểm tra alignment."))
    if title_words and hook_words and not title_words.intersection(hook_words):
        findings.append(_finding(
            "script", "packaging.title_hook_alignment", "warning",
            "Hook chưa dùng từ khóa chung nào với lời hứa trong tiêu đề.",
            excerpt=f"Title: {data.title}\nHook: {data.hook_text}",
        ))
    if thumbnail_words and not thumbnail_words.intersection(title_words | hook_words):
        findings.append(_finding(
            "script", "packaging.thumbnail_alignment", "warning",
            "Thông điệp thumbnail chưa có từ khóa chung với title hoặc hook.",
            excerpt=f"Thumbnail: {data.thumbnail_text}",
        ))
    return findings


def _script_findings(data: QualityReportInput) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    if not data.sections:
        return [_finding("script", "script.sections.present", "error", "Kịch bản phải có ít nhất một section.")]
    purposes: set[str] = set()
    for index, section in enumerate(data.sections):
        purpose = normalise_purpose(section.purpose)
        if purpose:
            purposes.add(purpose)
        if not section.caption.strip():
            findings.append(_finding("script", "script.section.caption", "error", "Section thiếu caption.", section_index=index))
        if not section.narration.strip():
            findings.append(_finding("script", "script.section.narration", "error", "Section thiếu narration.", section_index=index))
    required = _REQUIRED_PURPOSES.get(data.video_type.strip().lower())
    if required is None:
        findings.append(_finding("script", "script.video_type", "error", "video_type phải là short hoặc long."))
    else:
        for purpose in required:
            if purpose not in purposes:
                findings.append(_finding(
                    "script", f"script.required_purpose.{purpose}", "error",
                    f"Kịch bản thiếu section purpose='{purpose}'.",
                ))
    return findings


def _render_findings(data: QualityReportInput) -> list[QualityFinding]:
    if data.render is None:
        return [_finding("render", "render.evidence.present", "error", "Thiếu dimensions render để kiểm tra orientation.")]
    width, height = data.render.width, data.render.height
    if width <= 0 or height <= 0:
        return [_finding("render", "render.dimensions.valid", "error", "Render width và height phải lớn hơn 0.")]
    video_type = data.video_type.strip().lower()
    dimensions = f"{width}x{height}"
    if video_type == "short" and height <= width:
        return [_finding("render", "render.orientation.vertical", "error", f"Short phải dọc; nhận được {dimensions}.")]
    if video_type == "long" and width <= height:
        return [_finding("render", "render.orientation.landscape", "error", f"Long phải ngang; nhận được {dimensions}.")]
    return []


def _coerce_finding(item: QualityFinding | Mapping[str, Any]) -> QualityFinding:
    if isinstance(item, QualityFinding):
        return item
    if not isinstance(item, Mapping):
        return _finding("upstream", "upstream.finding.valid", "error", "Upstream finding phải là object có cấu trúc.")
    severity = str(item.get("severity", "error")).strip().lower()
    if severity not in _SEVERITY_ORDER:
        return _finding("upstream", "upstream.finding.severity", "error", "Upstream finding có severity không hợp lệ.")
    source = str(item.get("source", "upstream")).strip() or "upstream"
    if source == "video":
        source = "render"
    rule = str(item.get("rule", "")).strip()
    message = str(item.get("message", "")).strip()
    if not rule or not message:
        return _finding("upstream", "upstream.finding.required_fields", "error", "Upstream finding phải có rule và message.")
    section_index = item.get("section_index")
    if not isinstance(section_index, int) or isinstance(section_index, bool):
        section_index = None
    return QualityFinding(
        source=source,
        rule=rule,
        severity=severity,  # type: ignore[arg-type]
        message=message,
        excerpt=str(item.get("excerpt", "")).strip(),
        section_index=section_index,
    )


def _finding(source: str, rule: str, severity: Severity, message: str, **kwargs: Any) -> QualityFinding:
    return QualityFinding(source=source, rule=rule, severity=severity, message=message, **kwargs)


def _keywords(text: str) -> set[str]:
    normalized = unicodedata.normalize("NFD", text.lower())
    normalized = "".join(character for character in normalized if unicodedata.category(character) != "Mn")
    return {word for word in re.findall(r"[a-z0-9]+", normalized) if len(word) > 1 and word not in _STOP_WORDS}


def _bound_excerpt(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[:limit - 1].rstrip() + "…"


def _safe_filename(slug: str) -> str:
    ascii_slug = unicodedata.normalize("NFD", slug.lower().replace("đ", "d"))
    ascii_slug = "".join(character for character in ascii_slug if unicodedata.category(character) != "Mn")
    safe = re.sub(r"[^a-z0-9._-]+", "-", ascii_slug).strip(".-")
    return safe or "quality-report"


def _write_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
