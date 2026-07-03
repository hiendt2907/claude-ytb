"""Cổng verify (tiêu chuẩn cộng đồng/bản quyền/...) phải chặn TRƯỚC khi nạp kịch bản."""

from dataclasses import replace

import pytest

from ytb_pipeline.ideation.generator import load_script
from ytb_pipeline.pkg.models import ComplianceCheck, VideoIdea

from conftest import make_script, passing_compliance

# narration đủ dài để qua cổng độ dài Short (0.8–1.2 phút)
_SECTIONS = [{"caption": "c", "narration": "x" * 1100}]


def test_compliance_attaches_to_idea_immutably():
    # Arrange
    idea = VideoIdea(topic="t", title="ti", description="d")
    check = ComplianceCheck(passed=True, community="PASS")

    # Act
    enriched = replace(idea, compliance=check)

    # Assert
    assert enriched.compliance is check
    assert idea.compliance is None  # bản gốc không đổi


def test_load_script_passes_when_compliance_passed(write_script):
    # Arrange
    path = write_script(make_script(_SECTIONS))

    # Act
    script = load_script(path)

    # Assert
    assert script.compliance is not None
    assert script.compliance.passed is True


def test_load_script_rejects_missing_compliance(write_script):
    # Arrange
    data = make_script(_SECTIONS)
    del data["compliance"]
    path = write_script(data)

    # Act / Assert
    with pytest.raises(ValueError, match="compliance"):
        load_script(path)


def test_load_script_rejects_failed_compliance(write_script):
    # Arrange
    failing = passing_compliance(passed=False, copyright="FAIL — dùng nhạc có bản quyền")
    path = write_script(make_script(_SECTIONS, compliance=failing))

    # Act / Assert
    with pytest.raises(ValueError, match="verify"):
        load_script(path)


def test_load_script_normalizes_non_list_emphasis(write_script):
    data = make_script([{"caption": "c1", "narration": "x" * 600}, {"caption": "c2", "narration": "y" * 600}])
    data["sections"][0]["emphasis"] = True
    data["sections"][1]["emphasis"] = "cơ chế"
    path = write_script(data)

    script = load_script(path)

    assert script.segments[0].emphasis == ()
    assert script.segments[1].emphasis == ("cơ chế",)
