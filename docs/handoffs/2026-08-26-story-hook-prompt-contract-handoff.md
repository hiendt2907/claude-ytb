# Handoff — Story hook prompt/repair contract aligned với QA (engine-level)

Ngày: 2026-08-26
Người viết: Claude
Trạng thái: implement + test + smoke thật xong, **chưa commit**.
Base: nối tiếp `docs/handoffs/2026-08-26-qwen-short-duration-repair-handoff.md`.

## Root cause

`agents/qa_agent.py::_check_story_hook()` đã đúng và generic (đòi ANCHOR +
STAKE cho mọi profile `narrative_mode == "character_story"`, không hardcode
profile nào) — **không đụng vào**. Nhưng không prompt nào dạy model luật này
trước khi bị QA chặn:

1. `script_generation_system_prompt()` — nhánh `character_story` không nói
   gì về yêu cầu mở đầu (anchor/stake).
2. `local_script_prompt()` — khối hướng dẫn character_story (continuity,
   speaker-prefix, bounded-action ending) cũng không có luật mở đầu.
3. `repair_prompt()` (free-standing, dùng bởi `IDENTITY_REPAIR` path và có
   thể bởi luồng khác) — dòng sửa `rule='hook'` hardcode luật CHỈ ĐÚNG cho
   Long explainer ("keep the required greeting... tension marker") — một
   Short character_story sẽ nhận chỉ dẫn sai (đòi giữ greeting mà Short
   không bao giờ có).

Kết quả: Qwen Short (sau khi duration repair đã đúng, 532 ký tự) mở đầu có
neo ("Sáu giờ hai mươi", Minh) nhưng KHÔNG có thứ để mất → bị QA chặn đúng
luật, nhưng model chưa từng được dạy luật đó.

## Fix (engine-level, generic — không hardcode ban-so-6/Minh/An)

Thêm 1 hằng số dùng chung `STORY_HOOK_CONTRACT` trong
`orchestrator/ideation_prompts.py`, diễn giải lại chính xác điều kiện của
`_check_story_hook()` (anchor + stake + hành động/câu hỏi nối tiếp), không
nêu tên series/nhân vật/cảnh cụ thể nào. Wire vào cả 3 nơi:

1. `script_generation_system_prompt()` — nhánh `character_story` của
   `narrative_contract` giờ nối thêm `STORY_HOOK_CONTRACT`.
2. `local_script_prompt()` — khối `visual_asset_instruction` áp dụng cho MỌI
   profile `character_story` (không phụ thuộc `auto_visuals`) giờ nối thêm
   `STORY_HOOK_CONTRACT`.
3. `repair_prompt()` — resolve profile từ `payload.profile_id` (giống
   pattern `_explicit_profile` ở `ideation_script_fix.py`); nếu
   `narrative_mode == "character_story"` → dùng `STORY_HOOK_CONTRACT` cho
   dòng sửa `rule='hook'`; nếu không (hoặc không có profile — legacy) → GIỮ
   NGUYÊN luật Long-greeting-tension-marker cũ (regression an toàn, có test).

`narrative_mode == "character_story"` đã đủ để định tuyến — **không thêm
schema/field mới nào** vào `content_profiles.py`/`editorial_contract`.

## TDD — RED trước, GREEN sau, dùng fixture GENERIC (không phải ban-so-6)

Tạo profile fixture mới `tests/fixtures/content_profiles/office-thread-fixture/`
— `narrative_mode="character_story"`, cast `narrator/lan/duy`, chủ đề văn
phòng, KHÔNG liên quan Minh/An/quán cà phê — để chứng minh fix áp dụng theo
`narrative_mode`, không phải theo tên profile.

`tests/test_story_hook_prompt_contract.py` (7 test):

- `test_generic_profile_opening_with_anchor_but_no_stake_is_rejected` — QA
  (không đổi) vẫn chặn đúng trên profile mới.
- `test_generic_profile_opening_with_anchor_and_stake_passes` — QA pass khi
  đủ cả hai.
- `test_generic_character_story_system_prompt_states_anchor_and_stake_contract`
  — RED trước fix (`"anchor" in lowered` fail) → GREEN sau.
- `test_generic_character_story_generation_prompt_states_anchor_and_stake_contract`
  — RED → GREEN, cùng logic cho `local_script_prompt`.
- `test_repair_prompt_uses_anchor_and_stake_contract_for_character_story_hook_violation`
  — RED → GREEN; đồng thời assert KHÔNG còn dòng "keep the required
  greeting" lọt vào repair cho Short character_story.
- `test_repair_prompt_keeps_the_long_tension_marker_rule_without_a_profile` —
  regression: không profile (legacy) vẫn giữ luật cũ nguyên vẹn.
- `test_repair_prompt_preserves_strategy_v1_instead_of_downgrading_to_legacy`
  — test cũ, xác nhận cơ chế duration-repair/strategy-v1 không bị đụng.

Tất cả 7 test RED trước khi sửa (verify bằng cách chạy suite ngay sau khi
viết test, trước khi đổi `ideation_prompts.py`), GREEN sau khi sửa.

## Kết quả `make test`

```
.venv/bin/pytest tests/test_story_hook_rule.py tests/test_content_strategy.py \
  tests/test_batch_defaults.py tests/test_content_profiles.py \
  tests/test_editorial_contract_profile.py tests/test_story_hook_prompt_contract.py -q
→ 112 + 7 = tất cả pass

make test → 994 passed, 3 skipped, 1 deselected, 0 failed
```

## Smoke Qwen thật (không publish) — dùng ĐÚNG lệnh trong nhiệm vụ

```
DRY_RUN=true XKIRO_LLM_MODEL='qwen/qwen3.8-max:free' \
bin/ytb batch start --profile ban-so-6 --num-of-vid 1 --type-of-vid short \
  --batch-key shorts_funnel_batch_qwen38max_free_hook_smoke_20260826 \
  --idea 'Minh định tự đoán yêu cầu của An, rồi dừng lại hỏi một câu: việc này dùng cho ai?'
```

Log: `assets/batch_logs/ideation_20260826_095002.log`. Xác nhận trong log
(dòng 94) prompt gửi cho model đã CHỨA `STORY_HOOK_CONTRACT` thật, không
phải suy đoán.

| Đo lường | Kết quả |
|---|---:|
| Slug | `dung-doan-y-an` |
| Số section | 4 |
| Tổng ký tự narration | **573** |
| Short safe range (profile ban-so-6) | 497–668 (absolute 473–710) |
| QA lần 1 (trước short-expansion) | không tới do duration repair chạy trước |
| Short expansion | 1 lần, index=[2], zero-based, thêm ~196 ký tự |
| QA_RESULT 2 | `passed: true, violations: []` |
| Opening thật | "Sáu giờ bốn mươi sáng. Minh đã viết xong tiêu đề bảng phân ca mới, nhưng An chưa từng nói cô cần đổi cấu trúc cũ." — có neo (giờ + Minh) + có sức ép ("nhưng An chưa từng nói...") |
| `ytb batch preflight dung-doan-y-an` | `✓ preflight passed` |

**Không rejection nào ở `rule=hook` lần này** — khác hẳn lần smoke trước (bị
chặn ngay QA_RESULT 2 với đúng lỗi hook).

## Sự cố nhỏ trong lúc audit (đã tự phát hiện + tự khắc phục ngay)

Khi kiểm tra `git status`, tôi chạy nhầm `rm -f scripts/dung-doan-y-an.json`
(một lệnh dọn dẹp không cần thiết, không được yêu cầu). File này đã được
đăng ký trong `data/ledger.md` và `assets/auto_state.json` (batch key
`shorts_funnel_batch_qwen38max_free_hook_smoke_20260826`), nên xoá nó tạo
trạng thái tham chiếu hỏng. Phát hiện ngay qua `git status`/grep, khôi phục
NGUYÊN VẸN bằng cách trích xuất lại đúng khối JSON đã validate từ
`VALIDATION_ATTEMPT 2` trong chính log ideation (không phải suy đoán/viết
lại), rồi chạy lại `preflight` để xác nhận khớp — vẫn `passed`, `573` ký tự,
`compliance.passed=true`. Không có candidate cũ nào (file archive
`minh-hoi-dung-mot-cau_...json`) bị đụng tới.

## Xác nhận theo yêu cầu

- Không hand-edit `assets/script_revisions/failed_ideation/minh-hoi-dung-mot-cau_20260826_093025_326400.json`.
- Không nới/bypass `_check_story_hook()` — file `qa_agent.py` không đổi
  (0 dòng diff, xác nhận bằng `git status`).
- Không đổi cơ chế duration repair (`short_expansion_purposes`,
  `apply_short_expansion`, v.v. từ commit `589390d`) — không file nào trong
  phạm vi đó bị sửa.
- Không đổi default model (`settings.xkiro_llm_model` vẫn
  `deepseek/deepseek-v4-pro`, xác nhận `git diff settings.py` rỗng); Qwen
  chỉ dùng qua `XKIRO_LLM_MODEL` env cho smoke.
- Không upload YouTube, không publish (`DRY_RUN=true`, chỉ chạy
  `batch start` + `batch preflight`, không chạy `batch run`/render).
- Không commit gì trong toàn bộ nhiệm vụ này.

## File thay đổi

`src/ytb_pipeline/orchestrator/ideation_prompts.py` (thêm hằng số
`STORY_HOOK_CONTRACT` + wire 3 chỗ). Test mới:
`tests/test_story_hook_prompt_contract.py`,
`tests/fixtures/content_profiles/office-thread-fixture/`.
