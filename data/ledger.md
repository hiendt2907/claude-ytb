# Ledger sản xuất — claude-ytb

Sổ cái mọi video qua pipeline. **Bền xuyên mọi session** — đọc trước khi sản xuất,
ghi NGAY sau mỗi khâu. Đây là nguồn sự thật để resume; không giữ tiến độ trong đầu.

Quy ước cột `stage`: `ideation → approved → voiceover → render → publish → done`
(khớp `assets/auto_state.json`). `status`: `ok | error | paused`.

| Ngày | Slug | Tiêu đề | Stage | Status | URL / ghi chú |
|------|------|---------|-------|--------|---------------|
| 2026-06-15 | 5-lenh-linux-nguy-hiem | 5 lệnh Linux nguy hiểm | done | ok | https://youtu.be/hnb1CfDzyCY (private) |
| 2026-06-16 | 3-thoi-quen-buoi-sang | 3 thói quen buổi sáng | done | ok | Short AI-visual, kênh "1 Cốc Café 6h", private https://youtu.be/tGjjuq2QK-Y (#Shorts) |
| 2026-06-16 | 5-lenh-git-cuu-ban | 5 lệnh Git cứu bạn khi lỡ tay mất code | render | ok | Short AI-visual 1080x1920 31.8s, DRY_RUN; assets/output/5-lenh-git-cuu-ban-khi-lo-tay-mat-code.mp4 |
| 2026-06-16 | day-som-thay-doi-cuoc-doi | Dậy Sớm 30 Ngày Đã Thay Đổi Cả Cuộc Đời Tôi | render | ok | CLIP NGANG mẫu test render landscape: 1920x1080, 247s, AI-visual B-roll, DRY_RUN (phân loại "Clip thường") |
| 2026-06-16 | ky-luat-ban-than | Kỷ Luật Bản Thân: Cách Rèn Dù Không Có Động Lực | done | ok | https://youtu.be/LNYxk7MGDQY (private→public 2026-06-17T06:00). Clip ngang 334s AI-visual. Drive: 1RuVOj2-jDwPEb-hDyI7CEy0UwQfQ15te. ⚠ thumbnail custom 403 (kênh chưa verify) |
| 2026-06-16 | dung-cham-dien-thoai-sang | Đừng Cầm Điện Thoại! 5 Việc Làm Ngay Khi Vừa Thức Dậy | ideation | cancelled | User dừng task (2026-06-16) trước voiceover — chủ đề buổi sáng trùng hướng 3-thoi-quen-buoi-sang/day-som. Không sản xuất. |
| 2026-06-16 | quy-tac-50-30-20 | Quy Tắc 50/30/20: Tiêu Lương Sao Để Không Cháy Túi | done | ok | https://youtu.be/0y6zjIEcbpg (private→public 2026-06-16T14:00). Short dọc 33.4s AI-visual #Shorts. Chủ đề TÀI CHÍNH cá nhân (chống trùng). Drive 1rdWIXCb8a-io7gDcTajR8E4ZDPjpCWSk. ⚠ thumbnail 403 (chưa verify) |
| 2026-06-16 | quy-tac-2-phut | Trì Hoãn Cả Ngày? Quy Tắc 2 Phút Sửa Ngay | done | ok | https://youtu.be/eJgwdAeaNb4 (private→public 2026-06-16T20:00 giờ vàng). Short dọc 34.5s AI-visual #Shorts. Trục NĂNG SUẤT/chống trì hoãn (góc mới, chống trùng). Plan 30 ngày Shorts-first. Drive 1YfstckZncVZLJROrZeTyoS4F7WVeiz58. ⚠ thumbnail 403 (chưa verify) |
| 2026-06-17 | suc-manh-lai-kep | Bắt Đầu Sớm 10 Năm, Giàu Gấp Đôi Dù Bỏ Ít Tiền Hơn | done | ok | https://youtu.be/IHQtgP4Hnpc (private→public 2026-06-17T07:00). Short dọc 93s AI-visual. ⚠ Upload lúc engine còn ngưỡng <60s nên ban đầu xếp "Clip thường" → đã PATCH thêm #Shorts qua API + nâng SHORT_MAX_SEC=180. Trục TÀI CHÍNH/lãi kép. Drive 1OYD9k-8Jz6EgylAt3srWiSVuFcsO0nRx. ⚠ thumbnail 403 (chưa verify) |
| 2026-06-17 | im-lang-3-giay | Im Lặng 3 Giây: Mẹo Giao Tiếp Khiến Người Khác Nể Bạn | done | ok | https://youtu.be/YKBdy0Ehc3Q (private→public 2026-06-17T12:00). Short dọc 83.2s AI-visual #Shorts (xếp đúng nhờ ngưỡng 180s). Trục KỸ NĂNG MỀM/giao tiếp. Drive 1UseVFljO9Jfab95FOw_rgDfuwfObA3mH. ⚠ thumbnail 403 (chưa verify) |
| 2026-06-17 | ky-thuat-tho-4-7-8 | Trằn Trọc Mãi Không Ngủ? Thử Ngay Kiểu Thở 4-7-8 | done | ok | https://youtu.be/VcsNmP8Tmyo (private→public 2026-06-17T20:00). Short dọc 84.3s AI-visual #Shorts. Trục SỨC KHOẺ/giấc ngủ (advertiser-safe, có khuyến cáo y tế). Drive 1wcgP9km7Aw6RaN4J7nymLDYuWhga-5_8. ⚠ thumbnail 403 (chưa verify) |
| 2026-06-16 | deep-work-tap-trung-sau | Deep Work: Cách Tập Trung Sâu Trong Thời Đại Sao Nhãng | done | ok | User xác nhận ĐÃ XONG (session trước). Clip ngang AI-visual, publish thật. Trục NĂNG SUẤT/tập trung sâu. Script JSON đã được dọn; audio 27 đoạn còn sót trong assets/audio/ là đồ thừa — KHÔNG sản xuất lại. |
| 2026-06-17 | hoc-nhanh-nho-lau | Học Nhanh Nhớ Lâu: Kỹ Thuật Học Hiệu Quả Khoa Học Đã Chứng Minh | approved | paused | ĐÃ DUYỆT kịch bản (chat 16/6), user yêu cầu **lưu lại mai làm** → chưa voiceover. scripts/hoc-nhanh-nho-lau.json (26 đoạn, 12.2', qua load_script). Clip ngang AI-visual, publish thật. Trục KỸ NĂNG HỌC — trục hoàn toàn mới. ⚠ publish_at 06:00 17/6 → cập nhật nếu làm muộn hơn. |
| 2026-06-17 | hieu-ung-dunning-kruger | Hiệu Ứng Dunning-Kruger: Vì Sao Người Kém Nhất Lại Tự Tin Nhất | done | ok | **SERIES tập 1/30** "Cơ chế tâm trí". https://youtu.be/KL8227Nw8yA (private→public 20:00 17/6). Clip ngang 851.5s AI-visual. Drive 1g4UZJBre4I56rLaqRhz0RXeL5JT2dfmI. ⚠ thumbnail 403 (kênh chưa verify). |
| 2026-06-18 | hieu-ung-zeigarnik | Hiệu Ứng Zeigarnik: Vì Sao Việc Bạn Chưa Làm Xong Cứ Ám Ảnh Trong Đầu | done | ok | **SERIES tập 2/30**. https://youtu.be/Uqk71cy79Vs (private→public **06:00 19/6**). Clip ngang 708s AI-visual. Drive 1pfsNRm5rhJ_80kUWSqMvnGCT1I3mG-Ms. Nguồn Zeigarnik 1927/Masicampo&Baumeister 2011/Ovsiankina 1928. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-18 | nghich-ly-lua-chon | Nghịch Lý Lựa Chọn: Vì Sao Càng Nhiều Phương Án Càng Tê Liệt | done | ok | **SERIES tập 3/30**. https://youtu.be/h9xhq7rHl2Y (private→public **06:00 20/6**). Clip ngang 722s AI-visual. Drive 1fVNeEj43yKhKKo0ON0RunpMmRhbrrYDk. Nguồn Iyengar&Lepper 2000/Schwartz 2004/401k/Danziger 2011. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-18 | bay-chi-phi-chim | Bẫy Chi Phí Chìm: Vì Sao Bạn Cố Đấm Ăn Xôi Dù Biết Sai | done | ok | **SERIES tập 4/30**. https://youtu.be/Z8PnGXhM_wY (private→public **06:00 21/6**). Clip ngang 704s AI-visual. Drive 1xKbEEhDCBihY5j55vhlSiXkMhVA-p5fD. Nguồn Arkes&Blumer 1985/Concorde/Shubik 1971/Kahneman. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-21 | hieu-ung-mo-neo | Hiệu Ứng Mỏ Neo: Con Số Đầu Tiên Thao Túng Mọi Quyết Định | approved | ok | **SERIES tập 5/30**. scripts/hieu-ung-mo-neo.json (25 đoạn, 10.1', qua load_script). Nguồn Tversky&Kahneman 1974 Science (vòng quay số)/Ariely 2003 (số an sinh)/Northcraft&Neale 1987 (định giá nhà). Lịch public 06:00 21/6. Chờ chạy pipeline. |
| 2026-06-18 | thien-kien-tieu-cuc | Vì Sao 1 Lời Chê Ám Ảnh Hơn 10 Lời Khen — Thiên Kiến Tiêu Cực | done | ok | **Lô 5-short rời (không thuộc series), public 19h-23h tối 18/6**, tập 1/5. https://youtu.be/1k2p-YguyOQ (private→public **19:00 18/6**). Short dọc 133.7s AI-visual. Nguồn Baumeister, Bratslavsky, Finkenauer & Vohs 2001 "Bad Is Stronger Than Good", Review of General Psychology. Khác mọi video cũ: chưa video nào khai thác riêng negativity bias. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-18 | hieu-ung-baader-meinhof | Vừa Học Xong Một Từ, Nó Xuất Hiện Khắp Nơi — Hiệu Ứng Baader-Meinhof | done | ok | **Lô 5-short**, tập 2/5. https://youtu.be/ljte3adnbIk (private→public **20:00 18/6**). Short dọc 142.5s AI-visual. Nguồn frequency illusion, Arnold Zwicky 2005 (đặt tên) + chú ý chọn lọc/thiên kiến xác nhận. Khác mọi video cũ: chưa video nào khai thác hiệu ứng này. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-18 | hieu-ung-forer | Vì Sao Bói Toán Nào Cũng 'Đúng Y Mình' — Hiệu Ứng Forer | done | ok | **Lô 5-short**, tập 3/5. https://youtu.be/iqBlWpa7NLY (private→public **21:00 18/6**). Short dọc 133.9s AI-visual. Nguồn Bertram Forer 1948, Journal of Abnormal Psychology (điểm trung bình 4.26/5). Khác mọi video cũ: chưa video nào khai thác hiệu ứng Forer/Barnum. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-18 | thien-kien-lac-quan | Vì Sao Ai Cũng Tin Điều Xấu Sẽ Rơi Vào Người Khác — Thiên Kiến Lạc Quan | done | ok | **Lô 5-short**, tập 4/5. https://youtu.be/Ctfb_41Mlgw (private→public **22:00 18/6**). Short dọc 132.0s AI-visual. Nguồn Tali Sharot (UCL) 2011, Current Biology (fMRI). Khác mọi video cũ: chưa video nào khai thác optimism bias riêng. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-18 | hieu-ung-chim-da-dieu | Biết Tin Xấu Sắp Tới Mà Vẫn Không Dám Mở Xem — Hiệu Ứng Chim Đà Điểu | done | ok | **Lô 5-short**, tập 5/5 (chốt lô). https://youtu.be/g0d3F3ZzpMM (private→public **23:00 18/6**). Short dọc 123.7s AI-visual. Nguồn Karlsson, Loewenstein & Seppi (2009), Journal of Risk and Uncertainty. Khác mọi video cũ: chưa video nào khai thác ostrich effect. Lần chạy đầu publish lỗi timeout mạng giữa upload (resumable chunk), retry lần 2 thành công — voiceover/render không đổi. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-19 | hieu-ung-hao-quang | Một Điểm Tốt Khiến Bạn Tin Cả Con Người Họ Tốt — Hiệu Ứng Hào Quang | done | ok | **Lô 4-short** (mới, không thuộc 2 series 30 ngày), tập 1/4. https://youtu.be/DrCK9c4psVE (private→public **08:00 19/6**). Short dọc 131.0s AI-visual. Nguồn Thorndike 1920 + Nisbett & Wilson 1977. Khác mọi video cũ: chưa video nào khai thác halo effect. Engine render đã NÂNG SÁNG (veil 59%→43% + eq=brightness=0.08/saturation=1.08 trong `_kenburns_beat`, compose_ai.py) theo yêu cầu user — áp dụng từ video này. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-19 | hieu-ung-spotlight | Bạn Nghĩ Ai Cũng Nhìn Thấy Vết Bẩn Trên Áo — Sự Thật Là Không Ai Để Ý | done | ok | **Lô 4-short**, tập 2/4. https://youtu.be/26ouEdrOj9Q (private→public **12:00 19/6**). Short dọc 103.9s AI-visual. Nguồn Gilovich, Medvec & Savitsky 2000 (Cornell). Khác mọi video cũ: chưa video nào khai thác spotlight effect. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-19 | hieu-ung-dong-khung | Cùng Một Sự Thật, Đổi Một Câu Chữ — Bạn Quyết Định Khác Hẳn | done | ok | **Lô 4-short**, tập 3/4. https://youtu.be/ocQ1AwGG8pU (private→public **16:00 19/6**). Short dọc 121.4s AI-visual. Nguồn Tversky & Kahneman 1981, Science (framing effect). Khác mọi video cũ: chưa video nào khai thác framing effect (phân biệt với mỏ neo). Lần chạy đầu lỗi DNS tạm thời khi tải B-roll Pexels, retry thành công — voiceover không đổi. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-19 | hieu-ung-bang-quan | Đông Người Chứng Kiến — Càng Ít Người Ra Tay Giúp | done | ok | **Lô 4-short**, tập 4/4 (chốt lô). https://youtu.be/ZiTIQcZh8wA (private→public **20:00 19/6**). Short dọc 120.6s AI-visual. Nguồn Darley & Latané 1968 (sau vụ Kitty Genovese). Khác mọi video cũ: chưa video nào khai thác bystander effect. Drive backup lần đầu lỗi broken pipe, retry tay qua `backup_to_drive()` thành công. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-19 | hieu-ung-hawthorne | Hiệu Ứng Hawthorne: Bị Quan Sát Thôi Cũng Khiến Bạn Làm Việc Tốt Hơn | done | ok | **Lô 3-short sáng**, tập 1/3. https://youtu.be/Fk0eSTTZQ8E (private→public **07:00 20/6**). Short dọc AI-visual #Shorts. Nguồn Western Electric Hawthorne Works 1924-1932 (Elton Mayo)/Landsberger 1958. Khác mọi video cũ: chưa video nào khai thác Hawthorne effect. Drive 1yBHvIPCe0Fqraf2S7lo9OQOzWo5s-7VD. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-19 | thien-kien-nhan-thuc-muon | Tao Biết Trước Rồi! — Thiên Kiến Nhận Thức Muộn (Hindsight Bias) | done | ok | **Lô 3-short sáng**, tập 2/3. https://youtu.be/SRa-2YXKJC8 (private→public **09:30 20/6**). Short dọc AI-visual #Shorts. Nguồn Fischhoff 1975 + Arkes et al. 1981. Khác mọi video cũ: chưa video nào khai thác hindsight bias. Drive 1aHWO3RCfKYShKtyu-Fc7x9rh3rNl2VCS. ⚠ thumbnail 403 (chưa verify). |
| 2026-06-19 | nghich-ly-abilene | Cả Nhóm Đồng Ý — Nhưng Chẳng Ai Muốn Đi: Nghịch Lý Abilene | done | ok | **Lô 3-short sáng**, tập 3/3 (chốt lô). https://youtu.be/7iAQDJ5htkM (private→public **12:00 20/6**). Short dọc AI-visual #Shorts. Nguồn Jerry B. Harvey 1974, Organizational Dynamics. Khác mọi video cũ: chưa video nào khai thác Abilene paradox. Drive 1xYkW006w616uz5GJAem64F6UphSrUKV6. ⚠ thumbnail 403 (chưa verify). |

## Lô 3-short sáng (khởi động 2026-06-19, public 07:00/09:30/12:00 ngày 20/6)

Lô rời theo yêu cầu user ("3 clip short sáng mai 6h-12h"), không thuộc 2 series 30 ngày.
3 cơ chế tâm lý/hành vi CHƯA video nào trong kênh khai thác (đối chiếu ledger + cả 2 series
queued): (1) `hieu-ung-hawthorne` — Hiệu ứng Hawthorne (Mayo, Hawthorne studies 1924-1932),
07:00; (2) `thien-kien-nhan-thuc-muon` — Hindsight bias (Fischhoff 1975), 09:30;
(3) `nghich-ly-abilene` — Nghịch lý Abilene (Jerry Harvey 1974), 12:00. AI-visual, dọc
#Shorts, publish thật theo lịch. Giờ public lệch khỏi 06:00 (đã có episode dài series sáng
ngày 20/6) để tránh trùng giờ.

## Series 30 ngày "Cơ chế tâm trí" (khởi động 2026-06-17)

Ngách thắng (Bước B, 18đ): **Cơ chế tâm lý & hành vi học ứng dụng (mental models)** —
search 4 / competition 4 / ypp 5 / brand 5. Trending VN hiện do nhạc+game chiếm sóng
(không evergreen) → chọn domain bền hợp brand "1 Cốc Café 6h". 30 tập, 1 cơ chế/tập,
public 06:00 mỗi ngày (tập 1 lệch 20:00 tối nay theo yêu cầu). Khối `series` đầy đủ ở
`assets/auto_state.json`. Tập 2 = Hiệu ứng Zeigarnik (scripts/hieu-ung-zeigarnik.json đã có).

## Series 30 ngày "Cơ chế tài chính cá nhân" — slot 20:00 (khởi động 2026-06-18)

Series THỨ HAI chạy song song, khung **20:00 tối** mỗi ngày (slot `evening`,
key `series_evening` trong `auto_state.json`). Ngách: **cơ chế tài chính cá nhân**
(tâm lý tiền bạc & kinh tế học hành vi) — giải cơ chế THẬT, không self-help, CPM cao,
advertiser-safe. 30 tập, 1 cơ chế/tập, public 20:00 từ 2026-06-19 → 2026-07-18.
Tập 1 = Hiệu Ứng Sở Hữu. Dedup chéo ledger + series sáng "Cơ chế tâm trí" (06:00).
Đã loại `quy-tac-50-30-20`, `suc-manh-lai-kep` (đã làm) khỏi danh sách.

## Thay đổi engine render

- **2026-06-16** — Nâng cấp `render-ai` đồng bộ transcript (theo phản hồi Studio video
  `ky-luat-ban-than`). Mỗi segment giờ cắt thành nhiều beat ≤6s + Ken Burns motion
  (hết cảnh tĩnh dài), tải nhiều shot B-roll khác nhau/segment (`stock.fetch_broll_variants`).
  Thêm 3 field section tùy chọn: `emphasis` (pop chip từ khoá), `hook` (cold-open cảnh
  hành động đầu video), `transition` (whoosh + xfade ở bước ngoặt). Module mới
  `render/transitions.py`. Video render TRƯỚC mốc này dùng engine cũ (1 shot tĩnh/segment).

## Cách dùng

- **Trước khi làm 1 chủ đề:** tra ledger; nếu đã `done` thì bỏ qua, nếu dở thì tiếp từ `stage`.
- **Sau mỗi khâu:** cập nhật 1 dòng (atomic) — slug, stage mới, status, ghi chú.
- **Khi pause (98% limit):** ghi `status=paused` + stage hiện tại để resume sạch.
- **Khi lỗi:** `status=error` + lý do ngắn ở cột ghi chú; bỏ qua sang chủ đề kế.
