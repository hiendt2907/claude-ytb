"""Regression tests for concurrent F5/MPS batch workers."""

import inspect

import pytest

from ytb_pipeline.voiceover import f5_provider


@pytest.mark.unit
def test_f5_batch_does_not_serialize_workers_with_an_mps_lock():
    """Two batch workers may launch F5 inference concurrently on MPS."""
    assert not hasattr(f5_provider, "f5_device_lock")
    assert "flock" not in inspect.getsource(f5_provider.run_batch)
