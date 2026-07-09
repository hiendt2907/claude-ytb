"""Desktop entry point for packaged non-technical installs."""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
from pathlib import Path
from typing import TextIO
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

import uvicorn

from ytb_pipeline.webui.app import app

HOST = "127.0.0.1"
DEFAULT_PORT = 8000
PORT_SCAN_ATTEMPTS = 20


def _app_url(port: int) -> str:
    return f"http://{HOST}:{port}"


def _open_browser(port: int) -> None:
    webbrowser.open(_app_url(port))


def _default_working_dir() -> Path:
    """Thư mục làm việc mặc định khi app chạy dạng đóng gói (double-click).

    GUI launch (`open Foo.app` / double-click Finder) không đảm bảo current
    working directory là gì — thường là `/` hoặc thư mục chỉ đọc bên trong
    app bundle. Web UI mặc định `output_dir` là đường dẫn tương đối
    ("output") khi user chưa tự chọn thư mục lưu kết quả, nên nếu không set
    CWD về một chỗ ghi được trước, render sẽ crash "Read-only file system".
    """
    if sys.platform == "win32":
        base = Path.home() / "Videos"
    else:
        base = Path.home() / "Movies"
    working_dir = base / "Video Render"
    working_dir.mkdir(parents=True, exist_ok=True)
    return working_dir


def _app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "Video Render"
        return Path.home() / "AppData" / "Local" / "Video Render"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Logs" / "Video Render"
    return Path.home() / ".local" / "state" / "video-render"


def _log_path() -> Path:
    return _app_data_dir() / "desktop.log"


def _open_log_stream(log_path: Path) -> TextIO:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path.open("a", encoding="utf-8", buffering=1)


def _ensure_stdio() -> Path:
    log_path = _log_path()
    # Luôn tạo thư mục log trước, không phụ thuộc sys.stdout/sys.stderr có
    # là None hay không — PyInstaller `--windowed` không đảm bảo chúng là
    # None (có bản trỏ vào devnull thay vì None), nên nếu chỉ tạo thư mục
    # trong nhánh "is None", log_config bên dưới sẽ crash vì thư mục chưa
    # tồn tại khi FileHandler cố mở file.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if sys.stdout is None:
        sys.stdout = _open_log_stream(log_path)
    if sys.stderr is None:
        sys.stderr = _open_log_stream(log_path)
    return log_path


def _desktop_log_config(log_path: Path) -> dict:
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)s [%(name)s] %(message)s",
            },
        },
        "handlers": {
            "default": {
                "class": "logging.FileHandler",
                "formatter": "default",
                "filename": str(log_path),
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO", "propagate": False},
        },
        "root": {"handlers": ["default"], "level": "WARNING"},
    }


def _our_server_is_running(port: int) -> bool:
    """Xác minh đúng là video-render đang chạy ở port này, không chỉ là "có
    server nào đó trả lời". Trước đây chỉ check status < 500 nên nếu máy user
    có sẵn app khác (VD dev server cá nhân) đang dùng port 8000, launcher sẽ
    tưởng nhầm video-render "đã chạy" và mở trình duyệt vào đúng app kia."""
    try:
        with urlopen(f"{_app_url(port)}/api/edit-profiles", timeout=0.5) as response:
            if response.status >= 500:
                return False
            data = json.loads(response.read())
            return isinstance(data, dict) and "profiles" in data
    except (OSError, URLError, ValueError):
        return False


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        return probe.connect_ex((HOST, port)) != 0


def _find_available_port() -> int:
    for offset in range(PORT_SCAN_ATTEMPTS):
        port = DEFAULT_PORT + offset
        if _port_is_free(port):
            return port
    # Cực hiếm khi 20 port liền đều bận — để hệ điều hành tự cấp port trống.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((HOST, 0))
        return probe.getsockname()[1]


def main() -> None:
    os.chdir(_default_working_dir())
    log_path = _ensure_stdio()
    if _our_server_is_running(DEFAULT_PORT):
        _open_browser(DEFAULT_PORT)
        return

    port = DEFAULT_PORT if _port_is_free(DEFAULT_PORT) else _find_available_port()
    threading.Timer(1.0, _open_browser, args=(port,)).start()
    uvicorn.run(app, host=HOST, port=port, log_config=_desktop_log_config(log_path))


if __name__ == "__main__":
    main()
