# Handoff — Story renderer: caption card ≠ scene transition (P0 fix)

Ngày: 2026-08-26
Người viết: Claude
Trạng thái: implement + test xong, **chưa commit**.

## Bằng chứng lỗi ban đầu (do Codex cung cấp)

Video `assets/output/phan-hoi-dong-nghiep-nho-an-xem.mp4`: audio nguồn
393.897s, MP4 thực tế chỉ 338.837s — **mất 55s / 14% audio**. Script có 20
section nhưng renderer tách thành 162 caption card, và renderer cũ crossfade
**từng card** 0.4s thay vì chỉ crossfade giữa section.

## Root cause — 2 lỗi thật ở `src/ytb_pipeline/render/story.py`

1. **Lỗi chính:** `render_story_video()` cũ đẩy TỪNG caption card (162 card
   từ 20 section) thẳng vào `_compose_clips()`, và hàm này crossfade **mọi
   cặp clip liền kề** bằng `profile.render.transition_overlap_sec`. 162 card
   → 161 lần xfade thay vì đúng 19 lần (giữa 20 section thật) → mất audio.
2. **Lỗi thứ hai (lộ ra khi sửa lỗi 1):** khi gộp các card của một section
   thành một "section clip" bằng `-c copy` concat (`_concat_clips`),
   container-level `avg_frame_rate` bị lệch thành phân số méo (vd
   `1576320/52663` thay vì `30/1`) dù mỗi card gốc encode 30fps sạch —
   `ffmpeg xfade` từ chối ghép hai input có frame rate khai báo khác nhau,
   **crash thật** (`CalledProcessError`, `First input link main frame rate ...
   do not match ...`). Đồng thời `-t length` của mỗi card làm tròn lên khung
   hình nguyên, cộng dồn qua nhiều card khiến độ dài THẬT của section clip
   lệch khỏi tổng số học danh nghĩa (đo được +76ms cho 1 section 12-card thật
   từ chính video này) — dùng số danh nghĩa để tính offset xfade sẽ ra tổng
   thời lượng cuối sai.

## Fix (tối thiểu, chỉ trong `render/story.py`)

- `render_story_video()`: caption card của một section giờ concat với nhau
  (không crossfade, `_concat_clips`, giữ nguyên nếu chỉ có 1 card) thành MỘT
  "section clip" trước; chỉ các section clip (không phải card) mới được đưa
  vào `_compose_clips()` để xfade/acrossfade theo
  `profile.render.transition_overlap_sec`. Kết quả: overlap chỉ tốn đúng
  `section_count - 1` lần, không phải `card_count - 1` lần.
- `_probe_duration(path)` mới: đo duration THẬT bằng ffprobe sau khi build
  mỗi section clip, dùng số này (không phải `segment.duration_sec + gap`
  danh nghĩa) làm input cho `_compose_clips`'s offset math — sửa lỗi cộng
  dồn do làm tròn khung hình.
- `_compose_clips()`: filter đầu vào mỗi input thêm `fps=30` (khớp
  `-framerate 30` đã dùng ở `_render_clip`) trước `settb=AVTB,setpts=...` —
  chuẩn hoá frame rate bên trong filter graph, không phụ thuộc metadata
  container có thể bị méo sau `-c copy` concat.
- `expected_story_duration_sec()` **giữ nguyên công thức**
  `sum(audio) + gap×(N-1) − overlap×(N-1)` với N = số SECTION (không đổi vì
  công thức này vốn đã đúng — lỗi nằm ở renderer không tuân theo nó).

## TDD — RED trước, GREEN sau, verify thủ công cả hai chiều

Test có sẵn (Codex viết, chưa commit)
`test_story_renderer_preserves_audio_timeline_when_a_section_has_many_caption_cards`:
RED `3.502s vs 4.0s±0.2` trước khi sửa → GREEN sau khi tách card/section.

2 test mới trong `tests/test_profile_multivoice_render.py`:

- `test_compose_clips_normalises_frame_rate_after_concatenating_caption_cards`
  — RED xác nhận **crash thật** (`CalledProcessError`,
  `First input link main frame rate (30/1) do not match ... (30000/1001)`)
  khi tắt `fps=30`; GREEN sau khi thêm filter.
- `test_compose_clips_crossfades_sections_concatenated_from_many_caption_cards`
  — dùng ĐÚNG độ dài card đo được từ chính video thật này (section 0: 12
  card, section 1: 10 card) để verify `_probe_duration()` sửa đúng lỗi cộng
  dồn làm tròn khung hình.

Đã verify RED bằng cách tạm sửa file trực tiếp (không dùng git stash — một
lần dùng `git stash push -- <file>` suýt xoá mất toàn bộ thay đổi P0/P1 chưa
commit của phiên trước vì stash áp cho cả working tree, đã `git stash pop`
khôi phục kịp; **bài học: không dùng git stash để test tạm 1 file khi còn
nhiều thay đổi chưa commit khác trong cùng file/tree — dùng `cp` file backup
thường thay thế**).

## Kết quả render lại thật (không gọi LLM/TTS/ComfyUI)

Dùng lại audio segment + ảnh cache đã có trên đĩa từ lần chạy thật trước, chỉ
chạy lại bước compose ffmpeg:

- Audio nguồn: 393.897459s
- `expected_story_duration_sec(profile, audio_durations)` = 393.897459s
  (vì `ban-so-6` có `inter_segment_gap_sec == transition_overlap_sec == 0.4`,
  hai số này triệt tiêu nhau trong công thức)
- MP4 mới: **396.480s** (video stream 395.333s, audio stream 396.480s)
- Lệch so với audio nguồn: 2.583s = **0.656%** — trong ngưỡng
  `max(0.25s, 1%) = 3.94s` theo acceptance criteria. (Trước khi sửa: 338.837s,
  mất 14%.)

## Full test

`.venv/bin/pytest tests/ -q --no-cov` → **988 passed, 3 skipped, 1
deselected, 0 failed**.

## Việc CHƯA làm / cần Codex kiểm tra lại

1. **2.583s lệch dư (0.656%) chưa truy hết gốc** — nằm trong ngưỡng cho phép
   nên không chặn, nhưng KHÔNG bằng 0. Nghi ngờ: (a) làm tròn khung hình tích
   luỹ qua 20 section vẫn còn dư sau khi đã dùng `_probe_duration` cho từng
   section (mỗi section giảm sai số nội bộ nhưng chưa chắc sai số CHÉO giữa
   các section được triệt tiêu hoàn toàn bởi xfade offset cumulative); (b)
   `apad=pad_dur=gap` ở card cuối mỗi section có thể cộng thêm rounding riêng.
   Chưa điều tra sâu vì đã trong ngưỡng chấp nhận được — nếu muốn siết chặt
   hơn 0.656% cần đo lại pattern lệch trên nhiều video khác.
2. **Video stream duration (395.333s) khác container/audio duration
   (396.480s) khoảng 1.15s** — bình thường với muxer MP4 (track duration
   không nhất thiết bằng nhau), nhưng chưa xác nhận có ảnh hưởng phát lại
   thực tế (frame cuối đứng hình?) hay không — nên xem thử video thật.
3. Video đã render lại đè lên
   `assets/output/phan-hoi-dong-nghiep-nho-an-xem.mp4` (bản cũ 338.837s đã bị
   ghi đè) — nếu cần giữ bản cũ để so sánh, phải phục hồi từ history trước
   khi làm gì thêm với thư mục này.
4. Chưa commit gì (theo đúng yêu cầu P0 lần này) — cần gộp vào đợt commit
   chung với các thay đổi P0/P1 profile-engine trước đó (xem 2 handoff
   2026-08-25/26 khác) hoặc tách riêng, tuỳ quyết định của người review.

## File thay đổi

`src/ytb_pipeline/render/story.py` (91 dòng thêm, 11 xoá),
`tests/test_profile_multivoice_render.py` (+3 test mới, sửa 1 test không
đúng mục đích thành test khác chính xác hơn).

## Cập nhật 2026-08-26 (sau audit lần 2 của Codex) — đã sửa ở cấp ENGINE, không vá riêng video

Codex audit độc lập bản fix đầu (mục phía trên) và tìm ra lỗi thật còn lại:
video-stream 395.333s vs audio-stream 396.480s trong cùng MP4 (~1.15s audio
cuối không có hình mới). Đã sửa tiếp, **vẫn chỉ trong
`src/ytb_pipeline/render/story.py`**, không đụng script/profile/TTS nào,
không có `if slug == ...`/`if profile_id == ...` nào trong code (xác nhận
bằng grep — 0 kết quả).

### Root cause thứ ba (lộ ra sau khi audit lần 2)

Bản fix trước vẫn CẮT audio TTS gốc thành từng slice theo card rồi re-encode
AAC riêng cho mỗi slice trước khi concat — mỗi lần re-encode làm tròn độc
lập theo AAC frame (~21-23ms), lệch khác hướng với việc làm tròn video
(30fps). Sai lệch này tích luỹ khác nhau giữa 2 track qua 20 section → lệch
1.15s.

### Fix engine (4 thay đổi, tất cả generic — không tham số nào theo profile/slug)

1. **Card giờ là VIDEO-ONLY** (`_render_video_card`): dùng `-frames:v N`
   (số khung chính xác tuyệt đối) thay vì `-t length` (làm tròn). Card không
   còn audio input nào cả.
2. **`_frame_counts()`** — hàm thuần, cumulative rounding: tổng khung của
   mọi card trong 1 section luôn bằng đúng `round(tổng_giây × 30)`, không
   lệch dù bao nhiêu card.
3. **Audio gốc chỉ mux đúng 1 lần/section** (`_mux_section_audio`): không
   cắt nhỏ, chỉ transcode nguyên `segment.audio_path` + `apad` cho gap.
4. **`_compose_clips` dùng 2 timeline riêng** (`video_durations`,
   `audio_durations`) thay vì 1 list chung cho cả xfade video lẫn
   acrossfade audio.
5. **`_reconcile_section_streams`** (mới) — gọi 2 lần: sau mỗi section, VÀ
   trên output cuối cùng. Lý do cần cả 2 lần: dù mọi section đã khớp nhau
   (<16ms lệch mỗi section, đo thật), `xfade`/`acrossfade` vẫn tự làm tròn
   offset theo lưới frame riêng của TỪNG track ở MỖI lần chuyển cảnh (19 lần
   cho video Long thật 20 section) — 2 lớp lỗi độc lập, sửa 1 lớp không đủ.
   Cơ chế: nếu audio dài hơn video → GIỮ khung hình cuối (tpad), không bao
   giờ cắt audio; nếu video dài hơn → pad audio bằng silence.

### Bằng chứng RED/GREEN

- `test_frame_counts_sum_exactly_to_the_rounded_total_with_no_drift` — pure,
  không cần ffmpeg.
- `test_render_video_card_produces_the_exact_requested_frame_count` — xác
  nhận card không có audio track nào.
- `test_story_renderer_keeps_video_and_audio_streams_in_sync_with_many_cards_and_asymmetric_gap`
  (profile `gap=0.4 ≠ overlap=0.15`, 12 card/section) — RED thật trước fix:
  `abs(29.166667-29.231)=0.0643s` (vượt ngưỡng `1/30+0.01=0.0433s`) → GREEN
  sau fix: diff còn **4.7ms**.
- `test_reconcile_section_streams_holds_last_frame_when_audio_outlasts_video`
  — RED khi tắt reconcile (lệch 0.15s) → GREEN, xác nhận nội dung audio
  không bị cắt (so độ dài audio trước/sau reconcile bằng nhau).

Đã verify RED bằng cách tạm sửa file bằng `cp` backup (KHÔNG dùng git stash —
bài học từ lần trước) rồi khôi phục lại.

### Số liệu thật — render lại toàn bộ 20 section, không TTS/ComfyUI

Diagnostic output ghi vào `/tmp/story-diagnostic-output/` (KHÔNG đụng
`assets/output/`):

| | Trước (audit lần 2 phát hiện) | Sau |
|---|---|---|
| Audio nguồn | 393.897459s | 393.897459s |
| Video stream | 395.333s | **394.133333s** |
| Audio stream | 396.480s | **394.128005s** |
| **Lệch video↔audio** | **1.147s** | **0.0053s** (≈1/6 frame, ngưỡng cho phép 1 frame = 0.0333s) |
| Lệch so với audio nguồn | +2.583s (0.66%) | +0.235s (0.06%), trong `max(0.25s,1%)=3.94s` |

Không còn trailing audio thiếu hình ở cuối video. Không dùng `-shortest` ở
đâu trong toàn bộ file (grep xác nhận).

### Full test

`.venv/bin/pytest tests/test_profile_multivoice_render.py
tests/test_story_captions.py -q` → 18 passed.
`make test` → **990 passed, 3 skipped, 1 deselected, 0 failed**.

### Xác nhận cho Codex audit

- Không có `if slug ==`, `if profile_id ==`, hay literal tên video/profile
  nào trong `render/story.py` (grep `phan-hoi-dong-nghiep\|ban-so-6` trong
  file này ra 0 kết quả).
- File thay đổi CHỈ: `src/ytb_pipeline/render/story.py` (+302/-47 dòng so
  với bản trước audit lần 2), `tests/test_profile_multivoice_render.py`
  (+225 dòng). Không đụng script/profile.json/TTS/ComfyUI nào.
- Chưa commit, chưa publish, chưa gọi LLM/TTS/ComfyUI thật (chỉ tái dùng
  audio segment + ảnh cache có sẵn trên đĩa).
- Khi commit: renderer fix này nên tách 1 commit riêng, không lẫn với hunk
  profile-engine/narrator-role/image-provider khác đang cùng worktree
  (chưa commit từ trước).
