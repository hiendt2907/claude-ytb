"""Phase 11 — production xKiro vision Judge adapter contract tests.

All provider traffic is mocked.  These tests prove that the production
adapter transports real PNG/JPEG bytes rather than asking a text-only model
to infer an image from its filename or generation prompt.
"""
from __future__ import annotations

import base64
import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from urllib import error as urllib_error

import pytest
from PIL import Image

from ytb_pipeline.render.visual_judge import (
    JudgeCandidate,
    JudgeContext,
    JudgeInfrastructureError,
)


def _png(path, color=(20, 80, 180)) -> bytes:
    image = Image.new("RGB", (32, 24), color)
    image.save(path, format="PNG")
    return path.read_bytes()


def _jpeg(path, color=(180, 80, 20)) -> bytes:
    image = Image.new("RGB", (32, 24), color)
    image.save(path, format="JPEG")
    return path.read_bytes()


def _candidate(path, index: int) -> JudgeCandidate:
    payload = path.read_bytes()
    return JudgeCandidate(
        asset_id=f"ast_{index}",
        local_path=str(path),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        candidate_index=index,
    )


def _request():
    return SimpleNamespace(
        visual_intent="Minh đối diện An bên bàn số 6",
        characters=("minh", "an"),
        semantic_constraints=("required object: ceramic cup",),
        dimensions=(1080, 1920),
    )


def _context():
    return JudgeContext(scene_id="scene-003", shot_id="shot-semantic", video_slug="demo")


def _payload(asset_ids, score=0.8):
    return {
        "evaluations": [
            {
                "asset_id": asset_id,
                "semantic_score": score,
                "character_score": score,
                "composition_score": score,
                "continuity_score": score,
                "hard_failures": [],
                "reasons": ["request fidelity is sufficient"],
            }
            for asset_id in asset_ids
        ]
    }


class _RecordingTransport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.verified_models = []

    def verify_vision_model(self, model):
        self.verified_models.append(model)

    def complete(self, *, model, system, content):
        self.calls.append({"model": model, "system": system, "content": content})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def test_adapter_attaches_real_png_and_jpeg_bytes_with_unambiguous_mapping(tmp_path):
    from ytb_pipeline.providers.vision.xkiro_provider import XkiroVisualJudge

    png_path = tmp_path / "candidate-a.png"
    jpg_path = tmp_path / "candidate-b.jpg"
    png_bytes = _png(png_path)
    jpg_bytes = _jpeg(jpg_path)
    candidates = (_candidate(png_path, 0), _candidate(jpg_path, 1))
    transport = _RecordingTransport([json.dumps(_payload(["ast_0", "ast_1"]))])

    result = XkiroVisualJudge("qwen/qwen3.8-max:free", transport=transport).evaluate(
        _request(), candidates, _context()
    )

    assert [evaluation.asset_id for evaluation in result.evaluations] == ["ast_0", "ast_1"]
    assert transport.verified_models == ["qwen/qwen3.8-max:free"]
    parts = transport.calls[0]["content"]
    image_parts = [part for part in parts if part["type"] == "image_url"]
    text = "\n".join(part["text"] for part in parts if part["type"] == "text")
    assert len(image_parts) == 2
    assert "candidate_index=0 asset_id=ast_0" in text
    assert "candidate_index=1 asset_id=ast_1" in text
    assert text.index("asset_id=ast_0") < text.index("asset_id=ast_1")
    assert "scene-003" in text and "shot-semantic" in text
    assert "ceramic cup" in text and "minh, an" in text
    encoded = [part["image_url"]["url"] for part in image_parts]
    assert encoded[0].startswith("data:image/png;base64,")
    assert encoded[1].startswith("data:image/jpeg;base64,")
    assert base64.b64decode(encoded[0].split(",", 1)[1]) == png_bytes
    assert base64.b64decode(encoded[1].split(",", 1)[1]) == jpg_bytes
    assert str(png_path) not in text and str(jpg_path) not in text


def test_adapter_routes_output_through_phase10_strict_parser(tmp_path):
    from ytb_pipeline.providers.vision.xkiro_provider import XkiroVisualJudge

    path = tmp_path / "candidate.png"
    _png(path)
    invalid = _payload(["ast_unknown"])
    transport = _RecordingTransport([json.dumps(invalid), json.dumps(invalid)])

    with pytest.raises(JudgeInfrastructureError, match="sau 1 lần repair"):
        XkiroVisualJudge("qwen/qwen3.8-max:free", transport=transport).evaluate(
            _request(), (_candidate(path, 0),), _context()
        )

    assert len(transport.calls) == 2
    assert "Phản hồi trước không hợp lệ" in "\n".join(
        part["text"] for part in transport.calls[1]["content"] if part["type"] == "text"
    )


def test_adapter_repairs_once_then_accepts_valid_strict_output(tmp_path):
    from ytb_pipeline.providers.vision.xkiro_provider import XkiroVisualJudge

    path = tmp_path / "candidate.png"
    _png(path)
    transport = _RecordingTransport(["not json", json.dumps(_payload(["ast_0"]))])

    result = XkiroVisualJudge("qwen/qwen3.8-max:free", transport=transport).evaluate(
        _request(), (_candidate(path, 0),), _context()
    )

    assert result.evaluations[0].asset_id == "ast_0"
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        urllib_error.URLError("network down"),
    ],
)
def test_http_transport_maps_timeout_and_network_errors(monkeypatch, error):
    from ytb_pipeline.providers.vision.xkiro_provider import XkiroVisionTransport

    monkeypatch.setattr("ytb_pipeline.providers.vision.xkiro_provider.urllib_request.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(error))
    transport = XkiroVisionTransport(api_key="test-key")

    with pytest.raises(JudgeInfrastructureError):
        transport.complete(model="qwen/qwen3.8-max:free", system="system", content=({"type": "text", "text": "prompt"},))


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "authentication"), (403, "authentication"), (413, "payload too large"), (429, "rate limit"), (503, "unavailable")],
)
def test_http_transport_maps_provider_statuses(monkeypatch, status, message):
    from ytb_pipeline.providers.vision.xkiro_provider import XkiroVisionTransport

    error = urllib_error.HTTPError("https://api.xkiro.com/v1/chat/completions", status, "error", {}, BytesIO(b"{}"))
    monkeypatch.setattr("ytb_pipeline.providers.vision.xkiro_provider.urllib_request.urlopen", lambda *_a, **_k: (_ for _ in ()).throw(error))
    transport = XkiroVisionTransport(api_key="test-key")

    with pytest.raises(JudgeInfrastructureError, match=message):
        transport.complete(model="qwen/qwen3.8-max:free", system="system", content=({"type": "text", "text": "prompt"},))


def test_capability_probe_rejects_text_only_or_unknown_model(monkeypatch):
    from ytb_pipeline.providers.vision.xkiro_provider import XkiroVisionTransport

    catalog = {
        "data": [
            {"id": "deepseek/deepseek-v4-pro", "capabilities": {"vision": False}},
            {"id": "qwen/qwen3.8-max:free", "capabilities": {"vision": True}},
        ]
    }

    class _Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def read(self): return json.dumps(catalog).encode()

    monkeypatch.setattr("ytb_pipeline.providers.vision.xkiro_provider.urllib_request.urlopen", lambda *_a, **_k: _Response())
    transport = XkiroVisionTransport(api_key="test-key")
    transport.verify_vision_model("qwen/qwen3.8-max:free")
    with pytest.raises(JudgeInfrastructureError, match="vision=false"):
        transport.verify_vision_model("deepseek/deepseek-v4-pro")
    with pytest.raises(JudgeInfrastructureError, match="không có trong catalog"):
        transport.verify_vision_model("missing/model")


def test_adapter_rejects_changed_oversized_and_unsupported_candidate_media(tmp_path):
    from ytb_pipeline.providers.vision.xkiro_provider import XkiroVisualJudge

    transport = _RecordingTransport([])
    path = tmp_path / "candidate.png"
    _png(path)
    stale = _candidate(path, 0)
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(JudgeInfrastructureError, match="SHA-256"):
        XkiroVisualJudge("qwen/qwen3.8-max:free", transport=transport).evaluate(_request(), (stale,), _context())

    unsupported = tmp_path / "candidate.webp"
    unsupported.write_bytes(b"RIFFfake-webp")
    with pytest.raises(JudgeInfrastructureError, match="PNG/JPEG"):
        XkiroVisualJudge("qwen/qwen3.8-max:free", transport=transport).evaluate(
            _request(), (_candidate(unsupported, 0),), _context()
        )

    large = tmp_path / "large.png"
    large.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    with pytest.raises(JudgeInfrastructureError, match="quá lớn"):
        XkiroVisualJudge("qwen/qwen3.8-max:free", transport=transport, max_image_bytes=32).evaluate(
            _request(), (_candidate(large, 0),), _context()
        )


def test_registry_advertises_only_real_vision_judge_capability():
    from ytb_pipeline.providers.vision import available_visual_judges, get_visual_judge
    from ytb_pipeline.providers.vision.xkiro_provider import XkiroVisualJudge

    assert "xkiro" in available_visual_judges()
    assert isinstance(get_visual_judge("xkiro", "qwen/qwen3.8-max:free"), XkiroVisualJudge)
    with pytest.raises(ValueError, match="vision judge"):
        get_visual_judge("text-only", "deepseek/deepseek-v4-pro")
