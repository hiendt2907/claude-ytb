# Blueprint: Production engine profile-driven, provider-neutral

**Trạng thái:** Draft v2 — đã qua cổng review đối kháng (v1 bị **BLOCK**, 3 CRITICAL).
**Ngày tạo:** 2026-09-04 · **Sửa sau review:** 2026-09-04
**Chế độ:** Full mode (git + gh sẵn sàng, remote `origin` → `hiendt2907/claude-ytb`).
**Nhánh gốc:** `codex/production-readiness-e2e-gate1` (có thay đổi chưa commit — §0.5).

## Mục tiêu

Biến chất lượng từ một tập prompt/regex/magic-number rải rác thành **một contract
có kiểu, có version, đo được và truy được nguồn**, chạy suốt từ `CreativeIntent`
tới `MediaQualityVerdict`.

Thành công **không** phải "một video qua gate", mà là: thêm profile mới không
phải sửa core QA; thêm provider mới chỉ cần adapter + capability declaration;
không còn tên series/nhân vật/vendor trong engine rule.

## Quyết định đã chốt (user, 2026-09-04)

| Quyết định | Giá trị |
|---|---|
| Runtime Long `ban-so-6` | **5–7 phút** (khớp `profile.json`; `AGENTS.md`/`CHANNEL_GROWTH_PLAN.md` sửa phạm vi ở Step 4a) |
| Sản phẩm visual | **Multi-shot limited animation** (bật `scene_planning.mode="director"`) |
| Human gates | script · storyboard/contact sheet · full-watch |
| Budget | 3 candidate/shot · 2 vòng regeneration · 2 editorial repair |

---

# §0 — Bằng chứng (đã xác minh, 2026-09-04)

Mọi khẳng định có `file:line` **và đã được chạy hoặc đọc trực tiếp**. Agent thực
thi không cần audit lại §0.1–§0.4, nhưng **phải** tự kiểm `git status` (§0.5 có
thể cũ).

## §0.1 Luật nội dung đang nằm trong engine

| Vấn đề | Bằng chứng |
|---|---|
| Contract/char bound tính ở **import time** | `orchestrator/ideation_prompts.py:33–100`; lặp lại `ideation/generator.py:52–61` |
| `allow_short_generation: true` trái quyết định Long-only | `profiles/ban-so-6/profile.json:61` vs `docs/CHANNEL_GROWTH_PLAN.md:20-23` |
| Blacklist regex + `MAX_STATED_OBJECT_DETAILS = 2` (mẫu 5 shot) | `agents/qa_agent.py:609, 776` |
| `AGGREGATE_WEIGHTS` trong source | `render/visual_judge.py:66–70` |
| Filename prefix của một series | `providers/image/comfyui_story_provider.py:239` → `"ban_so_6_story"` |
| Editorial dimension hardcode | `agents/editorial_review_agent.py:30` |
| Vendor cpm trong contract layer | `content_contract.py:29 (F5), :42–43 (XKIRO), :48 (EDGE)` |
| **Luật nội dung** giả dạng constant | `content_contract.py:65–71` `SHORT_SITUATION_TENSION_MARKERS` — whitelist từ vựng tiếng Việt đóng |
| Channel identity của một profile trong engine | `ideation_prompts.py:102` hardcode `"1 Cốc Café 6h"` |
| Post-render validation mỏng, **fail ở lỗi đầu tiên** | `render/validation.py`, toàn bộ 122 dòng |

## §0.2 Đã tồn tại — nên đây là tiến hoá, không phải rewrite

- **`ContentContract` đã có** (`content_contract.py:74–152`), frozen, đủ 4 method
  runtime. → `EffectiveProductionContract` **mở rộng** nó.
- **Node `render_quality` đã có** (`pipeline.py:975`), DAG 8 node. → `media_quality`
  là **nâng cấp**, không thêm node.
- **`DirectorAgent` + multi-shot đã có** (`content_profiles.py:239`; dispatch
  `render/scene_planning.py:34–44`, lazy import `:27–29`). → Multi-shot là **bật
  cờ + sửa lỗi**.

## §0.3 LỖI CHẶN A — prompt lập kế hoạch ở tốc độ đọc SAI

Đo trực tiếp bằng cách chạy module, không suy từ source:

```
LONG_MIN_MINUTES = 5,  LONG_MAX_MINUTES = 7          (đúng — .env override settings default 720/900)
module-level cpm  = 1109.0   chars_per_min_for_provider  ← RAW, không có tts_pace_factor
profile-aware cpm =  876.11  effective_chars_per_min     ← có tts_pace_factor 0.79

LONG_SAFE_MIN_CHARS = 5892 · LONG_SAFE_MAX_CHARS = 7359   (tính ở cpm RAW)
   ở cpm THẬT  →  404s .. 504s
   cổng thật   →  300s .. 420s
```

`SCRIPT_GENERATION_SYSTEM_PROMPT` (`ideation_prompts.py:692`) là **f-string eval
lúc import**, nướng sẵn `5892–7359` vào `:699`, `:1098`, `:1603`. Ở tốc độ đọc
thật của profile, **cả nửa trên của khoảng nằm ngoài trần**, cận dưới chỉ cách
trần 16 giây. Trong khi `effective_chars_per_min` — hàm CÓ hiệu chỉnh — đã tồn
tại và đã được gọi ở `:227, :755, :1039, :1043`.

Đây là nguyên nhân gốc của 423.7s vượt trần trong handoff, và là lý do brief v19
phải tay chỉnh xuống 5400–5900 thay vì tin prompt. **Một luật, hai nơi, không gì
giữ đồng bộ** — đúng mô típ đã cắn repo này nhiều lần (`cf24cf6`, `4d63387`,
`fefedb8`).

> Review đối kháng báo lỗi này là "prompt đặt 12 phút trong khi gate 5–7". Sai:
> reviewer đọc `settings.py:165` (default 720/900) mà không chạy; `.env` override
> về 300/420. Cơ chế đúng là chênh **tốc độ đọc**, không phải chênh phút.

## §0.4 LỖI CHẶN B — đơn vị công việc của resolver là segment, không phải shot

Hôm nay `ban-so-6` không khai `scene_planning` → `legacy_single_shot` →
`build_story_scene_plan` (`scene_plan.py:273`) tạo **đúng 1 shot/scene**, nên
shot ≡ segment và lỗi **ngủ yên**.

Bật `mode="director"` → `normalize_directed_shots` (`scene_plan.py:221–246`) cho
mỗi `Shot` một `visual_intent` **và** một `characters` riêng. Lúc đó:

| Đường | Đọc gì | Vị trí |
|---|---|---|
| Cache key | `segment.visual_intent` + `segment.scene_characters` | `visual_assets.py:208–210` |
| Sinh ảnh | `segment.visual_intent` | `:332, :389, :407` |
| Cast → solo/duo IPAdapter | `segment.scene_characters` | `:332, :388, :597` qua `_generation_mode` |
| **Judge chấm** | `request.visual_intent` (= của **shot**) | `visual_judge.py:225` |

`visual_assets.py:1227, :1234` truyền cùng một `segment` cho mọi shot của scene.

**Hệ quả đo được, không phải suy đoán.** `_generation_key` quyết định
`asset_path`, `seed`, và `fresh = not asset_path.is_file()`. Shot 2 thấy file đã
tồn tại → `fresh=False` → **không gọi provider** → dùng lại PNG của shot 1
byte-for-byte.

**Nặng hơn ở đường candidate đang bật.** Profile đã có `candidate_count: 2`,
`selection_policy: "vlm_ranked"`, `hard_fail_on_judge_error: true`. Trong
`visual_candidates.py`, `_sets` khoá theo **`shot_id`** (`:304, :318`) nhưng
`candidate_cache_path`/`candidate_seed` khoá theo **`generation_key`**
(`:84–99, :124–141`). Nên shot B có candidate set riêng, nhưng trỏ vào **file và
seed y hệt** shot A, bị chấm theo contract khác → fail → regenerate round 1 →
cùng `generation_key` → cùng file → `fresh=False` → fail lần nữa →
`ReviewRequiredError`.

Kết cục không phải "ảnh sai lọt lưới" mà là **cháy ngân sách visual và mọi shot
thừa dồn vào cổng người bắt buộc**. Với budget đã chốt (3 candidate × 2 vòng),
đây là blocker cứng cho canary Step 12.

## §0.45 GIẢ ĐỊNH LÀM VIỆC — cổng đang đúng

**Đây là giả định do chủ repo chỉ định (2026-09-04), KHÔNG phải nhãn đo được.**
Ai đọc file này phải phân biệt được hai thứ đó.

Bối cảnh: hai vòng chấm đều không cho ra dữ liệu dùng được — vòng một lấy mẫu
sai (chỉ 5/20 là Long, mọi bản bị loại đều là Short cho series Long-only), vòng
hai trả về 12/12 trong 58 giây trên kịch bản cần ~74 phút để đọc. Thay vì chờ,
chủ repo chốt: **coi như mọi lần loại đều đúng.**

Giả định này **nhất quán** với phần đã biết: 20 bản chủ repo thật sự đọc đều
được chấm 9–10/10, và cả 5 bản `ban-so-6` Long trong đó đều là bản ĐÃ ĐẠT. Nên
"bản qua cổng thì tốt, bản rớt thì rớt đáng" không mâu thuẫn với gì cả.

### Hệ quả — đổi thứ tự ưu tiên thật sự

Nếu cổng đúng thì vấn đề **không phải** nới cổng, mà là engine sinh ra hàng
không đạt:

```
ban-so-6 Long: 5 dat / 51  =  10%
=> trung binh ~10 lượt sinh mới ra 1 Long dùng được
```

Đó mới là thứ đang đốt thời gian, không phải render hay TTS. Và thứ tự phải sửa
là thứ tự tần suất loại:

| % số lần loại | Rule | Step nào xử |
|---|---|---|
| 41% | `editorial_review` | **Step 5** (tách NarrativePlan/ScriptDraft) + Step 7 |
| 22% | `unrenderable_visual_intent` | **Step 8b** (VisualSpec, required vs optional) |
| 10% | `narrator_reflection` | Step 5 |
| 8% | không ghi rule | Step 6 (mọi Finding phải có `rule_id`) |
| 6% | `character_voiceover_direct` | Step 5 |
| 6% | `series_semantic_dedup` | Step 6 |

**Xác nhận Phase 2 là đúng hướng.** `editorial_review` một mình chiếm 41%, và
đó chính xác là thứ Step 5 nhắm tới: một response LLM đang phải vừa dựng
narrative vừa viết thoại vừa giữ continuity. Tách kế hoạch khỏi lời văn là cách
duy nhất đã biết để giảm con số đó.

### Cái giả định này KHÔNG mua được

- **Không** cho phép nói "đã calibration với nhãn người". Chưa có nhãn nào.
- Step 9 (`hard gate precision ≥ 0.9`) **bỏ tiêu chí đó** — nó cần nhãn ẢNH, chưa
  từng có, và một giả định không thay được phép đo.
- Nếu sau này Phase 2 chạy mà tỉ lệ đạt vẫn ~10%, phải quay lại chất vấn chính
  giả định này chứ không tiếp tục siết engine.

## §0.5 Worktree phải bảo toàn

**Không revert, không stage khi chưa được yêu cầu.** Agent phải chạy lại
`git status` — trạng thái dưới đây chụp lúc 2026-09-04 11:00:

```
 M docs/production-readiness/RUNBOOK-gate1.md
 M src/ytb_pipeline/orchestrator/{ideation_cmd,ideation_prompts,ideation_script_fix}.py
 M tests/{test_content_profiles,test_content_strategy,
          test_narration_speaker_migration,test_visual_assets}.py   <- cố ý không commit
?? tools/gate1/check_video.py
?? plans/
```

Phần `src/` chưa commit là bản sửa Codex cho lỗ hổng §4 handoff
(`visual_intent_repair_attempts` có budget riêng + feedback vòng sau). **Giữ** —
Step 6 tổng quát hoá, không vứt.

Quy ước repo: **không bao giờ commit file test**. Test vẫn viết và chạy đầy đủ.
Test có sẵn bị source làm hỏng thì sửa local, không commit. Đây là chủ đích, không
phải thiếu sót.

---

# §1 — Ranh giới

**Ra policy/profile:** thời lượng · số section · purpose vocabulary · editorial
dimension + threshold · visual constraint · Judge weight · candidate/retry/cost
budget · motion/cadence policy · provider capability · prompt bundle ·
`SHORT_SITUATION_TENSION_MARKERS`.

**Ở lại engine:** type/schema safety · immutable domain object · safe filesystem
path · deterministic fingerprint · retry hữu hạn · secret redaction · `DRY_RUN` ·
publish phải được cho phép rõ ràng.

**Tuyệt đối không:** nhánh `if profile_id == "..."` · hardcode tên cast/vendor ·
sửa artifact JSON thủ công · thêm regex cho mỗi lỗi visual mới · mutate domain
object · reset/revert worktree · stage/commit/publish khi chưa được yêu cầu ·
upload YouTube trong canary · big-bang rewrite.

**Đính chính một invariant.** `VisualManifest` (`visual_assets.py:148`) là
`@dataclass` **mutable** có chủ đích (`mark_running`/`mark_done`), và
`slot.attempt_count += 1` mutate tại chỗ. Đó là **checkpoint state**, không phải
domain object. Invariant `frozen=True` áp cho domain object trong `pkg/models.py`,
`content_contract.py`, `contract/`, `render/scene_plan.py` — **không** áp cho
checkpoint state. Step 8/9 mở rộng đúng các struct này; không được hiểu nhầm
thành yêu cầu rewrite.

---

# §2 — Bản đồ 18 step

```
Phase 0            Phase 1                        Phase 2            Phase 3              Phase 4          Phase 5
[0] tooling ─ [1] corpus ─ [2] contract ─┬ [3a] mech ─ [3b] thread ─ [4a] reloc ─ [4b] values ─┐
                                          └ [2b] fingerprint ─ [2c] manifest wiring ───────────┤
                                                                                                ├─ [5] narrative ─┐
                                                                                                ├─ [6] repair ────┼ [7] verdict
                                                                                                └─ [8a] shot-key ─┬ [8b] VisualSpec ─ [8c] capability
                                                                                                                   └─ [9] Judge
                                                                                       [8b] ─ [10] RenderPlan
                                                          [2] ─ [11a] media layers A ─┐
                                                                        [10] ─ [11b] layers B ─┴─ [12] canary
```

| Step | Phase | Tên | Deps | Tier |
|---|---|---|---|---|
| 0 | 0 | Tooling gate (mypy, coverage, snapshot 2.7.0, secret leak) | — | default |
| 1 | 0 | Golden corpus + `RunManifest` (library only) | 0 | default |
| 2 | 1 | `EffectiveProductionContract` + 3 fingerprint | 1 | **strongest** |
| 2b | 1 | Checkpoint invalidation theo fingerprint | 2 | **strongest** |
| 2c | 1 | Wire `RunManifest` vào `run_project` | 2b | default |
| 3a | 1 | Mechanical: constant → function (prompt byte-identical) | 2 | default |
| 3b | 1 | Behavioral: thread contract, **sửa §0.3** | 3a | **strongest** |
| 4a | 1 | Relocation ở giá trị Y HỆT + snapshot + doc conflict | 3b | default |
| 4b | 1 | Đổi giá trị (2→3 candidate, 1→2 vòng, Short off) | 4a | default |
| 5 | 2 | `NarrativePlan` / `ScriptDraft` split | 4b | **strongest** |
| 6 | 2 | Typed repair engine | 4b | **strongest** |
| 7 | 2 | `EditorialVerdict` + shadow eval | 5, 6 | default |
| 8a | 3 | **Sửa §0.4** — resolver khoá theo `(request, shot)` | 4b | **strongest** |
| 8b | 3 | `VisualSpec` + `StoryboardPlan` + provider compiler | 8a | **strongest** |
| 8c | 3 | Capability negotiation + gỡ series prefix | 8b | default |
| 9 | 3 | Judge tách hard gate / soft craft + calibration | 8b | **strongest** |
| 10 | 4 | `RenderPlan` + bật multi-shot | 8b | default |
| 11a | 4 | media_quality tầng A (container/AV/STT/subtitle) | 2 | default |
| 11b | 4 | media_quality tầng B (cadence/crop/fidelity) | 10, 11a | default |
| 12 | 5 | Shadow rollout + DRY_RUN Long canary | tất cả | default |

**Song song an toàn (đã kiểm file chồng lấn):** `2b ‖ 3a` · `5 ‖ 6` · `8c ‖ 9` ·
`9 ‖ 10` · `11a ‖ (8*, 9, 10)`.
**KHÔNG song song:** 3↔4 (cùng chạm `ideation_prompts.py` + symbol cpm) ·
6↔3 (cùng chạm `ideation_script_fix.py`) · 11b↔10 (cùng hợp đồng render).

**Bất biến kiểm sau MỌI step:**
```bash
.venv/bin/pytest --cov-fail-under=80          # Step 0 mới làm điều này khả thi
.venv/bin/mypy --config-file mypy.ini <file đã sửa>
git diff --name-only | grep '^tests/' && echo "NHAC: khong stage file test"
```

---

# PHASE 0 — Nền và baseline

## Step 0 — Tooling gate ✅ XONG (2026-09-04, chưa commit)

**Kết quả đo được.**
- mypy 2.3.1 cài + `mypy.ini`. Baseline thật: **110 lỗi / 29 file / 138 file**
  (nặng nhất `visual_assets.py` 27 — chính file Step 8a sẽ sửa nhiều nhất).
  `strict` bật sẵn cho `contract.*`, `observability.*`, `repair.*` để Step 2 trở
  đi không thể lọt code không type.
- `--cov-fail-under=80` đã ép; đo thật **83.42%**, nên trần cắn khi hồi quy chứ
  không cắn hiện trạng.
- **Snapshot `ban-so-6@2.7.0`** — dựng rồi. **72 artifact đã ghim version này**
  mà `versions/` chỉ tới 2.6.0; rủi ro đã hiện hữu, không phải giả định.
- **Snapshot `one-cup-cafe-6h@1.1.0`** — guard test phát hiện thêm, 11 artifact ghim.
- **Rò secret đã bịt.** Tái hiện được: `model_post_init` raise → pydantic bọc
  thành `ValidationError` mang **nguyên dict 28 field**, gồm `xkiro_api_key` đầy
  đủ, `telegram_bot_token`, `pexels_api_key`, `youtube_api_key`,
  `dashboard_password`. Thêm `SettingsError` + `build_settings()` render lỗi chỉ
  từ `loc`+`msg`, và **raise NGOÀI khối except** để bản gốc không sống sót thành
  `__context__`.
- Suite: **1472 passed, 3 skipped**, coverage gate xanh. mypy trên `settings.py`:
  1 lỗi trước, 1 lỗi sau — không hồi quy.

**Phát hiện phụ, chưa sửa (ngoài phạm vi Step 0):** `requirements.txt` vẫn khai
`mlx-lm` dù CLAUDE.md ghi MLX-LM *đã gỡ khỏi codebase*. Drift giữa doc và
dependency — xử ở Step 4a cùng đợt sửa doc.

**Ghi chú kỹ thuật cho người sau:** snapshot phải copy theo *thứ `profile.json`
tham chiếu*, không copy theo file set của snapshot trước. Bản 1.1.0 đầu tiên tôi
dựng theo 1.0.0 và thiếu `editorial-review.md` — guard test bắt được. Loại
`continuity-ledger.json` khỏi snapshot: đó là state chạy theo tập, không phải
hợp đồng (2.6.0 cũng loại).

### Đặc tả gốc

**Vì sao đứng đầu.** v1 của plan đặt `mypy --strict` làm cổng mỗi step, nhưng
**mypy không được cài** (`.venv/bin/` không có, `requirements.txt` không khai, không
có `mypy.ini`/`pyproject.toml`). Verify của Step 2 sẽ ENOENT ngay bước Phase 1 đầu
tiên. Tương tự `pytest.ini` có `--cov` nhưng **không có `--cov-fail-under`**, nên
"coverage ≥ 80%" chưa từng được ép.

**Tasks.**
1. Cài mypy; commit `mypy.ini` với allowlist per-file. `strict` áp cho **module
   mới**; file cũ (`visual_assets.py` 1251 dòng, `scene_planning.py` không
   annotation) đặt ở profile lỏng hơn với ràng buộc **không được xấu đi**.
2. `pytest.ini`: thêm `--cov-fail-under=80`.
3. **Snapshot `profiles/ban-so-6/versions/2.7.0/`** — hiện `versions/` chỉ có tới
   `2.6.0` trong khi active profile là `2.7.0`. `content_profiles.py:580` fallback
   về profile root rồi `:739-741` raise khi version lệch. Bất kỳ bump nào sau này
   sẽ **hard-break** mọi artifact ghim 2.7.0. Copy active profile (kèm binary asset
   đã duyệt) vào `versions/2.7.0/`, verify load được.
4. **Sửa rò secret:** validation error của pydantic in nguyên dict settings, trong
   đó có mật khẩu (handoff §6). Đây là **lỗi bảo mật, không được đợi 11 step**.

**Verify.**
```bash
.venv/bin/mypy --version
PYTHONPATH=src .venv/bin/python -c "
from ytb_pipeline.content_profiles import load_content_profile as L
print(L('ban-so-6', version='2.7.0').version)"
.venv/bin/pytest tests/test_settings_redaction.py -q
```

**Exit.** Test liệt kê **mọi** `content_profile_version` có mặt dưới `assets/` +
queue, và `load_content_profile` thành công cho từng cái.

**Rollback.** Gỡ `mypy.ini` + dòng cov; snapshot 2.7.0 là additive, giữ.

## Step 1 — Golden corpus + `RunManifest` (library only)

**Đính chính so với v1.** v1 đặt corpus ở `tests/golden/` "không commit" — nhưng
**sáu step sau gate lên nó**, và Step 9 cần `human_label` mà v1 hoãn vô thời hạn.
Quy ước repo là không commit **code test**, không phải không commit **dữ liệu
bằng chứng**: `assets/editorial_review_cache/`,
`assets/production_readiness/gate1/attempts.tsv` là tiền lệ đã commit.

**Tasks.**
1. Corpus ở `assets/golden_corpus/` **có commit**, kèm content hash pin.
   `tools/corpus/build_golden.py` phải **tất định và idempotent**.
2. Nguồn: `assets/projects/<slug>/project.json` · `assets/script_revisions/failed_ideation/` ·
   `assets/editorial_review_cache/ban-so-6/` · `attempts.tsv` (cột `owner` = tầng
   phải sửa) · `render/visual_evaluation_store.py`.
3. `RunManifest` frozen dataclass — **library only, không call site production**.
   Step 2c mới wire.
4. Characterization test pin hành vi HIỆN TẠI của `qa_agent.run`,
   `editorial_review_agent`, `build_visual_requests`, `validate_final_video`.

**Exit.** ≥ 2 profile · ≥ 40 entry · **≥ 20 entry có `human_label` do user điền**
(đây là cổng người của Phase 0, không hoãn sang Step 9) · corpus hash ổn định qua
2 lần build.

**Rollback.** Xoá `observability/`, `tools/corpus/`, `assets/golden_corpus/`.

---

# PHASE 1 — Contract compiler

## Step 2 — `EffectiveProductionContract` + tách fingerprint

**Tasks.**
1. `EffectiveProductionContract(frozen=True)`: `content: ContentContract` ·
   `editorial: EditorialPolicy` · `visual: VisualPolicy` · `repair: RepairPolicy` ·
   `render: RenderPolicy` · `runtime: RuntimeBinding`.
2. `compile_contract(profile, settings_snapshot, capability_snapshot)` — thuần,
   tất định. **Nhận snapshot settings làm tham số**, không đọc global (v1 đặt
   invariant "không đọc settings" nhưng exit criterion lại đòi parity với
   `contract_for`, vốn đọc `settings` ở `:176, :200` — mâu thuẫn; snapshot giải).
3. Ba fingerprint độc lập: `CreativePolicyFingerprint` (luật kể chuyện) ·
   `RuntimeBindingFingerprint` (provider/model) · `ProviderCapabilitySnapshot`.
4. Provenance cho mọi override (vd `settings.visual_judge_*` thắng profile,
   `visual_assets.py:60–87`): ghi `source` + `reason`.

**Invariant.** Đổi `visual_judge.model` **KHÔNG** làm đổi
`CreativePolicyFingerprint` — test bắt buộc, là bài học `86f3347` (snapshot từng
đóng băng cả vendor).

**Exit.** Shadow compile: `compile_contract(...).content` == `contract_for(...)`
trên toàn corpus, dưới một settings snapshot cố định. Chưa thay call site.

## Step 2b — Checkpoint invalidation theo fingerprint

**Vì sao là step riêng.** Acceptance đòi *"checkpoint resume + invalidation đúng
theo fingerprint"*, nhưng v1 không có step nào chạm
`pipeline._reset_stale_nodes` (`pipeline.py:467`) hay `CheckpointManager`, và
không ghi fingerprint nào vào `project.json`. Hôm nay invalidation là hardcode:
`pipeline.py:496` reset đúng `(("audio_quality","render"), ("render_quality","publish"))`.

**Tasks.** Ghi `creative_policy_fingerprint` + `runtime_binding_fingerprint` per
node vào `project.json`; mở rộng `_reset_stale_nodes` reset node có fingerprint
lệch; khai node nào phụ thuộc fingerprint nào.

**Exit.** Test case đầu tiên chính là bump profile version của Step 4a: đúng
những node phụ thuộc bị reset, không hơn.

## Step 2c — Wire `RunManifest`

**Vì sao là step riêng.** v1 nói Step 1 "ghi `run_manifest.json`" nhưng invariant
của chính nó cấm chạm ngoài `observability/`, và verify khẳng định
`git diff src/ | grep -v observability` rỗng. Mâu thuẫn, và không step nào sau đó
nhận việc.

**Tasks.** `run_project` phát manifest, ghi `provider_bindings` + 3 fingerprint +
`artifact_hashes`.

## Step 3a — Mechanical: constant → function

**Phạm vi.** Chuyển 33 phép gán constant ở module scope của `ideation_prompts.py`
thành function/`PromptBudget` property. Contract **vẫn chưa biết profile**.
Prompt phải **byte-identical**.

**Exit.** Assertion AST — không phải grep. (v1 dùng
`grep "^[A-Z_]* *= *contract_for"` chỉ bắt 9/33 dòng; `LONG_MIN_MINUTES = int(LONG_CONTRACT...)`,
`SHORT_MIN_CHARS, SHORT_MAX_CHARS = ...` đều lọt, nên grep có thể xanh khi lỗi còn
nguyên.)

```python
# test: không Assign nào ở module scope có Call trong value
tree = ast.parse(Path("src/.../ideation_prompts.py").read_text())
assert not [n for n in tree.body if isinstance(n, ast.Assign)
            and any(isinstance(c, ast.Call) for c in ast.walk(n.value))]
```

Cộng: characterization test cho rendered prompt **không đổi byte**.

## Step 3b — Behavioral: thread contract + **sửa §0.3**

**Đây là step sửa lỗi chặn A.** Prompt bytes **thay đổi có chủ đích** — Step 3a
giữ nguyên byte, 3b thì không.

**Tasks.**
1. Thread `EffectiveProductionContract` xuống mọi chỗ dựng prompt.
2. Mọi phép tính char budget dùng `effective_chars_per_min` (có `tts_pace_factor`),
   **không** `chars_per_min_for_provider` thô. Xoá đường tính trùng ở
   `generator.py:52–61`.
3. Rewrite editorial nhận **cùng một instance** contract với prompt sinh.
4. Test parity prompt↔gate: với mỗi rule, khẳng định (a) prompt nêu, (b) gate ép,
   (c) applier repair kiểm — **cùng một contract instance**. Đây là lớp test lẽ ra
   đã chặn `cf24cf6`, `4d63387`, `fefedb8`.

**Exit.** Diff prompt trước/sau được duyệt tường minh, và:
```
LONG_SAFE_MIN/MAX_CHARS ở cpm THẬT phải nằm TRỌN trong 300–420s
```
Hôm nay là 404–504s. Sau step phải trong trần.

## Step 4a — Relocation ở giá trị Y HỆT + snapshot + doc

**Tách khỏi 4b vì lý do đo được.** v1 gộp "externalization" với ba thay đổi
output: candidate 2→3, regeneration 1→2, Short off. Và
`profile.version` được hash vào `_generation_key` (`visual_assets.py:210`),
`_source_fingerprint` (`scene_plan.py:257`), `_planning_identity`
(`scene_planning.py:16`) → **bump version = vô hiệu toàn bộ cache ảnh + mọi
`scene_plan.json` đã lưu**. Gộp hai thứ vào một PR thì không biết cái nào gây
thay đổi.

**Files.** `profiles/ban-so-6/profile.json` (→ 3.0.0) · **`content_profiles.py`**
(bắt buộc — `profile.json` được parse tay ở `:544–740`; thiếu step này thì thêm
key vào JSON sẽ **không có tác dụng** và agent sẽ tự chế) · `qa_agent.py` ·
`visual_judge.py` · `editorial_review_agent.py` · `content_contract.py` ·
`ideation_prompts.py` (`CHANNEL_EDITORIAL_BRIEF:102`) · `AGENTS.md` ·
`docs/CHANNEL_GROWTH_PLAN.md`.

**Tasks.**
1. Snapshot `versions/2.7.0/` phải tồn tại (Step 0) **trước** khi bump.
2. Chuyển vào profile **ở đúng giá trị hiện tại**: `editorial.dimensions[]` ·
   `visual.judge_weights{}` · `visual.max_stated_object_details` ·
   `repair.*` · `channel_brief` · `SHORT_SITUATION_TENSION_MARKERS`.
3. Vendor cpm (`content_contract.py:29, 42–43, 48`) → bảng capability.
4. Engine fail-closed khi profile khai sai kiểu; **không im lặng rơi về legacy
   explainer taxonomy** — `narrative_mode="character_story"` mà thiếu editorial
   contract thì raise.
5. **Interlock chống bật multi-shot sớm:** assertion + test rằng
   `scene_planning.mode != "director"` khi chưa có capability
   `VISUAL_SHOT_KEYED_GENERATION` (Step 8a giới thiệu). `ScenePlanningProfile`
   mặc định `max_shots_per_scene=4` và `__post_init__` chỉ kiểm set membership
   (`content_profiles.py:235, 239`) — không có interlock thì một block
   `scene_planning` viết "cho Step 10" sẽ được nhận âm thầm và chạy ở lần
   regenerate toàn bộ ngay sau bump version, đúng lúc đắt nhất.
6. Sửa doc conflict: `AGENTS.md:72` và `CHANNEL_GROWTH_PLAN.md:71` ghi rõ 10–12 /
   12–15 phút áp cho profile giải thích cơ chế, **`ban-so-6` là 5–7 phút** — hai
   profile khác nhau thật, không san phẳng thành một số.

**Exit.** Test khẳng định policy compile ra **bằng đúng** constant hôm nay. Một
profile fixture *khác* `ban-so-6` đổi được judge weight + density cap mà **không
sửa dòng nào trong `src/`**.

**Rollback.** Về 2.7.0 (snapshot đã có từ Step 0). Ghi rõ: revert version **không**
un-regenerate cache, nó vô hiệu hoá lần thứ hai.

## Step 4b — Đổi giá trị

**Tasks.** `candidate_count` 2→3 · `semantic_rejection_recovery` 1 vòng→2 ·
`allow_short_generation` true→false (script Short cũ vẫn phải đọc được).

**Exit.** Có **ước lượng chi phí đo được** (số lần gọi provider/tập, thời gian) và
so sánh corpus trước/sau. Nếu chi phí vượt ngưỡng user chấp nhận → dừng, hỏi.

---

# PHASE 2 — Content compiler

## Step 5 — `NarrativePlan` / `ScriptDraft` split

**Tasks.** `NarrativePlan(frozen=True)`: `core_mechanism` · `conflict_and_stakes` ·
`timeline` · `knowledge_state` (ai biết gì) · `causal_beats` ·
`choices_and_consequences` · `next_episode_bridge`. `ScriptDraft` **chỉ** chuyển
plan → narration + dialogue. Validator **tất định**: timeline đơn điệu · không ai
phản ứng với thông tin chưa nói (qua `knowledge_state` + `responds_to` của turn
card) · mỗi beat có hệ quả.

**Exit — có số, không mô tả.** Trên ≥ 20 entry có nhãn người:
điểm rubric trung bình mới ≥ cũ − 0.3, và **không dimension nào** tụt > 1 điểm.

## Step 6 — Typed repair engine

**Tasks.** `Finding(frozen=True)` (`rule_id` · `stage` · `owner` · `severity` ·
`evidence` · `affected_sections` · `dependency_scope` · `repair_kind` ·
`retryability` · `policy_budget`). `RepairTransaction` trả artifact MỚI, ghi hash
trước/sau. Phân biệt `model_refused` (tiêu budget) vs `applier_rejected` (**sửa
được**, budget riêng, thông điệp kèm số đếm vào prompt vòng sau) — chính là bản
sửa Codex chưa commit, nay thành luật chung. **Tách ngân sách operator khỏi ngân
sách automation** (`MAX_MANUAL_OVERRIDES_PER_REVIEW` hiện dùng chung). Loop
detection bằng `artifact_hash`.

**Invariant.** Sau mỗi repair re-validate **toàn bộ** global invariant, không chỉ
rule vừa sửa — bài học `76213e5`.

**Exit.** Test reproduce lỗ hổng §4 handoff: applier từ chối 2 lần rồi thành công
lần 3. Đỏ trước step, xanh sau.

## Step 7 — `EditorialVerdict` + shadow eval

Rubric prompt sinh **từ** `EditorialPolicy`, không copy tay, và **raise** nếu một
dimension thiếu guidance — cùng cơ chế `renderability_contract_text()` ở `e2f02de`.
Threshold **9/10 mọi dimension, không hạ**. Exit dùng cùng metric số như Step 5.

---

# PHASE 3 — Visual compiler

## Step 8a — Sửa §0.4: resolver khoá theo `(request, shot)`

**Diff nhỏ nhất có thể, không kèm tính năng mới.** Đây là lỗi chặn B.

**Invariant thay cho danh sách dòng** (v1 liệt kê 4 dòng và bỏ sót một nửa):
> Đơn vị công việc của resolver là `(request, shot)`. `segment` chỉ là nguồn
> **narration**, không bao giờ là nguồn visual.

**Tasks.**
1. `_generation_key` nhận request/shot: `request.visual_intent` +
   `request.characters` + shot identity.
2. `characters_present=request.characters` (không `segment.scene_characters`) →
   `_generation_mode` chọn đúng solo/duo IPAdapter cho từng shot.
3. Quét hết, không chỉ 4 dòng: `visual_assets.py:208–210, 332, 333, 389, 407,
   598, 616`, lời gọi `_generation_key` thứ hai trong `resolve_manual_review`
   (~`:540`), và **cả `render/visual_candidates.py`**.
4. Giới thiệu capability `VISUAL_SHOT_KEYED_GENERATION` (interlock Step 4a đọc nó).

**Cảnh báo bắt buộc ghi vào PR body.** Đổi `_generation_key` **đổi tên mọi file
cache** → vô hiệu toàn bộ cache ảnh. Hoặc chấp nhận chi phí regenerate, hoặc ship
map một lần old-key→new-key cho trường hợp 1-shot (nơi key cũ và mới tương đương
về ngữ nghĩa).

**Exit — ba test.** 3 intent khác → 3 key. 2 shot cùng intent khác cast → 2 key.
2 shot giống hệt cả hai → 1 key (dedup ở đây là đúng).

**Rollback.** Cờ phải bọc **chính `_generation_key`**, nếu không lật cờ không khôi
phục được liên kết cache cũ — mà bọc thì lỗi vẫn với tới được. Chọn một, ghi rõ
trong PR: khuyến nghị **không cờ**, forward-only, vì lỗi này không có phiên bản
"đúng" để quay về.

## Step 8b — `VisualSpec` + `StoryboardPlan` + provider compiler

`VisualSpec(frozen=True)`: `subjects` + `character_identity` · `environment` ·
**đúng một** `observable_beat` · `required_facts` · `optional_props` ·
`composition`/`camera` · `crop` + `caption_safe_zone` · `continuity_refs` ·
`motion_treatment` · `forbidden`.

Hành động theo thời gian: tách nhiều shot **hoặc** compile thành một trạng thái
tĩnh quan sát được — thay 8 họ regex bằng một phép biến đổi có kiểu.

**Chỉ `required_facts` là hard gate**; `optional_props` không bị chấm. Trần mật độ
(2, mẫu 5 shot) trở thành trần cho `required_facts` — đây là lối thoát đúng cho
cảnh tĩnh liệt kê đồ vật mà handoff §6 nghi là quá chặt.

`lower(VisualSpec, capability) -> prompt` cho từng image provider.

## Step 8c — Capability negotiation + gỡ series prefix

Provider tuyên bố hỗ trợ gì; spec cần thứ provider không có → fail-closed, nêu rõ
thiếu capability nào. Bỏ `filename_prefix="ban_so_6_story"` → lấy từ profile.

**Exit.** Một **fake provider** trong test khai capability tối thiểu và chạy được
end-to-end — đây là bằng chứng cho acceptance *"thêm provider mới chỉ cần adapter
+ capability declaration"*, vốn v1 khẳng định mà không step nào chứng minh.

```bash
grep -rn "ban_so_6\|ban-so-6" src/ytb_pipeline/     # kỳ vọng: RỖNG
```

## Step 9 — Judge tách hard gate / soft craft + calibration

Tách **hard gate khách quan** (fidelity với `required_facts`, character identity,
technical) → pass/fail, không trộn điểm — khỏi **soft craft** (framing, focal
hierarchy, continuity, temporal usefulness) → điểm có trọng số. Weight/threshold/
budget đọc từ policy. Cấp **đầy đủ** `semantic_constraints` từ
`VisualSpec.required_facts`. Candidate diversity: biến thể composition/prompt có
kiểm soát, không chỉ đổi seed.

**Exit.** Trên tập nhãn người ≥ 40 ảnh (≥ 15 negative): hard gate precision ≥ 0.9.
Đổi weight trong profile làm đổi ranking mà không sửa `src/`.

**ADR bắt buộc.** `minimax/minimax-m3:free` là **giải pháp vòng** cho sự cố họ
qwen (403/500 toàn bộ, đã cô lập qua transport thật). Ghi ADR để nó không tự trôi
thành mặc định vĩnh viễn; quay lại hay không là quyết định của chủ repo.

---

# PHASE 4 — RenderPlan và media verification

## Step 10 — `RenderPlan` + bật multi-shot

1. **Tách `compose_ai.py` (620 dòng) xuống < 400 trước**, giữ nguyên public behavior.
2. `RenderPlan(frozen=True)`: `shot_cadence` · `cut/hold/pan/push/zoom` ·
   `transition` · `caption_layout` · `safe_area` · `audio_alignment` ·
   `thumbnail_treatment`.
3. Renderer **chỉ** tiêu thụ `RenderPlan`.
4. Bật `scene_planning.mode="director"`; gỡ interlock Step 4a.

**Exit.** Một Long render multi-shot thật, **hash ảnh từng shot khác nhau** — đây
là bài kiểm trực tiếp lỗi §0.4.

**Verify** (v1 chỉ quét `render/`, bỏ lọt file 1767 dòng ở `orchestrator/`):
```bash
git diff --name-only main...HEAD | grep '\.py$' | xargs wc -l | awk '$1 > 400'
```

## Step 11a — media_quality tầng A · Step 11b — tầng B

**Tách vì phụ thuộc khác nhau.** Tầng A không cần RenderPlan → `deps=[2]`, song
song thật. Tầng B cần cadence/crop/fidelity từ Step 10 → `deps=[10, 11a]`.

**11a:** container/codec/streams/dimensions · duration + A/V drift · dead air ·
**TTS↔STT từ audio trích trực tiếp trong MP4** (điểm 4–5 chưa từng chạy) ·
subtitle coverage/timing/overflow/contrast · blank/freeze/duplicate frame.
Hợp nhất `tools/gate1/check_video.py` vào engine.

**11b:** max static hold · shot cadence · crop + safe area · asset-to-render
fidelity · thumbnail vs brief · human review receipt (là artifact kiểm được của
cổng người Step 12).

**Cả hai:** thu **toàn bộ** evidence, không dừng ở lỗi đầu. `MediaQualityVerdict`
versioned, machine-readable, mang `contract_fingerprint`. Fixture FFmpeg offline.
Đổi tên node `render_quality` → `media_quality` **kèm compatibility loader** cho
`project.json` cũ.

---

# PHASE 5 — Canary

## Step 12 — Shadow rollout + một DRY_RUN Long canary

**Không sửa source hoặc profile giữa canary run.** Gặp lỗi thì ghi, phân loại,
sửa, rồi bắt đầu attempt MỚI phân biệt được.

Ba cổng người: duyệt script → duyệt storyboard/contact sheet → **xem hết** video
cuối. Receipt của cổng ba là artifact do Step 11b định nghĩa. Không upload;
publish chỉ khi user phê duyệt riêng, `privacy=private`.

**Cleanup bắt buộc (v1 thiếu).** Mọi feature flag do plan này tạo
(`content.compiler_v2`, `visual.compiler_v2`, per-profile editorial admission,
rollout flag) phải có tiêu chí gỡ, và Step 12 gỡ những cái đã đạt. Không để cờ
sống vĩnh viễn — đó là nhân đôi bề mặt cho lần refactor sau.

**Acceptance cấp engine.**
- [ ] Prompt, schema, validator, repair, release gate dùng **cùng** contract.
- [ ] Thêm profile mới không phải sửa core QA (profile fixture thứ hai chứng minh).
- [ ] Thêm provider mới chỉ cần adapter + capability (fake provider Step 8c).
- [ ] Không còn tên series/cast/vendor trong engine rule.
- [ ] Generation dùng shot-level spec (§0.4 đã chết).
- [ ] Required vs optional visual constraint phân biệt được.
- [ ] Judge calibration với nhãn người.
- [ ] `MediaQualityVerdict` đầy đủ sinh được từ MP4.
- [ ] Checkpoint resume + invalidation đúng fingerprint (Step 2b).
- [ ] Full suite pass, `--cov-fail-under=80` xanh.
- [ ] Một Long canary đi hết pipeline **không hand-edit artifact nào**.
- [ ] Human review xác nhận nội dung, visual, video.
- [ ] Không upload khi chưa có phê duyệt riêng.

---

# §3 — Rủi ro

| Rủi ro | Ảnh hưởng | Giảm thiểu |
|---|---|---|
| Bump `profile.version` vô hiệu **toàn bộ** cache ảnh + `scene_plan.json` | Lần chạy đầu sau Step 4a regenerate tất cả | Tách 4a/4b để đo riêng; ước lượng chi phí trước khi 4b nâng candidate |
| `_generation_key` đổi → đổi tên mọi file cache | Mất toàn bộ cache visual | Step 8a: hoặc chấp nhận, hoặc map một lần cho case 1-shot |
| Trần mật độ 2 dựa mẫu 5 shot | Có thể quá chặt cho cảnh tĩnh | Step 8b tách required/optional; đo lại trên corpus |
| Model Judge `minimax-m3:free` là giải pháp vòng | Sự cố provider lặp lại | Step 2 tách `RuntimeBindingFingerprint`; Step 9 ADR |
| Multi-shot làm chi phí Judge tăng theo số shot | Thời gian/chi phí mỗi tập tăng | Đo thật ở Step 4b trước rollout |
| Bật `director` sớm | Cháy budget, mọi shot dồn vào cổng người | Interlock Step 4a, gỡ ở Step 10 |
| Đổi tên node `render_quality` | `project.json` cũ mất resume | Compatibility loader bắt buộc |

# §4 — Protocol thay đổi plan

Step có thể split / insert / skip / reorder / abandon. Mọi thay đổi ghi vào chính
file này kèm ngày + lý do. Quyết định làm đổi **product direction** → dừng, hỏi user.

**Lịch sử:** v1 (2026-09-04) BLOCK ở review đối kháng — 3 CRITICAL. v2 sửa: thêm
Step 0/2b/2c; tách 3→3a/3b, 4→4a/4b, 8→8a/8b/8c, 11→11a/11b; corpus chuyển sang
committed + có nhãn người ngay; exit criteria đổi từ grep sang AST/số đo; thêm
interlock director; đính chính invariant `frozen` cho checkpoint state. Một finding
của reviewer (prompt đặt 12 phút) **bị bác bỏ bằng đo thực tế**, và thay bằng lỗi
thật cùng dạng ở §0.3.

# §5 — Quy ước thực thi

- Mọi lệnh Python trong `.venv`.
- TDD: test đỏ mô tả contract → implement tối thiểu → refactor → test liên quan →
  full suite → code review → verification report.
- **Không commit file test.** Test vẫn viết và chạy đầy đủ.
- Không stage/commit/publish khi chưa được yêu cầu.
- Một phase tại một thời điểm. Sau mỗi phase: Python review, code review, verification.
