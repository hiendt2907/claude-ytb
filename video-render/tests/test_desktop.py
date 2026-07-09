"""Tests for the packaged desktop launcher."""

from __future__ import annotations

import sys
from pathlib import Path

from ytb_pipeline import desktop


def test_desktop_log_config_uses_plain_file_formatter(tmp_path: Path) -> None:
    log_config = desktop._desktop_log_config(tmp_path / "desktop.log")

    assert log_config["handlers"]["default"]["class"] == "logging.FileHandler"
    assert "()" not in log_config["formatters"]["default"]


def test_ensure_stdio_replaces_missing_streams(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(desktop, "_log_path", lambda: tmp_path / "desktop.log")
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    log_path = desktop._ensure_stdio()

    assert log_path == tmp_path / "desktop.log"
    assert sys.stdout is not None
    assert sys.stderr is not None
    assert hasattr(sys.stderr, "isatty")


def test_ensure_stdio_creates_log_dir_even_when_streams_are_not_none(monkeypatch, tmp_path: Path) -> None:
    """Bug thật: PyInstaller `--windowed` không đảm bảo sys.stdout/stderr là
    None (có bản trỏ vào devnull thay vì None). Trước đây thư mục log chỉ
    được tạo trong nhánh "is None", nên log_config dùng sau đó crash với
    FileNotFoundError vì thư mục chưa tồn tại — app không khởi động được,
    không có bất kỳ log nào để biết lý do."""
    nested_log_path = tmp_path / "Library" / "Logs" / "Video Render" / "desktop.log"
    monkeypatch.setattr(desktop, "_log_path", lambda: nested_log_path)
    monkeypatch.setattr(sys, "stdout", object())  # không phải None, giống devnull-stream
    monkeypatch.setattr(sys, "stderr", object())

    log_path = desktop._ensure_stdio()

    assert log_path == nested_log_path
    assert nested_log_path.parent.is_dir()


def test_main_reopens_browser_when_our_server_already_running(monkeypatch, tmp_path: Path) -> None:
    calls: list = []

    monkeypatch.setattr(desktop, "_default_working_dir", lambda: tmp_path)
    monkeypatch.setattr(desktop.os, "chdir", lambda p: calls.append(("chdir", p)))
    monkeypatch.setattr(desktop, "_ensure_stdio", lambda: Path("desktop.log"))
    monkeypatch.setattr(desktop, "_our_server_is_running", lambda port: True)
    monkeypatch.setattr(desktop, "_open_browser", lambda port: calls.append(("browser", port)))
    monkeypatch.setattr(
        desktop.uvicorn,
        "run",
        lambda *args, **kwargs: calls.append(("uvicorn", kwargs.get("port"))),
    )

    desktop.main()

    assert calls == [("chdir", tmp_path), ("browser", desktop.DEFAULT_PORT)]


def test_main_falls_back_to_another_port_when_default_taken_by_other_app(monkeypatch, tmp_path: Path) -> None:
    """Bug thật: trước đây chỉ check "có server nào trả lời status < 500" nên
    nếu port mặc định đang bị app KHÁC chiếm (không phải video-render), app cũ
    sẽ tưởng nhầm là chính mình đã chạy và không tự khởi động server thật —
    user mở app nhưng không có gì xảy ra, hoặc mở nhầm trang app khác."""
    calls: list = []

    monkeypatch.setattr(desktop, "_default_working_dir", lambda: tmp_path)
    monkeypatch.setattr(desktop.os, "chdir", lambda p: calls.append(("chdir", p)))
    monkeypatch.setattr(desktop, "_ensure_stdio", lambda: Path("desktop.log"))
    monkeypatch.setattr(desktop, "_our_server_is_running", lambda port: False)
    monkeypatch.setattr(desktop, "_port_is_free", lambda port: port != desktop.DEFAULT_PORT)
    monkeypatch.setattr(desktop, "_find_available_port", lambda: desktop.DEFAULT_PORT + 1)
    monkeypatch.setattr(desktop, "_open_browser", lambda port: calls.append(("browser", port)))
    monkeypatch.setattr(
        desktop.uvicorn,
        "run",
        lambda *args, **kwargs: calls.append(("uvicorn", kwargs.get("port"))),
    )

    class _ImmediateTimer:
        def __init__(self, delay, fn, args=()):
            self._fn = fn
            self._args = args

        def start(self):
            self._fn(*self._args)

    monkeypatch.setattr(desktop.threading, "Timer", _ImmediateTimer)

    desktop.main()

    assert ("chdir", tmp_path) in calls
    assert ("uvicorn", desktop.DEFAULT_PORT + 1) in calls
    assert ("browser", desktop.DEFAULT_PORT + 1) in calls


def test_default_working_dir_creates_and_returns_writable_dir(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(desktop.Path, "home", lambda: tmp_path)

    working_dir = desktop._default_working_dir()

    assert working_dir.is_dir()
    assert working_dir.name == "Video Render"
    assert working_dir.parent.name in {"Movies", "Videos"}
