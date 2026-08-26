# Kế hoạch nâng cấp tool YouTube

**Trạng thái:** Đã chốt, áp dụng sau khi batch hiện tại hoàn tất
**Chủ sở hữu quyết định:** User
**Đối tượng đọc:** Codex, Claude và agent thực hiện thay đổi trong repo

## 1. Mục tiêu

Tool phải giúp thực hiện `CHANNEL_GROWTH_PLAN.md` nhanh hơn nhưng không đánh đổi chất lượng, tính nguyên bản, khả năng resume hoặc an toàn publish.

Không sửa tool chỉ để tăng số lượng video. Mỗi thay đổi phải gắn với một mục tiêu kênh hoặc một lỗi vận hành đo được.

## 2. Nguyên tắc bất biến

- Đọc `data/ledger.md` và `assets/auto_state.json` trước khi tạo hoặc chạy video.
- Không sản xuất chủ đề trùng nghĩa với bất kỳ dòng ledger nào.
- Claude, Codex hoặc xKiro là provider hợp lệ cho ideation (Ollama/MLX-LM đã
  gỡ khỏi codebase — xem Amendment 2026-08-24 bên dưới).
- QA phải chặn script không có ví dụ cụ thể, hành động áp dụng hoặc payoff — bắt
  buộc như nhau bất kể provider nào sinh script (xem `_cmd_start_local`,
  `strict_qa=True` cho mọi provider).
- **Historical — superseded by Amendment 2026-08-24. Amendment 2026-07-23**
  (chủ sở hữu quyết định: User): đảo ngược invariant cũ
  "Không gọi Ollama cho việc viết kịch bản". Lý do: Qwen3.6:27b (local, đã pull
  qua Ollama) kết hợp lớp heal JSON quyết định (`ideation_json_heal.py`, dùng
  `json_repair` khi `json.loads` chuẩn thất bại) đạt chất lượng đủ dùng cho
  script generation, và local-first là nguyên tắc bất biến gốc của dự án
  (`CLAUDE.md` §Triết lý dự án). `llm_provider` mặc định đổi từ `"claude"` sang
  `"ollama"`; `OllamaScriptProvider` fallback tự động về Claude CLI khi Ollama
  không sẵn sàng hoặc lỗi giữa chừng — QA gate không đổi, vẫn `strict_qa=True`
  bất kể provider nào sinh ra script.
- **Historical — superseded by Amendment 2026-08-24. Amendment 2026-08-12**
  (chủ sở hữu quyết định: User): `OLLAMA_MODEL` đổi
  từ `qwen3.6:27b` sang `qwen3:8b` (nhanh hơn nhiều, đã pull sẵn) — nếu QA gate
  `strict_qa=True` bắt đầu reject nhiều hơn hoặc script "ngáo" như lịch sử
  2026-07-06, quay lại `qwen3.6:27b` chỉ bằng cách sửa `.env`, không cần sửa
  code. Thêm `MLXProvider` (`providers/llm/mlx_provider.py`) làm backend local
  thứ hai — chạy `mlx-lm` in-process trên Apple Silicon, không cần daemon
  Ollama; chọn qua `LLM_PROVIDER=mlx` + `MLX_MODEL` (default
  `mlx-community/Qwen3-8B-8bit` — Qwen3.6 không có bản 8B nên dùng Qwen3 cùng
  kích cỡ với `ollama_model` để so sánh công bằng). `ideation_cmd._configured_script_provider("mlx")`
  bọc qua `OllamaScriptProvider` sẵn có (đã provider-agnostic), fallback Claude
  giống hệt path Ollama. Benchmark thực tế: MLX 9.5s/JSON hợp lệ ngay lần đầu;
  Ollama 10.9s nhưng khi chạy song song với MLX (tranh chấp RAM/Metal GPU)
  daemon Ollama trả `{"model": "", "response": "", "done": false}` — bug thật,
  không phải do `think`/`format`/model (chạy riêng lẻ với payload y hệt luôn
  thành công). Đã fix `OllamaProvider.complete()`
  (`providers/llm/ollama_provider.py`): raise `ProviderUnavailableError` khi
  `done=false` + `response` rỗng thay vì âm thầm trả `""` (trước đây khiến
  ideation tưởng nhầm là JSON lỗi thay vì provider lỗi, không trigger fallback
  Claude đúng lúc). Default provider vẫn là `ollama` (`qwen3:8b`) vì hoạt động
  bình thường khi chạy đơn lẻ (đúng luồng production, ideation không chạy song
  song nhiều provider); `mlx` là lựa chọn thay thế tương đương tốc độ, chọn qua
  `LLM_PROVIDER=mlx` nếu muốn tránh phụ thuộc Ollama daemon.
- **Amendment 2026-08-24** (chủ sở hữu quyết định: User, xem
  `PROJECT_VISION.md` Amendment Log cho amendment cấp Non-Negotiable
  Decision): đảo ngược lại Amendment 2026-07-23/2026-08-12 — MacBook không
  còn chạy local LLM/TTS inference, chỉ chạy workflow/pipeline orchestration
  + render, để giảm tải máy. `llm_provider`/`tts_provider` mặc định đổi
  sang `"xkiro"` (cloud, OpenAI-compatible aggregator, endpoint
  `/v1/chat/completions`); cascade tự động Codex CLI → Claude CLI khi xKiro
  lỗi qua `CascadeScriptProvider` (thay `OllamaScriptProvider`, gỡ khỏi
  codebase — `ideation_local_provider.py` → đổi tên
  `ideation_provider_cascade.py`). **XÓA HẲN**
  `providers/llm/ollama_provider.py`, `providers/llm/mlx_provider.py`,
  `providers/local_stack.py` (OMNI_LOCAL, dead code chưa từng được gọi).
  `settings.allow_cloud_providers` default đổi sang `true` (trước `false`)
  để không tự ép `tts_provider` về lại `"f5"` trên máy mới. Model xKiro
  chính + fallback chốt qua benchmark thật 2026-08-24 (14 model, xem
  `config/settings.py::xkiro_llm_model`/`xkiro_llm_fallback_models`) — model
  gắn nhãn anthropic/openai/google/qwen bị HTTP 403 với free-tier key hiện
  tại, không dùng được. **Rủi ro đã biết:** xKiro là aggregator bên thứ ba
  chưa có track record được biết trước tại thời điểm amendment; endpoint
  `GET /v1/models` liệt kê tên model trùng khớp bất thường với chính tên
  model Claude hiện tại — đã báo cho User, User xác nhận chấp nhận rủi ro và
  tiếp tục. Ảnh (Flux)/video (Wan2.2) KHÔNG đổi, vẫn local-first.
- **Amendment 2026-08-26** (chủ sở hữu quyết định: User): ideation chỉ dùng
  xKiro model `google/gemini-3.7-flash` (Gemini 3.7 Flash). Xóa model
  fallback và CLI cascade
  Codex → Claude cho bước sinh kịch bản: lỗi xKiro phải dừng minh bạch, không
  âm thầm đổi provider/model. TTS xKiro và visual/render không đổi.
- Không đưa người que hoặc legacy `image_motion` vào production.
- Publish phải tôn trọng `DRY_RUN`, privacy và publish schedule.
- Mọi trạng thái phải resume được sau lỗi hoặc dừng graceful.
- Domain dataclass bất biến; khi làm giàu model dùng `dataclasses.replace()`, không mutate input.

## 3. P0 — An toàn vận hành và concurrency

Mục tiêu: cho phép chạy song song có kiểm soát, bắt đầu với tối đa 2 worker.

Yêu cầu:

- Có giới hạn worker rõ ràng, không chạy nhiều terminal thủ công.
- Mỗi slug có log, audio, render và workspace riêng.
- Ghi `ledger.md` và `auto_state.json` qua cơ chế khóa/atomic write.
- Một video lỗi không làm dừng các worker khác.
- Dừng graceful phải dừng toàn bộ worker và process con.
- `ytb batch status` hiển thị worker, slug, stage, elapsed time và lỗi gần nhất.
- Không cho hai worker nhận cùng một slug.

Điều kiện nghiệm thu: chạy thử hai video độc lập, không ghi đè artifact, không mất ledger, không upload trùng và resume được sau khi dừng.

## 4. P0 — Quality gate cho ideation

QA phải trả lỗi có cấu trúc, chỉ rõ rule và section vi phạm.

Các gate bắt buộc:

- Hook cụ thể trong phần mở đầu.
- Một cơ chế trung tâm.
- Ví dụ có bối cảnh, hành động, hậu quả và cách áp dụng.
- Hành động áp dụng ngay.
- Payoff cuối video.
- Short đúng thời lượng; long đủ độ sâu.
- Nguồn hoặc cách diễn đạt an toàn với claim sức khỏe/tài chính.
- Không trùng nghĩa với ledger.
- Không template hóa nhiều video liên tiếp.

Khi fail, tool phải giữ script ở trạng thái cần sửa, không tự publish và không lặp vô hạn cùng một lỗi.

## 5. P0 — Asset catalog và reuse Pexels

Xây thư viện asset có metadata:

- Asset ID và đường dẫn local/Drive.
- Nguồn và license.
- Chủ đề/hành động/bối cảnh.
- Orientation và độ dài.
- Lịch sử video đã sử dụng.
- Số lần dùng gần đây.

Asset selector phải ưu tiên clip chưa dùng hoặc ít dùng, đồng thời tránh lặp cùng một chuỗi cảnh, hook và payoff.

Điều kiện nghiệm thu: tạo được hai video khác nhau dùng một phần asset chung nhưng viewer vẫn nhận thấy narration, nhịp dựng và mục đích minh họa khác nhau.

## 6. P1 — Series, queue và semantic dedup

Queue phải lưu thêm:

- Series.
- Content pillar.
- Core mechanism.
- Audience problem.
- Short/long relationship.
- Playlist.
- CTA target.

Ideation phải kiểm tra chéo ledger, queue hiện tại và các tập khác trong cùng series. Nếu không chứng minh được góc mới, loại chủ đề trước khi gọi LLM/render.

## 7. P1 — SEO và packaging

Metadata phải được sinh theo trụ cột và chủ đề thật:

- Title có lời hứa rõ.
- Description có ví dụ và CTA.
- Tags liên quan trực tiếp.
- Không thêm hashtag “giải trí”, “meme”, “hài hước” nếu nội dung không thuộc nhóm đó.
- Thumbnail/frame đầu thể hiện vấn đề cụ thể.
- Playlist và video liên quan được gán trước khi publish.

## 8. P1 — Analytics feedback loop

Sau 48–72 giờ, lưu analytics cho từng video:

- Views.
- 3-second retention.
- Viewed vs swiped away.
- Average percentage viewed.
- Subscribers gained.
- Comments.
- Chuyển đổi Short → long.

Analytics phải tạo ra nhãn: `scale`, `revise_hook`, `revise_value`, `drop_format` hoặc `needs_more_data`.

Ideation lượt sau đọc các nhãn này để sinh chủ đề và format mới. Không tự động nhân rộng chỉ vì views cao.

## 9. P1 — Lịch sản xuất

Tool phải hỗ trợ cấu hình theo chiến lược kênh:

- Mỗi ngày: 1 video dài và đúng 2 Shorts phễu cho video dài đó.
- Mỗi Short phải khai báo cùng `long_form_slug` và `cta_target` của Long đích; audit chặn thiếu, thừa hoặc lệch liên kết.
- Mỗi Short phải khai báo `source_long_slug`, `source_section_index` và `source_excerpt` từ đúng một phân đoạn Long; engine chỉ chọn phân đoạn có insight + curiosity, không chọn mở đầu/retention/kết thúc. Audit chặn thiếu dấu vết nguồn.
- Hai Short cùng Long phải lấy hai phân đoạn khác nhau, rồi thêm hook/bối cảnh/bước quan sát/CTA; không là bản cắt máy móc.
- Không tự gán lịch chỉ vì batch đã đủ; Short và Long chỉ được schedule sau QA/asset hợp lệ và lệnh schedule rõ ràng.
- Không ghi đè `publish_at` đã tồn tại.
- Không schedule video chưa qua QA hoặc chưa có asset hợp lệ.

## 10. P2 — Monetization safety

Trước publish, kiểm tra:

- Nội dung có commentary/education gốc.
- Không phải slideshow hoặc footage Pexels với narration sơ sài.
- Không có claim sức khỏe/tài chính tuyệt đối hoặc gây hiểu nhầm.
- Không có nhạc/asset không rõ quyền sử dụng.
- Metadata không spam hoặc lệch chủ đề.

Nếu fail, chuyển sang `needs_review`, không upload thật.

## 11. Thứ tự thực hiện

1. Concurrency và state locking.
2. Quality gate kịch bản.
3. Asset catalog Pexels.
4. Series và semantic dedup.
5. SEO/thumbnail/playlist packaging.
6. Analytics feedback.
7. Adaptive scheduling và monetization review.

Không bắt đầu P1/P2 nếu P0 chưa có test nghiệm thu.

## 12. Quy trình cho Codex và Claude

Trước mỗi task:

1. Đọc file này và `CHANNEL_GROWTH_PLAN.md`.
2. Đọc `AGENTS.md`, `CLAUDE.md`, `data/ledger.md` và `assets/auto_state.json`.
3. Xác định task thuộc P0, P1 hay P2.
4. Không code ngoài phạm vi acceptance criteria của phase.
5. Sau thay đổi, cập nhật test, ledger/memory liên quan và ghi rõ trạng thái nghiệm thu.

Nếu yêu cầu mới mâu thuẫn với kế hoạch này, dừng và báo phần mâu thuẫn trước khi thực hiện.
