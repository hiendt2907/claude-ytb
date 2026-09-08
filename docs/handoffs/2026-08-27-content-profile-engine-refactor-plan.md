# Kế hoạch refactor toàn dự án theo hướng "content-profile engine" (Codex đang xây)

Ngày: 2026-08-27
Người viết: Claude
Trạng thái: **Giai đoạn 0, 1, 2, 3, 4 đã thực thi trong phiên này** (người
dùng yêu cầu "xử lý luôn" thay vì giao Codex). Giai đoạn 5 CHƯA làm — cần một
profile thứ 3 thật để kiểm chứng, chưa tồn tại. `make test` sau tất cả các
giai đoạn: 1050 passed, 3 skipped, 1 deselected, 0 failed. Commit:
`05bd6ee` (Giai đoạn 0), `f85b72e` (Giai đoạn 1), `032a471` + `0c8c937`
(Giai đoạn 3-4), cộng 1 commit sửa `docs/CHANNEL_GROWTH_PLAN.md` (Giai đoạn
2, sau khi được xác nhận: `ban-so-6` Long-only là quyết định **vĩnh viễn**).
Trước đó có 1 patch nhỏ không thuộc kế hoạch này:
`fix: forbid episode-preview lead-in and mind-reading in explainer long
prompt`, commit `a0cdffd` — vá nốt RED test Codex để dở khi hết quota.

## 1. Bối cảnh: "hướng này" là gì, đánh giá trung thực hiện trạng

Đọc trực tiếp 71 commit (`git log --oneline main..HEAD`) + code hiện tại thay
vì suy đoán. Kết luận: **phần lớn engine đã được generalize đúng cách**, không
phải mì ăn liền. Bằng chứng cụ thể:

- `src/ytb_pipeline/agents/editorial_review_agent.py` — cổng LLM-rubric chấm
  điểm biên tập (5 tiêu chí `human_truth/spoken_naturalness/causal_coherence/
  role_fidelity/useful_restraint`), **opt-in per profile** qua
  `editorial_review.enabled`, cache theo `(profile_fingerprint, script content
  hash)`, dùng đúng `ReviewProvider` Protocol — không import SDK cụ thể. Đã
  wire vào cả `ideation_script_fix.py` (lúc sinh kịch bản) lẫn `pipeline.py`
  (gate trước render lúc resume). Không có chữ "ban-so-6"/"one-cup-cafe-6h"
  hardcode trong file này.
- `content_profiles.py`: `EditorialReviewProfile`, `format_prompts` (map
  `short`/`long` → tên prompt file khác nhau, validate tên prompt tồn tại),
  `ContentRules.story_primary_speaker_id`/`story_supporting_speaker_id`
  (thay hardcode `"minh"`/`"an"` bằng field profile khai báo),
  `allow_short_generation`, `long_opening_mode`, `short_ending_mode`,
  `require_next_episode_bridge` — tất cả có docstring giải thích lý do default,
  có `__post_init__` validate giá trị hợp lệ. `supports_generation()` tách rõ
  "đọc được script cũ" khỏi "được phép sinh script mới" — thiết kế tốt, không
  phá khả năng đọc lại Short cũ của series đã tắt sinh Short mới.
- `tests/test_transcript_format_contracts.py` đã tự đặt tên đúng nguyên tắc:
  *"The production engine must learn the format from profile data, never from
  a series name"* — và dùng `office-thread-fixture` (fixture generic), không
  dùng `ban-so-6` — đúng quy ước TDD đã thống nhất suốt phiên làm việc này.
- `grep` toàn `src/ytb_pipeline/` không tìm thấy chuỗi `"ban-so-6"` hay
  `"one-cup-cafe-6h"` hardcode trong code (đã kiểm tra trực tiếp).

→ **Kết luận:** đây không phải một tính năng vá tạm cần "đập đi xây lại". Việc
"refactor toàn bộ dự án theo hướng này" nên hiểu là: **hoàn thiện + đồng bộ +
tài liệu hoá** một kiến trúc đã đúng hướng, không phải viết lại từ đầu.

## 2. Khoảng trống thật đã xác nhận (không suy đoán)

### 2a. Tài liệu bị lệch so với code — vi phạm luật "Doc drift = bug" trong CLAUDE.md

`CLAUDE.md` và toàn bộ `docs/constitution/*` **không hề nhắc tới**:
`format_prompts`, `editorial_review`/`EditorialReviewProfile`,
`story_primary_speaker_id`/`story_supporting_speaker_id`,
`allow_short_generation`, `long_opening_mode`, `short_ending_mode`,
`require_next_episode_bridge`, hay quy ước `profiles/<id>/versions/<semver>/`
(snapshot mỗi lần bump version — cả hai profile đều đã có thư mục `versions/`
nhưng chưa có dòng nào mô tả quy ước này ở đâu). Đây là nợ tài liệu thật, theo
đúng định nghĩa của chính CLAUDE.md ("Doc drift = bug, ngang hàng với test
fail").

### 2b. Mâu thuẫn thật giữa 2 tài liệu chiến lược kênh và cấu hình engine hiện tại

`docs/CHANNEL_GROWTH_PLAN.md` (dòng 10-42) mặc định MỌI series đều chạy mô
hình phễu `Short → Long → playlist`, đăng "2 Shorts cùng cơ chế... xuất bản
lúc 06:00 và 12:30" cho mỗi Long. Nhưng `profiles/ban-so-6/profile.json` hiện
tại có `content_rules.allow_short_generation: false` — nghĩa là series này đã
được quyết định (qua các commit Codex, ví dụ hướng
`require_next_episode_bridge`) là **Long-only, không còn phễu Short**. Chiến
lược kênh chưa được cập nhật để phản ánh quyết định engine-level này — hai tài
liệu đang mô tả hai thực tế khác nhau cho cùng một series.

### 2c. Hai lớp gác chất lượng nội dung chưa có ranh giới viết thành văn

Hiện có **hai cơ chế độc lập** cùng phán xét "kịch bản có đọc tốt không":
1. `qa_agent.py` — luật cứng bằng từ khoá/heuristic tiếng Việt (hook contract,
   `_check_immediate_action`, `narrator_lesson_closing`, v.v.), chạy free,
   deterministic, không gọi LLM.
2. `editorial_review_agent.py` — LLM chấm điểm rubric 5 tiêu chí, tốn 1 lời
   gọi LLM mỗi script (có cache).

Cả hai đều có thể từ chối cùng một lỗi (vd một closing nhắc tên nhân vật có
thể vừa phạm luật cứng vừa bị LLM chấm thấp `role_fidelity`), nhưng **không
có tài liệu nào nói rõ layer nào là chốt chặn chính, layer nào bổ sung**, hay
khi nào một luật nên chuyển từ heuristic cứng sang rubric LLM (hoặc ngược
lại). Rủi ro: hai người sửa hai layer cho cùng một vấn đề, tạo luật chồng
chéo hoặc mâu thuẫn theo thời gian — services team gọi đây là "hai nguồn sự
thật".

### 2d. Chưa có "khuôn" (template/checklist) cho profile mới

Từ log 71 commit, `one-cup-cafe-6h` đi tới cấu hình hiện tại qua rất nhiều
vòng `test:`/`fix:` dò dẫm (đổi cả persona giữa chừng). Không có gì sai về mặt
kỹ thuật, nhưng **không hiệu quả** nếu profile thứ 3 phải lặp lại toàn bộ quá
trình dò dẫm này từ đầu. Chưa tồn tại: `profiles/_template/`, hay 1 file
checklist liệt kê đủ field bắt buộc + ý nghĩa (giống văn phong docstring rất
tốt đã có trong `content_profiles.py`, chỉ là chưa được gom thành tài liệu
hướng dẫn tác giả profile).

### 2e. Độ phủ test giữa 2 profile chưa cân xứng

`tests/test_profile_creative_contracts.py` (7 test) hiện chấm prompt lắp ráp
của CẢ `one-cup-cafe-6h` LẪN `ban-so-6` (2 test cuối file dành cho ban-so-6),
nhưng phần lớn assertion chi tiết (persona, kỷ luật điểm nhìn, self-awarded
9...) chỉ soi `one-cup-cafe-6h`. `ban-so-6` có bộ test riêng
(`test_story_hook_rule.py`, `test_narrator_lesson_closing.py`,
`test_transcript_format_contracts.py`) nhưng không cùng một chỗ, nên khó biết
"đã test đủ contract nào cho profile này chưa" chỉ bằng cách nhìn tên file.

## 3. Kế hoạch theo giai đoạn

Nguyên tắc xuyên suốt mọi giai đoạn: KHÔNG phá behavior hiện có của 2 profile
đang chạy, mỗi giai đoạn tự đóng (test xanh, có thể dừng giữa chừng mà không
để lại state dở dang), TDD bắt buộc cho bất kỳ thay đổi code nào.

### Giai đoạn 0 — Chốt ranh giới 2 lớp QA (2c), viết thành văn TRƯỚC khi làm gì khác

Vì đây là quyết định kiến trúc ảnh hưởng mọi việc sau, làm trước tiên và
**không code**: viết 1 file mới, ví dụ
`docs/constitution/38-EDITORIAL_QUALITY_LAYERS.md`, trả lời rõ:
- `script_contract.py` (shape/schema) → luôn chạy, mọi profile, không opt-out.
- `qa_agent.py` heuristic cứng → luật nào PHẢI ở đây (rẻ, tất định, chạy mọi
  lần kể cả không có LLM budget) vs luật nào nên chuyển sang rubric.
- `editorial_review_agent.py` LLM rubric → luật nào PHẢI ở đây (cần đánh giá
  ngữ nghĩa/tinh tế mà keyword không bắt được, chấp nhận tốn 1 lời gọi LLM).
- Quy tắc khi 1 profile mới cần 1 luật content mới: hỏi "luật này có thể diễn
  đạt bằng regex/keyword tất định không, hay cần hiểu ngữ cảnh?" để quyết định
  đặt ở đâu — tránh viết trùng 2 nơi.

Đây là quyết định SẢN PHẨM/KIẾN TRÚC cần bạn duyệt trực tiếp nội dung file này
trước khi Codex tiếp tục thêm luật content mới bất kỳ profile nào.

### Giai đoạn 1 — Dọn nợ tài liệu (2a), không đổi hành vi

- Cập nhật `docs/constitution/03-ARCHITECTURE.md` (hoặc file phù hợp nhất
  trong 00-37 hiện có) mô tả: `format_prompts`, `EditorialReviewProfile`,
  các `content_rules` field mới, quy ước `profiles/<id>/versions/<semver>/`.
- Cập nhật `CLAUDE.md` mục "Kiến trúc" + "Key Invariants" thêm các field mới
  là một phần hợp đồng chính thức (không phải chi tiết ẩn trong code).
- Không cần TDD (đây là docs), nhưng vẫn nên có 1 lượt review đối chiếu từng
  field với code thật (đã làm 1 phần ở mục 1 trên) để tránh doc lại lệch ngay
  từ đầu.

### Giai đoạn 2 — Đối chiếu & vá mâu thuẫn `CHANNEL_GROWTH_PLAN.md` (2b)

- Xác nhận với bạn: `ban-so-6` Long-only có phải quyết định VĨNH VIỄN không,
  hay tạm thời trong lúc chỉnh persona? (Đây là quyết định sản phẩm, không tự
  suy ra.)
- Nếu vĩnh viễn: sửa `CHANNEL_GROWTH_PLAN.md` ghi rõ series nào theo mô hình
  phễu Short→Long, series nào Long-only và lý do; tránh audit/schedule sau
  này cứ đòi `--long-form-slug`/`--playlist`/`--cta-target` cho một series đã
  chủ động tắt Short.
- Nếu tạm thời: ghi rõ điều kiện bật lại Short cho `ban-so-6` để không ai vô
  tình tưởng đây là hướng cuối cùng.

### Giai đoạn 3 — Dựng template/checklist tác giả profile (2d)

- Thêm `profiles/_template/README.md` (không phải profile thật, không được
  loader nạp) liệt kê mọi field bắt buộc/tuỳ chọn trong `profile.json`, kèm 1
  câu giải thích mỗi field (tái dùng nguyên văn docstring đã có trong
  `content_profiles.py` — không viết lại từ đầu, tránh 2 nguồn giải thích lệch
  nhau theo thời gian).
- Thêm 1 test engine-level (dùng fixture generic, không dùng 2 profile thật)
  xác nhận mọi field mà `_template` liệt kê đều thực sự được `content_profiles.py`
  đọc — chống việc template lạc hậu so với code (tự-kiểm chứng, không chỉ mô
  tả suông).

### Giai đoạn 4 — Cân bằng độ phủ test giữa 2 profile (2e)

- Không nhất thiết gộp file test, nhưng thêm 1 bảng/README ngắn trong
  `tests/` (vd `tests/README_profile_contracts.md`) liệt kê: profile nào ↔
  file test nào ↔ đang test loại contract gì (persona, closing, hook,
  editorial_review rubric, format_prompts). Mục đích: một người mới nhìn vào
  biết ngay còn thiếu test loại nào cho profile nào, không phải đọc lại 71
  commit.
- Chỉ thêm test MỚI khi phát hiện thật một khoảng trống contract chưa được
  test nào phủ (đừng thêm test để "cho đều" mà không có rủi ro thật đứng sau).

### Giai đoạn 5 — Áp dụng cho profile thứ 3 (khi có)

Chỉ tới lượt này mới thực sự "chứng minh" bộ khung đã đủ tổng quát: dựng một
profile hoàn toàn mới bằng cách CHỈ điền `profile.json` + prompt theo
`_template` từ Giai đoạn 3, không sửa một dòng code engine nào. Nếu phải sửa
code engine để profile mới hoạt động → đó là tín hiệu bộ khung ở Giai đoạn
0-4 vẫn thiếu, quay lại vá đúng chỗ thay vì vá riêng cho profile mới.

## 4. Việc KHÔNG làm trong kế hoạch này (cần quyết định riêng nếu muốn)

- KHÔNG viết lại `qa_agent.py` để chuyển toàn bộ luật cứng sang
  `editorial_review` LLM rubric — đó là thay đổi lớn, tốn thêm LLM call mỗi
  script, cần cân nhắc chi phí/latency riêng, không nằm trong "hoàn thiện
  kiến trúc đã có" mà là một quyết định kiến trúc mới.
- KHÔNG tự quyết `ban-so-6` Long-only là tạm hay vĩnh viễn (Giai đoạn 2) —
  chờ bạn xác nhận.
- KHÔNG tự đổi số hiệu/nội dung `docs/constitution/*` theo hướng khác với
  cấu trúc 00-37 đã có (CLAUDE.md ghi rõ đây là "bản đề xuất" chờ ratify theo
  từng phase của `29-MIGRATION_PLAN.md` — chỉ bổ sung đúng phạm vi, không tự
  ý tái cấu trúc toàn bộ constitution).

## 5. Ràng buộc bắt buộc khi thực thi (kế thừa từ toàn phiên làm việc)

- TDD bắt buộc cho MỌI thay đổi code (không áp dụng cho việc thuần cập nhật
  docs ở Giai đoạn 1-3, trừ test tự-kiểm-chứng template ở Giai đoạn 3).
- Fixture generic (không `ban-so-6`/`one-cup-cafe-6h`) cho mọi test engine-level
  mới, theo đúng tinh thần `test_transcript_format_contracts.py` đã có.
- Không hardcode tên profile/nhân vật vào code engine.
- Không nới lỏng/bypass QA gate hiện có để "cho dễ pass".
- Không sửa `settings.py`, default provider, renderer, TTS.
- Không `git stash`; dùng `cp`/`git show HEAD:<path>` để backup tạm nếu cần.
- `make test` phải xanh sau mỗi giai đoạn trước khi sang giai đoạn kế.
- Mỗi giai đoạn nên là 1 (hoặc vài) commit riêng, message rõ giai đoạn nào,
  để có thể dừng giữa chừng (như Codex vừa hết quota) mà không mất dấu.
- Không `batch run`/render/publish thật trong lúc làm kế hoạch này.
- Viết handoff kết quả sau mỗi giai đoạn (tiếp nối chuỗi `docs/handoffs/`),
  nêu rõ PASS/FAIL, không suy diễn.
