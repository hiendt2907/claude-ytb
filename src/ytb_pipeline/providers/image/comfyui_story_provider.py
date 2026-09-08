"""ComfyUI/SDXL + IPAdapter scene generation for character_story profiles.

Three modes, each a distinct workflow validated by hand before this module was
written (see `profiles/<id>/assets/identity/README.md` for the exact
experiments and why the naive approaches failed):

- **establishing** (no named character in frame): plain SDXL txt2img, no
  IPAdapter. Used for empty-room / prop-only beats.
- **solo** (one named character): txt2img with a single IPAdapter reference —
  the reference MUST be a real scene where that character is the dominant
  subject, never the multi-pose character sheet (IPAdapter reproduces the
  sheet's panel layout instead of a coherent scene) and never a scene
  dominated by the OTHER character (identity bleeds across).
- **duo** (two named characters in frame): img2img starting from an already
  -approved two-character keyframe (`visual_generation.duo_reference_image`),
  at low denoise, with BOTH characters' IPAdapter references applied at low
  weight. The base image supplies the two-person composition; IPAdapter only
  reinforces identity while the prompt changes the action. Generating a new
  two-person composition from an empty latent — either by chaining two global
  IPAdapters or by masking each identity to a screen region — was tried and
  both leaked identity between the two characters; low-denoise img2img on a
  real two-person photo does not have this failure mode because the spatial
  arrangement of two bodies is already fixed by the starting image.

Reference images are uploaded to ComfyUI's own `/upload/image` endpoint rather
than assumed to live on a shared filesystem, so this works whether ComfyUI
runs on this machine or elsewhere reachable at `settings.comfyui_url`.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from ...config.settings import settings
from ...content_profiles import ContentProfile, VisualGenerationProfile
from ..errors import ProviderUnavailableError

_PING_TIMEOUT_S = 3.0
_REQUEST_TIMEOUT_S = 60.0
_POLL_INTERVAL_S = 1.5
_POLL_ATTEMPTS = 240  # ~6 minutes; an SDXL/IPAdapter step on M4 Pro is far faster
SAMPLER = "dpmpp_2m"
SCHEDULER = "karras"

# A duo keyframe is deliberately free of work clutter so img2img does not
# hallucinate it into every story beat.  Individual scenes still opt in to
# those props by naming them in `visual_intent`.
_COMPUTER_INTENT = re.compile(
    r"\b(?:laptop|computer|desktop|pc|macbook)\b|máy\s+tính", re.IGNORECASE
)
_PAPERWORK_INTENT = re.compile(
    r"\b(?:document|documents|paper|papers|worksheet|printout|notebook)\b|"
    r"tài\s+liệu|giấy|bản\s+nháp|sổ\s+tay",
    re.IGNORECASE,
)


class ComfyUIStoryProvider:
    name = "comfyui_story"

    def availability_status(self) -> tuple[bool, str]:
        base = settings.comfyui_url.rstrip("/")
        try:
            with urllib.request.urlopen(f"{base}/system_stats", timeout=_PING_TIMEOUT_S) as response:
                if response.status != 200:
                    return False, f"ComfyUI trả HTTP {response.status} tại {base}"
            missing = [
                (node, model)
                for node, model in (
                    ("CheckpointLoaderSimple", settings.comfyui_sdxl_checkpoint),
                    ("CLIPVisionLoader", settings.comfyui_clip_vision_model),
                    ("IPAdapterModelLoader", settings.comfyui_ipadapter_model),
                )
                if model not in self._object_names(node)
            ]
            if missing:
                detail = ", ".join(f"{node}:{model}" for node, model in missing)
                return False, f"ComfyUI thiếu model đã khai trong settings: {detail}"
            return True, f"ComfyUI tại {base}"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return False, f"ComfyUI không phản hồi tại {base}: {exc}"

    def is_available(self) -> bool:
        ok, _detail = self.availability_status()
        return ok

    def _object_names(self, node_class: str) -> set[str]:
        base = settings.comfyui_url.rstrip("/")
        url = f"{base}/object_info/{node_class}"
        with urllib.request.urlopen(url, timeout=_PING_TIMEOUT_S) as response:
            body = json.loads(response.read().decode("utf-8"))
        required = body.get(node_class, {}).get("input", {}).get("required", {})
        field = next(iter(required.values()), [])
        options = field[0] if field and isinstance(field[0], list) else []
        return {str(name) for name in options}

    def generate_scene(
        self,
        profile: ContentProfile,
        *,
        characters_present: tuple[str, ...],
        prompt: str,
        width: int,
        height: int,
        seed: int,
        output_path: Path,
    ) -> Path:
        vg = profile.visual_generation
        if vg is None or not vg.enabled:
            raise ProviderUnavailableError(
                f"Profile '{profile.profile_id}' chưa bật visual_generation."
            )
        ok, detail = self.availability_status()
        if not ok:
            raise ProviderUnavailableError(f"ComfyUIStoryProvider không khả dụng: {detail}")

        unique = tuple(dict.fromkeys(characters_present))
        if len(unique) == 0:
            workflow = self._build_establishing(vg, prompt, width, height, seed)
        elif len(unique) == 1:
            workflow = self._build_solo(profile, vg, unique[0], prompt, width, height, seed)
        elif len(unique) == 2:
            workflow = self._build_duo(profile, vg, unique, prompt, width, height, seed)
        else:
            raise ValueError(
                f"Story scene chỉ hỗ trợ tối đa 2 nhân vật cùng khung hình, nhận {len(unique)}."
            )

        image_bytes = self._run(workflow)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return output_path

    def _build_establishing(
        self, vg: VisualGenerationProfile, prompt: str, width: int, height: int, seed: int
    ) -> dict:
        return {
            "ckpt": self._checkpoint_node(),
            "pos": self._text_node(f"{prompt}, {vg.style_prompt}", ["ckpt", 1]),
            "neg": self._text_node(
                self._scene_negative_prompt(vg, character_count=0, prompt=prompt), ["ckpt", 1]
            ),
            "latent": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "sampler": self._sampler_node(vg, seed, ["ckpt", 0], ["latent", 0], denoise=1.0),
            "vaedecode": self._decode_node(["ckpt", 2]),
            "save": self._save_node(),
        }

    def _build_solo(
        self, profile: ContentProfile, vg: VisualGenerationProfile, character_id: str,
        prompt: str, width: int, height: int, seed: int,
    ) -> dict:
        ref_name = self._upload(profile.character_reference_path(character_id))
        workflow: dict = {
            "ckpt": self._checkpoint_node(),
            "clipvision": self._clip_vision_node(),
            "ipaloader": self._ipadapter_loader_node(),
            "refimg": {"class_type": "LoadImage", "inputs": {"image": ref_name}},
            "ipadapter": self._ipadapter_apply_node(
                model=["ckpt", 0], image=["refimg", 0], weight=vg.solo_weight,
            ),
            "pos": self._text_node(f"{prompt}, {vg.style_prompt}", ["ckpt", 1]),
            "neg": self._text_node(
                self._scene_negative_prompt(vg, character_count=1, prompt=prompt), ["ckpt", 1]
            ),
            "latent": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
            "sampler": self._sampler_node(vg, seed, ["ipadapter", 0], ["latent", 0], denoise=1.0),
            "vaedecode": self._decode_node(["ckpt", 2]),
            "save": self._save_node(),
        }
        return workflow

    def _build_duo(
        self, profile: ContentProfile, vg: VisualGenerationProfile, character_ids: tuple[str, str],
        prompt: str, width: int, height: int, seed: int,
    ) -> dict:
        first_id, second_id = character_ids
        first_ref = self._upload(profile.character_reference_path(first_id))
        second_ref = self._upload(profile.character_reference_path(second_id))
        base_ref = self._upload(profile.duo_reference_path())
        workflow: dict = {
            "ckpt": self._checkpoint_node(),
            "clipvision": self._clip_vision_node(),
            "ipaloader": self._ipadapter_loader_node(),
            "firstimg": {"class_type": "LoadImage", "inputs": {"image": first_ref}},
            "secondimg": {"class_type": "LoadImage", "inputs": {"image": second_ref}},
            "baseimg": {"class_type": "LoadImage", "inputs": {"image": base_ref}},
            "baseresize": {
                "class_type": "ImageScale",
                "inputs": {"image": ["baseimg", 0], "width": width, "height": height, "upscale_method": "lanczos", "crop": "center"},
            },
            "ipa_first": self._ipadapter_apply_node(
                model=["ckpt", 0], image=["firstimg", 0], weight=vg.duo_weight,
            ),
            "ipa_second": self._ipadapter_apply_node(
                model=["ipa_first", 0], image=["secondimg", 0], weight=vg.duo_weight,
            ),
            "vaeencode": {"class_type": "VAEEncode", "inputs": {"pixels": ["baseresize", 0], "vae": ["ckpt", 2]}},
            "pos": self._text_node(f"{prompt}, {vg.style_prompt}", ["ckpt", 1]),
            "neg": self._text_node(
                self._scene_negative_prompt(vg, character_count=2, prompt=prompt), ["ckpt", 1]
            ),
            "sampler": self._sampler_node(
                vg, seed, ["ipa_second", 0], ["vaeencode", 0], denoise=vg.duo_denoise,
            ),
            "vaedecode": self._decode_node(["ckpt", 2]),
            "save": self._save_node(),
        }
        return workflow

    @staticmethod
    def _scene_negative_prompt(
        vg: VisualGenerationProfile, *, character_count: int, prompt: str
    ) -> str:
        if character_count == 1:
            exclusion = "multiple people, two people, duplicate person, extra person"
        elif character_count == 2:
            exclusion = "third person, extra person, duplicate person"
        else:
            exclusion = "people, person, character"
        prop_exclusions: list[str] = []
        if not _COMPUTER_INTENT.search(prompt):
            prop_exclusions.extend(("laptop", "computer"))
        if not _PAPERWORK_INTENT.search(prompt):
            prop_exclusions.extend(("documents", "papers", "notebook"))
        return ", ".join((vg.negative_prompt, exclusion, *prop_exclusions))

    def _checkpoint_node(self) -> dict:
        return {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": settings.comfyui_sdxl_checkpoint}}

    def _clip_vision_node(self) -> dict:
        return {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": settings.comfyui_clip_vision_model}}

    def _ipadapter_loader_node(self) -> dict:
        return {"class_type": "IPAdapterModelLoader", "inputs": {"ipadapter_file": settings.comfyui_ipadapter_model}}

    def _ipadapter_apply_node(self, *, model: list, image: list, weight: float) -> dict:
        return {
            "class_type": "IPAdapterAdvanced",
            "inputs": {
                "model": model, "ipadapter": ["ipaloader", 0], "image": image,
                "clip_vision": ["clipvision", 0], "weight": weight, "weight_type": "linear",
                "combine_embeds": "concat", "start_at": 0.0, "end_at": 1.0, "embeds_scaling": "V only",
            },
        }

    def _text_node(self, text: str, clip: list) -> dict:
        return {"class_type": "CLIPTextEncode", "inputs": {"text": text, "clip": clip}}

    def _sampler_node(
        self, vg: VisualGenerationProfile, seed: int, model: list, latent: list, *, denoise: float,
    ) -> dict:
        return {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed, "steps": vg.steps, "cfg": vg.cfg,
                "sampler_name": SAMPLER, "scheduler": SCHEDULER, "denoise": denoise,
                "model": model, "positive": ["pos", 0], "negative": ["neg", 0],
                "latent_image": latent,
            },
        }

    def _decode_node(self, vae: list) -> dict:
        return {"class_type": "VAEDecode", "inputs": {"samples": ["sampler", 0], "vae": vae}}

    def _save_node(self) -> dict:
        return {"class_type": "SaveImage", "inputs": {"filename_prefix": "ban_so_6_story", "images": ["vaedecode", 0]}}

    def _upload(self, path: Path) -> str:
        base = settings.comfyui_url.rstrip("/")
        boundary = uuid.uuid4().hex
        data = path.read_bytes()
        filename = f"{path.stem}-{uuid.uuid4().hex[:8]}{path.suffix}"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode("utf-8") + data + f"\r\n--{boundary}--\r\n".encode("utf-8")
        request = urllib.request.Request(
            f"{base}/upload/image", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
            result = json.loads(response.read().decode("utf-8"))
        return str(result.get("name") or filename)

    def _run(self, workflow: dict) -> bytes:
        base = settings.comfyui_url.rstrip("/")
        payload = json.dumps({"prompt": workflow}).encode("utf-8")
        request = urllib.request.Request(
            f"{base}/prompt", data=payload, headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_S) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise ProviderUnavailableError(f"ComfyUI từ chối workflow: {detail}") from exc
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise ProviderUnavailableError(f"ComfyUI không trả prompt_id: {body}")

        for _ in range(_POLL_ATTEMPTS):
            with urllib.request.urlopen(f"{base}/history/{prompt_id}", timeout=_PING_TIMEOUT_S) as response:
                history = json.loads(response.read().decode("utf-8"))
            entry = history.get(prompt_id, {})
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                raise ProviderUnavailableError(f"ComfyUI lỗi khi sinh ảnh: {json.dumps(status, ensure_ascii=False)[:800]}")
            for node in entry.get("outputs", {}).values():
                images = node.get("images") or []
                if images:
                    return self._download(images[0])
            time.sleep(_POLL_INTERVAL_S)
        raise ProviderUnavailableError(f"ComfyUI không sinh ảnh sau {_POLL_ATTEMPTS * _POLL_INTERVAL_S:.0f}s")

    def _download(self, meta: dict) -> bytes:
        base = settings.comfyui_url.rstrip("/")
        query = urllib.parse.urlencode({
            "filename": meta.get("filename", ""),
            "subfolder": meta.get("subfolder", ""),
            "type": meta.get("type", "output"),
        })
        with urllib.request.urlopen(f"{base}/view?{query}", timeout=_REQUEST_TIMEOUT_S) as response:
            return response.read()
