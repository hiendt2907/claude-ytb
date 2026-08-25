# Bàn giao Codex — ban-so-6: ComfyUI auto-generate + Long 5-7 phút

Ngày: 2026-08-25. Người viết: Claude (phiên hiện tại, không phải phiên đã dựng
prototype `../ai-money`). Trạng thái: **tạm dừng theo yêu cầu người dùng** để
Codex tiếp tục.

## Bối cảnh nhanh

Người dùng có prototype series kể chuyện "Bàn số 6" (Minh, An) tại
`../ai-money/series-pilot`, do Codex làm trước đó với model ảnh multimodal
thật (không rõ provider — có khả năng cao là model nhận nhiều ảnh tham chiếu
và sửa có chọn vùng, kiểu GPT-image/Gemini image edit). Phiên này đã:

1. Merge phần Codex làm dở thành `content profile` `ban-so-6` trong
   `claude-ytb` (1 DAG, N profile, xem `profiles/ban-so-6/`).
2. Cài **ComfyUI local thật** tại `/Users/hiendang/ComfyUI-run/ComfyUI` (SDXL
   base 1.0 + IPAdapter-plus), thay cho việc phải phụ thuộc model multimodal
   trả phí, để tự động hoá sinh ảnh cảnh trong pipeline.
3. Viết `ComfyUIStoryProvider` + nối vào `render/story.py` để renderer **tự
   sinh ảnh cảnh** (cache theo content-hash) thay vì cần asset tay.
4. Sửa 15+ lỗi lộ ra khi chạy thật (không phải khi chạy test) — xem mục dưới.
5. **Short tập 1 chạy trọn end-to-end, có video thật** (xem
   `assets/output/` lịch sử hoặc chạy lại — không còn trên đĩa vì batch
   dry-run tự dọn).
6. **Long tập 1 (5-7 phút) runtime đã đúng khung** sau khi hiệu chỉnh CPM
   riêng cho profile, nhưng **đang bị chặn ở cổng chất lượng audio**
   (transcript mismatch 81% < ngưỡng 82%). Đây là điểm dừng — xem mục cuối.

## ComfyUI — hạ tầng đã dựng, PHẢI biết trước khi động vào

- Cài tại `/Users/hiendang/ComfyUI-run/ComfyUI` (NGOÀI repo, không commit).
- Chạy: `cd /Users/hiendang/ComfyUI-run/ComfyUI && .venv/bin/python main.py --listen 127.0.0.1 --port 8188`
  (hiện tại có thể đã tắt nếu máy tắt/phiên trước dừng — kiểm bằng
  `curl -s http://127.0.0.1:8188/system_stats`).
- Model đã tải: `models/checkpoints/sd_xl_base_1.0.safetensors`,
  `models/clip_vision/CLIP-ViT-H-14-laion2B-s32B-b79K.safetensors`,
  `models/ipadapter/ip-adapter-plus_sdxl_vit-h.safetensors`.
- Custom node: `custom_nodes/ComfyUI_IPAdapter_plus` (clone từ
  `cubiq/ComfyUI_IPAdapter_plus`).
- Tên model khai trong `.env`/settings:
  `COMFYUI_SDXL_CHECKPOINT`/`COMFYUI_CLIP_VISION_MODEL`/`COMFYUI_IPADAPTER_MODEL`
  (mặc định trong `config/settings.py`, khớp 3 file trên).

### Ba kỹ thuật sinh ảnh đã kiểm chứng bằng ảnh thật (không phải đoán)

Đọc `profiles/ban-so-6/assets/identity/README.md` — ghi đủ lý do hai cách
sai trước khi tìm ra cách đúng. Tóm tắt:

1. **0 người (nền):** txt2img thuần.
2. **1 người:** txt2img + 1 IPAdapter. **Ảnh neo PHẢI là một cảnh thật** nơi
   nhân vật đó là chủ thể chính — KHÔNG dùng `character-sheet.png` (bảng
   nhiều pose, IPAdapter chép lại bố cục bảng), KHÔNG dùng ảnh mà nhân vật
   KHÁC là chủ thể (gây lây nhận dạng — An bị vẽ có kính/tóc của Minh).
3. **2 người:** **img2img trên MỘT keyframe 2-người đã duyệt** (
   `opening.png`/`recognition.png`, ảnh do Codex tạo trước đó), denoise thấp
   (~0.5), IPAdapter cả hai ở trọng số THẤP (~0.3) chỉ để giữ nhận dạng —
   KHÔNG sinh bố cục 2 người mới từ số 0 (đã thử chain 2 IPAdapter toàn cục
   và region-mask, cả hai đều lây nhận dạng). Đây chính là hướng người dùng
   chỉ ra: "Codex nó đã làm 1 hình có 2 người rồi mà" — dùng lại ảnh đó làm
   NỀN, không sinh mới.

Code: `src/ytb_pipeline/providers/image/comfyui_story_provider.py` —
`ComfyUIStoryProvider._build_establishing/_build_solo/_build_duo`.

### Ảnh neo nhận dạng hiện có

`profiles/ban-so-6/assets/identity/{minh,an}.png` — crop deterministic từ
`opening.png`/`recognition.png` (toạ độ crop ghi trong README cùng thư mục).
**Chưa có ảnh riêng cho cảnh 0-người** (establishing) ngoài style prompt
chung.

## Schema mới trong content profile (đọc trước khi sửa ideation/render)

`profiles/ban-so-6/profile.json` → khối `visual_generation`:

```json
"visual_generation": {
  "enabled": true,
  "style_prompt": "...", "negative_prompt": "...",
  "steps": 30, "cfg": 6.5,
  "solo_weight": 0.45, "duo_weight": 0.3, "duo_denoise": 0.5,
  "characters": {"minh": "identity/minh.png", "an": "identity/an.png"},
  "duo_reference_image": "recognition.png"
}
```

Fail-closed: bật `visual_generation` trên profile không phải
`narrative_mode == "character_story"` bị từ chối ngay lúc `load_content_profile`
(`content_profiles.py`).

`Segment` có field mới `scene_characters: tuple[str, ...]` — nhân vật xuất
hiện trong khung hình (tối đa 2, `()` cho cảnh không người). Khi
`visual_generation.enabled`, ideation phải khai `scene_characters` THAY CHO
`visual_asset` cố định (schema ép ở `generation_schema.py` +
`script_contract.py`; `visual_asset` vẫn hoạt động song song cho profile
KHÔNG bật auto-generate — tương thích ngược).

`render/story.py::resolve_scene_image()` là điểm resolve DUY NHẤT cho ảnh
một section: asset cố định nếu script khai, không thì cache-hoặc-sinh qua
`ComfyUIStoryProvider`. Cache: `assets/generated_visuals/<profile_id>/<hash>.png`
(trong `.gitignore`, không commit). **Fail-closed**: ComfyUI không phản hồi
→ `ProviderUnavailableError` bay thẳng lên, chặn render — không âm thầm rơi
về asset khác (quyết định người dùng đã chốt).

## Hệ số bù nhịp đọc riêng profile — MỚI, quan trọng

`ContentProfile.providers.tts_pace_factor` (mặc định 1.0, validate `(0, 2]`).
`content_contract.effective_chars_per_min(provider, video_type=, content_profile=)`
bọc `chars_per_min_for_provider` nhân thêm hệ số này.

**Vì sao có:** hằng số CPM chung (`XKIRO_LONG_CHARS_PER_MIN=1109`) đo trên
kênh 1-giọng (`one-cup-cafe-6h`). `ban-so-6` có hội thoại chuyển giọng giữa
các segment — overhead đó không nằm trong hằng số chung. Đo được TRỰC TIẾP
qua hai lần render Long thật: 7749 ký tự → 449.1s đo được (~1035 cpm thật,
cap 420s), rồi 7652 ký tự → 453.9s đo được (~1012 cpm thật). Cả hai vượt
trần ~7-8%, cùng hướng — hệ thống, không phải nhiễu. `ban-so-6` đặt
`tts_pace_factor: 0.92` (trung bình 2 lần đo ~0.923, lấy cận dưới cho margin).

**Đã kiểm chứng SAU khi set 0.92:** lần render Long thứ ba, audio đo được
**346.2s — đúng khung 300-420s** (trước đó 2 lần đều vượt trần). Hệ số này
đúng, không cần chỉnh lại — trừ khi có thêm dữ liệu đo mới cho thấy lệch.

Nếu tạo profile `character_story` MỚI khác, gần như chắc chắn cũng cần đo +
set `tts_pace_factor` riêng — đừng copy 0.92 của ban-so-6 sang profile khác
mà không đo.

## 15 lỗi đã sửa trong phiên này (tất cả lộ ra khi CHẠY THẬT, không phải khi chạy test)

Xem `git log --oneline` từ commit `b909e09` đến `83512c5` (19 commit) — mỗi
message giải thích rõ nguyên nhân + cách sửa + bằng chứng đo được. Đáng chú ý
nhất cho người tiếp theo:

- **`_check_hook_strength`/`_check_immediate_action`** viết cho kênh giải
  thích, chặn nhầm profile kể chuyện — đã tách luật riêng cho
  `character_story`.
- **Lây nhận dạng giữa 2 nhân vật** khi dùng chung 1 ảnh neo hoặc chain
  IPAdapter — xem mục ComfyUI ở trên.
- **`append_long_extension` không biết `max_sections`** — vá Long quá mỏng
  lại vượt trần, tự loại mình.
- **Hai section lặp nguyên văn** — bước `extend` từng phát lại nguyên văn
  phần mở đầu; không cổng nào so section với nhau trước khi có
  `sections.duplicate`.
- **HTTP 200 nhưng body không phải JSON hợp lệ** — `xkiro_provider.py`
  từng để lỗi này giết cả tiến trình `ytb batch start` thay vì cascade sang
  model kế tiếp.
- **`series_semantic_dedup`** chặn Long vì tiêu đề gần trùng Short cùng tập —
  KHÔNG phải bug, là hành vi đúng nhưng cần đặt tiêu đề Long khác Short khi
  sinh (đã làm bằng cách dặn trong `--idea`, chưa có cơ chế exempt tự động
  như `--replace-slug`).

## ĐIỂM DỪNG — việc Codex cần làm tiếp

Script hiện tại: `scripts/ban-nhap-xau-dau-tien.json` (24 section, 7137 ký
tự, `scene_characters` hợp lệ, preflight PASS, audio đo được 346.2s — đúng
khung 300-420s).

Chặn ở `audio_quality` gate:

```
TRANSCRIPT_MISMATCH: Transcript local khớp script 81%, dưới ngưỡng 82%.
```

Chi tiết đo được (từ `assets/projects/ban-nhap-xau-dau-tien/project.json`,
node `audio_quality`):

```
similarity: 0.806226956165506
transcript_chars (Whisper): 5422
script narration chars: 7137
duration actual_sec: 346.20966
```

**Nghi vấn chưa xác minh** (Claude phiên này CHƯA điều tra sâu, dừng theo
yêu cầu người dùng): độ lệch ký tự transcript (5422) so với script (7137) là
~24% — khá lớn cho một mismatch chỉ 1 điểm % dưới ngưỡng. Có thể do:

1. Cách đọc số giờ kiểu "6h07", "7h30" (viết tắt) — TTS/Whisper có thể xử lý
   khác cách viết trong script, tạo lệch text dù âm thanh đúng. Kịch bản này
   dùng NHIỀU mốc giờ dạng đó (13+ lần) — đáng nghi nhất.
2. Đối thoại chuyển giọng nhiều (24 section, nhiều đoạn ngắn) có thể làm
   Whisper cắt nhầm ranh giới segment khi transcribe toàn bộ audio ghép.
3. Có thể chỉ là nhiễu thật của TTS ở 1-2 segment cụ thể (âm thanh bị nuốt
   chữ) — cần nghe thử `assets/audio/ban-nhap-xau-dau-tien_xkiro_*.mp3`
   (từng segment còn nguyên trên đĩa, đánh số 00-23) để xác định segment lỗi.

Việc cần làm:
1. Đọc code cổng transcript mismatch (tìm `TRANSCRIPT_MISMATCH` trong
   `src/ytb_pipeline/voiceover/quality.py` hoặc tương đương) để hiểu thuật
   toán so khớp — có normalize số/giờ viết tắt không?
2. Nghe/so từng file `assets/audio/ban-nhap-xau-dau-tien_xkiro_NN_*.mp3` với
   `scripts/ban-nhap-xau-dau-tien.json`'s sections[NN].voiceover để tìm
   segment lệch nhiều nhất.
3. Nếu là vấn đề chuẩn hoá số/giờ (không phải TTS đọc sai) → sửa cách
   normalize trước khi so khớp (tương tự các lỗi "hằng số hiệu chỉnh sai
   ngữ cảnh" đã gặp suốt phiên này).
4. Nếu là TTS thật sự đọc sai 1-2 segment → dùng cơ chế `resynthesise_mismatched_segment`
   đã có sẵn trong `repair_payload` của report, hoặc `ytb batch retry` sau khi
   xoá riêng audio segment lỗi.
5. Sau khi qua audio_quality, sẽ tới `render` (24 section → 24 lần gọi
   ComfyUI, ước ~15-20 phút) rồi `render_quality` rồi `publish` (dry-run).
   CHƯA test render thật cho Long — Short đã test xong, Long thì mới tới
   audio_quality.

## Việc chưa làm, không phải lỗi — chỉ là chưa tới

- Chưa dọn cache `assets/generated_visuals/` (không giới hạn dung lượng).
- Chưa có ảnh neo riêng cho cảnh 0-người (establishing).
- Chưa thử profile `character_story` thứ hai để xác nhận thiết kế tổng quát
  hoá tốt (mới có ban-so-6).
- `tools/imageplayground/` — CLI thử nghiệm Apple Image Playground, xác nhận
  KHÔNG dùng được cho batch (Apple chặn `backgroundCreationForbidden` ngay
  cả khi đóng gói .app ký chữ ký thật). Giữ lại theo yêu cầu người dùng
  ("để nguyên đi"), chưa commit vào git, không phải phần đang dùng.

## Lệnh hữu ích để tiếp tục

```bash
# Kiểm ComfyUI còn sống không
curl -s http://127.0.0.1:8188/system_stats
# Nếu chết, khởi động lại:
cd /Users/hiendang/ComfyUI-run/ComfyUI && .venv/bin/python main.py --listen 127.0.0.1 --port 8188 &

# Chạy lại toàn suite trước khi sửa gì
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q -p no:cacheprovider --no-cov

# Xem lại chi tiết audio_quality của Long đang chặn
cat assets/projects/ban-nhap-xau-dau-tien/project.json | python3 -m json.tool

# Preflight lại sau khi sửa
bin/ytb batch preflight ban-nhap-xau-dau-tien
```
