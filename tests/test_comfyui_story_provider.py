"""ComfyUI story provider: workflow shape and HTTP failure handling.

No real network call in this file (project rule: fake providers in unit
tests). `availability_status`/`_run` are exercised against a fake urlopen;
the three workflow builders are exercised as pure functions once `_upload`
is stubbed to skip the network round trip.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from ytb_pipeline.content_profiles import load_content_profile
from ytb_pipeline.providers.errors import ProviderUnavailableError
from ytb_pipeline.providers.image.comfyui_story_provider import ComfyUIStoryProvider


@pytest.fixture
def profile():
    return load_content_profile("ban-so-6")


@pytest.fixture
def provider(monkeypatch):
    p = ComfyUIStoryProvider()
    monkeypatch.setattr(p, "_upload", lambda path: f"uploaded-{Path(path).name}")
    return p


# ---------------------------------------------------------------------------
# Workflow shape — pure, no network once _upload is stubbed
# ---------------------------------------------------------------------------

def test_establishing_workflow_has_no_ipadapter_node(provider, profile):
    workflow = provider._build_establishing(
        profile.visual_generation, "empty cafe counter", 1024, 1024, seed=1
    )

    assert "ipadapter" not in workflow
    assert workflow["sampler"]["inputs"]["model"] == ["ckpt", 0]
    assert workflow["sampler"]["inputs"]["denoise"] == 1.0


def test_solo_workflow_wires_the_character_reference_at_the_profile_weight(provider, profile):
    workflow = provider._build_solo(profile, profile.visual_generation, "minh", "sitting", 832, 1216, seed=2)

    assert workflow["refimg"]["inputs"]["image"] == "uploaded-minh.png"
    assert workflow["ipadapter"]["inputs"]["weight"] == profile.visual_generation.solo_weight
    assert workflow["ipadapter"]["inputs"]["image"] == ["refimg", 0]
    assert workflow["latent"]["inputs"] == {"width": 832, "height": 1216, "batch_size": 1}
    assert workflow["sampler"]["inputs"]["denoise"] == 1.0
    assert "sitting" in workflow["pos"]["inputs"]["text"]
    assert profile.visual_generation.style_prompt in workflow["pos"]["inputs"]["text"]


def test_duo_workflow_chains_both_identities_and_starts_from_the_base_image(provider, profile):
    workflow = provider._build_duo(
        profile, profile.visual_generation, ("minh", "an"), "handing over a paper", 1344, 768, seed=3
    )

    assert workflow["firstimg"]["inputs"]["image"] == "uploaded-minh.png"
    assert workflow["secondimg"]["inputs"]["image"] == "uploaded-an.png"
    assert workflow["baseimg"]["inputs"]["image"] == "uploaded-recognition.png"
    assert workflow["ipa_first"]["inputs"]["model"] == ["ckpt", 0]
    assert workflow["ipa_second"]["inputs"]["model"] == ["ipa_first", 0]
    assert workflow["ipa_first"]["inputs"]["weight"] == profile.visual_generation.duo_weight
    assert workflow["sampler"]["inputs"]["denoise"] == profile.visual_generation.duo_denoise
    assert workflow["sampler"]["inputs"]["latent_image"] == ["vaeencode", 0]
    assert workflow["vaeencode"]["inputs"]["pixels"] == ["baseresize", 0]


def test_generate_scene_rejects_more_than_two_characters(provider, profile, monkeypatch):
    monkeypatch.setattr(provider, "availability_status", lambda: (True, "ok"))

    with pytest.raises(ValueError, match="2 nhân vật"):
        provider.generate_scene(
            profile, characters_present=("minh", "an", "narrator"),
            prompt="x", width=1024, height=1024, seed=1, output_path=Path("/tmp/x.png"),
        )


def test_generate_scene_fails_closed_when_visual_generation_disabled(monkeypatch, tmp_path):
    from tests.test_visual_generation_profile import _vg, _write_profile

    _write_profile(tmp_path, "ban-so-6", visual_generation=_vg(enabled=False))
    from ytb_pipeline.content_profiles import load_content_profile

    disabled = load_content_profile("ban-so-6", profiles_dir=tmp_path)
    provider = ComfyUIStoryProvider()

    with pytest.raises(ProviderUnavailableError, match="visual_generation"):
        provider.generate_scene(
            disabled, characters_present=(), prompt="x", width=1024, height=1024,
            seed=1, output_path=tmp_path / "out.png",
        )


# ---------------------------------------------------------------------------
# HTTP layer — fully faked, no real network
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload: bytes, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _object_info(names):
    return json.dumps({"AnyNode": {"input": {"required": {"model": [names]}}}}).encode()


def test_availability_status_reports_missing_model(monkeypatch):
    provider = ComfyUIStoryProvider()

    def _ok(node: str, field: str, value: str):
        return _FakeResponse(json.dumps({node: {"input": {"required": {field: [[value]]}}}}).encode())

    responses = {
        "/system_stats": _FakeResponse(b"{}"),
        "/object_info/CheckpointLoaderSimple": _ok("CheckpointLoaderSimple", "ckpt_name", "some-other.safetensors"),
        "/object_info/CLIPVisionLoader": _ok("CLIPVisionLoader", "clip_name", "clip-vision.safetensors"),
        "/object_info/IPAdapterModelLoader": _ok("IPAdapterModelLoader", "ipadapter_file", "ipadapter.safetensors"),
    }

    def fake_urlopen(request, timeout=0):
        url = request.full_url if hasattr(request, "full_url") else request
        for suffix, response in responses.items():
            if str(url).endswith(suffix):
                return response
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    ok, detail = provider.availability_status()

    assert ok is False
    assert "thiếu model" in detail


def test_run_raises_on_comfyui_error_status(monkeypatch):
    provider = ComfyUIStoryProvider()
    history = {"abc": {"status": {"status_str": "error", "messages": ["boom"]}, "outputs": {}}}

    def fake_urlopen(request, timeout=0):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        if "/prompt" in url:
            return _FakeResponse(json.dumps({"prompt_id": "abc"}).encode())
        if "/history/abc" in url:
            return _FakeResponse(json.dumps(history).encode())
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    with pytest.raises(ProviderUnavailableError, match="boom"):
        provider._run({"ckpt": {"class_type": "CheckpointLoaderSimple", "inputs": {}}})
