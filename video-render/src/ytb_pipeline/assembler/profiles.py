"""Auto-edit animations, styles, and profiles for batch rendering."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AnimationSpec:
    name: str
    description: str


@dataclass(frozen=True)
class StyleSpec:
    name: str
    description: str


@dataclass(frozen=True)
class RenderTuning:
    scene_transition_duration: float = 0.75
    clip_transition_duration: float = 0.35
    motion_scale: float = 1.08
    pan_strength_x: float = 0.35
    pan_strength_y: float = 0.35
    pan_speed_x: float = 0.70
    pan_speed_y: float = 0.55
    end_fade_duration: float = 0.35


@dataclass(frozen=True)
class AutoEditProfile:
    name: str
    label: str
    description: str
    style_name: str
    animation_names: tuple[str, ...]
    tuning: RenderTuning


ANIMATIONS: dict[str, AnimationSpec] = {
    "soft_pan_zoom": AnimationSpec("soft_pan_zoom", "Pan/zoom nhẹ liên tục."),
    "slow_push_in": AnimationSpec("slow_push_in", "Zoom vào chậm cho sản phẩm tĩnh."),
    "micro_drift": AnimationSpec("micro_drift", "Dịch khung rất nhẹ để tránh freeze."),
    "punch_in": AnimationSpec("punch_in", "Nhấn zoom nhẹ quanh điểm cut."),
    "dissolve": AnimationSpec("dissolve", "Chồng mờ giữa hai cảnh."),
    "blur_dissolve": AnimationSpec("blur_dissolve", "Dissolve mềm cho cảnh khác nhau."),
    "zoom_blur_cut": AnimationSpec("zoom_blur_cut", "Cut nhanh có cảm giác zoom."),
    "swipe_soft": AnimationSpec("swipe_soft", "Trượt nhẹ, dùng hạn chế."),
    "fade_out": AnimationSpec("fade_out", "Kết video bằng fade-out mềm."),
    "match_cut": AnimationSpec("match_cut", "Cut ngắn có easing nhẹ."),
}

STYLES: dict[str, StyleSpec] = {
    "natural": StyleSpec("natural", "Dựng tự nhiên, ít hiệu ứng."),
    "clean_product": StyleSpec("clean_product", "Tập trung sản phẩm, crop ổn định."),
    "dynamic_sales": StyleSpec("dynamic_sales", "Nhịp nhanh, bán hàng rõ hơn."),
    "premium_smooth": StyleSpec("premium_smooth", "Mượt, ít gắt, transition dài hơn."),
    "ugc_raw": StyleSpec("ugc_raw", "Giữ cảm giác quay thật, chỉ chống đơ."),
    "high_energy": StyleSpec("high_energy", "Motion rõ và cut nhanh hơn."),
}

PROFILES: dict[str, AutoEditProfile] = {
    "affiliate_default": AutoEditProfile(
        name="affiliate_default",
        label="Affiliate mặc định",
        description="Cấu hình cân bằng cho video bán hàng dọc.",
        style_name="dynamic_sales",
        animation_names=("soft_pan_zoom", "micro_drift", "dissolve", "fade_out"),
        tuning=RenderTuning(),
    ),
    "tiktok_shop_fast": AutoEditProfile(
        name="tiktok_shop_fast",
        label="TikTok Shop nhanh",
        description="Nhịp nhanh hơn, motion rõ hơn cho video bán hàng ngắn.",
        style_name="high_energy",
        animation_names=("micro_drift", "punch_in", "zoom_blur_cut", "match_cut", "fade_out"),
        tuning=RenderTuning(
            scene_transition_duration=0.55,
            clip_transition_duration=0.25,
            motion_scale=1.11,
            pan_strength_x=0.45,
            pan_strength_y=0.40,
            pan_speed_x=0.95,
            pan_speed_y=0.80,
            end_fade_duration=0.25,
        ),
    ),
    "product_review_smooth": AutoEditProfile(
        name="product_review_smooth",
        label="Review mượt",
        description="Nhịp chậm hơn, transition mềm cho review sản phẩm.",
        style_name="premium_smooth",
        animation_names=("soft_pan_zoom", "slow_push_in", "dissolve", "blur_dissolve", "fade_out"),
        tuning=RenderTuning(
            scene_transition_duration=0.95,
            clip_transition_duration=0.40,
            motion_scale=1.06,
            pan_strength_x=0.25,
            pan_strength_y=0.22,
            pan_speed_x=0.45,
            pan_speed_y=0.35,
            end_fade_duration=0.45,
        ),
    ),
    "beauty_skincare": AutoEditProfile(
        name="beauty_skincare",
        label="Beauty / skincare",
        description="Mềm, sạch, ít cut gắt cho sản phẩm làm đẹp.",
        style_name="clean_product",
        animation_names=("soft_pan_zoom", "slow_push_in", "dissolve", "fade_out"),
        tuning=RenderTuning(
            scene_transition_duration=0.85,
            clip_transition_duration=0.35,
            motion_scale=1.055,
            pan_strength_x=0.22,
            pan_strength_y=0.20,
            pan_speed_x=0.40,
            pan_speed_y=0.35,
            end_fade_duration=0.45,
        ),
    ),
    "food_demo": AutoEditProfile(
        name="food_demo",
        label="Food demo",
        description="Crop gần và motion vừa cho demo đồ ăn.",
        style_name="clean_product",
        animation_names=("soft_pan_zoom", "micro_drift", "dissolve", "fade_out"),
        tuning=RenderTuning(
            scene_transition_duration=0.70,
            clip_transition_duration=0.30,
            motion_scale=1.09,
            pan_strength_x=0.38,
            pan_strength_y=0.34,
            pan_speed_x=0.75,
            pan_speed_y=0.60,
            end_fade_duration=0.30,
        ),
    ),
    "unboxing_koc": AutoEditProfile(
        name="unboxing_koc",
        label="Unboxing KOC",
        description="Nhịp vừa, nhiều push-in vào sản phẩm.",
        style_name="natural",
        animation_names=("slow_push_in", "micro_drift", "dissolve", "match_cut", "fade_out"),
        tuning=RenderTuning(
            scene_transition_duration=0.75,
            clip_transition_duration=0.35,
            motion_scale=1.08,
            pan_strength_x=0.32,
            pan_strength_y=0.30,
            pan_speed_x=0.65,
            pan_speed_y=0.55,
            end_fade_duration=0.35,
        ),
    ),
    "fashion_tryon": AutoEditProfile(
        name="fashion_tryon",
        label="Fashion try-on",
        description="Cut nhanh vừa cho thử đồ và nhiều dáng quay.",
        style_name="dynamic_sales",
        animation_names=("micro_drift", "punch_in", "swipe_soft", "dissolve", "fade_out"),
        tuning=RenderTuning(
            scene_transition_duration=0.60,
            clip_transition_duration=0.28,
            motion_scale=1.07,
            pan_strength_x=0.30,
            pan_strength_y=0.42,
            pan_speed_x=0.65,
            pan_speed_y=0.85,
            end_fade_duration=0.30,
        ),
    ),
    "voiceover_catalog": AutoEditProfile(
        name="voiceover_catalog",
        label="Voiceover catalog",
        description="Ổn định, dễ xem khi một voice dùng nhiều video sản phẩm.",
        style_name="natural",
        animation_names=("soft_pan_zoom", "micro_drift", "dissolve", "fade_out"),
        tuning=RenderTuning(
            scene_transition_duration=0.80,
            clip_transition_duration=0.35,
            motion_scale=1.065,
            pan_strength_x=0.28,
            pan_strength_y=0.25,
            pan_speed_x=0.50,
            pan_speed_y=0.42,
            end_fade_duration=0.40,
        ),
    ),
    "smooth_retry": AutoEditProfile(
        name="smooth_retry",
        label="Render lại mượt hơn",
        description="Fallback ổn định hơn cho video cần render lại sau kiểm tra chất lượng.",
        style_name="premium_smooth",
        animation_names=("soft_pan_zoom", "slow_push_in", "dissolve", "blur_dissolve", "fade_out"),
        tuning=RenderTuning(
            scene_transition_duration=1.00,
            clip_transition_duration=0.45,
            motion_scale=1.045,
            pan_strength_x=0.18,
            pan_strength_y=0.16,
            pan_speed_x=0.32,
            pan_speed_y=0.28,
            end_fade_duration=0.50,
        ),
    ),
}


def list_profiles() -> tuple[AutoEditProfile, ...]:
    return tuple(PROFILES[name] for name in sorted(PROFILES))


def resolve_profile(name: str | None) -> AutoEditProfile:
    normalized = (name or "affiliate_default").strip() or "affiliate_default"
    try:
        return PROFILES[normalized]
    except KeyError as exc:
        raise ValueError(
            f"edit_profile không hợp lệ: {normalized!r} (dùng {list(PROFILES)})"
        ) from exc
