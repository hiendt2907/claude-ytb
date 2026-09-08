from __future__ import annotations

import json


def _input(**overrides):
    from ytb_pipeline.analytics.quality_report import (
        QualityReportInput,
        RenderEvidence,
        ScriptSection,
    )

    data = {
        "slug": "nao-ne-viec-kho",
        "video_type": "short",
        "title": "Vì sao não né việc khó",
        "thumbnail_text": "Não né sự mơ hồ",
        "hook_text": "Mở laptop rồi cầm điện thoại? Não đang né sự mơ hồ.",
        "sections": (
            ScriptSection("Tình huống", "Mở laptop rồi cầm điện thoại.", "situation"),
            ScriptSection("Cơ chế", "Não đang né sự mơ hồ.", "core_answer"),
            ScriptSection("Thử ngay", "Viết bước đầu tiên trong mười phút.", "application"),
            ScriptSection("Chốt", "Rõ bước đầu, não bớt né việc khó.", "payoff"),
        ),
        "render": RenderEvidence(width=1080, height=1920, duration_sec=72.0),
    }
    data.update(overrides)
    return QualityReportInput(**data)


def test_quality_report_passes_a_complete_aligned_short():
    from ytb_pipeline.analytics.quality_report import evaluate_pre_publish_quality

    report = evaluate_pre_publish_quality(_input())

    assert report.status == "pass"
    assert report.slug == "nao-ne-viec-kho"
    assert report.counts == {"error": 0, "warning": 0, "info": 0}


def test_quality_report_blocks_missing_short_section_and_vertical_orientation():
    from ytb_pipeline.analytics.quality_report import RenderEvidence, evaluate_pre_publish_quality

    report = evaluate_pre_publish_quality(_input(
        sections=_input().sections[:2],
        render=RenderEvidence(width=1920, height=1080),
    ))

    rules = {finding.rule for finding in report.findings}
    assert report.status == "blocked"
    assert "script.required_purpose.application" in rules
    assert "script.required_purpose.payoff" in rules
    assert "render.orientation.vertical" in rules


def test_quality_report_merges_upstream_findings_without_mutating_input():
    from ytb_pipeline.analytics.quality_report import evaluate_pre_publish_quality

    upstream = [{
        "source": "audio", "rule": "audio.silence_ratio", "severity": "warning",
        "message": "Tỷ lệ khoảng lặng cao.", "excerpt": "... im lặng quá lâu ...",
    }]
    report = evaluate_pre_publish_quality(_input(upstream_findings=upstream))

    assert report.status == "needs_review"
    assert any(finding.rule == "audio.silence_ratio" for finding in report.findings)
    assert upstream[0]["message"] == "Tỷ lệ khoảng lặng cao."


def test_report_writers_emit_json_markdown_and_bounded_repair_brief(tmp_path):
    from ytb_pipeline.analytics.quality_report import (
        RenderEvidence,
        build_repair_brief,
        evaluate_pre_publish_quality,
        write_quality_report,
    )

    report = evaluate_pre_publish_quality(_input(
        thumbnail_text="",
        hook_text="Một câu mở đầu không cùng chủ đề.",
        render=RenderEvidence(width=1920, height=1080),
        upstream_findings=({
            "source": "audio", "rule": "audio.noise", "severity": "error",
            "message": "Nhiễu nền cần được xử lý.", "excerpt": "x" * 500,
        },),
    ))
    artifacts = write_quality_report(report, tmp_path)
    brief = build_repair_brief(report, max_items=2, max_excerpt_chars=48)

    saved = json.loads(artifacts.json_path.read_text(encoding="utf-8"))
    assert artifacts.markdown_path.exists()
    assert saved["schema_version"] == 1
    assert saved["status"] == "blocked"
    assert brief.count("### ") == 2
    assert "x" * 49 not in brief


def test_report_writer_keeps_unicode_slug_distinct_in_filename(tmp_path):
    from ytb_pipeline.analytics.quality_report import evaluate_pre_publish_quality, write_quality_report

    report = evaluate_pre_publish_quality(_input(slug="Dư âm chú ý"))

    artifacts = write_quality_report(report, tmp_path)

    assert artifacts.json_path.name == "du-am-chu-y.quality.json"


def test_long_report_requires_all_editorial_purposes_and_landscape_render():
    from ytb_pipeline.analytics.quality_report import (
        QualityReportInput,
        RenderEvidence,
        ScriptSection,
        evaluate_pre_publish_quality,
    )

    report = evaluate_pre_publish_quality(QualityReportInput(
        slug="du-am-chu-y", video_type="long", title="Dư âm chú ý", 
        thumbnail_text="Dư âm chú ý", hook_text="Não bạn chưa rời việc cũ.",
        sections=(ScriptSection("Hook", "Não bạn chưa rời việc cũ.", "situation"),),
        render=RenderEvidence(width=1080, height=1920),
    ))

    rules = {finding.rule for finding in report.findings}
    assert "script.required_purpose.core_answer" in rules
    assert "script.required_purpose.evidence" in rules
    assert "script.required_purpose.application" in rules
    assert "script.required_purpose.payoff" in rules
    assert "render.orientation.landscape" in rules
