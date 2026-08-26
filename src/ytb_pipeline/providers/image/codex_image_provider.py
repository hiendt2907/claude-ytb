"""Codex CLI (`codex exec`) as a config-selectable ALTERNATIVE story-scene
image provider — NOT the default, NOT a fallback.

Manually verified before writing this module: `codex exec --sandbox
workspace-write --skip-git-repo-check "<prompt>"` really invokes a built-in,
non-interactive `image_gen` tool (Codex feature flag `image_generation`,
stage `stable`) and writes a genuine PNG under
`~/.codex/generated_images/<session-id>/<file>.png`. This provider shells out
to that command, then picks up the newest PNG that appeared in that directory
during the call and resizes/copies it to `output_path`.

Same call shape as `ComfyUIStoryProvider.generate_scene` so
`render/story.py::resolve_scene_image` can select either one through
`providers/registry.py::get_story_image_provider()` without an if/else in
domain code. Default `settings.story_image_provider` stays "comfyui" —
CLAUDE.md's local-first visual/render policy is unchanged; this is an opt-in
cloud alternative, e.g. for a batch of free Codex credit.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from ...content_profiles import ContentProfile
from ..errors import ProviderUnavailableError

_DEFAULT_GENERATED_IMAGES_DIR = Path.home() / ".codex" / "generated_images"
_EXEC_TIMEOUT_S = 300


def _default_runner(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=_EXEC_TIMEOUT_S)


class CodexImageProvider:
    name = "codex_image"

    def __init__(
        self,
        *,
        runner: Callable[..., object] | None = None,
        generated_images_dir: Path | None = None,
    ) -> None:
        self._runner = runner or _default_runner
        self._generated_images_dir = Path(generated_images_dir or _DEFAULT_GENERATED_IMAGES_DIR)

    def availability_status(self) -> tuple[bool, str]:
        if shutil.which("codex") is None:
            return False, "Không tìm thấy lệnh `codex` trong PATH."
        return True, "codex CLI có sẵn trong PATH."

    def is_available(self) -> bool:
        ok, _detail = self.availability_status()
        return ok

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
            raise ProviderUnavailableError(f"CodexImageProvider không khả dụng: {detail}")

        unique = tuple(dict.fromkeys(characters_present))
        if len(unique) > 2:
            raise ValueError(
                f"Story scene chỉ hỗ trợ tối đa 2 nhân vật cùng khung hình, nhận {len(unique)}."
            )
        reference_images = [
            str(profile.character_reference_path(character_id)) for character_id in unique
        ]

        instruction = self._build_instruction(vg, prompt, unique, width, height)
        started_at = time.time()
        self._run_codex(instruction, reference_images)
        image_path = self._latest_generated_image(after=started_at)
        if image_path is None:
            raise ProviderUnavailableError(
                "codex exec chạy xong nhưng không có ảnh mới nào trong "
                f"{self._generated_images_dir} — không có gì để dùng."
            )
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        self._resize_and_copy(image_path, output_path, width, height)
        return output_path

    def _build_instruction(
        self, vg, prompt: str, characters: tuple[str, ...], width: int, height: int,
    ) -> str:
        identity_rule = (
            " Preserve the exact face/identity from the attached reference image(s); "
            "this is an identity-preserving edit, not a new character."
            if characters
            else ""
        )
        return (
            f"Generate a single scene image, {width}x{height}, using your built-in "
            "image generation tool — do not write code to draw it yourself. "
            f"Style: {vg.style_prompt}. Avoid: {vg.negative_prompt}. "
            f"Scene: {prompt}.{identity_rule} "
            "Save the result and reply with only the saved file path."
        )

    def _run_codex(self, instruction: str, reference_images: list[str]) -> None:
        cmd = ["codex", "exec", "--sandbox", "workspace-write", "--skip-git-repo-check"]
        for image in reference_images:
            cmd.extend(["-i", image])
        cmd.append(instruction)
        result = self._runner(cmd)
        if getattr(result, "returncode", 1) != 0:
            stderr = str(getattr(result, "stderr", ""))[-500:]
            raise ProviderUnavailableError(f"codex exec thất bại: {stderr}")

    def _latest_generated_image(self, *, after: float) -> Path | None:
        if not self._generated_images_dir.is_dir():
            return None
        candidates = [
            path for path in self._generated_images_dir.rglob("*.png")
            if path.is_file() and path.stat().st_mtime >= after - 1
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda path: path.stat().st_mtime)

    def _resize_and_copy(self, source: Path, output_path: Path, width: int, height: int) -> None:
        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover — Pillow is an existing dependency
            raise ProviderUnavailableError("Cần Pillow để resize ảnh Codex sinh ra.") from exc
        with Image.open(source) as image:
            image.convert("RGB").resize((width, height)).save(output_path, format="PNG")
