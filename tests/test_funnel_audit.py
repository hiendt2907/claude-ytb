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


def test_audit_ignores_empty_or_completed_batch():
    assert audit_batch({"status": "done", "long_videos": [], "short_videos": []}).ok is True
    assert audit_batch({}).ok is True
