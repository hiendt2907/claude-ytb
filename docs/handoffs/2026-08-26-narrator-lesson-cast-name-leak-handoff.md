# Handoff — narrator_lesson_closing: prompt cho phép nêu tên cast, QA lại cấm (chưa test end-to-end thật)

Ngày: 2026-08-26
Người viết: Claude
Trạng thái: PHÁT HIỆN qua đọc code + 1 script Qwen thật, **CHƯA sửa, chưa
verify bằng smoke end-to-end** (xKiro outage HTTP 500 giữa chừng, xem log
dưới). Nối tiếp `docs/handoffs/2026-08-26-story-hook-marker-and-recovery-fix-handoff.md`
(implement `content_rules.narrator_lesson_closing` cho `ban-so-6` v1.5.0).

## Bối cảnh: đã chạy workflow thật cho 2 profile để soi kịch bản sinh ra

```bash
DRY_RUN=true bin/ytb batch start --profile one-cup-cafe-6h --num-of-vid 1 \
  --type-of-vid long --batch-key smoke_profile_test_1787716814 \
  --idea "Cảm giác trì hoãn công việc dù biết deadline gần kề"
# log: assets/batch_logs/ideation_20260826_110015.log

DRY_RUN=true bin/ytb batch start --profile ban-so-6 --num-of-vid 1 \
  --type-of-vid short --batch-key smoke_ban6_retry_<ts> \
  --idea "Minh hứa sửa xong bug trước khi An về nhưng vẫn còn dở"
# log: assets/batch_logs/ideation_20260826_110109.log
```

Cả hai lần: LLM sinh script JSON thành công (PROMPT 1 → RAW_LLM_RESPONSE 1 →
VALIDATION_ATTEMPT 1), nhưng `validate_expected_video_type()` báo thiếu thời
lượng một chút:

- one-cup-cafe-6h: `Long quá ngắn: audio 261.7s; ít nhất 304.4s.`
- ban-so-6: `Short quá ngắn: audio 28.6s; ít nhất 30.0s.`

→ loop gọi `LONG_EXTENSION_PROMPT` / `SHORT_EXPANSION_PROMPT` để vá thêm câu
chữ, và CẢ HAI lần cuộc gọi xKiro thứ hai này trả **HTTP 500** (đúng luật
"lỗi thì dừng minh bạch, không fallback" — đã dừng đúng, KHÔNG phải bug
engine). Đã retry `ban-so-6` một lần, vẫn 500. Không retry thêm — nghi xKiro
đang có outage tại thời điểm 2026-08-26 ~11:00-11:03.

**Hệ quả quan trọng:** vì `validate_expected_video_type()` raise exception
TRƯỚC KHI code chạy tới `QAAgent`, cả hai script THẬT này **chưa từng được
QA nội dung chấm** trong lần chạy này (xem `validate_or_repair_script()`,
`ideation_script_fix.py` — khối `try` chứa `validate_expected_video_type`
raise thì `script = None`, vòng lặp `continue` mà không gọi `qa.run(...)`).

## Lỗi phát hiện được (đọc code trực tiếp, không suy đoán)

Payoff (closing) thật của `ban-so-6` mà Qwen sinh ra:

```
"Minh không sửa kịp như đã hứa, nhưng cậu đã chọn cho An thấy đúng chỗ đang
kẹt thay vì nói gần xong. Lần tới khi bạn lỡ hứa mà việc vẫn còn dở, hãy chỉ
ra chính xác một điểm đang chặn cho người có thể nhìn cùng."
```

speaker_id của section này = `"narrator"` (đúng contract).

Đối chiếu `_is_narrator_lesson_closing()` (`src/ytb_pipeline/agents/qa_agent.py:572`):

```python
cast = {name for name in profile.voice_cast if name != narrator_id}
if cast & set(words):
    return False
```

`profile.voice_cast` của `ban-so-6` = `{"narrator", "minh", "an"}` →
`cast = {"minh", "an"}`. Câu trên chứa từ `"minh"` (đã lowercase qua
`_story_words`) → `cast & set(words) = {"minh"}` → hàm trả `False` → **KHÔNG
được công nhận là narrator-lesson-closing hợp lệ**. Vì `_has_bounded_action`
trên câu này cũng không match (không phải hành động cụ thể của nhân vật, mà
là tổng quát hoá), `_check_immediate_action()` sẽ trả về violation
`immediate_action` NẾU script này thực sự chạm tới QA.

**Root cause ở prompt, không phải ở QA gate** — `_character_story_closing_instruction()`
(`src/ytb_pipeline/orchestrator/ideation_prompts.py:128`) hiện chỉ dặn:

```
"...addressed to \"you\"/\"bạn\", not to a character) — state the principle
the story demonstrated, not a command to act right now and not another
character's dialogue."
```

Không có dòng nào cấm **nhắc TÊN nhân vật ở ngôi thứ ba** khi tóm tắt lại sự
kiện trước khi đúc kết — mà đây là cách viết tự nhiên nhất bằng tiếng Việt
("X đã làm gì đó, nhưng Y..."). QA gate (đã cố ý thiết kế đúng, xem handoff
trước) cấm điều này, nhưng prompt không hướng dẫn model tránh nó.

**Thêm một lỗ hổng cấu trúc liên quan (đã có từ trước, không phải bug mới):**
không có repair path nào cho `rule=immediate_action` trong
`validate_or_repair_script()` (chỉ có `series_dedup` và `hook`, xem dòng 884
và 928 của `ideation_script_fix.py`). Nếu một script đủ thời lượng ngay từ
đầu (không rơi vào nhánh duration-repair như 2 lần chạy vừa rồi) mà closing
phạm lỗi nêu tên cast, script đó sẽ bị `IdeationQualityFailure` sau khi hết
`max_attempts` — **không có đường sửa**, y hệt kiểu "swallowed violation"
mà handoff trước đã xử lý cho `rule=hook`.

## CHƯA làm / CHƯA xác nhận (đọc kỹ trước khi coi đây là bug đã confirm)

- CHƯA có bằng chứng QA thật sự reject câu này — vì QA chưa từng chạy trên
  script thật này (duration chặn trước). Đây là **phân tích tĩnh qua code +
  1 sample thật**, không phải reproduction end-to-end. Trước khi sửa, nên
  viết 1 test tối thiểu gọi thẳng `_check_immediate_action`/`QAAgent.run()`
  với đúng câu payoff ở trên (dùng `office-thread-fixture` hoặc fixture
  generic tương tự, KHÔNG `ban-so-6`) để **xác nhận nó thật sự bị reject**
  trước khi kết luận đây là bug cần sửa.
- CHƯA re-run 2 smoke thật (`one-cup-cafe-6h` long + `ban-so-6` short) đến
  khi QA thật sự chấm nội dung (không bị chặn bởi duration) — vì xKiro đang
  500 lúc viết handoff này. Cần retry khi xKiro ổn định lại để xác nhận cả
  đường happy-path (không bị bug này) lẫn đường lỗi (bị bug này, nếu confirm).

## Việc cần làm (đề xuất, KHÔNG bắt buộc theo đúng thứ tự nếu Codex thấy hướng khác tốt hơn)

1. **RED trước:** viết test tối thiểu tái hiện đúng câu payoff thật ở trên
   (hoặc một câu tương đương generic, không hardcode "Minh"/"ban-so-6") qua
   `_check_immediate_action()`/`QAAgent`, xác nhận nó **thật sự** bị reject
   với lý do đúng như phân tích (không phải lý do khác).
2. Nếu confirm đúng: sửa `_character_story_closing_instruction()` trong
   `ideation_prompts.py` thêm một câu cấm rõ ràng, ví dụ dạng: "state the
   lesson without naming any character by name — describe what happened in
   general terms" (không hardcode tên nhân vật cụ thể, giữ generic cho mọi
   profile character_story).
3. **Cân nhắc riêng, cần quyết định có nên làm hay không:** có nên thêm một
   repair path bounded cho `rule=immediate_action` giống cấu trúc
   `apply_hook_repair`/`hook_repair_prompt` đã có (bounded, single-shot,
   cùng attempt slot), để một closing bị QA từ chối có cơ hội sửa thay vì
   fail thẳng cả candidate? Đây là thay đổi lớn hơn phạm vi lỗi hiện tại —
   nêu rõ trade-off (thêm 1 nhánh nữa vào vòng lặp vốn đã có 2 nhánh
   identity+hook trong cùng 1 attempt) trước khi quyết, đừng tự ý làm nếu
   không chắc còn nằm trong ngân sách `max_attempts=3` mặc định.
4. GREEN: chạy lại test ở bước 1, xác nhận pass.
5. `make test` full suite, báo pass/fail count.
6. Re-run 2 smoke thật (lệnh y hệt phần "Bối cảnh" ở trên, đổi `--batch-key`)
   khi xKiro không còn 500, đọc lại `assets/batch_logs/ideation_*.log` mới
   nhất, xác nhận: (a) closing mới KHÔNG nêu tên cast, (b) nếu vẫn thiếu
   thời lượng thì đó là vấn đề khác (không liên quan bug này), (c) nếu QA
   thật sự chạy tới đoạn `_check_immediate_action` thì nó phải PASS.
7. Viết handoff tiếp theo với kết quả thật (PASS/FAIL rõ ràng), không suy
   diễn từ 1 lần chạy may mắn.

## Ràng buộc bắt buộc (thừa hưởng từ toàn bộ phiên làm việc này)

- Không hardcode tên nhân vật/profile cụ thể vào code engine — chỉ được nêu
  ví dụ trong prompt text nếu prompt đó vốn đã generic (không phải case
  riêng cho `ban-so-6`).
- Không nới lỏng/bypass QA gate để script pass dễ hơn.
- Không sửa `settings.py`/default provider/renderer/TTS.
- TDD bắt buộc: RED thật (chạy fail) trước khi sửa, GREEN sau khi sửa.
- Không `git stash`; dùng `cp`/`git show HEAD:<path> > tmp` để backup tạm.
- Không commit, không render/publish, không `batch run` thật.
- Nếu sau khi điều tra thấy giả thuyết trong handoff này SAI (giống lỗi A
  trong handoff trước đã tự lật lại giả thuyết ban đầu) — cứ báo FAIL/SAI
  rõ ràng, đừng cố match kết luận có sẵn.
