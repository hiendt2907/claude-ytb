# Gate 1 — bàn giao cho Codex (2026-09-04)

Tiếp nối `2026-09-03-gate1-status-for-audit.md`. Mọi số đều lấy từ log/đo thật
và chạy lại được. Phần chưa chứng minh nằm ở §6, không giấu trong văn xuôi.

## 0. Kết luận ngắn

**Chưa có video.** Nhưng tuyến đã đi xa hơn hẳn: lần đầu một Long qua được
`voiceover → audio_quality → scene_plan → visual_assets` và chạy tới shot 3/18
với Judge thật chấm thật.

Suite: `1463 passed, 3 skipped, 1 deselected`.
Nhánh `codex/production-readiness-e2e-gate1`, 22 commit từ `05ca1ab`.

**Điểm chặn hiện tại: một lỗ hổng cụ thể trong vòng sửa `visual_intent`** — mô
tả ở §4, có sẵn hướng sửa.

## 1. Việc bị chặn ở đâu, và tại sao lâu

Mỗi lần tôi sửa một họ lỗi thì lỗi chuyển sang họ khác. Nguyên nhân chung, đo
được: **`visual_intent` được Judge chấm TỪNG MỆNH ĐỀ như hợp đồng bắt buộc**,
nên mỗi chi tiết là một cơ hội độc lập để hard-fail cả shot.

Đo trên 5 shot đầu của `hai-lan-may-ban-mot-tin-nhan-gui-di`:

| chi tiết "vật + trạng thái" | kết quả |
|---|---|
| 0 – 1 | qua |
| 3 – 4 | **chặn** |

Tám họ hard-fail trước đó đều cấm một **loại** chi tiết. Vá theo loại không bao
giờ hết — nguyên nhân là **số lượng**. `afd9669` đặt trần 2, dự đoán đúng 5/5
shot đã đo.

## 2. Đã sửa hôm nay

| commit | nội dung | bằng chứng |
|---|---|---|
| `217c958` | profile 2.4.0 — `tts_pace_factor` 0.92→0.79 | 5 Long thật, tốc độ đo 879→1035 cpm, xu hướng đơn điệu theo version |
| `3b89732` | LLM retry lỗi transport thoáng qua | một HTTP 502 giết trọn lượt sinh |
| `8be8ccb` | profile 2.5.0 — phép thử lời chốt | 2 lần bị loại vì nêu quy luật dạng rào đón |
| `4d63387` | chặn "vật KHÔNG có trong khung" | `"tách cà phê chưa có"` → 4/4 hard-fail |
| `16aa634` | chặn tư thế vật / thao tác dở | 8 candidate / 2 shot |
| `e0014bf` | chặn chuỗi hai nhịp trong một khung | `"nhìn A rồi nhìn B"` → 4/4 |
| `e2f02de` | **prompt dựng TỪ bảng guard** | drift đã cắn 2 lần trong 1 ngày |
| `34ddcb3` | sửa hồi quy do `cf24cf6` của tôi gây ra | cổng cast-leak chết âm thầm nửa ngày |
| `3efb505` | phủ định hỏng ở **cả hai** thứ tự từ | guard báo sạch 0/18, Judge chặn shot đầu |
| `afd9669` | **trần mật độ chi tiết** | 5/5 shot dự đoán đúng |
| `d0f6ef8` | một định nghĩa "lỗi 5xx" cho mỗi provider | node chết vì 5xx ngoài danh sách liệt kê |
| `c429f1e` | profile 2.6.0 — đổi model Judge | qwen trả 500 cho **mọi** request |
| `86f3347` | operator override model Judge | snapshot đóng băng cả nhà cung cấp |
| `18ffea0` | tập đã huỷ rời blacklist dedup | huỷ để làm lại, rồi bị chính nó chặn |
| `4fbe184` | profile 2.7.0 — sửa ví dụ mâu thuẫn | 3 ví dụ "Ưu tiên" của tôi đều **trượt chính cổng** |
| `fefedb8` | trần mật độ tới được bản sửa + prompt | applier nhận bản sửa 4 chi tiết |

### 2.1 Hai phát hiện đáng đọc kỹ

**Model Judge chết hoàn toàn** (`c429f1e`). Cô lập từng biến qua transport thật:
`GET /v1/models` OK · POST ảnh 500 · ảnh 55KB cũng 500 · **POST chỉ-text cũng
500**. Cả họ qwen hỏng trên gateway; mọi model trả phí trả **403** vì khoá chỉ
với tới tier `:free`. `minimax/minimax-m3:free` là model free duy nhất đo được
là chấm thật (phân biệt candidate 0.30 vs 0.75, đúng taxonomy).

**Snapshot đóng băng cả hạ tầng** (`86f3347`). Script ghim `profile_version`,
profile mang model Judge — nên một nhà cung cấp sập là **mọi script ghim version
đó vĩnh viễn không sản xuất được**, kể cả sau khi profile mới đã sửa. Snapshot
sinh ra để *luật kể chuyện* không đổi; đóng băng tên vendor là tác dụng phụ.
`settings.visual_judge_provider/model` giờ là cửa thoát tường minh.

## 3. Ba lỗi do chính tôi gây ra

Ghi riêng để Codex cân đúng độ tin của phần còn lại.

1. **`cf24cf6` giết cổng nó định siết.** Khớp tên riêng viết hoa, nhưng caller
   duy nhất viết thường trước → cổng cast-leak không bao giờ khớp được nữa.
   Rubric LLM bắt thay, tốn cả lượt sinh. Bài học: **sửa cổng xong phải chạy
   qua đúng đường gọi thật**, không chỉ gọi trực tiếp bằng dữ liệu tự dựng.
2. **`8be8ccb` viết ví dụ mâu thuẫn với cổng.** Cả 3 câu "Ưu tiên" tôi đưa vào
   profile đều **trượt** `_is_narrator_lesson_closing` (thiếu từ hướng về người
   xem). Model làm theo và bị chặn 4 lượt. Bản 2.7.0 verify từng câu trước khi
   ghi vào profile.
3. **`76213e5` ép lời chốt thành câu lê thê.** Ngân sách độ dài dồn phần thiếu
   của cả kịch bản vào một section bị buộc 2–3 câu. Sửa ở `8539904`.

## 4. Điểm chặn hiện tại — việc tiếp theo

Sáu lượt gần nhất: 5 hỏng vì `unrenderable_visual_intent` (mật độ), 3 vì
`ENCODING_ASCII` (phát lại cache).

Kịch bản sinh ra **gần đạt**: 16 section, 5453 ký tự → **316–380s (5.3–6.3
phút)**, và mật độ phân bố:

```
[2, 0, 0, 3, 0, 0, 0, 3, 4, 0, 0, 2, 0, 0, 0, 0]   trần 2 → chỉ 3/16 vượt
```

Ba intent vượt đều là **cảnh tĩnh liệt kê đồ vật trên bàn**:

```
§4 (3)  Điện thoại nằm yên trên bàn, màn hình tối, cạnh tách cà phê còn nguyên.
§8 (3)  Điện thoại nằm ngửa trên bàn, màn hình tối, cạnh cuốn sổ mở, bút đặt ngang.
§9 (4)  Một cuốn sổ mở trên bàn, bút nằm ngang, điện thoại nằm ngửa, màn hình sáng mờ.
```

**Lỗ hổng cần sửa:** `visual_intent_repair_attempted` là cờ **single-shot mỗi
lượt sinh**. Khi `apply_visual_intent_repair` từ chối bản sửa (vẫn quá dày), cờ
đã tiêu — không còn lượt sửa nào, và cả lượt sinh chết.

Nhưng **applier từ chối là một thất bại SỬA ĐƯỢC**, khác hẳn "model từ chối
tuân luật". Hướng đề xuất: cho phép thử lại vòng sửa khi applier từ chối, có
trần riêng (2–3 lượt), và đưa **lý do từ chối kèm số đếm** vào prompt lượt sau
— hiện thông điệp đã có sẵn số chi tiết.

## 5. Cách chạy

```bash
SP=<scratchpad>
nohup bash "$SP/gate1.sh" all 6 > "$SP/g1_all.log" 2>&1 < /dev/null & disown
```

Chạy `nohup … & disown` chứ đừng để làm con của task wrapper — hai lượt đã bị
giết giữa chừng vì thế (2026-09-02).

- Brief hiện dùng: `idea_long_v19.txt` — 16 section, **5.400–5.900 ký tự**.
  Cửa sổ luôn-trên-5-phút, tính từ hai đầu dải tốc độ đo được (860.8–1035.3
  cpm): `>5.176` và `<6.026`.
- Ledger: `assets/production_readiness/gate1/attempts.tsv`, cột `owner` là cột
  chính — nó nói **tầng nào phải sửa**.
- `.env` đang đặt `VISUAL_JUDGE_PROVIDER=xkiro` + `VISUAL_JUDGE_MODEL=minimax/
  minimax-m3:free`. Bắt buộc đặt **cả hai**, validator từ chối một nửa.

## 6. Chưa chứng minh được

- **Chưa có MP4 nào.** `render` và `verify` 5 tầng chưa từng chạy. Điểm 4–5 của
  bất biến TTS↔STT (audio rút từ chính MP4) **chưa từng được chạy**.
- **Short phái sinh** chưa làm.
- **Trần mật độ = 2** dựa trên 5 shot. Đúng 5/5 nhưng mẫu nhỏ; có thể quá chặt
  cho cảnh tĩnh (§4 với 3 chi tiết chưa chắc đã hỏng thật).
- **Đổi model Judge là giải pháp vòng** cho sự cố của nhà cung cấp. Nếu qwen
  sống lại, quay về hay không là quyết định của chủ repo — đừng để nó tự trôi.
- **`MAX_MANUAL_OVERRIDES_PER_REVIEW` bị driver tiêu.** Đã chặn driver
  regenerate (`MAX_REGEN_PER_SHOT = 0`), nhưng **ngân sách vẫn dùng chung** —
  chưa tách nguồn tự động khỏi nguồn operator.
- **Lỗi validation của pydantic in nguyên dict settings**, trong đó có mật
  khẩu. Bất kỳ lần config sai nào cũng rò nó vào log/stderr. Chưa sửa.

## 7. Quy ước cần biết

**Không commit file test.** Yêu cầu của chủ repo 2026-09-03: test vẫn viết và
chạy, chỉ không stage. Test có sẵn bị thay đổi source làm hỏng thì **sửa local,
không commit** — nên `git status` để lại vài file `tests/` ở trạng thái modified
là bình thường và đúng ý.

Hiện đang modified và **cố ý không commit**: `test_content_profiles.py`,
`test_content_strategy.py`, `test_narration_speaker_migration.py`,
`test_visual_assets.py`.
