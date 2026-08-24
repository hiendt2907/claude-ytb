# Blueprint: Vòng lặp tự trị hardening code pipeline ytb (dev-hardening-loop)

**Trạng thái:** Draft — chờ review + phê duyệt user trước khi bắt đầu Step 1.
**Ngày tạo:** 2026-07-24
**Chế độ:** Full mode (git + gh CLI có sẵn, remote `origin` → `hiendt2907/claude-ytb`, branch mặc định `main`).

## Mục tiêu

Xây một vòng lặp tự trị, **có điểm dừng hội tụ** (không phải vòng lặp vô tận),
chuyên sửa lỗi / nâng chất lượng code của **chính pipeline sản xuất video**
(`voiceover/`, `render/`, `render` AI, audio quality gate) — khác với skill
`youtube-auto` đã có (vốn dùng pipeline để *sinh* video). Vòng lặp này *sửa*
code sinh video, không sinh video.

**Điều kiện dừng hội tụ** ("hết việc" thật sự — xem Step 6): pipeline đạt
chuẩn chất lượng đã định nghĩa. Sau khi đạt, vòng lặp báo Telegram tổng kết
và dừng hẳn (không ngủ chờ vô hạn như youtube-auto) — vì mục tiêu là *một
lần đạt chuẩn*, không phải sản xuất liên tục.

## Nguồn backlog task (đã chốt với user)

1. Scanner quét code tìm debt signal (Step 1) — **không dựa TODO/FIXME đơn
   thuần** vì repo hiện tại **0 comment TODO/FIXME** (đã kiểm tra
   2026-07-24). Nguồn thật:
   - File > 400 dòng trong `src/ytb_pipeline/render/`, `voiceover/`
     (`compose_ai.py` hiện 609 dòng — đã vi phạm rule 400 dòng, tăng từ 577
     dòng ghi trong CLAUDE.md, cần cập nhật con số).
   - Các dòng "VI PHẠM"/"CHƯA ĐẠT" đã tự ghi nhận trong `CLAUDE.md` (ví dụ
     Pexels-as-default ở mục Triết lý dự án #3) — nhưng **chỉ lấy các mục
     liên quan trực tiếp chất lượng audio/video/voiceover**, KHÔNG đụng
     hạng mục kiến trúc khác ngoài phạm vi.
   - Test đỏ/skip liên quan render/voiceover/audio quality gate.
2. Scanner → Agent `planner` soạn task draft (title, mô tả, acceptance
   criteria, tier).
3. Agent đóng vai reporter gửi draft qua Telegram (`notify/telegram.py`,
   `ask_choice`) — user **Approve / Edit / Skip** từng task trước khi vào
   `TaskCreate`. Không có task nào vào hàng đợi mà chưa qua cổng duyệt này.

## Ngưỡng "hết việc" (đã chốt với user)

KHÔNG phải "TaskList rỗng" đơn thuần — TaskList rỗng chỉ là *tạm hết việc
đã duyệt*. Điều kiện dừng THẬT là **quality bar cụ thể** (định nghĩa ở Step
6), được kiểm tra lại mỗi khi TaskList rỗng: nếu quality bar đã đạt → dừng
hẳn + báo cáo tổng kết; nếu TaskList rỗng nhưng quality bar CHƯA đạt →
scanner chạy lại vòng mới để tìm task tiếp theo (không cần user re-trigger).

## Ràng buộc kiến trúc bắt buộc (rút từ Research phase)

- **Không giành `getUpdates` với `listener.py`**: mọi gửi Telegram dùng
  thẳng `notify/telegram.py` (helper gửi tin, không tự poll). Nếu vòng lặp
  cần *hỏi* user (approve/edit task) và đang chạy dưới listener
  (`YTB_LISTENER_MANAGED=1`), phải tạm dừng poll của listener y hệt cơ chế
  `/auto` hiện có — tái dùng, không viết cơ chế song song.
- **MANAGED vs STANDALONE** (theo đúng pattern `youtube-auto`): dưới
  listener → hết task đã duyệt thì THOÁT, trả quyền; standalone → được
  phép `ScheduleWakeup` ngủ chờ.
- **Checkpoint bền, không dựa RAM**: trạng thái loop (task hiện tại, lần
  quét cuối) phải đọc lại được sau khi tiến trình Claude Code restart —
  dùng TaskList (đã có state `pending/in_progress/done`) làm nguồn sự thật
  duy nhất, không tạo file trạng thái song song.
- **`listener.py` (412 dòng) đã > 400 dòng** — KHÔNG thêm logic mới trực
  tiếp vào file này (đúng Refactoring Rules của CLAUDE.md). Nếu cần thêm
  route Telegram, tách route mới ra module riêng rồi import vào
  `listener.py`, giữ file chính dưới 400 dòng hoặc tách theo pattern đã
  làm với `batch_cli.py` → package.
- **`.claude/commands/` hiện có uncommitted changes** (`git status` đầu
  phiên cho thấy `?? .claude/commands/`) — Step 1 phải kiểm tra lại trước
  khi thêm command mới, tránh đè lên việc dở của phiên trước.

## Danh sách bước (7 step, 1 PR/step)

```
Step 1 (serial, không phụ thuộc)
  └─> Step 2 (phụ thuộc Step 1: cần schema task draft)
        └─> Step 3 (phụ thuộc Step 2: cần TaskCreate contract)
              └─> Step 4 (phụ thuộc Step 3: cần vòng heartbeat để gắn cycle vào)
                    └─> Step 5 (phụ thuộc Step 4: bọc thêm quanh cycle)
Step 6 (song song được với Step 2-5, phụ thuộc Step 1 — dùng chung debt-signal logic)
Step 7 (cuối cùng, phụ thuộc tất cả — doc + integration test)
```

---

### Step 1 — Debt scanner thuần (pure function, model: default/Sonnet)

**Bối cảnh:** Cần một hàm thuần (không I/O phụ, dễ test) quét
`src/ytb_pipeline/render/`, `src/ytb_pipeline/voiceover/` và nội dung
`CLAUDE.md` để liệt kê debt signal. Đặt tại module mới
`src/ytb_pipeline/orchestrator/dev_loop/scanner.py` (package mới
`dev_loop/` tách biệt hoàn toàn khỏi `ideation_*`/`batch_cli` hiện có).

**Việc cần làm:**
- Hàm `scan_file_size_violations(root: Path, max_lines: int = 400) -> list[DebtSignal]`
  — liệt kê file trong `render/`, `voiceover/` vượt quá `max_lines`.
- Hàm `scan_claude_md_violations(claude_md_text: str) -> list[DebtSignal]`
  — parse các dòng có marker "VI PHẠM"/"CHƯA ĐẠT" trong `CLAUDE.md`, lọc
  chỉ giữ mục có từ khoá liên quan render/voiceover/audio/video quality.
- Hàm `scan_failing_tests(pytest_report: ...) -> list[DebtSignal]` — nhận
  kết quả pytest đã chạy sẵn (JSON report), KHÔNG tự chạy subprocess bên
  trong hàm thuần (giữ đúng rule "no subprocess trong unit test" — hàm chỉ
  parse, việc chạy subprocess là code gọi bên ngoài, có test riêng dạng
  integration).
- `DebtSignal` là `@dataclass(frozen=True)`: `{source, file, description, severity}`.
- `collect_debt_signals(...) -> list[DebtSignal]` gộp cả 3 nguồn.

**Acceptance criteria:**
- Unit test cho từng hàm scan với fixture file/text giả (không đọc file
  thật của repo trong assert cứng số dòng, vì số dòng sẽ đổi theo thời gian).
- `mypy --strict` sạch trên module mới.
- Không import gì từ `ideation_*`/`batch_cli` — module độc lập.

**Rollback:** Xoá package `dev_loop/` — không ai phụ thuộc nó ở bước này.

---

### Step 2 — Planner draft + cổng duyệt Telegram (model: default/Sonnet cho code, planner agent do loop gọi ở runtime không phải lúc build)

**Bối cảnh:** Biến `list[DebtSignal]` (Step 1) thành task draft gửi user
duyệt qua Telegram trước khi vào hàng đợi thật.

**Việc cần làm:**
- `src/ytb_pipeline/orchestrator/dev_loop/task_draft.py`:
  - `DebtSignal` → prompt cho Agent `planner` (gọi runtime, không hardcode
    kết quả) sinh `TaskDraft {title, description, acceptance_criteria,
    tier}`.
  - `request_approval(draft: TaskDraft) -> ApprovalResult` dùng
    `notify.telegram.ask_choice` với 3 nút: `["Approve", "Edit", "Skip"]`.
    `Edit` → đọc tin nhắn tự do tiếp theo của user làm ghi chú sửa, quay lại
    planner với ghi chú đó, sinh draft mới, hỏi lại.
- Chỉ khi `Approve` → hàm trả về draft đã duyệt để Step 3 gọi `TaskCreate`.

**Acceptance criteria:**
- Test với fake `ask_choice`/fake planner response (không gọi Telegram/LLM
  thật trong unit test).
- Không tự động approve bất kỳ trường hợp nào — mọi task bắt buộc qua
  người dùng.

**Rollback:** Xoá `task_draft.py`; Step 1 vẫn đứng độc lập.

---

### Step 3 — Heartbeat loop (ScheduleWakeup) + MANAGED/STANDALONE (model: default/Sonnet)

**Bối cảnh:** Nhịp tái kích hoạt, mô phỏng theo đúng mục "Quản lý giới hạn
token" + "Chế độ chạy: standalone vs managed" của skill `youtube-auto`
(đọc lại `.claude/skills/youtube-auto/SKILL.md` trước khi code — copy đúng
tinh thần, KHÔNG copy-paste logic sản xuất video vào đây).

**Việc cần làm:**
- Skill mới `.claude/skills/dev-hardening-loop/SKILL.md` (đây là skill
  markdown điều khiển hành vi Claude, không phải Python) mô tả vòng lặp:
  1. Kiểm tra `YTB_LISTENER_MANAGED` — MANAGED thì hết batch đã duyệt =
     THOÁT; STANDALONE thì được `ScheduleWakeup` ngủ chờ.
  2. Mỗi lần tỉnh: `TaskList` — có `pending` → dequeue (Step 4); không có
     → chạy Step 1+2 để tìm task mới; nếu Step 1 không tìm ra debt signal
     nào nữa → kiểm tra quality bar (Step 6):
     - Đạt → gửi Telegram tổng kết, **dừng hẳn** (không ngủ chờ lại, khác
       youtube-auto — mục tiêu là hội tụ một lần, không sản xuất liên tục).
     - Chưa đạt nhưng cũng không tìm được debt signal mới → báo Telegram
       "cần con người quyết định bước tiếp" rồi dừng, không đoán mò.
  3. Chạm ~98% token của phiên → pause sạch (ghi TaskUpdate trạng thái
     hiện tại), `ScheduleWakeup` resume — giống hệt youtube-auto.

**Acceptance criteria:**
- Skill doc review được: một agent mới đọc file này từ đầu vẫn hiểu đúng
  luồng, không cần đọc thêm gì khác ngoài các skill được dẫn chiếu.
- Không có nhánh nào trong skill khiến loop tự thoát mà không gửi Telegram
  trước (trừ nhánh MANAGED-hết-batch, theo đúng luật listener hiện có).

**Rollback:** Xoá file skill mới; không ảnh hưởng `youtube-auto` hiện có.

---

### Step 4 — Chu trình thực thi 1 task (model: strongest/Opus cho phần thiết kế cycle, thực thi dùng default)

**Bối cảnh:** Với 1 task đã `TaskUpdate(in_progress)`, chạy chu trình:
start-new-task → thực thi → code-reviewer gate → done → báo cáo → clear.

**Việc cần làm:**
- Bổ sung vào skill `dev-hardening-loop` (Step 3) phần "Chu trình 1 task":
  1. Chạy skill `start-new-task` (đã có sẵn) để nạp memory liên quan tới
     phạm vi task (ví dụ memory `ytb-brightness-fix-2026-06-22` nếu task
     đụng compose_ai.py).
  2. Thực thi thay đổi theo `acceptance_criteria` đã duyệt ở Step 2.
  3. Gọi Agent `code-reviewer`; có CRITICAL/HIGH → không đánh dấu done,
     quay lại sửa (tối đa N lần lặp trước khi báo lỗi cho user thay vì
     lặp vô hạn).
  4. `TaskUpdate(done)`.
  5. Gửi Telegram hoàn thành qua `notify/telegram.py`: task, file thay
     đổi, kết quả test, link diff nếu có PR.
  6. Chạy `/prepare-clear` rồi `/clear` trước khi vào chu kỳ kế tiếp.

**Acceptance criteria:**
- Format báo cáo Telegram hoàn thành và báo cáo lên-kế-hoạch (Step 2) dùng
  chung 1 template hàm trong `notify/telegram.py` (tránh 2 chỗ tự chế
  chuỗi khác nhau).
- Có giới hạn số lần lặp sửa-theo-review (tránh vòng lặp vô hạn nội bộ 1
  task) — ghi rõ số cụ thể trong skill doc, không để mặc định ngầm.

**Rollback:** Revert phần "Chu trình 1 task" trong skill doc; Step 3 vẫn
chạy được ở dạng khung sườn (không tự thực thi task).

---

### Step 5 — Rate-limit / backoff (model: default/Sonnet)

**Bối cảnh:** Bọc chu trình Step 4 để không coi rate-limit là fail.

**Việc cần làm:**
- Thêm vào skill doc: khi gặp lỗi giới hạn sử dụng giữa chu trình, KHÔNG
  `TaskUpdate(failed)` — giữ nguyên `in_progress`, ghi log lý do, gọi
  `ScheduleWakeup` với backoff (dùng thời gian reset nếu response trả về,
  nếu không thì tăng dần theo cấp số, có trần tối đa), rồi khi tỉnh dậy
  resume đúng task đó từ đầu chu trình (không đoán trạng thái giữa chừng,
  chu trình 1 task được coi là atomic — nếu bị cắt giữa chừng, làm lại
  toàn bộ chu trình cho task đó là chấp nhận được, vì mỗi task nên đủ nhỏ).

**Acceptance criteria:**
- Phân biệt rõ trong skill doc: lỗi rate-limit (retry) vs lỗi thực thi
  thật (báo lỗi + skip task, chuyển task tiếp, giống lỗi 1 chủ đề trong
  youtube-auto).

**Rollback:** Bỏ đoạn backoff; Step 4 vẫn chạy được (chỉ là không chịu
được rate-limit giữa chừng).

---

### Step 6 — Định nghĩa quality bar hội tụ (model: strongest/Opus — quyết định tiêu chí ảnh hưởng lâu dài)

**Bối cảnh:** Đây là quyết định quan trọng nhất — nếu định nghĩa mơ hồ,
vòng lặp không bao giờ dừng đúng hoặc dừng sai lúc.

**Việc cần làm:**
- Thêm `src/ytb_pipeline/orchestrator/dev_loop/quality_bar.py`:
  `evaluate_quality_bar() -> QualityBarResult` kiểm tra CỤ THỂ (không mơ
  hồ "chất lượng cao"):
  - Không còn file nào trong `render/`, `voiceover/` vượt 400 dòng.
  - Không còn dòng "VI PHẠM"/"CHƯA ĐẠT" liên quan audio/render/voiceover
    trong `CLAUDE.md`.
  - `pytest -m "not integration and not e2e"` xanh 100%.
  - Không có finding CRITICAL/HIGH còn mở từ lần code-reviewer gần nhất
    (Step 4) trên các file thuộc `render/`/`voiceover/`.
- **Không tự đặt thêm tiêu chí ngoài danh sách này** trừ khi user xác nhận
  — đây là ranh giới "hết việc" ảnh hưởng trực tiếp khi nào vòng lặp dừng
  hẳn, phải giữ hẹp và có thể kiểm chứng bằng code, không suy diễn.

**Acceptance criteria:**
- `evaluate_quality_bar()` là hàm thuần nhận input đã thu thập sẵn (danh
  sách vi phạm, kết quả pytest) — không tự chạy subprocess bên trong,
  giống rule ở Step 1.
- Unit test cho từng nhánh đạt/chưa đạt.

**Rollback:** Xoá `quality_bar.py`; Step 3 tạm dùng "TaskList rỗng" làm
điều kiện dừng placeholder cho tới khi Step 6 xong (ghi rõ TODO tạm thời
trong PR, không để lẫn với repo debt thật).

---

### Step 7 — Docs + integration test (model: default/Sonnet)

**Bối cảnh:** Theo Documentation Rules của CLAUDE.md — thay đổi kiến trúc
phải cập nhật doc cùng change set.

**Việc cần làm:**
- Cập nhật `CLAUDE.md` (bản `CLAUDE.md` hiện tại đang là "Proposed" theo
  đầu file — làm rõ với user xem cập nhật vào `CLAUDE.md` này hay chờ bản
  ratified, tránh sửa nhầm file không phải nguồn sự thật).
- Thêm memory `dev-hardening-loop-architecture.md` (type: project) ghi lại
  quyết định: vì sao tách khỏi youtube-auto, quality bar là gì, vì sao
  không dùng TODO/FIXME đơn thuần.
- Integration test (`@pytest.mark.integration`) mô phỏng 1 chu kỳ đầy đủ
  bằng fake Telegram + fake planner/code-reviewer response — KHÔNG gọi
  Claude/Telegram thật, đúng Testing Rules của CLAUDE.md.

**Acceptance criteria:**
- `make test` + `make test-integration` xanh.
- Memory mới xuất hiện đúng 1 dòng trong `MEMORY.md`.

**Rollback:** Chỉ là docs/test — an toàn revert bất kỳ lúc nào.

---

## Rủi ro đã xác định (không được bỏ qua)

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| Quality bar định nghĩa quá hẹp/quá rộng | Loop dừng sai lúc (quá sớm = pipeline vẫn kém; quá muộn = chạy vô ích) | Step 6 dùng model mạnh nhất, giữ tiêu chí có thể kiểm chứng bằng code, KHÔNG suy diễn thêm |
| `listener.py` đã 412 dòng, gần chạm rule 400 | Thêm route mới trực tiếp sẽ vi phạm Refactoring Rules | Step 3/4 không đụng `listener.py`; nếu cần route Telegram mới, tách module riêng theo đúng pattern `batch_cli` → package |
| Vòng lặp sửa-theo-review nội bộ 1 task có thể không hội tụ | Tốn token vô ích, có thể chạm rate-limit liên tục vì 1 task kẹt | Step 4 đặt giới hạn số lần lặp rõ ràng, vượt ngưỡng → báo lỗi cho user thay vì lặp mãi |
| `.claude/commands/` đang có thay đổi chưa commit từ trước | Step 1 có thể đụng việc dở của phiên trước nếu không kiểm tra | Step 1 phải `git status`/đọc nội dung trước khi thêm gì vào `.claude/commands/` |
| CLAUDE.md hiện là bản "Proposed" chưa ratified | Step 7 sửa nhầm file không phải nguồn sự thật | Hỏi user tại Step 7 trước khi sửa, theo đúng thứ tự ưu tiên tài liệu ghi trong `docs/constitution/00-CONSTITUTION.md` |

## Bước tiếp theo

Plan này cần **review đối kháng** (adversarial review) bởi 1 agent model
mạnh nhất trước khi bắt đầu Step 1, theo đúng quy trình `blueprint`. Sau
review, trình bản tóm tắt cho user phê duyệt trước khi mở PR Step 1.
