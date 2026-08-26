# Handoff — Prompt engine profile-driven, không gắn chặt Bàn số 6

Ngày: 2026-08-25
Người viết: Codex
Trạng thái: audit hoàn tất; chưa triển khai refactor này.

## Kết luận

Kiến trúc `profiles/<profile_id>/` và queue mang `profile_id` đã là nền đúng.
Nhưng prompt/gate hiện mới *profile-aware*, chưa *profile-driven*: engine vẫn
chứa quyết định biên tập của kênh explainer và một số giả định story. Nếu thêm
profile mới, code sẽ tiếp tục nở `if narrative_mode == ...` hoặc boolean mới.

Đích:

```text
Core system contract (universal)
  + runtime contract từ profile
  + prompt pack có slot rõ nghĩa của profile
  + policy editorial khai báo bởi profile
  -> structured JSON -> deterministic validation -> profile editorial review
```

Core chỉ biết cấu trúc, artifact, safety và capability. Profile quyết định
cách kể, beat/purpose, narrator, CTA/evidence và rubric creative.

## Bằng chứng audit

### P0 — taxonomy explainer đang ở core

`src/ytb_pipeline/orchestrator/ideation_prompts.py::script_generation_system_prompt`
ép mọi profile Long có `situation, core_answer, evidence, application, payoff`
và Short có `situation, core_answer, application, payoff`.

Bàn số 6 hiện phải diễn giải `evidence` thành “observed consequence”. Đây là
workaround, không phải engine: drama, interview, documentary hay podcast không
nhất thiết có `core_answer`/`application`.

Chuyển allowed/required purposes theo từng video type sang profile policy. Core
chỉ validate vocabulary/presence được profile khai báo.

### P0 — repair path quay về legacy assumptions

`long_extension_prompt`, `short_expansion_prompt`, `repair_prompt` trong
`ideation_prompts.py` còn hardcode `pexels_query`, knowledge/mechanism/evidence/
application, greeting và CTA legacy. Initial generation có profile system prompt,
nhưng Long delta hoặc repair vẫn có thể sinh section trái profile.

Mọi LLM entry path (initial, repair, Long delta, Short delta) phải dùng cùng
một resolved PromptBundle và schema. Không prompt nhánh nào tự nêu Pexels,
greeting, CTA, purpose hay “knowledge” nếu profile không khai.

### P1 — `narrator` đang là identity hardcode

`content_profiles.py` bắt buộc `voice_cast.narrator`; `voice_for()` default
`narrator`; `profile_environment()` luôn lấy voice đó. Schema/prompt/QA/render
cũng lọc cast bằng `!= "narrator"`.

Hiện đúng Bàn số 6 nhưng không mô hình hoá host tên khác, diary không người kể,
hay panel có moderator. Bàn số 6 cần narrator dẫn chuyện, nhưng đó là policy
của profile, không phải sentinel core.

### P0 design — booleans sẽ nở vô hạn

`ContentRules` gồm `require_pexels_query`, `require_short_source_trace`,
`require_conversation_turns`. Mỗi luật mới có nguy cơ thành boolean + nhánh
core. `require_conversation_turns` là bước tốt hơn hardcode Minh/An, nhưng chưa
đủ cho N narrative form.

### P1 — prompt artifacts chưa có slot và precedence

`script_generation_system_prompt()` đang join toàn bộ `profile.prompts`.
Prompt bible, instruction và JSON continuity có thể trộn ngang nhau, thứ tự/budget
khó kiểm soát. Cần Prompt Pack có slot rõ nghĩa.

## Kiến trúc đề xuất

### 1. Core system prompt versioned, genre-agnostic

Là artifact `core_system.md`, không chứa profile id, tên nhân vật, Pexels,
greeting, “Hãy”, `core_answer`, hay niche. Nó chỉ ép JSON hợp lệ, field/metadata
không lẫn vào TTS, an toàn/claim handling, visual alignment và self-audit.

### 2. Declarative editorial contract của profile

Hình dạng tham khảo (không bắt buộc copy nguyên xi):

```json
"editorial_contract": {
  "purpose_policy": {
    "short": {"allowed": ["..."], "required": ["..."]},
    "long": {"allowed": ["..."], "required": ["..."]}
  },
  "speaker_policy": {
    "narration": {"speaker_id": "narrator", "required": true},
    "turns": {"enabled": true, "direct_voiceover_only": true}
  },
  "claims_policy": "verify_when_used",
  "packaging_policy": {"thumbnail_brief": "required", "cta": "profile_prompt"}
}
```

Loader phải validate; v1 profile hiện có nhận default compatibility. Không gắn
profile id/cast cụ thể vào core.

### 3. Một PromptBundle resolver

`resolve_script_prompt_bundle(profile, video_type, context)` trả system prompt,
schema và directives cho generation/repair/Long delta/Short delta từ *cùng*
contract. Prompt pack có thứ tự/slot: `editorial`, `spoken_language`,
`narrative`, `series_memory`, `visual_direction`; data continuity là context,
không lẫn với instruction.

### 4. Quality gates đúng ranh giới

Deterministic gate chỉ xác minh được schema/cast/turn reference/field. Chất
lượng thoại, narrator dẫn truyện, causal turn và timeline phải là editorial
review JSON theo rubric profile (`passed`, `blocking_findings`, `section_refs`,
`repair_brief`) trước TTS. Chỉ profile bật review mới gọi LLM; cache theo profile
fingerprint + script content hash.

## Phạm vi Claude cần làm

1. Viết test RED cho PromptBundle, purpose policy, schema/contract consistency,
   và regression prompt của repair/Long delta/Short delta.
2. Implement `EditorialContractProfile` (hoặc tương đương) + migration v1 an
   toàn trong `content_profiles.py`.
3. Wire system prompt, JSON schema, `validate_release_purposes`, repair và hai
   delta prompt qua resolver. Wrapper legacy được phép giữ để tương thích, nhưng
   profile không được fallback sang luật global.
4. Khi policy bật turns, `generation_schema.py` và `script_contract.py` phải
   cùng require/validate field `turn`; story delta không được đòi Pexels và phải
   có `speaker_id`/`turn` theo policy.
5. Thay dần `narrator` sentinel bằng narration speaker/role profile khai báo,
   giữ `narrator` làm default v1. Không đổi đồng loạt nếu chưa có test migration.
6. Không render/publish trong task; test bằng fixture/captured prompt/schema.

## Acceptance criteria

1. Có fixture profile thứ hai (có thể test-only) purpose/cast khác, không
   Pexels; thêm nó không sửa pipeline.
2. Prompt core không có Minh/An/Bàn số 6/Pexels/greeting/`Hãy `/`core_answer`
   trừ khi profile cung cấp; Bàn số 6 resolved prompt vẫn có Conversation Contract
   và narrator là người dẫn chuyện.
3. Initial/repair/Long delta/Short delta đều lấy policy profile; tests chứng minh.
4. Schema, script contract, preflight và release dùng cùng declared purpose
   vocabulary; legacy suite vẫn xanh.
5. Không new `if profile_id == ...`, `minh`, `an` hay prompt ngành trong
   `src/ytb_pipeline/` ngoài test/fixture/profile artifact.

## Không được làm

- Không biến narrator thành im lặng: Bàn số 6 phải có lời dẫn truyện; narrator
  chỉ không được đọc hộ thoại trực tiếp của nhân vật.
- Không hardcode profile/cast/genre mới vào pipeline.
- Không break queue/scripts v1, không reset/revert worktree bẩn, không commit
  nếu user chưa yêu cầu.
