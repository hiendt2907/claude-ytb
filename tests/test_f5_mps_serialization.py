"""Regression coverage for F5's MPS-only internal inference serialization."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


_WORKER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "f5_batch_worker.py"
_SPEC = importlib.util.spec_from_file_location("f5_batch_worker_serialization", _WORKER_PATH)
worker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)


def test_mps_executor_adapter_serializes_only_f5_internal_batches():
    upstream = SimpleNamespace(ThreadPoolExecutor=object())

    worker._configure_f5_inference_executor("mps", upstream)
    executor = upstream.ThreadPoolExecutor()
    try:
        assert executor._max_workers == 1
    finally:
        executor.shutdown()



def test_cpu_executor_adapter_leaves_upstream_executor_unchanged():
    original = object()
    upstream = SimpleNamespace(ThreadPoolExecutor=original)

    worker._configure_f5_inference_executor("cpu", upstream)

    assert upstream.ThreadPoolExecutor is original
