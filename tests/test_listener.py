"""Test bộ công cụ Telegram ⇄ Claude (listener).

Không gọi mạng/subprocess thật — monkeypatch send_message + Popen/run.
"""

from __future__ import annotations

import pytest

from ytb_pipeline import listener
from ytb_pipeline.config.settings import settings


@pytest.fixture(autouse=True)
def _capture_sends(monkeypatch):
    sent: list[str] = []
    monkeypatch.setattr(listener.telegram, "send_message", lambda t: sent.append(t))
    # mỗi test bắt đầu với job rảnh
    listener._Job.proc = None
    listener._Job.label = None
    return sent


@pytest.fixture(autouse=True)
def _no_spawn(monkeypatch):
    """Chặn spawn thật, ghi lại (label, cmd) để assert."""
    calls: list[tuple[str, list[str]]] = []
    monkeypatch.setattr(listener, "_spawn", lambda label, cmd: calls.append((label, cmd)))
    return calls


# ── router ────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("word", ["/help", "/ping", "/status", "?"])
def test_control_words_handled_no_spawn(word, _capture_sends, _no_spawn):
    assert listener._dispatch(word) is None
    assert _no_spawn == []
    assert len(_capture_sends) == 1


def test_free_text_spawns_claude(_no_spawn):
    assert listener._dispatch("tóm tắt repo này") is None
    assert len(_no_spawn) == 1
    label, cmd = _no_spawn[0]
    assert cmd[-2:] == ["-p", "tóm tắt repo này"]


def test_ask_strips_verb(_no_spawn):
    listener._dispatch("/ask sửa bug X")
    _, cmd = _no_spawn[0]
    assert cmd[-1] == "sửa bug X"


def test_cont_adds_continue(_no_spawn):
    listener._dispatch("/cont làm tiếp")
    _, cmd = _no_spawn[0]
    assert "--continue" in cmd


def test_auto_returns_instruction_for_interactive(_no_spawn):
    # /auto KHÔNG spawn nền — trả (kind, payload) để caller chạy đồng bộ
    assert listener._dispatch("/auto làm 1 clip dài") == ("auto", "làm 1 clip dài")
    assert _no_spawn == []


def test_auto_without_arg_shows_usage_not_run(_no_spawn, _capture_sends):
    # /auto trơn KHÔNG chạy skill — báo cú pháp
    assert listener._dispatch("/auto") is None
    assert _no_spawn == []
    assert any("Cú pháp" in m for m in _capture_sends)


def test_sh_respects_toggle(monkeypatch, _no_spawn, _capture_sends):
    monkeypatch.setattr(settings, "listener_allow_shell", False)
    listener._dispatch("/sh rm -rf /")
    assert _no_spawn == []
    assert any("bị tắt" in m for m in _capture_sends)

    monkeypatch.setattr(settings, "listener_allow_shell", True)
    listener._dispatch("/sh ls")
    assert _no_spawn and _no_spawn[-1][1] == ["bash", "-lc", "ls"]


# ── /batch ────────────────────────────────────────────────────────────────────
def test_batch_status_spawns_background_job(_no_spawn):
    assert listener._dispatch("/batch status") is None
    label, cmd = _no_spawn[0]
    assert label.startswith("batch:")
    assert cmd[-1] == "status"
    assert "ytb_pipeline.orchestrator.batch_cli" in cmd


def test_batch_run_loop_spawns_with_args(_no_spawn):
    listener._dispatch("/batch run --loop")
    _, cmd = _no_spawn[0]
    assert cmd[-2:] == ["run", "--loop"]


def test_batch_without_arg_shows_command_list(_no_spawn, _capture_sends):
    assert listener._dispatch("/batch") is None
    assert _no_spawn == []
    assert any("ytb batch" in m for m in _capture_sends)


def test_batch_start_returns_instruction_for_interactive(_no_spawn):
    result = listener._dispatch("/batch start -n 5 --type-of-vid long")
    assert result == ("batch_start", "start -n 5 --type-of-vid long")
    assert _no_spawn == []


def test_batch_start_rejected_when_busy(_no_spawn, _capture_sends):
    class _FakeProc:
        def poll(self):
            return None

    listener._Job.proc, listener._Job.label = _FakeProc(), "claude: x"
    result = listener._dispatch("/batch start -n 1")
    assert result is None
    assert _no_spawn == []
    assert any("Đang bận" in m for m in _capture_sends)


def test_ytb_cmd_returns_wizard_instruction(_no_spawn, _capture_sends):
    # /ytb-cmd KHÔNG gửi text tĩnh — trả (kind, payload) để caller chạy wizard nút bấm
    assert listener._dispatch("/ytb-cmd") == ("ytb_wizard", "")
    assert _no_spawn == []
    assert _capture_sends == []


def test_ytb_cmd_rejected_when_busy(_no_spawn, _capture_sends):
    class _FakeProc:
        def poll(self):
            return None

    listener._Job.proc, listener._Job.label = _FakeProc(), "claude: x"
    assert listener._dispatch("/ytb-cmd") is None
    assert _no_spawn == []
    assert any("Đang bận" in m for m in _capture_sends)


# ── wizard /ytb-cmd ───────────────────────────────────────────────────────────
def test_wizard_cancel_sends_message(monkeypatch, _capture_sends):
    monkeypatch.setattr(listener.telegram, "ask_choice", lambda q, opts: listener._CANCEL)
    listener._run_ytb_wizard()
    assert any("hủy" in m.lower() for m in _capture_sends)


def test_wizard_status_spawns_no_extra_questions(monkeypatch, _no_spawn):
    choices = iter(["status"])
    monkeypatch.setattr(listener.telegram, "ask_choice", lambda q, opts: next(choices))
    listener._run_ytb_wizard()
    _, cmd = _no_spawn[0]
    assert cmd[-1] == "status"


def test_wizard_start_collects_answers_and_runs_sync(monkeypatch):
    choices = iter(["start", "long", "Tự để Claude chọn (auto)"])
    texts = iter(["5"])
    captured = {}

    monkeypatch.setattr(listener.telegram, "ask_choice", lambda q, opts: next(choices))
    monkeypatch.setattr(listener.telegram, "ask_text", lambda q: next(texts))
    monkeypatch.setattr(
        listener, "_run_batch_start_sync", lambda args_str: captured.setdefault("args", args_str)
    )

    listener._run_ytb_wizard()

    assert captured["args"] == "start -n 5 --type-of-vid long --type-of-rules auto"


def test_wizard_run_loop_choice(monkeypatch, _no_spawn):
    choices = iter(["run", "Hết queue (--loop)"])
    monkeypatch.setattr(listener.telegram, "ask_choice", lambda q, opts: next(choices))
    listener._run_ytb_wizard()
    _, cmd = _no_spawn[0]
    assert cmd[-2:] == ["run", "--loop"]


def test_wizard_retry_asks_slug(monkeypatch, _no_spawn):
    choices = iter(["retry"])
    monkeypatch.setattr(listener.telegram, "ask_choice", lambda q, opts: next(choices))
    monkeypatch.setattr(listener.telegram, "ask_text", lambda q: "ten-slug")
    listener._run_ytb_wizard()
    _, cmd = _no_spawn[0]
    assert cmd[-2:] == ["retry", "ten-slug"]


# ── stop ──────────────────────────────────────────────────────────────────────
def test_stop_when_idle(_capture_sends):
    listener._dispatch("/stop")
    assert any("Không có job" in m for m in _capture_sends)


def test_stop_terminates_running(_capture_sends):
    class _FakeProc:
        def __init__(self):
            self.terminated = False

        def poll(self):
            return None  # đang chạy

        def terminate(self):
            self.terminated = True

    proc = _FakeProc()
    listener._Job.proc, listener._Job.label = proc, "claude: x"
    listener._dispatch("/stop")
    assert proc.terminated
    assert any("Đã yêu cầu dừng" in m for m in _capture_sends)


def test_wizard_run_loop_schedule(monkeypatch, _no_spawn):
    choices = iter(["run", "Hết queue + tự xếp lịch (--loop --schedule)"])
    monkeypatch.setattr(listener.telegram, "ask_choice", lambda q, opts: next(choices))

    listener._run_ytb_wizard()

    _, cmd = _no_spawn[0]
    assert cmd[-3:] == ["run", "--loop", "--schedule"]


def test_status_includes_pipeline_progress_line(_capture_sends, _no_spawn):
    listener._dispatch("/status")

    assert len(_capture_sends) == 1
    assert "🎬 Pipeline:" in _capture_sends[0]
