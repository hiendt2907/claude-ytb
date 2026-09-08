from __future__ import annotations

import argparse
import json
from types import SimpleNamespace

import pytest

from ytb_pipeline.content_contract import CONTRACT_VERSION, contract_for


@pytest.fixture(autouse=True)
def _preflight_pass_for_queue_metadata_tests(monkeypatch):
    from ytb_pipeline.orchestrator import ideation_state

    monkeypatch.setattr(ideation_state, "preflight_script", lambda _path: SimpleNamespace(passed=True, failures=()))


def _sections(video_type: str) -> list[dict]:
    """Minimal section list satisfying `script_contract._validate_sections`.

    A Short's first two sections must be `situation` then `core_answer`
    (script_contract._validate_short_strategy's opening-order check).
    """
    count = contract_for(video_type).minimum_sections
    purposes = {0: "situation", 1: "core_answer"} if video_type == "short" else {0: "situation"}
    return [
        {
            "purpose": purposes.get(i, "point"),
            "voiceover": f"Nội dung phần {i}.",
            "visual_intent": "cảnh minh hoạ",
            "pexels_query": "abstract",
            "time_goal": 0.5,
        }
        for i in range(count)
    ]


def _valid_payload(video_type: str = "short", **overrides) -> dict:
    """Payload đạt `validate_script_payload` hiện hành, dùng làm nền cho từng test.

    Test caller ghi đè field cần thiết qua `overrides` (bao gồm cả `strategy`
    cho Short, `target_minutes` cho Long nếu muốn khác giá trị mặc định).
    """
    payload = {
        "ruleset_id": CONTRACT_VERSION,
        "video_type": video_type,
        "title": "Tiêu đề mẫu",
        "topic": "cơ chế",
        "thumbnail_brief": {
            "visual_contradiction": "Đối lập hình ảnh",
            "subject": "Chủ thể",
            "emotion": "Ngạc nhiên",
            "headline": "Tiêu đề phụ",
        },
        "sections": _sections(video_type),
    }
    if video_type == "long":
        lower_min = contract_for("long").viewer_runtime_bounds_sec[0] / 60
        payload["target_minutes"] = lower_min
    else:
        payload["strategy"] = {
            "format_id": "core_answer_first_v1",
            "core_mechanism": "tránh né sự mơ hồ",
            "audience_problem": "mở laptop rồi cầm điện thoại",
            "angle": "trang trắng trước khi bắt đầu",
            "long_form_slug": "long-a",
            "playlist": "series",
            "cta_target": "long-a",
            "source_long_slug": "long-a",
            "source_excerpt": "Trích đoạn nguồn.",
            "source_section_index": 0,
            "hook": {
                "situation": "Mở laptop rồi lại cầm điện thoại",
                "core_answer": "Não đang né khoảnh khắc chưa biết bắt đầu từ đâu",
                "open_loop": "Vì sao sự mơ hồ thắng ý chí?",
            },
        }
    payload.update(overrides)
    return payload


def test_release_contract_fails_closed_when_a_section_lacks_voiceover():
    from ytb_pipeline.ideation.script_contract import validate_script_payload

    payload = _valid_payload()
    payload["sections"][2].pop("voiceover")

    result = validate_script_payload(payload)

    assert result.publishable is False
    assert any(item.path == "sections[2]" for item in result.findings)


def test_write_local_batch_item_honors_explicit_batch_key(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import ideation_state

    state = tmp_path / "auto_state.json"
    state.write_text(json.dumps({
        "shorts_funnel_batch_week1": {
            "status": "active",
            "long_videos": [{"slug": "week1-long"}],
            "short_videos": [],
        },
    }), encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")

    class CLI:
        AUTO_STATE_PATH = state

        @staticmethod
        def update_ledger(*_args, **_kwargs):
            return None

        class settings:
            dry_run = True
            youtube_publish_at = ""

    monkeypatch.setattr(ideation_state, "_cli", lambda: CLI)
    script = tmp_path / "week1-short.json"
    ideation_state.write_local_batch_item(
        script,
        _valid_payload("short", title="Week 1 Short"),
        argparse.Namespace(
            type_of_vid="short",
            batch_key="shorts_funnel_batch_week1",
            long_form_slug="week1-long",
            playlist="week1-playlist",
            cta_target="week1-long",
        ),
    )

    data = json.loads(state.read_text(encoding="utf-8"))
    assert "shorts_funnel_batch_week1" in data
    assert data["shorts_funnel_batch_week1"]["short_videos"][0]["slug"] == "week1-short"
    assert data["shorts_funnel_batch_week1"]["short_videos"][0]["cta_target"] == "week1-long"


def test_new_explicit_funnel_batch_defaults_to_one_long_and_two_shorts_daily(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import ideation_state

    state = tmp_path / "auto_state.json"
    state.write_text("{}", encoding="utf-8")

    class CLI:
        AUTO_STATE_PATH = state
        ROOT = tmp_path

        @staticmethod
        def update_ledger(*_args, **_kwargs):
            return None

        class settings:
            dry_run = True
            youtube_publish_at = ""

    monkeypatch.setattr(ideation_state, "_cli", lambda: CLI)
    script = tmp_path / "long-a.json"
    script.write_text('{"slug":"long-a"}', encoding="utf-8")

    ideation_state.write_local_batch_item(
        script,
        _valid_payload("long", title="Long A"),
        argparse.Namespace(type_of_vid="long", batch_key="shorts_funnel_batch_new"),
    )

    batch = json.loads(state.read_text(encoding="utf-8"))["shorts_funnel_batch_new"]
    assert batch["shorts_per_long"] == 2
    assert batch["daily_cadence"] == {"longs": 1, "shorts": 2}


def test_long_source_context_selects_traceable_sections(tmp_path):
    from ytb_pipeline.orchestrator.ideation_cmd import load_short_source_long_context

    long_script = tmp_path / "long-a.json"
    long_script.write_text(json.dumps({
        "slug": "long-a",
        "title": "Long A",
        "sections": [
            {"purpose": "mở đầu", "voiceover": "Mở đầu chung."},
            {"purpose": "giải thích điều bất ngờ", "voiceover": "Đây là phần giải thích có giá trị."},
            {"purpose": "cầu nối", "voiceover": "Kết thúc."},
        ],
    }), encoding="utf-8")

    context = load_short_source_long_context(long_script, "long-a")

    assert context["slug"] == "long-a"
    assert context["candidates"][0]["section_index"] == 1
    assert context["candidates"][0]["excerpt"] == "Đây là phần giải thích có giá trị."


def test_short_source_dedup_exemptions_include_only_verified_source_identity():
    from ytb_pipeline.orchestrator.ideation_cmd import short_source_dedup_exemptions

    exemptions = short_source_dedup_exemptions(
        replacement_slug="short-slot",
        source_long_context={
            "slug": "long-a",
            "title": "Long A: Im Lặng Hay Nói?",
            "topic": "Một lựa chọn trong cuộc họp",
        },
    )

    assert exemptions == (
        "short-slot",
        "long-a",
        "Long A: Im Lặng Hay Nói?",
        "Một lựa chọn trong cuộc họp",
    )


def test_available_long_source_context_excludes_sections_used_by_other_shorts():
    from ytb_pipeline.orchestrator.ideation_cmd import available_short_source_context

    context = available_short_source_context({
        "slug": "long-a",
        "candidates": [
            {"section_index": 1, "excerpt": "Một."},
            {"section_index": 2, "excerpt": "Hai."},
        ],
    }, {1})

    assert [item["section_index"] for item in context["candidates"]] == [2]


def test_replacing_short_releases_its_own_source_section():
    from ytb_pipeline.orchestrator.ideation_cmd import used_short_source_section_indexes

    batch = {
        "short_videos": [
            {
                "slug": "short-a",
                "long_form_slug": "long-a",
                "source_section_index": 3,
            },
            {
                "slug": "short-b",
                "long_form_slug": "long-a",
                "source_section_index": 4,
            },
        ],
    }

    assert used_short_source_section_indexes(
        batch,
        long_slug="long-a",
        replacement_slugs={"short-a"},
    ) == {4}


def test_short_batch_item_requires_a_complete_long_form_funnel(tmp_path, monkeypatch):
    """A Short must not be persisted until its funnel contract is complete."""
    from ytb_pipeline.orchestrator import ideation_state

    state = tmp_path / "auto_state.json"
    state.write_text("{}", encoding="utf-8")

    class CLI:
        AUTO_STATE_PATH = state

        @staticmethod
        def update_ledger(*_args, **_kwargs):
            raise AssertionError("rejected Short must not reach the ledger")

        class settings:
            dry_run = True
            youtube_publish_at = ""

    monkeypatch.setattr(ideation_state, "_cli", lambda: CLI)

    import pytest

    # The content contract now requires a Short's `strategy` object to already
    # carry long_form_slug/playlist/cta_target (script_contract.py
    # _validate_short_strategy), so a payload missing those outright is
    # rejected earlier by validate_script_payload. The funnel gate exercised
    # here is the next layer down: the batch never contains the Long the
    # Short claims to belong to.
    with pytest.raises(SystemExit, match="long_form_slug.*trỏ tới Long"):
        ideation_state.write_local_batch_item(
            tmp_path / "orphan-short.json",
            _valid_payload("short", title="Orphan Short"),
            argparse.Namespace(type_of_vid="short", batch_key="shorts_funnel_batch_week2"),
        )

    assert json.loads(state.read_text(encoding="utf-8")) == {}


def test_short_can_explicitly_reference_a_completed_external_long(tmp_path, monkeypatch):
    """Phase dry-runs may reference a verified Long outside a fresh batch."""
    from ytb_pipeline.orchestrator import ideation_state

    state = tmp_path / "auto_state.json"
    state.write_text(json.dumps({
        "shorts_funnel_batch_phase1": {"status": "pending", "long_videos": [], "short_videos": []},
    }), encoding="utf-8")

    class CLI:
        AUTO_STATE_PATH = state
        ROOT = tmp_path

        @staticmethod
        def done_slugs():
            return {"external-long"}

        @staticmethod
        def update_ledger(*_args, **_kwargs):
            return None

        class settings:
            dry_run = True
            youtube_publish_at = ""

    monkeypatch.setattr(ideation_state, "_cli", lambda: CLI)
    source = tmp_path / "scripts" / "archive" / "external-long.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        "video_type": "long",
        "sections": [{"purpose": "explanation", "voiceover": "Nguồn Long hợp lệ."}],
    }), encoding="utf-8")
    payload = _valid_payload("short")
    payload["strategy"].update({
        "long_form_slug": "external-long", "cta_target": "external-long", "source_long_slug": "external-long",
    })
    ideation_state.write_local_batch_item(
        tmp_path / "phase1-short.json", payload,
        argparse.Namespace(
            type_of_vid="short", batch_key="shorts_funnel_batch_phase1",
            long_form_slug="external-long", playlist="series", cta_target="external-long",
            allow_external_long=True,
        ),
    )

    batch = json.loads(state.read_text(encoding="utf-8"))["shorts_funnel_batch_phase1"]
    assert batch["short_videos"][0]["long_form_slug"] == "external-long"


def test_external_long_source_context_reads_archive_only_when_explicit(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    archived = scripts_dir / "archive" / "external-long.json"
    archived.parent.mkdir(parents=True)
    archived.write_text(
        '{"video_type":"long","sections":[{"purpose":"explanation","voiceover":"Nguồn."}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ideation_cmd, "_cli", lambda: SimpleNamespace(done_slugs=lambda: {"external-long"}))

    assert ideation_cmd.resolve_short_source_long_path(
        scripts_dir, "external-long", allow_external_long=True
    ) == archived
    with pytest.raises(SystemExit, match="cùng --batch-key"):
        ideation_cmd.resolve_short_source_long_path(scripts_dir, "external-long", allow_external_long=False)


@pytest.mark.parametrize("archive_payload", ["{not json}", "[]", '{"video_type":"short","sections":[{}]}'])
def test_external_long_source_context_rejects_non_long_or_malformed_archive(tmp_path, monkeypatch, archive_payload):
    from ytb_pipeline.orchestrator import ideation_cmd

    scripts_dir = tmp_path / "scripts"
    archived = scripts_dir / "archive" / "external-long.json"
    archived.parent.mkdir(parents=True)
    archived.write_text(archive_payload, encoding="utf-8")
    monkeypatch.setattr(ideation_cmd, "_cli", lambda: SimpleNamespace(done_slugs=lambda: {"external-long"}))

    with pytest.raises(SystemExit, match="source archive"):
        ideation_cmd.resolve_short_source_long_path(scripts_dir, "external-long", allow_external_long=True)


def test_strategy_short_marks_a_new_batch_v1_and_persists_its_format(tmp_path, monkeypatch):
    from ytb_pipeline.orchestrator import ideation_state

    state = tmp_path / "auto_state.json"
    state.write_text(json.dumps({
        "shorts_funnel_batch_new": {"status": "active", "long_videos": [{"slug": "long-a"}], "short_videos": []},
    }), encoding="utf-8")

    class CLI:
        AUTO_STATE_PATH = state

        @staticmethod
        def update_ledger(*_args, **_kwargs):
            return None

        class settings:
            dry_run = True
            youtube_publish_at = ""

    monkeypatch.setattr(ideation_state, "_cli", lambda: CLI)
    strategy = {
        "format_id": "core_answer_first_v1", "core_mechanism": "tránh né sự mơ hồ",
        "audience_problem": "mở laptop rồi cầm điện thoại", "angle": "trang trắng",
        "long_form_slug": "long-a", "playlist": "series", "cta_target": "long-a",
        "source_long_slug": "long-a", "source_excerpt": "Trích đoạn nguồn.",
        "source_section_index": 0,
        "hook": {
            "situation": "Mở laptop rồi lại cầm điện thoại",
            "core_answer": "Não đang né khoảnh khắc chưa biết bắt đầu từ đâu",
            "open_loop": "Vì sao sự mơ hồ thắng ý chí?",
        },
    }
    ideation_state.write_local_batch_item(
        tmp_path / "short-a.json",
        _valid_payload("short", title="Short", strategy=strategy),
        argparse.Namespace(type_of_vid="short", batch_key="shorts_funnel_batch_new"),
    )

    batch = json.loads(state.read_text(encoding="utf-8"))["shorts_funnel_batch_new"]
    assert batch["content_strategy_version"] == "v1"
    assert batch["short_videos"][0]["format_id"] == "core_answer_first_v1"


def test_write_local_batch_item_replaces_the_declared_slot_without_appending(tmp_path, monkeypatch):
    """Regenerating a broken long must preserve its slug, day, and queue identity."""
    from ytb_pipeline.orchestrator import ideation_state

    state = tmp_path / "auto_state.json"
    state.write_text(json.dumps({
        "shorts_funnel_batch_week2": {
            "status": "active",
            "long_videos": [{"day": 2, "slug": "week2-long", "status": "needs_regeneration"}],
            "short_videos": [],
        },
    }), encoding="utf-8")

    class CLI:
        AUTO_STATE_PATH = state

        @staticmethod
        def update_ledger(*_args, **_kwargs):
            return None

        class settings:
            dry_run = False
            youtube_publish_at = ""

    monkeypatch.setattr(ideation_state, "_cli", lambda: CLI)

    (tmp_path / "week2-long.json").write_text('{"slug":"week2-long"}', encoding="utf-8")
    ideation_state.write_local_batch_item(
        tmp_path / "week2-long.json",
        _valid_payload("long", title="Long mới", topic="cơ chế mới"),
        argparse.Namespace(
            type_of_vid="long",
            batch_key="shorts_funnel_batch_week2",
            replace_slug="week2-long",
        ),
    )

    videos = json.loads(state.read_text(encoding="utf-8"))["shorts_funnel_batch_week2"]["long_videos"]
    assert len(videos) == 1
    assert videos[0]["slug"] == "week2-long"
    assert videos[0]["day"] == 2
    assert videos[0]["status"] == "ok"
    assert videos[0]["provenance"]["revision"] == 1
