"""Tests cho Project Model (Phase 2): CheckpointManager, CacheManager,
WorkflowGraph, và serialization của Project/WorkflowNode.
"""

import asyncio

import pytest

from ytb_pipeline.project.cache import CacheManager
from ytb_pipeline.project.checkpoint import CheckpointManager
from ytb_pipeline.project.models import NodeStatus, Project, ProjectStatus, WorkflowNode
from ytb_pipeline.project.workflow import NodeDef, WorkflowError, WorkflowGraph


# ---------------------------------------------------------------------------
# CheckpointManager
# ---------------------------------------------------------------------------


def test_load_missing_project_returns_none(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    assert checkpoint.load("does-not-exist") is None


def test_save_and_load_roundtrip(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    project = Project(project_id="my-video", status=ProjectStatus.DRAFT)

    checkpoint.save(project)
    loaded = checkpoint.load("my-video")

    assert loaded is not None
    assert loaded.project_id == "my-video"
    assert loaded.status == ProjectStatus.DRAFT


def test_save_writes_atomically_via_tmp_rename(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    project = Project(project_id="atomic-test")

    checkpoint.save(project)

    final_path = tmp_path / "atomic-test" / "project.json"
    tmp_path_file = tmp_path / "atomic-test" / "project.json.tmp"
    assert final_path.exists()
    assert not tmp_path_file.exists()


def test_mark_running_sets_status_and_started_at(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    project = Project(project_id="p1")

    updated = checkpoint.mark_running(project, "ideation")

    node = updated.nodes["ideation"]
    assert node.status == NodeStatus.RUNNING
    assert node.started_at is not None


def test_mark_done_sets_status_output_ref_completed_at(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    project = Project(project_id="p1")

    updated = checkpoint.mark_running(project, "ideation")
    updated = checkpoint.mark_done(updated, "ideation", "scripts/foo.json")

    node = updated.nodes["ideation"]
    assert node.status == NodeStatus.DONE
    assert node.output_ref == "scripts/foo.json"
    assert node.completed_at is not None


def test_mark_done_preserves_rich_output_data(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    project = Project(project_id="p1")

    updated = checkpoint.mark_done(
        project,
        "voiceover",
        "assets/audio/foo.mp3",
        {"duration_sec": 12.5, "segments": [{"index": 0, "duration_sec": 12.5}]},
    )

    assert updated.nodes["voiceover"].output_data["duration_sec"] == 12.5
    assert checkpoint.get_output_data(updated, "voiceover")["segments"][0]["index"] == 0


def test_mark_failed_sets_error_and_increments_retry_count(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    project = Project(project_id="p1")

    updated = checkpoint.mark_failed(project, "voiceover", "TTS timeout")
    assert updated.nodes["voiceover"].retry_count == 1
    assert updated.nodes["voiceover"].error == "TTS timeout"

    updated = checkpoint.mark_failed(updated, "voiceover", "TTS timeout again")
    assert updated.nodes["voiceover"].retry_count == 2
    assert updated.nodes["voiceover"].status == NodeStatus.FAILED


def test_is_done_true_only_when_node_status_done(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    project = Project(project_id="p1")

    assert checkpoint.is_done(project, "ideation") is False

    running = checkpoint.mark_running(project, "ideation")
    assert checkpoint.is_done(running, "ideation") is False

    done = checkpoint.mark_done(running, "ideation", "out.json")
    assert checkpoint.is_done(done, "ideation") is True


def test_get_output_returns_ref_for_done_node(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    project = Project(project_id="p1")

    assert checkpoint.get_output(project, "render") is None

    done = checkpoint.mark_done(project, "render", "assets/output/v1.mp4")
    assert checkpoint.get_output(done, "render") == "assets/output/v1.mp4"


def test_save_load_preserves_node_state_across_restart(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    project = Project(project_id="resumable")
    project = checkpoint.mark_done(project, "ideation", "script.json")
    checkpoint.save(project)

    # Simulate fresh process: new CheckpointManager instance.
    fresh_checkpoint = CheckpointManager(tmp_path)
    loaded = fresh_checkpoint.load("resumable")

    assert fresh_checkpoint.is_done(loaded, "ideation") is True
    assert fresh_checkpoint.get_output(loaded, "ideation") == "script.json"


# ---------------------------------------------------------------------------
# CacheManager
# ---------------------------------------------------------------------------


def test_cache_key_is_deterministic(tmp_path):
    cache = CacheManager(tmp_path)
    key1 = cache.key(prompt="hello", model="gpt", temperature=0.5)
    key2 = cache.key(prompt="hello", model="gpt", temperature=0.5)
    assert key1 == key2


def test_cache_key_is_order_independent(tmp_path):
    cache = CacheManager(tmp_path)
    key1 = cache.key(prompt="hello", model="gpt")
    key2 = cache.key(model="gpt", prompt="hello")
    assert key1 == key2


def test_cache_key_different_params_yield_different_keys(tmp_path):
    cache = CacheManager(tmp_path)
    key1 = cache.key(prompt="hello", model="gpt")
    key2 = cache.key(prompt="world", model="gpt")
    assert key1 != key2


def test_cache_get_missing_returns_none(tmp_path):
    cache = CacheManager(tmp_path)
    assert cache.get("nonexistent-key", "mp3") is None


def test_cache_put_and_get_roundtrip(tmp_path):
    cache_dir = tmp_path / "cache"
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    source_file = source_dir / "audio.mp3"
    source_file.write_bytes(b"fake-audio-bytes")

    cache = CacheManager(cache_dir)
    key = cache.key(text="hello")

    cached_path = cache.put(key, "mp3", source_file)
    assert cached_path.exists()
    assert cached_path.read_bytes() == b"fake-audio-bytes"

    retrieved = cache.get(key, "mp3")
    assert retrieved == cached_path


def test_cache_has_reflects_put(tmp_path):
    cache_dir = tmp_path / "cache"
    source = tmp_path / "x.mp4"
    source.write_bytes(b"video")

    cache = CacheManager(cache_dir)
    key = cache.key(a=1)

    assert cache.has(key, "mp4") is False
    cache.put(key, "mp4", source)
    assert cache.has(key, "mp4") is True


def test_cache_stats_reports_total_files_and_bytes(tmp_path):
    cache_dir = tmp_path / "cache"
    source = tmp_path / "a.mp3"
    source.write_bytes(b"12345")

    cache = CacheManager(cache_dir)
    key = cache.key(x="y")
    cache.put(key, "mp3", source)

    stats = cache.stats()
    assert stats["total_files"] == 1
    assert stats["total_bytes"] == 5


def test_cache_stats_hit_rate_tracks_session_lookups(tmp_path):
    cache_dir = tmp_path / "cache"
    source = tmp_path / "a.mp3"
    source.write_bytes(b"data")

    cache = CacheManager(cache_dir)
    key = cache.key(x="y")
    cache.put(key, "mp3", source)

    cache.get(key, "mp3")  # hit
    cache.get("missing", "mp3")  # miss

    stats = cache.stats()
    assert stats["hit_rate_this_session"] == 0.5


# ---------------------------------------------------------------------------
# WorkflowNode / Project serialization
# ---------------------------------------------------------------------------


def test_workflow_node_to_dict_from_dict_roundtrip():
    node = WorkflowNode(
        node_id="ideation",
        stage="ideation",
        status=NodeStatus.DONE,
        output_ref="script.json",
        retry_count=2,
    )
    restored = WorkflowNode.from_dict(node.to_dict())
    assert restored == node


def test_project_to_dict_from_dict_roundtrip():
    project = Project(
        project_id="p1",
        status=ProjectStatus.RENDERING,
        script_path="scripts/p1.json",
        metadata={"slug": "p1"},
    )
    project = project.with_node(WorkflowNode(node_id="ideation", stage="ideation"))

    restored = Project.from_dict(project.to_dict())

    assert restored.project_id == project.project_id
    assert restored.status == ProjectStatus.RENDERING
    assert restored.nodes["ideation"].stage == "ideation"


def test_project_status_enum_serializes_as_string_value():
    project = Project(project_id="p1", status=ProjectStatus.PUBLISHED)
    assert project.to_dict()["status"] == "published"


# ---------------------------------------------------------------------------
# WorkflowGraph
# ---------------------------------------------------------------------------


def test_topo_sort_respects_dependencies(tmp_path):
    checkpoint = CheckpointManager(tmp_path)

    async def fn(project):
        return "ok"

    nodes = [
        NodeDef(node_id="publish", stage="publish", fn=fn, deps=["render"]),
        NodeDef(node_id="render", stage="render", fn=fn, deps=["voiceover"]),
        NodeDef(node_id="voiceover", stage="voiceover", fn=fn, deps=["ideation"]),
        NodeDef(node_id="ideation", stage="ideation", fn=fn, deps=[]),
    ]
    graph = WorkflowGraph(nodes, checkpoint)

    order = graph._topo_sort()

    assert order.index("ideation") < order.index("voiceover")
    assert order.index("voiceover") < order.index("render")
    assert order.index("render") < order.index("publish")


def test_execute_skips_done_nodes(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    calls = []

    def make_fn(name):
        async def fn(project):
            calls.append(name)
            return name

        return fn

    nodes = [
        NodeDef(node_id="ideation", stage="ideation", fn=make_fn("ideation"), deps=[]),
        NodeDef(node_id="voiceover", stage="voiceover", fn=make_fn("voiceover"), deps=["ideation"]),
    ]
    graph = WorkflowGraph(nodes, checkpoint)

    project = Project(project_id="skip-test")
    project = checkpoint.mark_done(project, "ideation", "already-done.json")

    asyncio.run(graph.execute(project))

    assert "ideation" not in calls
    assert "voiceover" in calls


def test_execute_runs_nodes_in_topological_order(tmp_path):
    checkpoint = CheckpointManager(tmp_path)
    call_order = []

    def make_fn(name):
        async def fn(project):
            call_order.append(name)
            return name

        return fn

    nodes = [
        NodeDef(node_id="b", stage="b", fn=make_fn("b"), deps=["a"]),
        NodeDef(node_id="a", stage="a", fn=make_fn("a"), deps=[]),
        NodeDef(node_id="c", stage="c", fn=make_fn("c"), deps=["b"]),
    ]
    graph = WorkflowGraph(nodes, checkpoint)
    project = Project(project_id="order-test")

    asyncio.run(graph.execute(project))

    assert call_order == ["a", "b", "c"]


def test_execute_marks_node_done_with_output_ref(tmp_path):
    checkpoint = CheckpointManager(tmp_path)

    async def fn(project):
        return "produced-output"

    nodes = [NodeDef(node_id="solo", stage="solo", fn=fn, deps=[])]
    graph = WorkflowGraph(nodes, checkpoint)
    project = Project(project_id="output-test")

    result = asyncio.run(graph.execute(project))

    assert result.nodes["solo"].status == NodeStatus.DONE
    assert result.nodes["solo"].output_ref == "produced-output"


def test_execute_marks_project_published_after_all_nodes_complete(tmp_path):
    """A completed checkpoint must not remain indistinguishable from a draft."""
    checkpoint = CheckpointManager(tmp_path)

    async def fn(project):
        return "published-url"

    graph = WorkflowGraph(
        [NodeDef(node_id="publish", stage="publish", fn=fn, deps=[])],
        checkpoint,
    )

    result = asyncio.run(graph.execute(Project(project_id="completed-project")))

    assert result.status == ProjectStatus.PUBLISHED
    persisted = checkpoint.load("completed-project")
    assert persisted is not None
    assert persisted.status == ProjectStatus.PUBLISHED


def test_execute_accepts_node_output_data_tuple(tmp_path):
    checkpoint = CheckpointManager(tmp_path)

    async def fn(project):
        return "produced-output", {"duration_sec": 3.0}

    nodes = [NodeDef(node_id="solo", stage="solo", fn=fn, deps=[])]
    graph = WorkflowGraph(nodes, checkpoint)
    project = Project(project_id="output-data-test")

    result = asyncio.run(graph.execute(project))

    assert result.nodes["solo"].output_ref == "produced-output"
    assert result.nodes["solo"].output_data == {"duration_sec": 3.0}


def test_execute_raises_workflow_error_on_node_failure(tmp_path):
    checkpoint = CheckpointManager(tmp_path)

    async def failing_fn(project):
        raise RuntimeError("boom")

    nodes = [NodeDef(node_id="bad", stage="bad", fn=failing_fn, deps=[])]
    graph = WorkflowGraph(nodes, checkpoint)
    project = Project(project_id="fail-test")

    with pytest.raises(WorkflowError) as exc_info:
        asyncio.run(graph.execute(project))

    assert exc_info.value.node_id == "bad"
    assert "boom" in exc_info.value.error


def test_execute_persists_failed_status_to_checkpoint(tmp_path):
    checkpoint = CheckpointManager(tmp_path)

    async def failing_fn(project):
        raise RuntimeError("disk full")

    nodes = [NodeDef(node_id="bad", stage="bad", fn=failing_fn, deps=[])]
    graph = WorkflowGraph(nodes, checkpoint)
    project = Project(project_id="persist-fail-test")

    with pytest.raises(WorkflowError):
        asyncio.run(graph.execute(project))

    reloaded = checkpoint.load("persist-fail-test")
    assert reloaded.nodes["bad"].status == NodeStatus.FAILED
    assert reloaded.nodes["bad"].error == "disk full"


def test_ready_nodes_excludes_nodes_with_pending_deps(tmp_path):
    checkpoint = CheckpointManager(tmp_path)

    async def fn(project):
        return "ok"

    nodes = [
        NodeDef(node_id="a", stage="a", fn=fn, deps=[]),
        NodeDef(node_id="b", stage="b", fn=fn, deps=["a"]),
    ]
    graph = WorkflowGraph(nodes, checkpoint)
    project = Project(project_id="ready-test")

    ready = graph._ready_nodes(project)
    assert ready == ["a"]
