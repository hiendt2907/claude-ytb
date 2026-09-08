# Handoff — Story hook: stake marker class + swallowed repair (engine-level)

Ngày: 2026-08-26
Người viết: Claude
Trạng thái: implement + test + 2 smoke thật xong, **chưa commit**.
Base: nối tiếp `docs/handoffs/2026-08-26-story-hook-prompt-contract-handoff.md`
(Codex audit độc lập contract lần trước, tìm ra 2 lỗi thật mới — log
`assets/batch_logs/ideation_20260826_095554.log`).

## Root-cause map đầy đủ (bắt buộc trace trước khi sửa)

**Đường chạy thật, không suy đoán:**

```
raw LLM JSON
  → generator._segment_from_raw() / _section_voiceover()
      narration = raw.get("voiceover") or raw.get("narration")   # voiceover ƯU TIÊN
      Segment(narration=narration, voiceover=narration)          # CẢ HAI = cùng 1 giá trị
  → Script.segments (đối tượng đã nạp qua load_script)
  → QAAgent.run({"script": script, ...})
      qa_agent._narration_of(segment) đọc segment.narration      # ĐÃ = voiceover, không phải
                                                                   # narration thô trong JSON gốc
      qa_agent._check_story_hook() → _check_hook_strength()
  → violations list
  → validate_or_repair_script() vòng lặp validate→QA→repair
      - series_dedup → identity repair (title/topic only)
      - hook → TRƯỚC KHI SỬA: KHÔNG có path nào — break ngay
      - duration → long_extension_prompt / short_expansion_prompt
```

### Lỗi A — đã XÁC MINH KHÔNG PHẢI field-mismatch (giả thuyết ban đầu sai)

**Đã tự kiểm chứng bằng `load_script()` thật** trên chính candidate fail
(`dung-doan-y-bang-mot-cau-hoi_20260826_095629_489312.json`, có `voiceover`
và `narration` KHÁC NHAU trong JSON thô — `narration` là mô tả camera/staging
"Mở cảnh bằng đồng hồ treo tường chỉ 6:20..."): `Segment.narration` sau khi
nạp **đã đúng bằng `voiceover`** ("Sáu giờ hai mươi sáng. Minh đã gạch ba
phương án..."), không phải mô tả staging. `generator._section_voiceover()`
đã ưu tiên `voiceover` từ trước — **đây không phải lỗi**, và `qa_agent.py`
đọc đúng field. Ghi test khoá hành vi đúng này lại
(`test_qa_judges_the_canonical_spoken_text_not_a_staging_description`) để
không ai vô tình đổi field QA đọc trong tương lai.

**Lỗi thật ở A:** `_check_story_hook()`'s `_STORY_STAKE_MARKERS` chỉ có lớp
NGHĨA VỤ/THỜI HẠN ("phải", "chưa", "sắp", "hạn", "trễ"...), **thiếu hoàn
toàn** lớp HẬU QUẢ/RỦI RO mà chính `STORY_HOOK_CONTRACT` đã hứa ("a
consequence, or something the character could still lose"). Câu mở thật của
Qwen — "sợ hỏi An thì bị chê là thiếu chủ động" — có anchor rõ (giờ + Minh)
và có rủi ro rõ (sợ bị chê), nhưng marker list không nhận ra được lớp rủi ro
này nên vẫn reject.

**Đã tự verify bằng script trực tiếp** (không suy đoán):
```python
qa_agent._check_hook_strength(script_that_failed)
# -> [{'rule': 'hook', ...}]
words = qa_agent._story_words(first)
# 'sợ', 'bị', 'chê' đều KHÔNG có trong _STORY_STAKE_MARKERS trước khi sửa
```

### Lỗi B — đã XÁC MINH bằng chính log audit, không suy đoán

Đọc `QA_RESULT 2` → `IDENTITY_REPAIR_PROMPT` → `VALIDATION_ATTEMPT 3` →
`QA_RESULT 3` → `FINAL_FAILURE` trong log thật: identity repair đổi
title/topic (dedup hết), nhưng `hook` violation **y hệt** ở QA_RESULT 3 —
xác nhận **không có path nào từng sửa `rule=hook`**, dù đứng một mình hay
cùng lúc với `series_dedup`. Đọc toàn bộ `validate_or_repair_script()`
(855 dòng): chỉ có 2 loại LLM follow-up hợp lệ trước khi sửa — long
extension (duration) và short expansion (duration) — cộng identity repair
(chỉ cho series_dedup). Không có nhánh nào cho `rule=hook`; code rơi thẳng
xuống `break` (fail closed) ngay khi QA fail mà không phải
series_dedup/duration. Đây là lỗi có thật với BẤT KỲ hook violation nào,
không riêng khi đi cùng series_dedup.

**Vì sao test cũ không bắt được:** không có test nào từng dựng kịch bản có
`rule=hook` VÀ chạy qua `validate_or_repair_script()` thật (chỉ có test đơn
vị cho `_check_story_hook()` — kiểm QA thuần, không kiểm đường repair).

## Thiết kế chọn — vì sao không phải patch keyword / patch riêng lẻ

### A — mở rộng lớp ngữ nghĩa, không phải patch câu

Không thêm literal `"sợ hỏi An thì bị chê"`. Thêm **"bị"** làm marker độc
lập — đây là trợ từ bị động-nghịch (adversative passive) của tiếng Việt,
gần như luôn đứng trước một hậu quả XẤU xảy đến cho chủ thể ("bị chê", "bị
la", "bị phạt", "bị đuổi", "bị trừ điểm"...), khác hẳn "được" (trung
tính/tích cực) — nên khái quát được CẢ LỚP hậu quả mà không liệt kê từng
động từ. Thêm "sợ"/"lo"/"nếu"/"nhỡ"/"kẻo" cho lớp rủi ro-lường-trước. Test
chứng minh tính khái quát bằng 2 câu khác hẳn câu gốc: "bị anh quản lý gọi
lên" (không phải "bị chê") và "lo Duy đọc bản nháp rồi lại nghĩ cô làm ẩu"
(không dùng "sợ" hay "bị" nào cả) — cả hai đều PASS sau fix.

### B — bounded, order rõ ràng, idempotent, không đổi max_attempts

Không thêm LLM call "đoán" QA — hook repair CẦN LLM vì nó phải VIẾT LẠI nội
dung câu mở (việc sáng tạo, không thể làm bằng gate xác định), nhưng bounded
giống hệt mẫu `short_expansion_prompt`: trả về ĐÚNG 1 field
(`{"voiceover": ...}`), không được đổi field nào khác — `apply_hook_repair()`
chỉ ghi đè `sections[0].voiceover`/`narration`, deepcopy giữ nguyên phần
còn lại.

**Không dùng LLM call riêng cho mỗi violation + không tăng `max_attempts`:**
cả identity repair (series_dedup) và hook repair đều chạy trong CÙNG một
attempt slot khi cả hai violation cùng xuất hiện trong một `QA_RESULT` —
gom vào 1 khối, thứ tự cố định (series_dedup trước, hook sau), mỗi loại
đúng 1 lần (`identity_repair_attempted`/`hook_repair_attempted`), rồi
`continue` MỘT LẦN để validate lại cả hai. Với `max_attempts=3` mặc định ở
production, việc này vẫn nằm gọn trong ngân sách hiện có (không cần đổi
call site nào) — verify bằng test thật `test_series_dedup_and_hook_failing_together_both_get_repaired`.
`hook_repair_prompt()`/`_hook_repair_directive()` dùng CHUNG routing với
`repair_prompt()` (character_story → `STORY_HOOK_CONTRACT`; ngược lại → luật
Long-greeting-tension-marker cũ), đảm bảo cùng một contract ở mọi entry
point.

## File thay đổi

- `src/ytb_pipeline/agents/qa_agent.py` — tách `_STORY_STAKE_MARKERS` thành
  2 lớp có comment giải thích, thêm lớp rủi ro/hậu quả (`bị`, `sợ`, `lo`,
  `nếu`, `nhỡ`, `kẻo`). **0 thay đổi logic khác** trong file.
- `src/ytb_pipeline/orchestrator/ideation_prompts.py` — thêm
  `_hook_repair_directive()` (refactor DRY từ `repair_prompt()`), thêm
  `hook_repair_prompt()`. `repair_prompt()`'s hành vi output **không đổi**
  (chỉ refactor cách build chuỗi).
- `src/ytb_pipeline/orchestrator/ideation_script_fix.py` — thêm
  `apply_hook_repair()`; thay khối `if not identity_repair_attempted and
  series_dedup...` bằng khối xử lý CẢ hai loại repairable violation (dedup
  + hook) theo thứ tự cố định trong cùng attempt. Import thêm
  `hook_repair_prompt`.

Test mới: `tests/test_story_hook_stake_semantics.py` (6 test, dùng
`office-thread-fixture`), `tests/test_hook_repair_recovery.py` (2 test, real
`QAAgent` + real loop, fake LLM provider).

## RED → GREEN (verify bằng `cp` backup, KHÔNG git stash)

- `test_anchor_with_natural_fear_and_consequence_stake_passes` — RED thật
  trước fix (đúng lỗi thật của Qwen, tái lập bằng profile khác ban-so-6) →
  GREEN.
- `test_other_members_of_the_risk_consequence_class_also_pass` (2 case: "bị"
  đơn lẻ với động từ khác, "lo" không kèm "bị"/"trễ") — RED → GREEN, chứng
  minh khái quát hoá lớp, không phải patch câu.
- `test_anchor_without_any_stake_class_is_still_rejected`,
  `test_stake_without_any_anchor_is_rejected` — cả hai chiều đều PASS ngay
  (không RED — đây là regression khẳng định contract "cần CẢ HAI" vẫn đúng
  sau khi mở rộng marker).
- `test_qa_judges_the_canonical_spoken_text_not_a_staging_description` —
  PASS ngay (khoá hành vi ĐÃ ĐÚNG, không phải fix).
- `test_series_dedup_and_hook_failing_together_both_get_repaired` — RED
  thật khi revert về `HEAD` (`cp` từ `git show HEAD:...`, không stash):
  `provider.calls == 0` thay vì gọi cả 2 prompt theo đúng thứ tự → GREEN
  sau khi thêm khối repair kết hợp; verify title/topic đổi, opening đổi
  ĐÚNG MỘT chỗ, 4 section/thứ tự purpose/payoff/CTA/compliance giữ nguyên.
- `test_hook_repair_is_single_shot_and_does_not_loop_forever` — RED tương tự
  → GREEN: model vẫn trả opening yếu lần 2, loop dừng đúng sau 2 lệnh gọi
  LLM (không lặp vô hạn), raise `IdeationQualityFailure` đúng như thiết kế.

## Kết quả test

```
.venv/bin/pytest tests/test_hook_repair_recovery.py tests/test_story_hook_stake_semantics.py \
  tests/test_story_hook_rule.py tests/test_story_hook_prompt_contract.py \
  tests/test_repair_failure_is_contained.py tests/test_batch_defaults.py \
  tests/test_content_strategy.py -q
→ 89 passed

make test → 1002 passed, 3 skipped, 1 deselected, 0 failed
```

## Regression xác nhận

- Legacy/no-profile Long vẫn giữ greeting + tension-marker contract cũ —
  `test_repair_prompt_keeps_the_long_tension_marker_rule_without_a_profile`
  (từ handoff trước) vẫn pass nguyên vẹn, không sửa lại.
- Duration repair (commit `589390d`) — `test_repair_failure_is_contained.py`,
  `test_content_strategy.py` pass không đổi; `apply_short_expansion`/
  `short_expansion_prompt`/`long_extension_prompt` **0 dòng diff**.
- Profile fixture: `office-thread-fixture` (cast `lan`/`duy`), khác hẳn
  `ban-so-6`, dùng xuyên suốt mọi test mới.

## Hai smoke Qwen độc lập (DRY_RUN=true, không publish/render)

Batch key riêng, ý tưởng khác nhau, cùng loại xung đột (sợ hỏi → bị đánh
giá):

| Smoke | Slug | Total chars | QA cuối | Preflight |
|---|---|---:|---|---|
| 1 (`...smoke3...`) | `gop-y-mot-chi-tiet-nho` | 540 | `passed: true, violations: []` (attempt 1) | `✓ passed` |
| 2 (`...smoke5...`) | `an-hoi-de-kiem-tra-thay-vi-nhac-deadline` | 572 | `passed: true, violations: []` (attempt 2) | `✓ passed` |

Cả hai nằm trong safe range 497–668. Log xác nhận
`STORY_HOOK_CONTRACT`/"The opening narration must pass a hook gate" thật
sự có trong prompt gửi model ở cả hai lần.

**2 lần chạy khác** (batch key `...smoke2...`, `...smoke4...`) **fail —
nhưng KHÔNG phải vì `rule=hook`**: một lần `character_voiceover_direct` +
`immediate_action`, một lần chỉ `immediate_action`. Đây là 2 gate KHÁC,
NGOÀI PHẠM VI nhiệm vụ này (không sửa). Ghi nhận trung thực: trong 4 lần
chạy Qwen thật sau fix, **0/4 lần fail vì hook** (trước fix: fail vì hook ở
100% các lần thử theo 2 handoff trước) — bằng chứng thống nhất, không phải
một lần ngẫu nhiên may mắn.

## FAIL rõ ràng — đường recovery CHƯA được chứng minh bằng Qwen thật

Cả 4 lần chạy Qwen thật sau fix đều **không** tạo ra một `rule=hook`
violation nào (contract ở tầng generation đã đủ mạnh để Qwen tự viết đúng
ngay từ đầu trong các lần thử này) — nghĩa là **path `hook_repair_prompt`/
`apply_hook_repair` (root cause B) chưa được một lần Qwen thật nào đi qua
LIVE END-TO-END**; nó chỉ được verify bằng `QAAgent` thật + loop thật + LLM
GIẢ LẬP (`tests/test_hook_repair_recovery.py`). Đây KHÔNG phải kết luận
"đã xong" cho toàn bộ call graph — nếu cần bằng chứng Qwen thật đi qua đúng
path repair này, cần cố tình tạo một script có hook yếu KHÔNG bị chặn bởi
gate khác (hoặc chạy đủ nhiều lần tới khi Qwen tự tạo ra hook thật sự yếu)
rồi quan sát `HOOK_REPAIR_PROMPT` xuất hiện trong log thật.

## Xác nhận theo yêu cầu

- Không nới/bypass QA — `_check_story_hook()`'s cấu trúc (yêu cầu ≥8 từ +
  anchor + stake) không đổi, chỉ mở rộng ĐÚNG vocabulary đã hứa.
- Không hand-edit candidate archive nào (grep xác nhận không file nào trong
  `assets/script_revisions/failed_ideation/` bị sửa tay — các file mới ở đó
  là kết quả THẬT của 2 lần Qwen fail vì lý do khác).
- Không đổi `settings.py`, default model (`deepseek/deepseek-v4-pro`,
  `git diff settings.py` rỗng), xKiro provider, renderer, TTS,
  short_expansion/duration-repair logic.
- Không dùng git stash — mọi RED verify dùng `cp`/`git show HEAD:... > tmp`
  rồi khôi phục bằng `cp` ngược lại.
- Không `batch run`, không render, không publish/upload YouTube.
- Không commit gì trong toàn bộ nhiệm vụ này.

## File chính đã đổi

`src/ytb_pipeline/agents/qa_agent.py`,
`src/ytb_pipeline/orchestrator/ideation_prompts.py`,
`src/ytb_pipeline/orchestrator/ideation_script_fix.py`. Test mới:
`tests/test_story_hook_stake_semantics.py`,
`tests/test_hook_repair_recovery.py`,
`tests/fixtures/content_profiles/office-thread-fixture/` (đã có từ handoff
trước, tái dùng).
