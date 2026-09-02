# Runbook — Gate 1 chạy liên tục

Tài liệu này tồn tại vì một lý do cụ thể: Gate 1 đã kéo dài quá lâu, và nguyên
nhân không phải độ khó kỹ thuật mà là **cách làm việc**. Mỗi lần một lượt sinh
thất bại, chuỗi dừng lại chờ người bấm lệnh tiếp theo. Một lượt Long mất 8–12
phút; nếu tỉ lệ đạt là 1/4 thì một script tốn gần một giờ *đồng hồ treo tường*
nhưng chỉ vài phút *máy chạy* — phần còn lại là chờ người.

Runbook này thay việc bấm tay bằng một vòng chạy khép kín, và thay việc "sửa
lỗi vừa gặp" bằng "đo lớp lỗi nào lặp lại rồi sửa ở tầng sở hữu nó".

## Nguyên tắc

1. **Không sửa code giữa một lượt chạy.** Bắt được lỗi → phân loại → ghi ledger
   → để lượt đó chết hẳn → sửa → mở lượt mới phân biệt được.
2. **Không chạm tay vào artifact.** Không chép file sinh ra vào chỗ pipeline
   mong đợi, không sửa JSON để đẩy stage. Nếu phải làm thế thì pipeline đang
   hỏng, và việc chép tay chỉ giấu chỗ hỏng đi.
3. **Một lớp lỗi lặp 4 lần là lỗi engine, không phải xui.** Runner tự dừng ở
   ngưỡng đó thay vì đốt tiếp hạn mức.
4. **Nới cổng không bao giờ là bản sửa.** Cổng chặn đúng thì phải bỏ *nguyên
   nhân* ở phía trên nó.

## Chạy

```bash
SP=<scratchpad>
bash "$SP/gate1.sh" all 6        # ideate -> produce -> verify
bash "$SP/gate1.sh" ideate 6     # chỉ sinh kịch bản, lặp tới khi đạt
bash "$SP/gate1.sh" produce <slug>
bash "$SP/gate1.sh" verify <slug>
```

Ledger: `assets/production_readiness/gate1/attempts.tsv` —
`ts / stage / result / class / owner / evidence`.

Cột `owner` là cột quan trọng nhất: nó nói **tầng nào phải sửa**, không phải
lỗi trông như thế nào. `classify.py` giữ bảng ánh xạ đó; pattern nào không
khớp trả `UNCLASSIFIED` chứ không ép vào lớp gần đúng — một lớp sai còn tệ hơn
không có lớp.

## Ba tầng, và cách phân biệt

| Triệu chứng | Tầng sở hữu | Cách sửa đúng |
|---|---|---|
| Gateway trả byte hỏng / body rỗng / timeout / 5xx | `providers/` | Hỏi lại có ngân sách ở ranh giới provider |
| Model viết sai luật đã được nêu trong prompt | vòng sửa hẹp trong `ideation_script_fix` | Cho luật đó một đường sửa hẹp như `hook` đã có |
| Kịch bản sai về nội dung/biên tập | prompt + rubric | Sửa prompt hoặc brief, **không** nới rubric |

Ranh giới giữa hàng 2 và hàng 3 là chỗ dễ nhầm nhất. Câu hỏi phân biệt: *viết
lại field này có làm đổi thứ khán giả nghe được không?* Nếu không (ví dụ
`visual_intent`), sửa hẹp là an toàn. Nếu có (narration), phải qua rubric.

## Bài học đã trả giá

- **Nêu luật trong prompt là không đủ.** Model không giữ nổi một ràng buộc phủ
  định qua 20 section. Hệ thống đã chấp nhận điều đó cho `hook` và
  `narrator_reflection`; luật nào thiếu đường sửa hẹp thì mỗi lần vi phạm sẽ
  ném đi cả một lượt sinh nhiều phút. Đo thật 2026-09-01..02: 3/5 lượt bị từ
  chối chỉ vì `unrenderable_visual_intent`.
- **Viết ràng buộc vào brief là vá triệu chứng.** Nó cứu đúng một chủ đề và
  không giúp gì cho chủ đề sau, profile sau, hay người sau.
- **Ranh giới provider phải chịu được lỗi thoáng qua.** Bốn lỗi transport khác
  nhau từ cùng một gateway trong một phiên. Với ~250 lời gọi Judge mỗi video,
  gặp ít nhất một lỗi là gần như chắc chắn.
- **Chấm điểm trên clip ~0.6s là dụng cụ đo không tin được.** 3 trong 6 "lỗi"
  từng đo được hoá ra là ảo ảnh của phép đo.

## Sau khi render: 5 tầng phải chạy hết

`check_video.sh <slug>` — container/drift, dead air, TTS↔STT trên audio rút từ
chính MP4, subtitle, visual. Chạy hết rồi mới kết luận, không dừng ở tầng đầu
tiên báo lỗi: cần biết *lớp nào* hỏng, không chỉ *có hỏng không*.

Cái duy nhất script không làm được là ngồi xem. Đó là việc của người, và không
có kết luận PASS nào hợp lệ nếu bước đó bị bỏ.
