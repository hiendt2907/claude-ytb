---
name: youtube-auto
description: >-
  Orchestrator tự trị — chạy LIÊN TỤC vòng sản xuất funnel (1 Long + 2 Short mỗi
  ngày) qua `ytb batch` cho tới khi hết kế hoạch hoặc chạm giới hạn token, rồi
  ngủ chờ và tự tiếp tục. Dùng khi muốn sản xuất video theo lô nhiều ngày mà
  không phải ngồi canh từng lệnh.
---

# YouTube Auto — vòng lặp sản xuất tự trị

Chạy **cụm funnel** theo `docs/CHANNEL_GROWTH_PLAN.md`: mỗi ngày 1 Long (một cơ
chế trung tâm) + 2 Short khai thác góc khác, mỗi Short dẫn CTA về Long ngày đó.

> **Nguồn sự thật là CLI `ytb batch`, không phải `python -m ytb_pipeline` trực tiếp.**
> Mọi khâu đi qua preflight → checkpoint DAG 6 node → publish gate. Không gọi
> `python -m ytb_pipeline` tay: bỏ qua admission và ghi ledger/queue không nhất quán.

## Bước 1 — ĐỌC SỔ + CHỐNG TRÙNG (BẮT BUỘC, chạy đầu tiên)

Trước mọi thứ khác, đọc đủ:

1. `data/ledger.md` — mọi video đã/đang sản xuất.
2. `assets/auto_state.json` — queue + khối series đang chạy.
3. `scripts/archive/*.json` — **hơn 200 script đã sinh nhưng chưa publish**. Chống
   trùng phải soi cả đây, không chỉ ledger.
4. Memory `ytb-pipeline-state.md`.

**LUẬT CHỐNG TRÙNG (cứng):** không sản xuất cơ chế lõi trùng với bất kỳ dòng ledger
(mọi status) **hoặc** bất kỳ script archive nào. "Trùng" = cùng cơ chế tâm lý/hành
vi, dù đổi tiêu đề, đổi ví dụ, hay đổi số lượng mẹo.

Cách kiểm nhanh trước khi chốt một cơ chế:

```bash
for kw in "<từ khoá cơ chế>" "<tên tiếng Anh>"; do
  echo "$kw -> $(grep -lic "$kw" scripts/archive/*.json 2>/dev/null | wc -l) file archive"
  grep -ic "$kw" data/ledger.md
done
```

Đếm >0 → đọc file khớp, so `strategy.core_mechanism` thật; nếu cùng cơ chế → đổi
chủ đề, không chỉ đổi tiêu đề. Ghi 1 dòng lý do chọn vào ledger.

## Bước 2 — Đọc prompt sau lệnh (nếu có)

`/youtube-auto <chỉ dẫn>` — phân tích thành kế hoạch, KHÔNG hỏi lại điều prompt đã
nói. Prompt không nêu chủ đề → **tự sinh** theo 4 trụ cột trong growth plan (tâm lý
& hành vi; tập trung/trì hoãn/năng suất; thói quen sức khỏe an toàn; tiền bạc &
quyết định đời thường). Sinh chủ đề là việc của skill, không hỏi user.

## Bước 3 — Kế hoạch cụm funnel (idempotent)

**Kiểm tra đầu tiên:** nếu `assets/auto_state.json` đã có khối series `status=active`
còn tập `queued` → BỎ QUA bước lập kế hoạch, vào thẳng vòng sản xuất.

Chưa có → dựng kế hoạch bằng `ideation/series.py` (thuần, có test):

```python
from ytb_pipeline.ideation.series import build_funnel_episodes, build_series, write_series

clusters = [
    {"long": "<cơ chế trung tâm>", "shorts": ["<góc 1>", "<góc 2>"]},
    # ... 1 cụm/ngày
]
episodes = build_funnel_episodes(clusters, "<YYYY-MM-DD hôm nay>",
                                 long_hour=6, short_hours=(11, 20))
block = build_series(niche=..., reason=..., research={}, topics=[],
                     started_at="<YYYY-MM-DD>", days_total=len(clusters))
block["episodes"] = episodes
write_series(block, "assets/auto_state.json")
```

`build_funnel_episodes` gắn sẵn `video_type`, `long_form_slug`, `cta_target`,
`publish_at` theo giờ từng slot. `next_episode` tự giữ Short lại cho tới khi Long
của nó `done` — cùng luật `process_next` áp lên queue.

**Batch key:** mỗi lô dùng một key `shorts_funnel_batch_<tên>_<YYYYMMDD>` sắp xếp
SAU mọi key hiện có (`load_queue` chọn `sorted(keys)[-1]`). Batch cũ đổi tên thành
`archived_<key>` để không bị chọn nhầm — KHÔNG xoá dữ liệu.

## Bước 4 — Vòng sản xuất một tập

Lấy tập kế tiếp bằng `next_episode(block)`. Với mỗi tập:

### 4a. Ideation

```bash
bin/ytb batch start \
  --num-of-vid 1 --type-of-vid <long|short> --llm-provider codex \
  --batch-key <BATCH_KEY> \
  [--long-form-slug <slug Long> --cta-target <slug Long> --playlist "<tên>"] \
  --idea "<chủ đề + ràng buộc>"
```

- **Long dùng `--llm-provider codex`**, không phải xKiro: đã đo, xKiro/DeepSeek chỉ
  viết ~9.6k ký tự trong khi Long cần ~15.8k. Short thì provider nào cũng được.
- Ideation có thể bị QA từ chối vài lần (lệch dải ký tự, thiếu hành động cụ thể) —
  **bình thường, gate đang làm đúng việc**. Đọc `reason=` trong
  `assets/batch_logs/ideation_*.log`, bổ sung ràng buộc vào `--idea`, chạy lại.
- Ràng buộc hay phải thêm: số ký tự mục tiêu cho Short; yêu cầu section `payoff`
  kết bằng một hành động làm được ngay.

### 4b. Kiểm 3 điều kiện TRƯỚC khi tốn TTS

```bash
bin/ytb batch preflight <slug>
```

Preflight đã xét orientation theo `video_type` nên batch trộn Long+Short chạy được
dưới một tiến trình. Ngoài preflight, kiểm thêm bằng mắt: số ký tự nằm giữa dải
`safe_character_bounds`, đủ 5 purpose (`situation`, `core_answer`, `evidence`,
`application`, `payoff`), `situation` dưới `situation_char_budget`.

### 4c. Sản xuất + publish

```bash
bin/ytb batch run --publish --batch-key <BATCH_KEY>
```

Mặc định upload **private**. Không truyền `--publish` = dry-run, không upload.

### 4d. Chuyển public

Video lên private trước, người dùng duyệt, rồi chuyển public qua YouTube API
(`videos().update`, part="status", giữ nguyên mọi field khác chỉ đổi `privacyStatus`).

> **BẮT BUỘC: Long phải public TRƯỚC khi sinh Short của nó.** CTA comment dùng
> `commentThreads.insert`, và YouTube trả 403 khi video đích còn private — đã xác
> minh thật. Long public rồi thì CTA của Short đăng được ngay.

### 4e. Ghi sổ

`ytb batch run` tự ghi ledger + `auto_state.json` (`shorts_status`, `youtube_id`,
`youtube_url`). Sau khi tập xong, gọi `mark_episode_done(block, slug)` rồi
`write_series(...)`.

## Điều kiện dừng

Kiểm `YTB_LISTENER_MANAGED` đầu vòng:

- **MANAGED (`=1`)** — đang chạy dưới daemon listener. Làm hết lô, bắn Telegram tổng
  kết, **THOÁT skill**. Tuyệt đối không ngủ chờ Telegram (sẽ giành `getUpdates`).
- **STANDALONE** — hết việc thì KHÔNG thoát: bắn Telegram tổng kết + trạng thái chờ,
  rồi `ScheduleWakeup` (~1200–1800s) để tái nhập vòng lặp. Chỉ dừng hẳn khi user ra
  lệnh tường minh.

Chạm ~98% giới hạn token → ghi sổ, bắn Telegram, `ScheduleWakeup`, **không thoát**.
Lỗi một tập → ghi `status=error` + lý do, bỏ qua sang tập kế, không chặn cả lô.

## Bẫy đã gặp thật — đọc trước khi debug

| Triệu chứng | Nguyên nhân |
|---|---|
| Ideation Long timeout, cascade sang Codex | xKiro không đủ sức viết Long. Dùng `--llm-provider codex` thẳng. |
| QA từ chối nhiều lần liên tiếp | Bình thường. Đọc `reason=`, thêm ràng buộc vào `--idea`. |
| CTA comment 403 | Long đích còn private. Public Long trước rồi mới sinh Short. |
| Gate chặn dù đã vá code | Verdict cũ trong checkpoint. `load_or_create_project` tự reset node QA khi `render` chưa done — chạy lại là đủ, KHÔNG cần `ytb batch reset`. |
| `load_queue` lấy nhầm batch cũ | Nó chọn `sorted(keys)[-1]`. Đặt tên batch mới sắp xếp sau, archive key cũ. |

## Checklist mỗi vòng

- [ ] Đọc `data/ledger.md` + `assets/auto_state.json` + `scripts/archive/` trước tiên
- [ ] Chiếu LUẬT CHỐNG TRÙNG lên cả ledger VÀ archive (>200 script)
- [ ] Series đang active → bỏ qua lập kế hoạch, lấy `next_episode`
- [ ] Long dùng `--llm-provider codex`
- [ ] `bin/ytb batch preflight <slug>` PASS trước khi chạy
- [ ] Kiểm ký tự / 5 purpose / situation budget trước khi tốn TTS
- [ ] `bin/ytb batch run --publish` → private
- [ ] Long PUBLIC trước khi sinh Short của nó (điều kiện CTA)
- [ ] `mark_episode_done` + `write_series` sau mỗi tập
- [ ] Kiểm `YTB_LISTENER_MANAGED`: MANAGED thì thoát, STANDALONE thì ngủ chờ
- [ ] Chạm 98% token → ghi sổ + ScheduleWakeup, không thoát
