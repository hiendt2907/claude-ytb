# Audit handoff — narrator lesson và cast-name

Ngày: 2026-08-26  
Người audit: Codex  
Trạng thái: **FAIL: hypothesis không xác nhận. Không sửa engine, không smoke.**

Nối tiếp `2026-08-26-narrator-lesson-cast-name-leak-handoff.md` và
`2026-08-26-story-hook-marker-and-recovery-fix-handoff.md`.

## Kết luận

Giả thuyết rằng narrator lesson có tên cast sẽ bị
`_check_immediate_action()` reject là **sai với câu payoff nêu trong handoff**.
Vì vậy không được thêm prompt rule “không nêu tên cast” chỉ để khớp một gate
mà thực tế không chặn câu đó.

## Reproduction thật

Dùng profile fixture generic, khác `ban-so-6`: `character_story`, cast
`narrator`/`hieu`/`lam`, và `narrator_lesson_closing=true`.

Gọi thẳng QA với closing narrator:

```text
Hiếu đã im lặng quá lâu trước khi hỏi rõ. Lần tới khi bạn phân vân,
hãy nói điều mình chưa hiểu thay vì tự đoán ý người khác.
```

Kỳ vọng từ handoff cũ: violation `immediate_action`.  
Kết quả thật: `[]` (PASS). Không tái lập được bug.

Lệnh audit sau khi gỡ test thử nghiệm:  
`.venv/bin/pytest tests/test_narrator_lesson_closing.py -q` → `3 passed`.

## Root cause của phân tích sai

Handoff cũ chỉ nhìn vào `_is_narrator_lesson_closing()` và check cast name,
nhưng bỏ qua thứ tự thực thi của `_check_immediate_action()`:

```text
1. Có _IMMEDIATE_ACTION_HINTS? → pass ngay.
2. Character story có bounded action? → pass.
3. narrator_lesson_closing hợp lệ? → mới check speaker, độ dài, cast name,
   direct address.
4. Không nhánh nào pass → immediate_action violation.
```

Câu mẫu có `“hãy”`, một immediate-action hint; nó pass ở bước 1, trước khi
check cast-name chạy. Nhận định cũ chỉ xét `_has_bounded_action()` nên thiếu
nhánh quyết định đầu tiên.

## Hệ quả

- Không có bằng chứng prompt cho phép một shape mà QA thực sự cấm.
- Hai assertion thử yêu cầu prompt chứa `do not name any cast member` có fail,
  nhưng chúng kiểm policy chưa được QA thực thi; đã gỡ, không để lại test/code.
- Không có cơ sở thêm recovery path cho `immediate_action` trong task này.
  Làm vậy sẽ mở rộng để sửa một lỗi chưa được chứng minh.

Không chạy full suite hay hai smoke vì không có production fix GREEN để
verify. Không chạy batch run/render/publish và không commit.

## Nếu muốn đổi policy

Nếu product quyết định narrator lesson **không bao giờ được nhắc tên nhân
vật**, đó là một editorial rule mới. Cần chốt nó độc lập rồi mới thay prompt
và QA cùng một contract; không suy ra rule đó từ handoff bị bác bỏ này.
