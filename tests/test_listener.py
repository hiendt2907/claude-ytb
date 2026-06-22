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


# ── dựng lệnh ─────────────────────────────────────────────────────────────────
def test_claude_cmd_default_bypass_permissions(monkeypatch):
    monkeypatch.setattr(settings, "claude_bin", "claude")
    monkeypatch.setattr(settings, "listener_claude_args", "--dangerously-skip-permissions")

    cmd = listener._claude_cmd("xin chào")

    assert cmd == ["claude", "--dangerously-skip-permissions", "-p", "xin chào"]


def test_claude_cmd_continue_flag(monkeypatch):
    monkeypatch.setattr(settings, "claude_bin", "claude")
    monkeypatch.setattr(settings, "listener_claude_args", "")

    cmd = listener._claude_cmd("tiếp", cont=True)

    assert cmd == ["claude", "--continue", "-p", "tiếp"]


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
    # /auto KHÔNG spawn nền — trả instruction để caller chạy đồng bộ
    assert listener._dispatch("/auto làm 1 clip dài") == "làm 1 clip dài"
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
