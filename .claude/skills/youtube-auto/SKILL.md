---
name: youtube-auto
description: Orchestrator tự trị — chạy LIÊN TỤC toàn bộ pipeline youtube-* (ideation → voiceover → render → publish + monetization) trong một vòng lặp. Tự pause khi hết việc hoặc khi chạm 98% limit Claude, KHÔNG thoát skill; tới khi limit reset thì tự tiếp tục. KHÔNG BAO GIỜ tự kết thúc — kể cả khi hết task, phải bắn Telegram báo trống việc rồi NGỦ CHỜ lệnh tiếp theo của user. Dùng khi muốn sản xuất video theo lô không cần ngồi canh.
version: 1.5.0
source: project-architecture
---

# YouTube Auto — vòng lặp sản xuất tự trị

Trước tiên chốt **1 ngách chính + series 30 ngày** từ trending (Bước -0.5), rồi gọi
tuần tự tất cả skill `youtube-*` cho từng tập trong series, lặp liên tục.
Khi cạn việc **hoặc** chạm ~98% giới hạn token của Claude → **pause** (không thoát
skill/prompt). Khi limit của Claude reset → **tự tiếp tục** đúng chỗ đang dở.

## Bước -2 — ĐỌC SỔ TRƯỚC TIÊN + CHỐNG TRÙNG NỘI DUNG (BẮT BUỘC, chạy đầu tiên)

> Đây là cổng chặn đặt TRƯỚC mọi bước khác. Không được bỏ qua, kể cả khi có prompt.

**Trước khi làm bất cứ điều gì** (kể cả phân tích prompt ở Bước -1), PHẢI đọc đủ:

1. `data/ledger.md` — mọi video đã/đang sản xuất (slug, tiêu đề, stage, status).
2. `assets/auto_state.json` — tiến độ runtime + cấu hình từng item.
3. Memory dự án `ytb-pipeline-state.md` — định hướng, cột mốc, ngách kênh.

Mục đích: (a) **resume** đúng item dở dang, KHÔNG làm lại khâu đã xong; (b) **biết
toàn bộ nội dung đã ra lò** để KHÔNG tạo trùng.

**LUẬT CHỐNG TRÙNG (cứng):** TUYỆT ĐỐI không sản xuất video có chủ đề/góc nhìn/tiêu
đề **tương tự** bất kỳ dòng nào trong ledger (mọi status — kể cả `done`, `render`,
`cancelled`). "Tương tự" = cùng chủ đề lõi, cùng thông điệp, hoặc cùng danh sách mẹo
dù đổi câu chữ. Ví dụ: đã có "3 thói quen buổi sáng" + "dậy sớm 30 ngày" thì KHÔNG
làm thêm "5 việc làm buổi sáng" / "cách dậy sớm" — đó là trùng hướng.

Quy trình bắt buộc khi ideation định ra một chủ đề mới:

- Đối chiếu chủ đề dự kiến với TỪNG dòng ledger. Nếu trùng/tương tự → **loại bỏ**,
  sinh góc khác đủ KHÁC BIỆT (chủ đề lõi mới, không chỉ đổi tiêu đề).
- Nếu sau vài lần vẫn chỉ ra được chủ đề trùng → **dừng + hỏi user** qua Telegram
  thay vì sản xuất trùng.
- Ghi 1 dòng lý do chọn chủ đề (và nó khác các video cũ ở điểm nào) vào ghi chú ledger.

## Bước -1 — Đọc prompt sau lệnh (nếu có)

Lệnh có thể kèm chỉ dẫn tự do phía sau, ví dụ:

- `/youtube-auto tạo 1 clip short và 1 clip dài`
- `/youtube-auto làm 3 short về cà phê, publish thật`
- `/youtube-auto 1 video dài 12 phút về dậy sớm, chỉ render`

**Nếu có prompt:** PHÂN TÍCH nó thành kế hoạch sản xuất và **bỏ qua những câu phỏng
vấn Telegram mà prompt đã trả lời**. Chỉ hỏi lại qua Telegram những gì prompt CHƯA nói.
Trích từ prompt:

- **Số lượng + loại mỗi video** → dựng danh sách công việc. Ví dụ "1 short và 1 clip
  dài" = 2 video: video A `Short (dọc)`, video B `Video dài (ngang)`. Mỗi video giữ
  cấu hình riêng (orientation/render/publish) chứ KHÔNG ép chung cả lượt.
- **Chủ đề** — nếu prompt NÊU chủ đề → nạp thẳng vào ideation. Nếu prompt KHÔNG nêu
  chủ đề → **TUYỆT ĐỐI KHÔNG hỏi user**; để [[youtube-ideation]] TỰ SINH ý tưởng hợp
  ngách kênh (tổng hợp, ưu tiên sáng sớm/động lực/lifestyle), bám tiêu chí giữ chân +
  SEO. Sinh chủ đề là việc của ideation, không phải việc của user.
  **BẮT BUỘC chiếu luật chống trùng ở Bước -2:** chủ đề tự sinh phải KHÁC mọi video
  đã có trong ledger; nếu trùng hướng phải đổi chủ đề lõi, không chỉ đổi tiêu đề.
- **Độ dài / dọc-ngang** → map `ORIENTATION` (xem bảng dưới).
- **Kiểu hình** ("AI", "stock", "slide") → map `RENDER_PROVIDER`.
- **Xuất bản** ("publish thật", "chỉ render", "dry run") → map `DRY_RUN`.

Sau khi phân tích, **xác nhận lại kế hoạch qua Telegram bằng 1 nút** (vd "Đúng kế
hoạch: 1 short + 1 clip dài, AI visual, DRY_RUN?" → `["Đúng, chạy", "Sửa lại"]`) để
tránh hiểu sai, rồi vào vòng sản xuất. Ghi kế hoạch đã chốt vào `assets/auto_state.json`
+ ledger để resume không hỏi lại.

**Nếu KHÔNG có prompt:** làm Bước 0 (phỏng vấn đầy đủ) như cũ.

## Bước -0.5 — KHỞI ĐỘNG SERIES: trending → chọn ngách → 30 ngày (BẮT BUỘC)

> Giai đoạn này đặt **SAU** Bước -2/-1 (đọc sổ + chống trùng + đọc prompt), **TRƯỚC**
> vòng sản xuất. Mục tiêu: chốt một **ngách (domain) chính** và một **series 30 ngày
> liên tục** (30 video, 1/ngày) làm xương sống nội dung, thay vì sinh chủ đề rời rạc.

**IDEMPOTENT (kiểm tra đầu tiên):** nếu `assets/auto_state.json` đã có **bất kỳ** khối
series đang chạy (`status == active` và còn tập chưa `done`) → **BỎ QUA toàn bộ Bước
-0.5** cho slot đó, không nghiên cứu lại, vào thẳng vòng sản xuất với tập kế tiếp.
Chỉ chạy 3 bước dưới khi một slot CHƯA có series active (lần đầu, hoặc series cũ đã đủ 30 tập).

### Đa series song song (nhiều khung giờ)

State có thể chứa **nhiều khối series**, mỗi khối một khung giờ riêng:

| Key trong `auto_state.json` | Slot | Giờ publish | Ngách |
|------|------|------|------|
| `series` | `morning` | **06:00** | Cơ chế tâm lý & hành vi (mental models) |
| `series_evening` | `evening` | **20:00** | Cơ chế tài chính cá nhân |

Mỗi khối độc lập: có `episodes`/`status`/`slot`/`seo_pool` riêng, dùng chung các hàm
thuần trong `series.py` (`next_episode`, `mark_episode_done`). **Mỗi vòng sản xuất:**
duyệt LẦN LƯỢT từng khối series active, lấy `next_episode` của khối đó, chạy đủ pipeline
youtube-* cho tập ấy với `publish_at` theo đúng slot (06:00 cho `series`, 20:00 cho
`series_evening`). LUẬT CHỐNG TRÙNG soi **chéo cả hai series** + ledger. Dựng series mới
cho một slot: gọi `build_series(..., hour=20, slot="evening")` rồi
`write_series(block, path, key="series_evening")`.

### Bước A — Nghiên cứu trending / hot search / hashtag

- **Nguồn (region VN, tiếng Việt):**
  - YouTube Data API `videos.list(chart=mostPopular, regionCode=VN)` — lấy video đang
    hot + category. Dùng OAuth/API key sẵn có trong `.env`/`settings`; **thiếu key →
    fail fast**, gửi Telegram báo lỗi, KHÔNG bịa số liệu.
  - Google Trends (region VN) — từ khoá/chủ đề đang lên (`pytrends` hoặc nguồn tương
    đương; nếu không có công cụ → ghi rõ hạn chế, dựa vào YouTube mostPopular là chính).
- **Hashtag / tags đang hot (BẮT BUỘC):** từ chính danh sách `videos.list(chart=mostPopular)`
  ở trên, đọc `snippet.tags` của từng video đang hot, **gom tần suất** để ra top
  hashtag/tag được dùng nhiều nhất (kèm số lần xuất hiện). Đồng thời trích các `#hashtag`
  xuất hiện trong `snippet.title`/`snippet.description`. Không gọi thêm API riêng cho
  bước này — tái dùng response mostPopular đã có để khỏi tốn quota.
- **Related / autocomplete search (gợi ý dài đuôi):** với mỗi từ khoá nóng ở trên, lấy
  gợi ý tìm kiếm để mở rộng cụm dài đuôi:
  - YouTube/Google **search autocomplete** (endpoint `suggestqueries`/`complete/search`
    `ds=yt`, hl=vi, gl=VN) — KHÔNG cần API key. Nếu endpoint chặn/không truy được → ghi
    rõ hạn chế, **KHÔNG bịa**, dựa vào tags mostPopular là chính.
  - Gom thành **keyword cluster** (cụm từ khoá liên quan) cho mỗi chủ đề nóng.
- Tổng hợp **10–20 chủ đề/từ khoá** đang nóng kèm chỉ số có được (lượt xem, đà tăng,
  category, **hashtags**, **keywords**). Ghi tạm vào `assets/auto_state.json` (khối
  `series.research`). Bộ `hashtags`/`keywords` này được [[youtube-monetization]] tái
  dùng làm SEO tag khi publish — sinh một lần ở đây, dùng lại cho cả series.

### Bước B — Chọn 1 ngách tiềm năng (chấm điểm)

Chấm mỗi ứng viên theo 4 tiêu chí (thang 1–5), chọn **điểm cao nhất**:

1. **Search/đà tăng** — mức quan tâm & xu hướng tăng.
2. **Cạnh tranh** — càng ít kênh lớn áp đảo càng tốt (điểm cao = dễ chen).
3. **Hợp YPP & advertiser-safe** — tránh chủ đề nhạy cảm/giới hạn quảng cáo.
4. **Hợp brand "1 Cốc Café 6h"** — sáng sớm/động lực/lifestyle/kỹ năng/năng suất.

Ghi **1 dòng lý do** chọn ngách (điểm từng tiêu chí + vì sao thắng) vào sổ + ledger.

### Bước C — Lấy ngách làm DOMAIN CHÍNH, dựng series 30 ngày

- Sinh **30 chủ đề con KHÁC NHAU** trong cùng ngách (1 video/ngày, 30 ngày liên tục).
- **BẮT BUỘC chiếu LUẬT CHỐNG TRÙNG (Bước -2)** cho từng tập: mỗi chủ đề con phải
  khác mọi dòng `data/ledger.md` (mọi status) **và** khác các tập khác trong series
  (chủ đề lõi mới, không chỉ đổi tiêu đề). Tập nào trùng → thay bằng góc đủ khác.
- Lên **lịch publish** mỗi tập theo giờ vàng brand (mặc định **06:00 sáng** mỗi ngày,
  `YOUTUBE_PUBLISH_AT` RFC3339 lệch +1 ngày/tập).
- **Ghi bền** kế hoạch series vào `assets/auto_state.json` (khối `series`) **và** ghi
  dòng tiêu đề series + 30 slug dự kiến vào `data/ledger.md`, để resume KHÔNG nghiên
  cứu lại và KHÔNG dựng trùng series.

```jsonc
// assets/auto_state.json — thêm khối series (cạnh "config" và "items")
"series": {
  "status": "active",                 // active | done
  "niche": "<tên ngách>",
  "reason": "<1 dòng lý do chọn + điểm tiêu chí>",
  "research": [
    {
      "topic": "...", "views": 0, "trend": "up", "source": "youtube",
      "category": "...",
      "hashtags": [ { "tag": "#...", "count": 0 } ],   // gom tần suất từ snippet.tags video hot
      "keywords": [ "cụm dài đuôi 1", "cụm dài đuôi 2" ] // từ autocomplete/related search
    }
  ],
  // hashtags/keywords tổng hợp toàn ngách, để khâu monetization tái dùng làm SEO tag
  "seo_pool": { "hashtags": [ "#..." ], "keywords": [ "..." ] },
  "started_at": "2026-06-17",
  "days_total": 30,
  "episodes": [
    { "day": 1, "slug": "...", "topic": "...", "publish_at": "2026-06-18T06:00:00+0700", "status": "queued" }
    // ... 30 tập; status: queued | done
  ]
}
```

Sau khi chốt series → mỗi vòng sản xuất lấy tập `episodes` có `status=queued` sớm nhất
làm chủ đề hiện tại, nạp vào ideation. Khi đủ 30 tập `done` → đặt `series.status=done`.

### Code hỗ trợ (dùng thay vì làm tay)

Hai module lo phần XÁC ĐỊNH của Bước -0.5; Claude chỉ lo phần sáng tạo (sinh 30 chủ đề,
chấm điểm 4 tiêu chí cho ứng viên ngách):

- `ideation/research.py::research_trending(region="VN")` — Bước A: gọi YouTube
  `videos.list(mostPopular)` + autocomplete → trả `{"research":[...], "seo_pool":{...}}`
  (đã gom hashtag/tags hot + keyword dài đuôi). Cần `YOUTUBE_API_KEY`, fail-fast nếu thiếu.
- `ideation/series.py` — Bước B+C:
  - `rank_niches(candidates)` / `pick_niche(...)` — chấm tổng & chọn ngách (candidate do
    Claude chấm `{niche, scores:{search,competition,ypp,brand}}`; `derive_search_score`
    quy đổi views→điểm search gợi ý).
  - `dedup_topics(topics, ledger_text)` — lưới an toàn cấp slug, loại tập trùng ledger
    (chống-trùng NGỮ NGHĨA vẫn do Claude phán đoán theo Bước -2).
  - `build_series(...)` + `write_series(block, "assets/auto_state.json")` — lắp khối
    `series` (lịch publish 06:00, +1 ngày/tập) và ghi atomic, KHÔNG đụng `config`/`items`.
  - `next_episode(series_block)` — mỗi vòng gọi để lấy tập `queued` sớm nhất nạp vào
    ideation; trả `None` khi hết tập / series đã `done` (→ điều kiện dừng vòng lặp).
  - `mark_episode_done(series_block, slug)` — sau khi tập `done`, trả series MỚI
    (immutable) với tập đó `done`; tự đặt `series.status=done` khi đủ 30 tập. Ghi lại
    bằng `write_series(...)`.

## Bước 0 — Phỏng vấn cấu hình qua Telegram (NÚT BẤM)

> Chỉ chạy khi prompt sau lệnh KHÔNG cung cấp đủ thông tin (xem Bước -1). Mỗi câu
> hỏi mà prompt đã trả lời thì BỎ QUA, không hỏi lại.

**Trước khi sản xuất bất kỳ video nào**, hỏi user qua Telegram bằng **nút chọn sẵn**
(inline keyboard) — KHÔNG bắt user gõ tay. Dùng `notify.telegram.ask_choice(question, options)`:
gửi câu hỏi + nút, chờ user bấm, trả về nhãn đã chọn. Hỏi tuần tự, mỗi câu 1 lần,
rồi áp dụng cho toàn bộ video trong lượt chạy (hoặc hỏi lại mỗi video nếu user muốn khác nhau).

Bộ câu hỏi chuẩn (thêm/bớt tùy ngữ cảnh):

1. **Độ dài** — "Làm video ngắn hay dài?" → `["Short (dọc ≤60s)", "Video dài (ngang)"]`
2. **Kiểu hình** — "Render hình thế nào?" → `["Slide tĩnh (youtube-render)", "AI visual (youtube-render-ai)"]`
3. **Xuất bản** — "Publish luôn sau render?" → `["Publish thật ngay", "Chỉ render (DRY_RUN)"]`
4. **Số lượng** — "Làm mấy video lượt này?" → `["1", "3", "5", "Hết hàng đợi"]`
   (tùy chọn, nếu queue chưa cố định)

Ghi câu trả lời vào sổ trạng thái + ledger để **resume biết cấu hình** đã chọn, không
hỏi lại sau pause/reset. "Publish thật ngay" → đảm bảo `DRY_RUN=false` ở khâu publish;
mặc định giữ DRY_RUN nếu user chọn "Chỉ render".

```python
from ytb_pipeline.notify.telegram import ask_choice
length = ask_choice("Làm video ngắn hay dài?", ["Short (dọc ≤60s)", "Video dài (ngang)"])
visual = ask_choice("Render hình thế nào?", ["Slide tĩnh", "AI visual"])
publish = ask_choice("Publish luôn sau render?", ["Publish thật ngay", "Chỉ render (DRY_RUN)"])
```

### Map cấu hình → biến môi trường KHI CHẠY (mỗi lượt, KHÔNG sửa .env cố định)

Truyền env inline cho lệnh `python -m ytb_pipeline <slug>` theo lựa chọn vừa hỏi —
để mỗi video dùng đúng cấu hình của nó, không để biến dính cứng trong `.env`:

- `visual == "AI visual"` → `RENDER_PROVIDER=ai` (cần `PEXELS_API_KEY` trong `.env`,
  fail fast nếu thiếu); `visual == "Slide tĩnh"` → bỏ qua (mặc định `slide`).
- `length == "Video dài (ngang)"` → `ORIENTATION=landscape` (render 1920x1080, B-roll
  ngang; khâu publish tự xếp loại **clip** chứ không gắn #Shorts).
  **BẮT BUỘC:** khâu ideation phải sinh kịch bản **10–30 phút** (đặt `target_minutes`
  trong JSON), nội dung dày/chi tiết theo mục **2b** video-quality-rules.md — KHÔNG để
  video dài < 10 phút (`load_script` fail-fast nếu mỏng).
  `length == "Short (dọc ≤60s)"` → bỏ qua (mặc định `portrait` 1080x1920 → #Shorts).
  Lưu ý: hướng ngang chỉ áp dụng ở renderer AI; Short dọc dùng được cả slide lẫn AI.
- `publish == "Publish thật ngay"` → `DRY_RUN=false`; `"Chỉ render"` → `DRY_RUN=true`.
- **Lên lịch công khai**: nếu muốn video tự PUBLIC vào một mốc giờ → `YOUTUBE_PRIVACY=private`
  + `YOUTUBE_PUBLISH_AT=<RFC3339>` (YouTube giữ private tới giờ đó rồi tự công khai).
  Mặc định brand "1 Cốc Café 6h" nên lên lịch **6:00 sáng** cho hợp tên kênh.
  Publish thật xong vẫn **move file lên Drive** `Claude-YTB` rồi xoá local.

```bash
RENDER_PROVIDER=ai ORIENTATION=landscape DRY_RUN=false \
  YOUTUBE_PRIVACY=private YOUTUBE_PUBLISH_AT=2026-06-17T06:00:00+0700 \
  .venv/bin/python -m ytb_pipeline <slug>
```

`settings.render_provider` (mặc định `slide`) đọc env này; `pipeline.run` tự chọn
`render_video_ai` vs `render_video`. KHÔNG thêm `RENDER_PROVIDER`/`ORIENTATION` vào
`.env` — sẽ khoá cứng mọi lượt sau.

## Thứ tự gọi skill (mỗi chủ đề = 1 vòng)

1. **[[youtube-pipeline-core]]** — nạp quy ước (dataclass bất biến, DRY_RUN). Đọc 1 lần đầu.
2. **[[youtube-ideation]]** — sinh `VideoIdea` + `Script`, rồi **CHỜ DUYỆT qua Telegram**.
   Đây là điểm chặn người dùng: chỉ qua bước sau khi user gõ *OK* trên Telegram.
   Nếu user yêu cầu sửa → sửa prompt, sinh lại, gửi lại bản đầy đủ (skill tự xử lý).
3. **[[youtube-voiceover]]** — TTS kịch bản đã duyệt (provider theo `settings.tts_provider`).
4. **[[youtube-render]]** — dựng .mp4 + thumbnail (hoặc **[[youtube-render-ai]]** nếu
   muốn visual sinh bằng AI thay slide tĩnh).
5. **[[youtube-publish]]** — upload (tôn trọng `DRY_RUN`); rồi **[[youtube-monetization]]**
   tối ưu SEO/analytics.
6. Ghi kết quả vào sổ trạng thái (xem dưới), sang chủ đề kế tiếp.

## Hàng đợi & sổ trạng thái (để resume được)

Trạng thái phải **bền** qua lần pause/reset VÀ qua mọi session — không giữ trong đầu.
Ba lớp ghi bắt buộc, cập nhật NGAY sau mỗi khâu (atomic):

1. **Hàng đợi chủ đề:** `scripts/queue.json` (danh sách slug/topic cần làm).
2. **Sổ tiến độ runtime:** `assets/auto_state.json` — mỗi item
   `{topic, orientation, render_provider, dry_run, stage, status, updated}`
   với `stage ∈ {ideation, approved, voiceover, render, publish, done}`. Khi prompt
   yêu cầu các video KHÁC nhau (vd 1 short + 1 dài), mỗi item GIỮ cấu hình riêng của
   nó — chạy đúng env theo item, không ép chung cả lượt.
3. **Ledger sản xuất:** `data/ledger.md` — sổ cái người-đọc-được, bền xuyên mọi session.
   Thêm/ cập nhật 1 dòng cho mỗi video (slug, tiêu đề, stage, status, URL/ghi chú).
4. **Memory dự án:** cập nhật `ytb-pipeline-state.md` trong memory khi có thay đổi
   định hướng/cột mốc (vd video mới `done`, đổi provider) — để session sau biết bối cảnh.

Khi resume (đầu mỗi session hoặc sau pause): **đọc `data/ledger.md` + `assets/auto_state.json`
trước tiên**, tiếp tục từ `stage` dang dở, **không làm lại** khâu đã xong.

## Quản lý giới hạn token (pause ở 98%)

Mục tiêu: không bao giờ bị cắt giữa chừng một khâu.

- **Trước mỗi khâu nặng** (ideation gọi LLM, hoặc trước khi sang chủ đề mới), ước
  lượng token còn lại. Nếu đã dùng **≥ 98%** ngân sách phiên → **không bắt đầu khâu mới**.
- Khi chạm ngưỡng: ghi sổ trạng thái (đảm bảo điểm dừng sạch), gửi Telegram
  `⏸️ Tạm dừng — chạm 98% limit. Sẽ tiếp tục khi reset.`, rồi **lên lịch thức dậy**
  bằng `ScheduleWakeup` vào thời điểm limit reset (nếu biết) hoặc fallback ~20–30 phút.
  **KHÔNG kết thúc skill** — vòng lặp ngủ chờ, không exit prompt.
- Khi thức dậy / limit đã reset → đọc sổ, tiếp tục đúng chỗ.

> Lưu ý cơ chế: khi Claude Code chạm limit cứng, phiên tự dừng và hiện giờ reset.
> Skill này chủ động dừng SỚM (98%) để có điểm dừng sạch + lịch resume, thay vì bị
> ngắt giữa một khâu. Dùng `ScheduleWakeup(delaySeconds, prompt=<lệnh /loop của skill này>)`
> để tái nhập vòng lặp sau khi reset.

## Chế độ chạy: standalone vs managed (dưới listener)

> Kiểm tra biến môi trường `YTB_LISTENER_MANAGED` NGAY đầu vòng để chọn hành vi khi hết task.

- **MANAGED (`YTB_LISTENER_MANAGED=1`):** đang chạy DƯỚI daemon listener Telegram
  (`src/ytb_pipeline/listener.py`). Listener mới là kênh nhận lệnh duy nhất. Vì vậy:
  làm hết LÔ việc được giao (theo prompt/`/auto`), bắn Telegram tổng kết, rồi **THOÁT
  skill (return)** để trả quyền + luồng Telegram lại cho listener. **TUYỆT ĐỐI KHÔNG**
  ngủ chờ lệnh trên Telegram ở chế độ này (sẽ giành `getUpdates` với listener + treo daemon).
- **STANDALONE (không có biến đó):** chạy trực tiếp, không qua listener → áp dụng quy
  tắc "không tự thoát, chờ lệnh" ở mục dưới.

## Điều kiện dừng vòng lặp — STANDALONE (KHÔNG BAO GIỜ tự thoát)

> Chỉ áp dụng khi KHÔNG có `YTB_LISTENER_MANAGED`. Vòng lặp này **không có điểm exit
> tự nguyện**: mọi nhánh "hết việc" kết thúc bằng **bắn Telegram + ngủ chờ lệnh user**.

- **Hết hàng đợi & mọi item `stage=done` (hết task):** KHÔNG kết thúc. Thay vào đó:
  1. Gửi Telegram **tổng kết lô vừa xong** (số video done, link/slug, trạng thái).
  2. Gửi tiếp Telegram trạng thái chờ lệnh, ví dụ:
     `✅ Hết hàng đợi. Đang chờ lệnh tiếp theo. Nhắn chủ đề/số lượng để làm tiếp, hoặc "dừng" để tắt.`
     Ưu tiên kèm nút `ask_choice` (vd `["Làm thêm theo series", "Nhập chủ đề mới", "Tạm dừng hẳn"]`).
  3. **Ngủ chờ** bằng `ScheduleWakeup(delaySeconds, prompt=<lệnh /loop của skill này>)`
     (fallback ~1200–1800s) để tái nhập vòng lặp; mỗi lần thức dậy kiểm tra xem user
     đã nhắn lệnh/hàng đợi đã có thêm việc chưa → có thì làm tiếp, chưa thì lại ngủ chờ.
  4. Chỉ DỪNG HẲN khi **user ra lệnh dừng tường minh** (vd bấm "Tạm dừng hẳn" hoặc nhắn "dừng/stop").
- Chạm 98% limit → **pause** (ngủ chờ reset), KHÔNG kết thúc.
- Lỗi một chủ đề → ghi `status=error` + lý do vào sổ, gửi Telegram, **bỏ qua** sang
  chủ đề kế (không để 1 lỗi chặn cả lô).

## Checklist mỗi vòng

- [ ] Bước -2 (ĐẦU TIÊN): ĐỌC `data/ledger.md` + `assets/auto_state.json` + memory `ytb-pipeline-state.md`
- [ ] Bước -2: chiếu LUẬT CHỐNG TRÙNG — chủ đề mới KHÔNG được tương tự bất kỳ dòng ledger (mọi status)
- [ ] Bước -1: nếu có prompt sau lệnh → phân tích thành kế hoạch, BỎ QUA câu hỏi đã được trả lời
- [ ] Bước -0.5: nếu CHƯA có series active → research trending VN (+ gom hashtag/tags hot + autocomplete keywords) → chấm điểm chọn 1 ngách → dựng series 30 ngày, ghi vào auto_state.json + ledger
- [ ] Bước -0.5/A: ghi `hashtags`/`keywords` vào `series.research` + `seo_pool` để monetization tái dùng làm SEO tag
- [ ] Bước -0.5: nếu ĐÃ có series active → BỎ QUA nghiên cứu, lấy tập `queued` sớm nhất làm chủ đề hiện tại
- [ ] Mỗi tập trong series phải qua LUẬT CHỐNG TRÙNG (khác ledger + khác các tập khác)
- [ ] Prompt nhiều video khác loại (short + dài) → mỗi video giữ cấu hình riêng, không ép chung
- [ ] Bước 0: phỏng vấn cấu hình qua Telegram bằng NÚT BẤM (ask_choice), không bắt gõ tay
- [ ] Lưu lựa chọn cấu hình vào sổ/ledger để resume không hỏi lại
- [ ] Đọc `data/ledger.md` + `assets/auto_state.json` trước khi làm — không lặp khâu đã xong
- [ ] Cập nhật ledger + memory dự án sau mỗi video (bền xuyên session)
- [ ] Ideation phải qua cổng duyệt Telegram mới sang voiceover ([[youtube-ideation]])
- [ ] Tôn trọng `DRY_RUN` ở publish ([[youtube-publish]])
- [ ] Cập nhật sổ trạng thái NGAY sau mỗi khâu (resume an toàn)
- [ ] Kiểm tra ngưỡng 98% TRƯỚC mỗi khâu nặng; pause sạch nếu chạm
- [ ] Pause = ngủ chờ reset (ScheduleWakeup), KHÔNG thoát skill/prompt
- [ ] Đầu vòng: kiểm tra `YTB_LISTENER_MANAGED` — MANAGED thì hết lô = THOÁT (trả quyền listener), KHÔNG ngủ chờ Telegram
- [ ] STANDALONE: HẾT TASK ≠ kết thúc — bắn Telegram tổng kết + ngủ chờ lệnh user (ScheduleWakeup); chỉ dừng khi user lệnh tường minh
- [ ] Lỗi 1 chủ đề không làm dừng cả lô
