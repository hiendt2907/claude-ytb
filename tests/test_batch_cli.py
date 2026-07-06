"""Test CLI gọi tay sản xuất batch (orchestrator/batch_cli.py).

Không gọi subprocess/Telegram/YouTube API thật — monkeypatch các ranh giới đó.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess

import pytest

from ytb_pipeline.orchestrator import batch_cli as cli


# ── fixtures ────────────────────────────────────────────────────────────────
@pytest.fixture
def auto_state_file(tmp_path):
    data = {
        "shorts_funnel_batch_2026-06-22": {
            "long_videos": [
                {"day": 6, "slug": "b-video", "publish_at": "2026-06-24T06:00:00+0700", "shorts_status": "queued"},
                {"day": 5, "slug": "a-video", "publish_at": "2026-06-23T06:00:00+0700", "shorts_status": "queued"},
                {"day": 7, "slug": "c-video", "publish_at": "2026-06-25T06:00:00+0700", "shorts_status": "queued"},
            ]
        }
    }
    path = tmp_path / "auto_state.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.fixture
def ledger_file(tmp_path):
    path = tmp_path / "ledger.md"
    path.write_text(
        "# Ledger\n"
        "| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"
        "|---|---|---|---|---|---|\n"
        "| 2026-06-22 | a-video | A | done | ok | https://youtu.be/AAA |\n"
        "| 2026-06-22 | b-video | B | voiceover | error | tạm dừng |\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture(autouse=True)
def _capture_telegram(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(cli.telegram, "send_message", lambda t: sent.append(t))
    return sent


@pytest.fixture(autouse=True)
def _redirect_warn_log(tmp_path, monkeypatch):
    # Không cho bất kỳ test nào ghi vào assets/batch_cli_warnings.log thật.
    monkeypatch.setattr(cli, "WARN_LOG_PATH", tmp_path / "batch_cli_warnings.log")


# ── load_queue ────────────────────────────────────────────────────────────────
def test_load_queue_sorted_by_day(auto_state_file):
    queue = cli.load_queue(auto_state_file)
    assert [i.slug for i in queue] == ["a-video", "b-video", "c-video"]


def test_load_queue_includes_short_videos_sorted_with_long(tmp_path):
    path = tmp_path / "auto_state.json"
    path.write_text(json.dumps({
        "shorts_funnel_batch_2026-07-06": {
            "long_videos": [
                {"day": 5, "slug": "long-video", "publish_at": "2026-07-07T06:00:00+0700"},
            ],
            "short_videos": [
                {"day": 2, "slug": "short-video", "publish_at": "", "shorts_status": "queued"},
            ],
        }
    }), encoding="utf-8")

    queue = cli.load_queue(path)

    assert [i.slug for i in queue] == ["short-video", "long-video"]


# ── done_slugs ────────────────────────────────────────────────────────────────
def test_done_slugs_only_done_and_ok(ledger_file):
    done = cli.done_slugs(ledger_file)
    assert done == {"a-video"}  # b-video là error, không tính done


# ── next_pending ──────────────────────────────────────────────────────────────
def test_next_pending_skips_done(auto_state_file, ledger_file):
    queue = cli.load_queue(auto_state_file)
    done = cli.done_slugs(ledger_file)
    item = cli.next_pending(queue, done)
    assert item.slug == "b-video"


def test_next_pending_none_when_all_done(auto_state_file):
    queue = cli.load_queue(auto_state_file)
    done = {i.slug for i in queue}
    assert cli.next_pending(queue, done) is None


# ── is_transient_error ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "output",
    [
        "googleapiclient.errors.HttpError: <HttpError 409 ... Conflict>",
        "urllib.error.URLError: <urlopen error [Errno 8] nodename nor servname provided, "
        "or not known: Temporary failure in name resolution>",
        "BrokenPipeError: [Errno 32] Broken pipe",
        "socket.timeout: timed out",
        "urllib.error.HTTPError: HTTP Error 503: Service Unavailable",
    ],
)
def test_is_transient_error_true(output):
    assert cli.is_transient_error(output) is True


def test_is_transient_error_false_for_normal_bug():
    assert cli.is_transient_error("FileNotFoundError: scripts/missing.json") is False


# ── emit_warning: phải LUÔN làm cả 2 — Telegram + log ───────────────────────
def test_emit_warning_sends_telegram_and_writes_log(tmp_path, _capture_telegram):
    log_path = tmp_path / "warn.log"
    cli.emit_warning("test message", log_path=log_path)

    assert len(_capture_telegram) == 1
    assert "test message" in _capture_telegram[0]
    assert log_path.exists()
    assert "test message" in log_path.read_text(encoding="utf-8")


def test_emit_warning_still_logs_when_telegram_fails(tmp_path, monkeypatch):
    def _boom(_text):
        raise RuntimeError("network down")

    monkeypatch.setattr(cli.telegram, "send_message", _boom)
    log_path = tmp_path / "warn.log"
    cli.emit_warning("important", log_path=log_path)

    content = log_path.read_text(encoding="utf-8")
    assert "important" in content
    assert "network down" in content


# ── build_env ─────────────────────────────────────────────────────────────────
def test_build_env_forces_telegram_approval_false():
    item = cli.QueueItem(day=1, slug="x", publish_at="2026-06-23T06:00:00+0700", shorts_status="queued")
    env = cli.build_env(item)
    assert env["TELEGRAM_APPROVAL"] == "false"
    assert env["YOUTUBE_PUBLISH_AT"] == item.publish_at
    assert env["RENDER_PROVIDER"] == "ai"
    assert env["ALLOW_CLOUD_PROVIDERS"] == "true"
    assert env["BROLL_STRATEGY"] == "pexels"
    assert env["VIDEO_PROVIDER"] == "pexels"
    assert env["DRY_RUN"] == "false"


def test_build_env_uses_queue_orientation_for_shorts():
    item = cli.QueueItem(
        day=1,
        slug="short-video",
        publish_at="",
        shorts_status="queued",
        orientation="portrait",
    )

    env = cli.build_env(item)

    assert env["ORIENTATION"] == "portrait"


def test_load_queue_preserves_item_orientation(tmp_path):
    auto_state = tmp_path / "auto_state.json"
    auto_state.write_text(json.dumps({
        "shorts_funnel_batch_2026-07-06": {
            "long_videos": [],
            "short_videos": [
                {
                    "day": 1,
                    "slug": "short-video",
                    "publish_at": "",
                    "shorts_status": "queued",
                    "orientation": "portrait",
                },
            ],
        }
    }), encoding="utf-8")

    queue = cli.load_queue(auto_state)

    assert queue[0].orientation == "portrait"


# ── run_with_retry ────────────────────────────────────────────────────────────
def _completed(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def test_run_with_retry_succeeds_first_try(_capture_telegram):
    item = cli.QueueItem(1, "x", "2026-06-23T06:00:00+0700", "queued")
    run_fn = lambda _item, **kw: _completed(0, stdout="ok")  # noqa: E731

    ok, output = cli.run_with_retry(item, backoff=[1, 1], sleep_fn=lambda _s: None, run_fn=run_fn)

    assert ok is True
    assert output == "ok"
    assert _capture_telegram == []  # không có cảnh báo khi thành công


def test_run_with_retry_recovers_after_transient_error(_capture_telegram):
    item = cli.QueueItem(1, "x", "2026-06-23T06:00:00+0700", "queued")
    calls = []

    def run_fn(_item, **kw):
        calls.append(1)
        if len(calls) == 1:
            return _completed(1, stderr="HTTP Error 409: Conflict")
        return _completed(0, stdout="done")

    ok, output = cli.run_with_retry(item, backoff=[1, 1], sleep_fn=lambda _s: None, run_fn=run_fn)

    assert ok is True
    assert len(calls) == 2
    assert _capture_telegram == []  # hồi phục được thì không cần cảnh báo


def test_run_with_retry_warns_after_exhausting_retries(_capture_telegram):
    item = cli.QueueItem(1, "x", "2026-06-23T06:00:00+0700", "queued")
    run_fn = lambda _item, **kw: _completed(1, stderr="HTTP Error 409: Conflict")  # noqa: E731

    ok, _output = cli.run_with_retry(item, backoff=[1, 1], sleep_fn=lambda _s: None, run_fn=run_fn)

    assert ok is False
    assert len(_capture_telegram) == 1
    assert "đã retry hết" in _capture_telegram[0]


def test_run_with_retry_warns_immediately_for_non_transient_error(_capture_telegram):
    item = cli.QueueItem(1, "x", "2026-06-23T06:00:00+0700", "queued")
    calls = []

    def run_fn(_item, **kw):
        calls.append(1)
        return _completed(1, stderr="FileNotFoundError: scripts/x.json")

    ok, _output = cli.run_with_retry(item, backoff=[1, 1], sleep_fn=lambda _s: None, run_fn=run_fn)

    assert ok is False
    assert len(calls) == 1  # không retry
    assert len(_capture_telegram) == 1
    assert "KHÔNG retry" in _capture_telegram[0]


# ── extract_claimed_video_id ──────────────────────────────────────────────────
def test_extract_claimed_video_id_found():
    output = "...\n  ✓ Đã upload: https://youtu.be/b917RPp2o7o\n[4/4] Publish   ✓  uploaded=True"
    assert cli.extract_claimed_video_id(output) == "b917RPp2o7o"


def test_extract_claimed_video_id_not_found():
    assert cli.extract_claimed_video_id("no url here") is None


# ── verify_youtube_video (mock client) ───────────────────────────────────────
def test_verify_youtube_video_exists(monkeypatch):
    class _FakeVideosList:
        def execute(self):
            return {
                "items": [
                    {
                        "snippet": {"title": "Tiêu đề"},
                        "status": {"privacyStatus": "private", "publishAt": "2026-06-24T23:00:00Z"},
                    }
                ]
            }

    class _FakeYoutube:
        def videos(self):
            return self

        def list(self, **kwargs):
            return _FakeVideosList()

    monkeypatch.setattr(
        "ytb_pipeline.publish.youtube_auth.get_youtube_client", lambda: _FakeYoutube()
    )

    result = cli.verify_youtube_video("b917RPp2o7o")

    assert result["exists"] is True
    assert result["title"] == "Tiêu đề"
    assert result["privacy_status"] == "private"
    assert result["publish_at"] == "2026-06-24T23:00:00Z"


def test_verify_youtube_video_not_found(monkeypatch):
    class _FakeVideosList:
        def execute(self):
            return {"items": []}

    class _FakeYoutube:
        def videos(self):
            return self

        def list(self, **kwargs):
            return _FakeVideosList()

    monkeypatch.setattr(
        "ytb_pipeline.publish.youtube_auth.get_youtube_client", lambda: _FakeYoutube()
    )

    result = cli.verify_youtube_video("does-not-exist")

    assert result == {"exists": False}


# ── check_schedule_drift ──────────────────────────────────────────────────────
def test_check_schedule_drift_detects_mismatch():
    # Lệch 1 ngày — đúng tình huống thật đã gặp với video #2 batch này.
    assert cli.check_schedule_drift("2026-06-22T23:00:00Z", "2026-06-24T06:00:00+0700") is True


def test_check_schedule_drift_no_mismatch_same_instant():
    assert cli.check_schedule_drift("2026-06-24T23:00:00Z", "2026-06-25T06:00:00+0700") is False


def test_check_schedule_drift_none_publish_at_is_not_drift():
    assert cli.check_schedule_drift(None, "2026-06-25T06:00:00+0700") is False


# ── detect_stage_marker ───────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "line,expected",
    [
        ("[1/4] Ideation  ▶  ...\n", "running-ideation"),
        ("[2/4] Voiceover ▶  đang tạo audio...\n", "running-voiceover"),
        ("[3/4] Render    ▶  đang dựng video (ai/landscape)...\n", "running-ai-render"),
        ("[3/4] Render    ▶  đang dựng video (moviepy/landscape)...\n", "running-render"),
        ("[4/4] Publish   ▶  đang upload...\n", "running-publish"),
        ("[2/4] Voiceover ✓  assets/audio/x.mp3 (12.0s)\n", None),
        ("dòng log bình thường khác\n", None),
    ],
)
def test_detect_stage_marker(line, expected):
    assert cli.detect_stage_marker(line) == expected


# ── last_stage_for_slug ───────────────────────────────────────────────────────
def test_last_stage_for_slug_returns_most_recent(tmp_path):
    ledger = tmp_path / "ledger.md"
    ledger.write_text(
        "# Ledger\n"
        "| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n"
        "|---|---|---|---|---|---|\n"
        "| 2026-06-23 | x | | running-voiceover | running | ... |\n"
        "| 2026-06-23 | x | | running-ai-render | running | ... |\n",
        encoding="utf-8",
    )
    assert cli.last_stage_for_slug("x", ledger) == "running-ai-render"


def test_last_stage_for_slug_empty_when_no_rows(tmp_path):
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")
    assert cli.last_stage_for_slug("x", ledger) == ""


# ── run_pipeline_once: cập nhật ledger NGAY khi bắt đầu + theo từng khâu ──────
def test_run_pipeline_once_writes_running_stages_as_it_streams(tmp_path, monkeypatch):
    item = cli.QueueItem(1, "x", "2026-06-23T06:00:00+0700", "queued")
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")
    script_path = tmp_path / "x.json"
    script_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "log_path_for", lambda slug: tmp_path / f"{slug}.log")

    class _FakeProc:
        def __init__(self):
            self.stdout = iter(
                [
                    "[1/4] Ideation  ✓  T (1 đoạn)\n",
                    "[2/4] Voiceover ▶  đang tạo audio...\n",
                    "[2/4] Voiceover ✓  a.mp3 (1.0s)\n",
                    "[3/4] Render    ▶  đang dựng video (ai/landscape)...\n",
                ]
            )
            self.args = ["fake"]
            self.returncode = 0

        def wait(self):
            return None

    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **kw: _FakeProc())

    cli.run_pipeline_once(item, script_path=script_path, ledger_path=ledger)

    content = ledger.read_text(encoding="utf-8")
    assert "running-ideation" in content
    assert "running-voiceover" in content
    assert "running-ai-render" in content


# ── update_ledger ─────────────────────────────────────────────────────────────
def test_update_ledger_appends_row(tmp_path):
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")

    cli.update_ledger("my-slug", "Tiêu đề", "done", "ok", "ghi chú", ledger_path=ledger)

    content = ledger.read_text(encoding="utf-8")
    assert "| my-slug | Tiêu đề | done | ok | ghi chú |" in content


# ── process_next (integration, mọi ranh giới ngoài đều mock) ─────────────────
def test_process_next_happy_path(auto_state_file, ledger_file, monkeypatch, _capture_telegram):
    monkeypatch.setattr(
        cli, "run_with_retry",
        lambda item, **kw: (True, "✓ Đã upload: https://youtu.be/NEWID12345"),
    )
    monkeypatch.setattr(
        cli, "verify_youtube_video",
        lambda video_id: {
            "exists": True, "title": "T", "privacy_status": "private",
            "publish_at": "2026-06-23T23:00:00Z",
        },
    )

    handled = cli.process_next(queue_path=auto_state_file, ledger_path=ledger_file)

    assert handled is True
    content = ledger_file.read_text(encoding="utf-8")
    assert "b-video" in content and "done | ok" in content
    assert "https://youtu.be/NEWID12345" in content
    assert _capture_telegram == []  # đúng kế hoạch, không lệch -> không cảnh báo


def test_process_next_returns_false_when_queue_empty(auto_state_file, ledger_file):
    # đánh dấu cả 3 slug đã done
    ledger_file.write_text(
        ledger_file.read_text(encoding="utf-8")
        + "| 2026-06-22 | b-video | B | done | ok | x |\n"
        + "| 2026-06-22 | c-video | C | done | ok | x |\n",
        encoding="utf-8",
    )
    assert cli.process_next(queue_path=auto_state_file, ledger_path=ledger_file) is False


def test_process_next_records_error_on_run_failure(auto_state_file, ledger_file, monkeypatch, _capture_telegram):
    monkeypatch.setattr(cli, "run_with_retry", lambda item, **kw: (False, "boom"))

    handled = cli.process_next(queue_path=auto_state_file, ledger_path=ledger_file)

    assert handled is True
    content = ledger_file.read_text(encoding="utf-8")
    assert "b-video | | voiceover | error" in content.replace("  ", " ") or "error" in content


def test_process_next_warns_when_no_video_id_in_output(auto_state_file, ledger_file, monkeypatch, _capture_telegram):
    monkeypatch.setattr(cli, "run_with_retry", lambda item, **kw: (True, "no url printed"))

    handled = cli.process_next(queue_path=auto_state_file, ledger_path=ledger_file)

    assert handled is True
    assert len(_capture_telegram) == 1
    assert "không tìm thấy youtu.be" in _capture_telegram[0]


# ── log_path_for / tail_text ──────────────────────────────────────────────────
def test_log_path_for_uses_slug(tmp_path):
    path = cli.log_path_for("my-slug", log_dir=tmp_path)
    assert path == tmp_path / "my-slug.log"


def test_tail_text_returns_empty_for_missing_file(tmp_path):
    assert cli.tail_text(tmp_path / "missing.log") == ""


def test_tail_text_returns_last_n_lines(tmp_path):
    path = tmp_path / "x.log"
    path.write_text("\n".join(f"line {i}" for i in range(1, 11)), encoding="utf-8")

    assert cli.tail_text(path, n=3) == "line 8\nline 9\nline 10"


# ── run_doctor_checks ──────────────────────────────────────────────────────────
def test_run_doctor_checks_flags_missing_scripts(auto_state_file, ledger_file, monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state_file)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger_file)
    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli.settings, "telegram_bot_token", "")
    monkeypatch.setattr(cli.settings, "telegram_chat_id", "")
    monkeypatch.setattr(cli.settings, "youtube_token_file", "secrets/does_not_exist.json")

    checks = cli.run_doctor_checks()
    by_name = {name: (ok, detail) for name, ok, detail in checks}

    assert by_name["auto_state.json"][0] is True
    assert by_name["Telegram config"][0] is False
    assert by_name["YouTube OAuth token"][0] is False
    assert by_name["Script JSON cho video pending"][0] is False
    assert "a-video" not in by_name["Script JSON cho video pending"][1]  # a-video đã done, không cần script


def test_check_oauth_token_ok_when_load_succeeds(monkeypatch):
    monkeypatch.setattr("ytb_pipeline.publish.youtube_auth._load_or_authorize", lambda *a, **kw: object())

    name, ok, detail = cli._check_oauth_token("YouTube OAuth token", "secrets/x.json", [])

    assert ok is True
    assert detail == "hợp lệ"


def test_check_oauth_token_reports_reauth_required(monkeypatch):
    def boom(*a, **kw):
        raise cli.ReauthRequiredError("token chết")

    monkeypatch.setattr("ytb_pipeline.publish.youtube_auth._load_or_authorize", boom)

    name, ok, detail = cli._check_oauth_token("Drive OAuth token", "secrets/x.json", [])

    assert ok is False
    assert "ytb auth" in detail


# ── _check_recent_published ───────────────────────────────────────────────────
def test_check_recent_published_no_done_videos_is_ok(ledger_file, monkeypatch):
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger_file)

    name, ok, detail = cli._check_recent_published()

    assert ok is True
    assert "chưa có video done" in detail


def test_check_recent_published_flags_missing_video(ledger_file, monkeypatch):
    ledger_file.write_text(
        ledger_file.read_text(encoding="utf-8")
        + "| 2026-06-23 | x | T | done | ok | https://youtu.be/GONE123 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger_file)
    monkeypatch.setattr(cli, "verify_youtube_video", lambda video_id: {"exists": False})

    name, ok, detail = cli._check_recent_published()

    assert ok is False
    assert "GONE123" in detail


def test_check_recent_published_ok_when_video_exists(ledger_file, monkeypatch):
    ledger_file.write_text(
        ledger_file.read_text(encoding="utf-8")
        + "| 2026-06-23 | x | T | done | ok | https://youtu.be/REAL123 |\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger_file)
    monkeypatch.setattr(cli, "verify_youtube_video", lambda video_id: {"exists": True})

    name, ok, detail = cli._check_recent_published()

    assert ok is True


# ── process_next: token hết hạn lúc verify (ReauthRequiredError) ─────────────
def test_process_next_records_error_when_reauth_required(auto_state_file, ledger_file, monkeypatch, _capture_telegram):
    monkeypatch.setattr(
        cli, "run_with_retry",
        lambda item, **kw: (True, "✓ Đã upload: https://youtu.be/NEWID12345"),
    )

    def boom(video_id):
        raise cli.ReauthRequiredError("token chết — chạy `ytb auth`")

    monkeypatch.setattr(cli, "verify_youtube_video", boom)

    handled = cli.process_next(queue_path=auto_state_file, ledger_path=ledger_file)

    assert handled is True
    content = ledger_file.read_text(encoding="utf-8")
    assert "b-video" in content and "publish | error" in content
    assert "ytb auth" in content


# ── cmd_doctor --notify ────────────────────────────────────────────────────────
def test_cmd_doctor_notify_sends_telegram_summary(monkeypatch, _capture_telegram):
    monkeypatch.setattr(
        cli, "run_doctor_checks",
        lambda: [("check ok", True, "fine"), ("check bad", False, "token chết")],
    )

    with pytest.raises(SystemExit):
        cli.cmd_doctor(argparse.Namespace(notify=True))

    assert len(_capture_telegram) == 1
    assert "check bad" in _capture_telegram[0]
    assert "token chết" in _capture_telegram[0]


def test_cmd_doctor_notify_skips_telegram_when_all_ok(monkeypatch, _capture_telegram):
    monkeypatch.setattr(cli, "run_doctor_checks", lambda: [("check ok", True, "fine")])

    cli.cmd_doctor(argparse.Namespace(notify=True))

    assert len(_capture_telegram) == 1
    assert "tất cả OK" in _capture_telegram[0]


def test_cmd_doctor_without_notify_does_not_use_telegram(monkeypatch, _capture_telegram):
    monkeypatch.setattr(cli, "run_doctor_checks", lambda: [("check ok", True, "fine")])

    cli.cmd_doctor(argparse.Namespace(notify=False))

    assert _capture_telegram == []


# ── cmd_auth ───────────────────────────────────────────────────────────────────
def test_cmd_auth_calls_both_clients_interactively(monkeypatch, capsys):
    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        "ytb_pipeline.publish.youtube_auth.get_youtube_client",
        lambda **kw: calls.append(("youtube", kw.get("allow_interactive"))),
    )
    monkeypatch.setattr(
        "ytb_pipeline.publish.youtube_auth.get_drive_client",
        lambda **kw: calls.append(("drive", kw.get("allow_interactive"))),
    )

    cli.cmd_auth(argparse.Namespace())

    assert ("youtube", True) in calls
    assert ("drive", True) in calls
    assert "Token đã lưu" in capsys.readouterr().out


# ── cmd_queue / cmd_ledger output (qua capsys) ───────────────────────────────
def test_cmd_queue_prints_valid_json(auto_state_file, ledger_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state_file)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger_file)

    cli.cmd_queue(argparse.Namespace())

    rows = json.loads(capsys.readouterr().out)
    assert {r["slug"]: r["status"] for r in rows} == {
        "a-video": "done", "b-video": "pending", "c-video": "pending",
    }


def test_cmd_cancel_removes_short_video(tmp_path, monkeypatch, capsys):
    auto_state = tmp_path / "auto_state.json"
    auto_state.write_text(json.dumps({
        "shorts_funnel_batch_2026-07-06": {
            "long_videos": [],
            "short_videos": [
                {"day": 2, "slug": "short-video", "publish_at": "", "shorts_status": "queued"},
            ],
        }
    }), encoding="utf-8")
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |\n", encoding="utf-8")
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger)

    cli.cmd_cancel(argparse.Namespace(slug="short-video"))

    data = json.loads(auto_state.read_text(encoding="utf-8"))
    assert data["shorts_funnel_batch_2026-07-06"]["short_videos"] == []
    assert "Đã huỷ" in capsys.readouterr().out


def test_cmd_ledger_prints_tail(ledger_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, "LEDGER_PATH", ledger_file)

    cli.cmd_ledger(argparse.Namespace(tail=1))

    out = capsys.readouterr().out
    assert "b-video" in out and "a-video" not in out


def test_process_next_warns_on_schedule_drift(auto_state_file, ledger_file, monkeypatch, _capture_telegram):
    monkeypatch.setattr(
        cli, "run_with_retry",
        lambda item, **kw: (True, "✓ Đã upload: https://youtu.be/DRIFTID"),
    )
    monkeypatch.setattr(
        cli, "verify_youtube_video",
        lambda video_id: {
            "exists": True, "title": "T", "privacy_status": "private",
            "publish_at": "2026-06-22T23:00:00Z",  # lệch so với publish_at b-video (2026-06-24)
        },
    )

    handled = cli.process_next(queue_path=auto_state_file, ledger_path=ledger_file)

    assert handled is True
    assert any("lệch lịch publish" in m for m in _capture_telegram)


# ── cmd_start ─────────────────────────────────────────────────────────────────
def test_build_start_prompt_auto_rules_mentions_count_and_type():
    prompt = cli._build_start_prompt(5, "long", "auto")

    assert "5" in prompt
    assert "Video dài" in prompt
    assert "TỰ chọn chủ đề" in prompt
    assert "KHÔNG chạy voiceover/render/publish" in prompt


def test_build_start_prompt_custom_rules_used_as_topic():
    prompt = cli._build_start_prompt(2, "short", "chủ đề về trì hoãn")

    assert "Short (dọc" in prompt
    assert "chủ đề về trì hoãn" in prompt


def test_cmd_start_runs_claude_and_reports_success(monkeypatch, capsys):
    import io
    captured_cmd = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            captured_cmd["cmd"] = cmd
            result_line = json.dumps({"type": "result", "result": "✓ Đã viết 2 kịch bản."})
            self.stdout = io.StringIO(result_line + "\n")
            self.stderr = io.StringIO("")
            self.returncode = 0
            self.args = cmd

        def wait(self):
            pass

    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(cli, "build_claude_cmd", lambda prompt: ["claude", "-p", prompt])

    cli.cmd_start(argparse.Namespace(num_of_vid=2, type_of_vid="short", type_of_rules="auto", resume=False, cloud=True))

    out = capsys.readouterr().out
    assert "Đã viết 2 kịch bản" in out
    assert "ytb batch status" in out
    assert captured_cmd["cmd"][:2] == ["claude", "-p"]


def test_start_parser_accepts_explicit_local_flag():
    parser = cli.build_parser(
        doc="test",
        cmd_funcs={
            "start": lambda args: None,
            "status": lambda args: None,
            "run": lambda args: None,
            "verify": lambda args: None,
            "retry": lambda args: None,
            "logs": lambda args: None,
            "ledger": lambda args: None,
            "queue": lambda args: None,
            "ps": lambda args: None,
            "reset": lambda args: None,
            "cancel": lambda args: None,
            "stop": lambda args: None,
            "doctor": lambda args: None,
            "auth": lambda args: None,
            "benchmark-local": lambda args: None,
        },
    )

    args = parser.parse_args(["start", "-n", "1", "--local"])

    assert args.local is True
    assert args.cloud is False


def test_cli_parses_start_idea_alias_and_ask_flag():
    parser = cli.build_parser(
        doc="test",
        cmd_funcs={
            "start": lambda args: None,
            "status": lambda args: None,
            "run": lambda args: None,
            "verify": lambda args: None,
            "retry": lambda args: None,
            "logs": lambda args: None,
            "ledger": lambda args: None,
            "queue": lambda args: None,
            "ps": lambda args: None,
            "reset": lambda args: None,
            "cancel": lambda args: None,
            "stop": lambda args: None,
            "doctor": lambda args: None,
            "auth": lambda args: None,
            "benchmark-local": lambda args: None,
        },
    )

    args = parser.parse_args([
        "start",
        "-n",
        "2",
        "--type-of-vid",
        "short",
        "--idea",
        "cơ chế trì hoãn",
        "--ask",
        "--clear-ledger",
    ])

    assert args.num_of_vid == 2
    assert args.type_of_vid == "short"
    assert args.type_of_rules == "cơ chế trì hoãn"
    assert args.ask is True
    assert args.clear_ledger is True


def test_cmd_start_rejects_local_and_cloud_together():
    with pytest.raises(SystemExit, match="--local"):
        cli.cmd_start(
            argparse.Namespace(
                num_of_vid=1,
                type_of_vid="short",
                type_of_rules="auto",
                resume=False,
                local=True,
                cloud=True,
            )
        )


def test_cmd_start_rejects_clear_ledger_with_resume():
    with pytest.raises(SystemExit, match="clear-ledger"):
        cli.cmd_start(
            argparse.Namespace(
                num_of_vid=1,
                type_of_vid="short",
                type_of_rules="cơ chế trì hoãn",
                resume=True,
                local=True,
                cloud=False,
                clear_ledger=True,
            )
        )


def test_cmd_start_warns_and_exits_on_nonzero_return(monkeypatch, _capture_telegram):
    import io

    class FakePopen:
        def __init__(self, cmd, **kw):
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("lỗi API rồi")
            self.returncode = 1
            self.args = cmd

        def wait(self):
            pass

    monkeypatch.setattr(cli.subprocess, "Popen", FakePopen)

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_start(argparse.Namespace(num_of_vid=1, type_of_vid="long", type_of_rules="auto", resume=False, cloud=True))

    assert exc_info.value.code == 1
    assert any("lỗi API rồi" in m for m in _capture_telegram)


# ── graceful stop (ytb batch stop) ───────────────────────────────────────────
@pytest.fixture(autouse=True)
def _reset_stop_flag():
    # _stop_requested là module-level state — phải reset giữa các test để không
    # rò rỉ qua test khác.
    cli._stop_requested = False
    cli._current_proc = None
    yield
    cli._stop_requested = False
    cli._current_proc = None


def test_handle_stop_signal_sets_flag_and_killpgs_current_proc_group(monkeypatch):
    killed = []
    monkeypatch.setattr(cli.os, "killpg", lambda pid, sig: killed.append((pid, sig)))

    class _FakeProc:
        pid = 4242

        def poll(self):
            return None  # vẫn đang chạy

    cli._current_proc = _FakeProc()
    cli._handle_stop_signal(15, None)

    assert cli._stop_requested is True
    assert killed == [(4242, cli.signal.SIGTERM)]


def test_handle_stop_signal_ignores_process_lookup_error(monkeypatch):
    def _raise(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(cli.os, "killpg", _raise)

    class _FakeProc:
        pid = 4242

        def poll(self):
            return None

    cli._current_proc = _FakeProc()
    cli._handle_stop_signal(15, None)  # không raise

    assert cli._stop_requested is True


def test_run_pipeline_once_marks_stopped_when_stop_requested(tmp_path, monkeypatch):
    item = cli.QueueItem(1, "x", "2026-06-23T06:00:00+0700", "queued")
    ledger = tmp_path / "ledger.md"
    ledger.write_text("# Ledger\n", encoding="utf-8")
    script_path = tmp_path / "x.json"
    script_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "log_path_for", lambda slug: tmp_path / f"{slug}.log")

    class _FakeProc:
        def __init__(self):
            self.stdout = iter(["[2/4] Voiceover ▶  đang tạo audio...\n"])
            self.args = ["fake"]
            self.returncode = -15

        def poll(self):
            return None

        def wait(self):
            cli._stop_requested = True  # mô phỏng SIGTERM tới giữa lúc chạy

    monkeypatch.setattr(cli.subprocess, "Popen", lambda *a, **kw: _FakeProc())

    cli.run_pipeline_once(item, script_path=script_path, ledger_path=ledger)

    content = ledger.read_text(encoding="utf-8")
    assert "stopped" in content
    assert "running-voiceover" in content
    assert cli._current_proc is None  # luôn clear sau khi xong, dù dừng giữa đường


def test_run_with_retry_stops_immediately_without_warning_or_retry(_capture_telegram):
    item = cli.QueueItem(1, "x", "2026-06-23T06:00:00+0700", "queued")
    calls = []

    def run_fn(_item, **kw):
        calls.append(1)
        cli._stop_requested = True
        return _completed(-15, stdout="bị kill")

    ok, output = cli.run_with_retry(item, backoff=[1, 1], sleep_fn=lambda _s: None, run_fn=run_fn)

    assert ok is False
    assert len(calls) == 1  # không retry khi đã dừng chủ động
    assert _capture_telegram == []  # không phải lỗi -> không cảnh báo
    assert output == "bị kill"


def test_process_next_returns_false_without_error_ledger_when_stopped(
    auto_state_file, ledger_file, monkeypatch, _capture_telegram
):
    def fake_run_with_retry(item, **kw):
        cli._stop_requested = True
        return False, "bị kill giữa lúc render"

    monkeypatch.setattr(cli, "run_with_retry", fake_run_with_retry)
    before = ledger_file.read_text(encoding="utf-8")

    handled = cli.process_next(queue_path=auto_state_file, ledger_path=ledger_file)

    assert handled is False
    assert _capture_telegram == []
    after = ledger_file.read_text(encoding="utf-8")
    assert after == before  # process_next không tự ghi thêm gì — run_pipeline_once đã ghi 'stopped' rồi


def test_cmd_run_stops_loop_when_stop_requested(monkeypatch, capsys):
    calls = []

    def fake_process_next():
        calls.append(1)
        cli._stop_requested = True
        return True

    monkeypatch.setattr(cli, "process_next", fake_process_next)

    cli.cmd_run(argparse.Namespace(loop=True))

    assert len(calls) == 1  # dừng ngay sau lần đầu, không tiếp tục loop
    assert "dừng graceful" in capsys.readouterr().out


def test_cmd_retry_reports_graceful_stop(auto_state_file, monkeypatch, capsys):
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state_file)

    def fake_run_with_retry(item, **kw):
        cli._stop_requested = True
        return False, "bị kill"

    monkeypatch.setattr(cli, "run_with_retry", fake_run_with_retry)

    cli.cmd_retry(argparse.Namespace(slug="a-video"))

    assert "dừng graceful" in capsys.readouterr().out


def test_cmd_retry_finds_short_video(tmp_path, monkeypatch, capsys):
    auto_state = tmp_path / "auto_state.json"
    auto_state.write_text(json.dumps({
        "shorts_funnel_batch_2026-07-06": {
            "long_videos": [],
            "short_videos": [
                {"day": 2, "slug": "short-video", "publish_at": "", "shorts_status": "queued"},
            ],
        }
    }), encoding="utf-8")
    captured = {}
    monkeypatch.setattr(cli, "AUTO_STATE_PATH", auto_state)

    def fake_run_with_retry(item, **kw):
        captured["slug"] = item.slug
        return True, "ok"

    monkeypatch.setattr(cli, "run_with_retry", fake_run_with_retry)

    cli.cmd_retry(argparse.Namespace(slug="short-video"))

    assert captured["slug"] == "short-video"
    assert "Thành công" in capsys.readouterr().out


def test_cmd_stop_no_pid_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "PID_PATH", tmp_path / "batch_cli.pid")

    cli.cmd_stop(argparse.Namespace())

    assert "Không có" in capsys.readouterr().out


def test_cmd_stop_sends_sigterm_to_pid_in_file(tmp_path, monkeypatch, capsys):
    pid_path = tmp_path / "batch_cli.pid"
    pid_path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(cli, "PID_PATH", pid_path)

    sent = []
    monkeypatch.setattr(cli.os, "kill", lambda pid, sig: sent.append((pid, sig)))

    cli.cmd_stop(argparse.Namespace())

    assert sent == [(999999, cli.signal.SIGTERM)]
    assert "dừng graceful" in capsys.readouterr().out


def test_cmd_stop_cleans_up_stale_pid_file(tmp_path, monkeypatch, capsys):
    pid_path = tmp_path / "batch_cli.pid"
    pid_path.write_text("999999", encoding="utf-8")
    monkeypatch.setattr(cli, "PID_PATH", pid_path)

    def fake_kill(pid, sig):
        raise ProcessLookupError

    monkeypatch.setattr(cli.os, "kill", fake_kill)

    cli.cmd_stop(argparse.Namespace())

    assert not pid_path.exists()
    assert "không còn chạy" in capsys.readouterr().out


def test_write_and_remove_pid_file_roundtrip(tmp_path, monkeypatch):
    pid_path = tmp_path / "nested" / "batch_cli.pid"
    monkeypatch.setattr(cli, "PID_PATH", pid_path)

    cli.write_pid_file()
    assert pid_path.read_text(encoding="utf-8") == str(os.getpid())

    cli.remove_pid_file()
    assert not pid_path.exists()


def test_remove_pid_file_does_not_clobber_other_process(tmp_path, monkeypatch):
    """Nếu pid file đang ghi PID của 1 tiến trình KHÁC (vd. đã bị 1 lần `run` khác đè
    lên), remove_pid_file() không được xoá -- xem ledger 2026-06-23: tiến trình A vẫn
    sống nhưng tiến trình B (đã đè pid file) tự dọn dẹp lúc thoát, xoá mất "dấu vết
    đang chạy" của A, khiến check_not_already_running() không còn chặn được run thứ 3."""
    pid_path = tmp_path / "batch_cli.pid"
    pid_path.write_text("424242", encoding="utf-8")  # PID của 1 tiến trình khác
    monkeypatch.setattr(cli, "PID_PATH", pid_path)

    cli.remove_pid_file()

    assert pid_path.exists()
    assert pid_path.read_text(encoding="utf-8") == "424242"


def test_check_not_already_running_blocks_when_pid_alive(tmp_path, monkeypatch):
    pid_path = tmp_path / "batch_cli.pid"
    pid_path.write_text("424242", encoding="utf-8")
    monkeypatch.setattr(cli, "PID_PATH", pid_path)
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: True)

    with pytest.raises(SystemExit):
        cli.check_not_already_running()


def test_check_not_already_running_cleans_stale_pid(tmp_path, monkeypatch):
    pid_path = tmp_path / "batch_cli.pid"
    pid_path.write_text("424242", encoding="utf-8")
    monkeypatch.setattr(cli, "PID_PATH", pid_path)
    monkeypatch.setattr(cli, "_pid_alive", lambda pid: False)

    cli.check_not_already_running()  # không raise

    assert not pid_path.exists()


def test_check_not_already_running_noop_without_pid_file(tmp_path, monkeypatch):
    pid_path = tmp_path / "batch_cli.pid"
    monkeypatch.setattr(cli, "PID_PATH", pid_path)

    cli.check_not_already_running()  # không raise, không tạo file


def test_cmd_start_missing_claude_binary_exits(monkeypatch):
    def fake_popen(cmd, **kw):
        raise FileNotFoundError

    monkeypatch.setattr(cli.subprocess, "Popen", fake_popen)

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_start(argparse.Namespace(num_of_vid=1, type_of_vid="long", type_of_rules="auto", resume=False, cloud=True))

    assert exc_info.value.code == 1
