from ytb_pipeline.analytics.funnel import audit_batch


def test_audit_passes_when_shorts_link_to_long_form():
    result = audit_batch({
        "status": "active",
        "long_videos": [{"slug": "long-core"}],
        "short_videos": [{
            "slug": "short-hook",
            "long_form_slug": "long-core",
            "playlist": "playlist-id",
            "cta_target": "long-core",
        }],
    })

    assert result.ok is True
    assert result.issues == ()


def test_audit_reports_broken_short_to_long_funnel():
    result = audit_batch({
        "status": "active",
        "long_videos": [],
        "short_videos": [{"slug": "short-hook"}],
    })

    assert result.ok is False
    assert "no_long_form" in result.issues
    assert "shorts_without_target" in result.issues


def test_audit_requires_exactly_two_shorts_for_each_long_when_batch_declares_policy():
    result = audit_batch({
        "status": "active",
        "shorts_per_long": 2,
        "long_videos": [{"slug": "long-a"}, {"slug": "long-b"}],
        "short_videos": [
            {"slug": "a-1", "long_form_slug": "long-a", "playlist": "series", "cta_target": "long-a"},
            {"slug": "a-2", "long_form_slug": "long-a", "playlist": "series", "cta_target": "long-a"},
            {"slug": "b-1", "long_form_slug": "long-b", "playlist": "series", "cta_target": "long-b"},
        ],
    })

    assert result.ok is False
    assert "shorts_per_long_mismatch:long-b:1/2" in result.issues


def test_audit_accepts_two_shorts_for_each_long_when_batch_declares_policy():
    result = audit_batch({
        "status": "active",
        "shorts_per_long": 2,
        "long_videos": [{"slug": "long-a"}],
        "short_videos": [
            {"slug": "a-1", "long_form_slug": "long-a", "playlist": "series", "cta_target": "long-a"},
            {"slug": "a-2", "long_form_slug": "long-a", "playlist": "series", "cta_target": "long-a"},
        ],
    })

    assert result.ok is True


def test_audit_requires_traceable_long_source_when_batch_declares_source_strategy():
    result = audit_batch({
        "status": "active",
        "short_source_strategy_version": "v1",
        "long_videos": [{"slug": "long-a"}],
        "short_videos": [{
            "slug": "short-a", "long_form_slug": "long-a", "playlist": "series", "cta_target": "long-a",
            "source_long_slug": "long-a", "source_section_index": 4, "source_excerpt": "Một insight.",
        }, {
            "slug": "short-b", "long_form_slug": "long-a", "playlist": "series", "cta_target": "long-a",
        }],
    })

    assert "shorts_without_long_source" in result.issues


def test_audit_ignores_empty_or_completed_batch():
    assert audit_batch({"status": "done", "long_videos": [], "short_videos": []}).ok is True
    assert audit_batch({}).ok is True
