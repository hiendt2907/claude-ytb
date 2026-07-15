"""Process-safe, atomic persistence helpers for batch state files."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, TypeVar

T = TypeVar("T")


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Hold an advisory exclusive lock in a sidecar file until the body exits."""
    lock_path = path.with_name(f".{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str) -> None:
    """Replace *path* atomically, flushing the temporary file before rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as temporary:
            temporary.write(text)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, data: T) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def locked_json_update(path: Path) -> Iterator[dict]:
    """Read, exclusively lock, and atomically persist a JSON object on success."""
    with file_lock(path):
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object in {path}")
        yield data
        atomic_write_json(path, data)


def locked_append_text(path: Path, text: str) -> None:
    """Append one logical record while preventing concurrent interleaving."""
    with file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
