"""Regression tests for the machine-wide F5/MPS execution lock."""

import fcntl

import pytest

from ytb_pipeline.voiceover.f5_provider import f5_device_lock


@pytest.mark.unit
def test_f5_device_lock_excludes_another_batch_worker(tmp_path):
    """Two batch workers must not load/infer on the single MPS device together."""
    lock_path = tmp_path / "f5-mps.lock"

    with f5_device_lock(lock_path):
        contender = lock_path.open("a+")
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            contender.close()

    contender = lock_path.open("a+")
    try:
        fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        fcntl.flock(contender.fileno(), fcntl.LOCK_UN)
        contender.close()
