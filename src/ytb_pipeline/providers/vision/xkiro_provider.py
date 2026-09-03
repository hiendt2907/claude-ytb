"""Production xKiro multimodal adapter for the Phase-10 ``VisualJudge`` port.

xKiro's OpenAI-compatible Chat Completions endpoint accepts image content as
``image_url`` parts, including base64 data URLs.  This adapter sends every
technically-valid candidate for one Shot in a single comparative request.  It
never mutates the original media and never creates an ``AssetRecord`` for its
transport bytes.

The configured model is checked against xKiro's live ``GET /v1/models``
catalog before any image request.  Merely sharing ``/chat/completions`` with a
text model is not treated as evidence of vision capability.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from PIL import Image, UnidentifiedImageError

from ...config.settings import settings
from ...render.visual_judge import (
    KNOWN_HARD_FAILURE_CODES,
    JudgeCandidate,
    JudgeContext,
    JudgeInfrastructureError,
    JudgeMalformedResponseError,
    JudgeResult,
    parse_judge_payload,
)

logger = logging.getLogger(__name__)

DEFAULT_MAX_IMAGE_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_IMAGE_PIXELS = 16_000_000
DEFAULT_TIMEOUT_SEC = 90.0
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"

_SYSTEM_PROMPT = (
    "Bạn là VisualJudge đánh giá ảnh cho pipeline sản xuất video. Chỉ đánh "
    "giá độ khớp VisualRequest, nhân vật/vật thể/hành động/môi trường bắt "
    "buộc, bố cục phù hợp, continuity có căn cứ, mâu thuẫn ngữ nghĩa và chữ "
    "bắt buộc có đọc được hay không. Không đánh giá vẻ đẹp, sức hấp dẫn, cơ "
    "thể, độ tuổi, giới tính hay chủng tộc. Trả DUY NHẤT một object JSON đúng "
    "schema được yêu cầu; không markdown hay prose bên ngoài JSON."
)


# Một Long gọi Judge khoảng 250 lần; xác suất gặp ít nhất một lỗi thoáng qua
# gần như chắc chắn. Trước đây một lần timeout giết cả node `visual_assets`
# sau khi ảnh đã sinh xong — mất toàn bộ công của node (đo thật 2026-09-01).
# Ba lượt là đủ cho lỗi thoáng qua; hơn nữa chỉ kéo dài một gateway đã chết.
MAX_TRANSPORT_ATTEMPTS = 3
_RETRY_BACKOFF_SEC = (1.0, 3.0)

# 5xx = phía provider hỏng, 429 = tạm hết lượt: cả hai đều có thể qua ở lần
# sau. 401/403 (sai khoá) và 413 (payload quá lớn) thì hỏi lại bao nhiêu lần
# cũng vậy — retry chỉ làm chậm và che mất nguyên nhân thật.
# "Lỗi server" phải có MỘT định nghĩa trong file này. `_provider_error_message`
# coi mọi status >= 500 là "provider unavailable"; retry từng liệt kê một tập
# con, nên một 5xx ngoài tập (520/521/529 của Cloudflare) báo unavailable mà
# không bao giờ được hỏi lại. Đo 2026-09-04: node visual_assets chết vì đúng
# thế, 0 dòng retry trong log, và endpoint sống lại ngay khi probe.
_RETRYABLE_STATUSES = frozenset({429})


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, urllib_error.HTTPError):
        return exc.code >= 500 or exc.code in _RETRYABLE_STATUSES
    return isinstance(exc, (urllib_error.URLError, TimeoutError))


def _provider_error_message(status: int) -> str:
    if status in {401, 403}:
        return "xKiro vision authentication failed."
    if status == 413:
        return "xKiro vision payload too large."
    if status == 429:
        return "xKiro vision rate limit exceeded."
    if status >= 500:
        return "xKiro vision provider unavailable."
    return f"xKiro vision request failed with HTTP {status}."


class XkiroVisionTransport:
    """Provider-specific HTTP and capability boundary.

    The transport returns raw assistant text.  Strict Phase-10 schema parsing
    remains outside it in ``XkiroVisualJudge``.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
        timeout_sec: float = DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self.api_key = settings.xkiro_api_key if api_key is None else api_key
        self.endpoint = endpoint or settings.xkiro_llm_url
        self.timeout_sec = timeout_sec
        self._verified_models: set[str] = set()

    @property
    def models_url(self) -> str:
        marker = "/chat/completions"
        if marker not in self.endpoint:
            raise JudgeInfrastructureError(
                "XKIRO_LLM_URL không phải endpoint /chat/completions hợp lệ."
            )
        return self.endpoint.split(marker, 1)[0] + "/models"

    def _headers(self) -> dict[str, str]:
        if not self.api_key.strip():
            raise JudgeInfrastructureError(
                "xKiro vision chưa khả dụng: XKIRO_API_KEY chưa được cấu hình."
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "ytb-pipeline/1.0 (+https://xkiro.com)",
        }

    def _open(self, request: urllib_request.Request) -> bytes:
        """Gửi một request, hỏi lại khi gateway lỗi thoáng qua.

        Không sửa gì và không bịa gì: cùng request đó được gửi lại. Hết lượt
        thì hỏng đúng như trước, mang đúng thông điệp cũ, nên mọi thứ đọc lỗi
        ở tầng trên không đổi.
        """
        last: BaseException | None = None
        for attempt in range(1, MAX_TRANSPORT_ATTEMPTS + 1):
            try:
                with urllib_request.urlopen(request, timeout=self.timeout_sec) as response:
                    return bytes(response.read())
            except (urllib_error.URLError, TimeoutError) as exc:
                # HTTPError là con của URLError, nên nhánh này bắt cả hai.
                last = exc
                if not _is_retryable(exc) or attempt == MAX_TRANSPORT_ATTEMPTS:
                    break
                logger.warning(
                    "visual_judge.transport_retry provider=xkiro attempt=%d/%d reason=%s",
                    attempt,
                    MAX_TRANSPORT_ATTEMPTS,
                    exc,
                )
                time.sleep(_RETRY_BACKOFF_SEC[min(attempt - 1, len(_RETRY_BACKOFF_SEC) - 1)])
        if isinstance(last, urllib_error.HTTPError):
            raise JudgeInfrastructureError(_provider_error_message(last.code)) from last
        raise JudgeInfrastructureError(f"xKiro vision network/timeout failure: {last}") from last

    def verify_vision_model(self, model: str) -> None:
        """Fail fast unless the exact configured model advertises vision."""
        if model in self._verified_models:
            return
        request = urllib_request.Request(self.models_url, headers=self._headers(), method="GET")
        raw = self._open(request)
        try:
            payload = json.loads(raw.decode("utf-8", "replace"))
            models = payload["data"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise JudgeInfrastructureError("xKiro model catalog response không hợp lệ.") from exc
        match = next(
            (item for item in models if isinstance(item, dict) and item.get("id") == model),
            None,
        )
        if match is None:
            raise JudgeInfrastructureError(
                f"Judge model {model!r} không có trong catalog xKiro."
            )
        capabilities = match.get("capabilities") or {}
        if capabilities.get("vision") is not True:
            raise JudgeInfrastructureError(
                f"Judge model {model!r} quảng cáo vision=false; không được dùng để chấm ảnh."
            )
        self._verified_models.add(model)

    def complete(
        self,
        *,
        model: str,
        system: str,
        content: tuple[dict[str, Any], ...],
    ) -> str:
        """Send one bounded multi-image Chat Completions request."""
        payload = json.dumps(
            {
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": list(content)},
                ],
                "temperature": 0,
                "max_tokens": 2048,
                "response_format": {"type": "json_object"},
            }
        ).encode("utf-8")
        request = urllib_request.Request(
            self.endpoint,
            data=payload,
            headers=self._headers(),
            method="POST",
        )
        raw = self._open(request)
        try:
            response = json.loads(raw.decode("utf-8", "replace"))
            content_text = response["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise JudgeInfrastructureError("xKiro vision provider response không hợp lệ.") from exc
        if not isinstance(content_text, str) or not content_text.strip():
            raise JudgeInfrastructureError("xKiro vision provider trả content rỗng.")
        return content_text


def _mime_and_bytes(
    candidate: JudgeCandidate,
    *,
    max_image_bytes: int,
    max_image_pixels: int,
) -> tuple[str, bytes]:
    path = Path(candidate.local_path)
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise JudgeInfrastructureError(
            f"Không đọc được candidate media {candidate.asset_id}."
        ) from exc
    observed_sha = hashlib.sha256(payload).hexdigest()
    if observed_sha != candidate.content_sha256:
        raise JudgeInfrastructureError(
            f"Candidate {candidate.asset_id} có SHA-256 thay đổi trước Judge transport."
        )
    if len(payload) > max_image_bytes:
        raise JudgeInfrastructureError(
            f"Candidate {candidate.asset_id} quá lớn cho Judge transport "
            f"({len(payload)} > {max_image_bytes} bytes)."
        )
    if payload.startswith(_PNG_SIGNATURE):
        mime, expected_format = "image/png", "PNG"
    elif payload.startswith(_JPEG_SIGNATURE):
        mime, expected_format = "image/jpeg", "JPEG"
    else:
        raise JudgeInfrastructureError(
            f"Candidate {candidate.asset_id} không phải PNG/JPEG được Phase 11 hỗ trợ."
        )
    try:
        with Image.open(BytesIO(payload)) as image:
            if image.format != expected_format:
                raise OSError(
                    f"magic bytes là {expected_format} nhưng decoder nhận {image.format}"
                )
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > max_image_pixels:
                raise JudgeInfrastructureError(
                    f"Candidate {candidate.asset_id} vượt giới hạn Judge transport "
                    f"({width}x{height} > {max_image_pixels} pixels)."
                )
            image.verify()
    except JudgeInfrastructureError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise JudgeInfrastructureError(
            f"Candidate {candidate.asset_id} không giải mã được thành ảnh hợp lệ."
        ) from exc
    return mime, payload


def _request_intro(request: Any, context: JudgeContext) -> str:
    constraints = tuple(getattr(request, "semantic_constraints", ()))
    dimensions = getattr(request, "dimensions", None)
    return "\n".join(
        (
            f"visual_intent: {request.visual_intent.strip()}",
            f"characters: {', '.join(request.characters) or '(không có)'}",
            f"semantic_constraints: {', '.join(constraints) or '(không có)'}",
            f"target_dimensions: {dimensions!r}",
            f"scene_id: {context.scene_id}",
            f"shot_id: {context.shot_id}",
            "Đánh giá từng ảnh dưới đây theo đúng asset_id được ghi ngay trước ảnh.",
        )
    )


def _response_instruction(candidate_count: int) -> str:
    allowed_failures = ", ".join(sorted(KNOWN_HARD_FAILURE_CODES))
    return (
        'Trả JSON đúng dạng {"evaluations": [{"asset_id": str, '
        '"semantic_score": 0..1, "character_score": 0..1, '
        '"composition_score": 0..1, "continuity_score": 0..1, '
        '"hard_failures": [str, ...], "reasons": [str, ...]}, ...]}. '
        f"Phải có đúng {candidate_count} evaluation, một cho mỗi asset_id; "
        f"hard_failures chỉ được dùng mã: {allowed_failures}."
    )


class XkiroVisualJudge:
    """One xKiro multimodal request per Shot, with one bounded repair."""

    name = "xkiro"

    def __init__(
        self,
        model: str,
        *,
        transport: XkiroVisionTransport | Any | None = None,
        max_image_bytes: int = DEFAULT_MAX_IMAGE_BYTES,
        max_image_pixels: int = DEFAULT_MAX_IMAGE_PIXELS,
    ) -> None:
        if not model.strip():
            raise ValueError("xKiro VisualJudge model không được rỗng.")
        if max_image_bytes <= 0:
            raise ValueError("max_image_bytes phải > 0.")
        if max_image_pixels <= 0:
            raise ValueError("max_image_pixels phải > 0.")
        self.model = model
        self.transport = transport or XkiroVisionTransport()
        self.max_image_bytes = max_image_bytes
        self.max_image_pixels = max_image_pixels

    def evaluate(
        self,
        request: Any,
        candidates: tuple[JudgeCandidate, ...],
        context: JudgeContext,
    ) -> JudgeResult:
        if not candidates:
            raise JudgeInfrastructureError("VisualJudge cần ít nhất một candidate.")
        self.transport.verify_vision_model(self.model)
        content: list[dict[str, Any]] = [
            {"type": "text", "text": _request_intro(request, context)}
        ]
        for candidate in candidates:
            mime, payload = _mime_and_bytes(
                candidate,
                max_image_bytes=self.max_image_bytes,
                max_image_pixels=self.max_image_pixels,
            )
            content.append(
                {
                    "type": "text",
                    "text": (
                        f"candidate_index={candidate.candidate_index} "
                        f"asset_id={candidate.asset_id}"
                    ),
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{mime};base64,{base64.b64encode(payload).decode('ascii')}"
                    },
                }
            )
        content.append(
            {"type": "text", "text": _response_instruction(len(candidates))}
        )

        candidate_ids = tuple(candidate.asset_id for candidate in candidates)

        def attempt(parts: tuple[dict[str, Any], ...]) -> JudgeResult:
            raw_text = self.transport.complete(
                model=self.model,
                system=_SYSTEM_PROMPT,
                content=parts,
            )
            try:
                payload = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise JudgeMalformedResponseError(
                    f"Judge response không phải JSON hợp lệ: {exc}"
                ) from exc
            return parse_judge_payload(
                payload,
                candidate_asset_ids=candidate_ids,
                judge_provider=self.name,
                judge_model=self.model,
            )

        parts = tuple(content)
        logger.info(
            "visual_judge.transport provider=xkiro model=%s shot_id=%s image_count=%s",
            self.model,
            context.shot_id,
            len(candidates),
        )
        try:
            return attempt(parts)
        except JudgeMalformedResponseError as first_error:
            logger.info(
                "visual_judge.repair provider=xkiro model=%s shot_id=%s reason=%s",
                self.model,
                context.shot_id,
                first_error,
            )
            repair_parts = parts + (
                {
                    "type": "text",
                    "text": (
                        f"Phản hồi trước không hợp lệ ({first_error}). Trả lại DUY NHẤT "
                        "JSON hợp lệ đúng schema; không thêm gì khác."
                    ),
                },
            )
            try:
                return attempt(repair_parts)
            except JudgeMalformedResponseError as second_error:
                raise JudgeInfrastructureError(
                    f"Judge response không hợp lệ sau 1 lần repair: {second_error}"
                ) from second_error


__all__ = [
    "DEFAULT_MAX_IMAGE_BYTES",
    "XkiroVisionTransport",
    "XkiroVisualJudge",
]
