# CLAUDE.md (Proposed — see `docs/constitution/` for ratified detail)

> **Đây là bản đề xuất thay thế `CLAUDE.md`.** KHÔNG ghi đè `CLAUDE.md` hiện
> tại. File này phản ánh kiến trúc đích (AI Native Creative OS) theo
> `PROJECT_VISION.md` + `docs/constitution/00-30`, dùng để review trước khi
> merge vào `CLAUDE.md` chính thức theo từng phase của
> `docs/constitution/29-MIGRATION_PLAN.md`.

## Triết lý dự án (Repository Philosophy)

`claude-ytb` đang chuyển từ **pipeline tự động hoá YouTube** thành
**AI Native Creative Operating System** — một engine local-first chạy chủ
yếu trên MacBook Pro M4, biến một creative intent (chủ đề, series, nhân vật
tái sử dụng) thành nội dung hoàn chỉnh đa nền tảng (video, audio, slide,
text) qua một DAG các bước sản xuất dùng AI provider có thể thay thế lẫn
nhau.

Nguyên tắc bất biến (xem `PROJECT_VISION.md` §2 — KHÔNG đổi trừ khi có
amendment ghi rõ ngày + lý do trong chính file đó):

1. **Offline-first.** Toàn pipeline (trừ bước publish cuối) phải chạy được
   không cần internet.
2. **Local inference priority.** LLM (Ollama/Qwen3), TTS (F5-TTS), ảnh
   (Flux), video (Wan2.2) là **default**. Cloud (Claude API, ElevenLabs,
   Pexels) là **fallback tuỳ chọn**, chọn rõ qua config — không bao giờ âm
   thầm thay default.
3. **Không stock video làm default.** Pexels không bao giờ là nguồn B-roll
   mặc định. Ảnh/video AI-generated là default path của `render.ai`.
   **CHƯA ĐẠT (2026-07-06):** `settings.video_provider`/`broll_strategy`
   default hiện vẫn là `"pexels"`, và `render/compose_ai.py` xác nhận Pexels
   là production path thật — đây là vi phạm invariant đã biết, ghi nhận là
   technical debt trong `PROJECT_VISION.md` §5 (v1→v2), KHÔNG được coi là
   "đã đúng" chỉ vì code chạy được. Không mở rộng thêm tính năng dựa trên
   Pexels-as-default; ưu tiên migrate sang local diffusion khi lên kế hoạch
   Phase tiếp theo.
4. **Provider Pattern cho mọi capability ngoài.** LLM/Voice/Image/Video/
   Publish đều là `Protocol` port + adapter — thêm provider mới = thêm 1
   file, không sửa code domain/pipeline.
5. **`script.json` → `project.json`.** Artifact gốc tiến hoá thành cấu trúc
   DAG đầy đủ: research, outline, narrative, scenes, shots, prompts, assets,
   render jobs, checkpoints.

## Kiến trúc (Architecture Rules)

- **Clean + Hexagonal.** Dependency luôn hướng vào trong: Interface →
  Application → Domain. Domain layer (frozen dataclasses) không phụ thuộc
  gì bên ngoài — không Pillow, không FFmpeg, không SDK Google/Ollama trực
  tiếp.
- **Provider Pattern.** Mọi pipeline/domain code chỉ import `Protocol`
  (`VoiceProvider`, `RenderProvider`, `ImageProvider`, `PublishProvider`),
  không bao giờ import SDK cụ thể ngoài thư mục `providers/<capability>/`.
  Chọn provider runtime qua đúng 1 hàm registry/capability — không rải
  `if provider == "x"` khắp call site.
- **DAG + checkpoint.** Pipeline là DAG các node (không phải linear 4-stage
  cứng). Mỗi node checkpoint độc lập (`pending/running/done/failed`) trong
  `project.json`. Resume = skip node `done`, retry node `failed`, không bao
  giờ recompute toàn bộ vì 1 node lỗi.
  **Trạng thái thực tế (2026-07-06):** `project/models.py` +
  `project/workflow.py` (`WorkflowGraph`, Kahn topo-sort) +
  `project/checkpoint.py` (`CheckpointManager`, atomic write) ĐÃ tồn tại và
  hoạt động độc lập — nhưng `orchestrator/batch_cli.py` CHƯA import/dùng
  chúng, vẫn chạy linear qua `assets/auto_state.json` cũ. Đây là 2 hệ thống
  song song chưa hợp nhất — không viết thêm logic mới dựa trên
  `auto_state.json`, ưu tiên wire batch_cli vào `WorkflowGraph` khi có cơ hội
  refactor lớn (cần phê duyệt trước, xem Repository Evolution Rules).
- **Gateway/Worker separation** (khi áp dụng pattern đa-service trong
  tương lai): code share → package chung, không service nào import trực
  tiếp internals của service khác.

## Coding Standards

Chi tiết đầy đủ: `docs/constitution/27-CODING_STANDARD.md`. Tóm tắt bắt
buộc:

- **Python 3.13+.** Type hints bắt buộc mọi nơi, `mypy --strict` sạch.
- **Async-first.** `async`/`await` cho mọi I/O. `asyncio.run()` chỉ ở đúng
  1 điểm vào top-level — không bao giờ nested.
- **Immutable.** `@dataclass(frozen=True)` cho mọi domain object. Enrich
  qua `dataclasses.replace()`. KHÔNG BAO GIỜ mutate bản gốc — đây là
  invariant trung tâm của codebase.
- **Structured logging.** `structlog` JSON, event name dot-namespaced
  (`"voiceover.segment.synthesized"`), correlation ID (`project_id`)
  bind 1 lần qua contextvars. Không `print()`/`logging.info(f"...")` trong
  `src/ytb_pipeline/`.
- **File size.** Tối đa 400 dòng/file. `batch_cli.py` đã được split (còn
  382 dòng — ĐẠT). Hiện đang VI PHẠM: `orchestrator/ideation_cmd.py` (746
  dòng) và `render/compose_ai.py` (573 dòng) — cần tách trước khi thêm logic
  mới vào 2 file này (xem Refactoring Rules bên dưới).
- **No hardcoded path.** Mọi path qua `settings.<field>`.
- **Naming.** `snake_case` hàm/biến, `PascalCase` class/Protocol/enum,
  `UPPER_SNAKE_CASE` constant.

## Prompt Standards

- Prompt là **versioned artifact**, không phải string rải trong code. Mọi
  prompt template dùng cho LLM/Image/Video provider sống trong một vị trí
  có thể diff được (file `.md`/`.txt`/`.json` riêng theo skill hoặc theo
  agent), không hardcode inline trong logic gọi provider.
- Mọi output từ LLM phải qua **structured output** (JSON schema / Pydantic
  model) trước khi vào domain code — không parse free text bằng regex
  ad-hoc nếu provider hỗ trợ structured output mode.
- **Quality gates** cho ideation: 3-gate ngách (không self-help / mật độ ý
  / nguồn truy được) + ràng buộc series (một cơ chế/tập, liên kết tập) theo
  `.claude/skills/youtube-ideation/video-quality-rules.md` mục 0c/0d — ép
  bằng code, không chỉ review thủ công.
- Mọi prompt thay đổi có ảnh hưởng tới chất lượng output đã ship cần ghi
  vào ledger/memory (`docs/constitution/23-MEMORY_SYSTEM.md`) để so sánh
  được qua thời gian, không chỉ sửa rồi quên.

## Workflow Rules

- Pipeline production = **DAG node execution**, mỗi node:
  1. Checkpoint lookup trước (skip nếu `done`).
  2. Cache lookup trước khi gọi provider thật (content-hash, xem
     `docs/constitution/24-CACHE_SYSTEM.md`).
  3. Checkpoint ghi `running` trước khi bắt đầu side-effect thật.
  4. Ghi `done`/`failed` ngay khi xong — write-through, không batch ở cuối
     run.
- **Checkpoint trước mọi expensive op.** Một node không bao giờ giả định
  "lần đầu chạy" — luôn check cache/checkpoint trước khi gọi provider.
- **Resume protocol:** `ytb project resume <id>` load `project.json`, replay
  DAG theo topological order, skip `done`, retry `failed` (tới
  `max_attempts`), treat `running` (process chết giữa chừng) như `pending`.
- Mọi node phải **idempotent** — an toàn re-run với input giống nhau.

## AI Rules

- **Local-first.** Default provider cho LLM/Voice/Image/Video luôn là local
  model. Cloud chỉ dùng khi config chọn rõ ràng (không phải vì local "chưa
  setup xong" trong code).
- **Fallback to cloud** là một adapter hợp lệ, không phải nhánh đặc biệt —
  implement như mọi `Provider` khác, chọn qua registry.
- **Token/cost tracking.** Mọi lời gọi cloud LLM/TTS phải log
  `tokens_used`/`cost_estimate` (nếu provider trả về) qua structured logging
  để theo dõi chi phí — local inference không cần track cost nhưng nên log
  `duration_ms` để theo dõi hiệu năng M4.
- **Cost awareness.** Trước khi thêm 1 cloud call mới vào default path,
  cân nhắc: có local alternative chưa được thử chưa? Nếu có, local phải là
  default, cloud là fallback — không phải ngược lại.

## Review Rules

- **Code review gate bắt buộc** sau khi viết/sửa code: dùng agent
  `code-reviewer` (hoặc tương đương) trước khi commit lên nhánh chia sẻ.
- **Security review trigger:** bất kỳ thay đổi liên quan OAuth
  (`secrets/`, `OAuthManager`), Telegram input handling, hoặc bất kỳ chỗ
  nhận input từ bên ngoài (Telegram command, file upload) → phải qua
  security review trước khi merge.
- Không merge khi còn issue CRITICAL/HIGH theo checklist review chuẩn của
  team (xem rule `code-review.md` ở cấp global).

## Documentation Rules

- **Bất kỳ thay đổi kiến trúc** (provider mới loại capability, domain
  object mới, DAG node mới có ý nghĩa kiến trúc) → cập nhật file
  `docs/constitution/` tương ứng **trong cùng change set** với code. Doc
  drift = bug, ngang hàng với test fail.
- `data/ledger.md` (hoặc memory system kế thừa, xem
  `docs/constitution/23-MEMORY_SYSTEM.md`) phải được cập nhật mỗi khi một
  episode/project hoàn thành — không để người sau phải tự suy luận lại từ
  output.
- `PROJECT_VISION.md` > `docs/constitution/*` > `CLAUDE.md`/`CLAUDE_NEW.md`
  > inline comment, theo đúng thứ tự ưu tiên ghi trong
  `docs/constitution/00-CONSTITUTION.md`.

## Testing Rules

Chi tiết: `docs/constitution/28-TESTING.md`. Tóm tắt:

- Test pyramid: unit 70% / integration 20% / e2e 10%.
- Coverage target 90% (đang nâng dần từ 80% hiện tại, sau khi
  `batch_cli.py` được split — xem Migration Plan Phase 0).
- **Không gọi real TTS/LLM/YouTube API trong unit test.** Fixture audio
  ngắn cho TTS, mock `googleapiclient` cho YouTube, fake `Provider` cho
  LLM/Image/Video.
- **Không `subprocess` trong unit test.** FFmpeg thật → integration test
  (`@pytest.mark.integration`).
- `pytest.ini`: `asyncio_mode = auto`, `pythonpath = src`, marker
  `integration`/`e2e`/`slow` loại khỏi default run.
- TDD bắt buộc cho subsystem mới (Cache/Checkpoint/Provider registry):
  viết test trước, fail trước, implement sau.

## Pull Request Rules

- **Không breaking change** lên `project.json`/`script.json` schema mà
  không kèm migration note + compatibility loader.
- Mọi PR thay đổi default provider/behavior phải nêu rõ trong PR body:
  behavior trước/sau, vì sao đổi, có vi phạm `PROJECT_VISION.md`
  Non-Negotiable Decision nào không (nếu có → PR này phải là amendment đề
  xuất, không phải code change đơn thuần).
- PR liên quan tới split file lớn (`batch_cli.py` và tương tự) phải giữ
  đúng public behavior — test trước/sau phải pass identical assertions trừ
  khi PR tự nhận là behavior change có chủ đích.

## Refactoring Rules

- File > 400 dòng → bắt buộc tách trước khi thêm logic mới vào file đó
  (không "thêm 1 chút nữa rồi tách sau").
- Extract pure function trước khi viết test cho logic phức tạp lồng trong
  I/O — pure function dễ test hơn, không cần mock.
- Refactor phải giữ backward compatibility cho `project.json`/`script.json`
  artifact đã tồn tại trên đĩa, trừ khi có migration script kèm theo.

## Commands Quick Reference

```bash
make setup                          # tạo .venv + cài requirements.txt
make run TOPIC="<chủ đề>"           # chạy pipeline 1 chủ đề (mặc định DRY_RUN)
make test                           # pytest unit (mặc định loại integration/e2e)
make test-integration               # pytest -m integration
make test-e2e                       # pytest -m e2e
make clean                          # xoá output/audio/cache

.venv/bin/pytest tests/test_models.py::test_script_enriches_idea_without_mutation

# Khi DAG/checkpoint system tồn tại (Migration Plan Phase 2):
ytb project resume <project_id>
ytb checkpoint show <project_id>
ytb checkpoint reset <project_id> <node_id>
ytb cache warm
```

## Key Invariants (KHÔNG được vi phạm)

- `dry_run=True` là default — publish thật chỉ xảy ra khi config chọn rõ
  `dry_run=False`.
- Domain objects luôn `frozen=True`; KHÔNG `object.__setattr__` workaround.
- `src/ytb_pipeline/pkg/` là nơi duy nhất chứa shared kernel logic — không
  duplicate config loading/checkpoint serialization mỗi stage.
- Pipeline/domain code KHÔNG import SDK cụ thể ngoài `providers/`.
- Pexels KHÔNG bao giờ là default B-roll — chỉ opt-in qua
  `config_overrides.broll_strategy`.
- `secrets/` không commit; mọi path qua `settings`, không hardcode.
- `script.json` cũ phải luôn load được qua compatibility loader sau khi
  `project.json` thành canonical.

# Repository Evolution Rules

## Mục tiêu

Claude không chỉ có trách nhiệm hoàn thành yêu cầu hiện tại.

Claude còn có trách nhiệm giúp repository tiến hóa theo đúng PROJECT_VISION.md và Constitution.

Mọi thay đổi phải giúp hệ thống tốt hơn hoặc tối thiểu không làm suy giảm chất lượng kiến trúc.

---

## Chủ động phát hiện vấn đề

Trong quá trình làm việc, nếu phát hiện:

- mã nguồn trùng lặp;
- module quá lớn;
- kiến trúc không còn phù hợp;
- provider có thể chuẩn hóa;
- workflow có thể đơn giản hơn;
- tài liệu không còn đồng bộ;
- test chưa bao phủ đầy đủ;
- technical debt tích lũy;
- naming không nhất quán;
- abstraction chưa hợp lý;
- dependency không cần thiết;
- hiệu năng có thể cải thiện;

Claude phải chủ động ghi nhận.

Nếu việc sửa ngay không phù hợp với phạm vi hiện tại, Claude phải đưa vào Technical Debt hoặc đề xuất Refactoring Plan.

Không được bỏ qua.

---

## Không mở rộng trên nền kiến trúc sai

Nếu phát hiện kiến trúc hiện tại không còn phù hợp cho tính năng mới, Claude không được tiếp tục mở rộng trực tiếp.

Claude phải:

1. Phân tích nguyên nhân.
2. Đề xuất phương án refactor.
3. Giải thích trade-off.
4. Chờ quyết định nếu thay đổi có ảnh hưởng lớn.

Không được "vá tạm" chỉ để hoàn thành tính năng.

---

## Đánh giá tác động

Trước khi triển khai bất kỳ thay đổi nào, Claude phải đánh giá:

- phạm vi ảnh hưởng;
- module bị tác động;
- khả năng tương thích ngược;
- ảnh hưởng tới workflow;
- ảnh hưởng tới Provider;
- ảnh hưởng tới Domain Model;
- ảnh hưởng tới Prompt;
- ảnh hưởng tới hiệu năng;
- ảnh hưởng tới khả năng kiểm thử.

Nếu có rủi ro, phải nêu rõ trước khi triển khai.

---

## Tự rà soát sau triển khai

Sau khi hoàn thành một tính năng, Claude phải tự đánh giá:

- Có phát sinh Technical Debt mới không?
- Có tạo thêm mã nguồn trùng lặp không?
- Có module nào nên tiếp tục tách nhỏ không?
- Có interface nào nên chuẩn hóa không?
- Có provider nào nên chuyển sang Provider Pattern không?
- Có tài liệu nào cần cập nhật thêm không?
- Có ADR nào cần bổ sung không?

Nếu có, Claude phải nêu rõ trong phần báo cáo cuối.

---

## Báo cáo sức khỏe Repository

Sau mỗi thay đổi lớn, Claude nên cung cấp một báo cáo ngắn gồm:

- Vision Compliance
- Constitution Compliance
- Architecture Impact
- Technical Debt
- Documentation Status
- Test Status
- Migration Progress
- Next Recommended Step

Báo cáo phải phản ánh đúng trạng thái hiện tại của repository.

---

## Cải tiến có kiểm soát

Claude được phép đề xuất cải tiến ngoài yêu cầu ban đầu nếu:

- giúp giảm Technical Debt;
- tăng khả năng mở rộng;
- tăng khả năng bảo trì;
- giảm độ phức tạp;
- chuẩn hóa kiến trúc;
- cải thiện hiệu năng.

Tuy nhiên:

- Không được tự ý thay đổi PROJECT_VISION.md.
- Không được tự ý thay đổi Constitution.
- Không được thực hiện refactor lớn nếu chưa được người dùng phê duyệt.

Mọi đề xuất phải giải thích rõ lợi ích, chi phí và rủi ro.

---

## Nguyên tắc cuối cùng

Claude không chỉ thực hiện yêu cầu.

Claude có trách nhiệm giữ cho repository luôn:

- nhất quán;
- dễ bảo trì;
- dễ mở rộng;
- có tài liệu đầy đủ;
- tuân thủ PROJECT_VISION.md;
- tuân thủ Constitution;
- sẵn sàng cho sự phát triển lâu dài.

Một repository khỏe mạnh quan trọng hơn việc hoàn thành một tính năng trong thời gian ngắn.

## Nguyên tắc về phạm vi thay đổi (Scope Control)

Claude phải ưu tiên các thay đổi có phạm vi nhỏ, rõ ràng và dễ kiểm chứng.

Không được tự ý thực hiện refactor diện rộng chỉ vì thấy "đẹp hơn" hoặc "hiện đại hơn".

Đối với mọi thay đổi vượt quá phạm vi yêu cầu của người dùng, Claude phải:

- giải thích lý do;
- phân tích lợi ích và rủi ro;
- đề xuất kế hoạch triển khai;
- chờ người dùng phê duyệt trước khi thực hiện.

Ưu tiên tiến hóa từng bước (incremental evolution) thay vì thay đổi lớn trong một lần.

Mọi cải tiến đều phải đảm bảo:
- không phá vỡ khả năng tương thích ngược (trừ khi đã được chấp thuận);
- không làm gián đoạn các chức năng đang hoạt động;
- có thể kiểm thử và hoàn nguyên khi cần.

## COMMUNICATION

- **Code trước.** Viết code ngay, không hỏi lại trừ khi thiếu thông tin
  chặn cứng.
- **Giải thích tối đa 100 chữ** khi thật sự cần giải thích.
