---
name: youtube-monetization
description: Bổ trợ — tối ưu SEO (title/tag/thumbnail/description), theo dõi analytics & doanh thu, vòng phản hồi cải thiện nội dung. Dùng khi tối ưu khả năng kiếm tiền, phân tích hiệu suất kênh, hoặc thiết kế feedback loop. Liên quan [[youtube-publish]], [[youtube-ideation]].
version: 1.0.0
source: project-architecture
---

# YouTube Monetization & SEO

Skill bổ trợ, cắt ngang nhiều khâu — mục tiêu cuối của pipeline là kiếm tiền bền vững.

## SEO ngay từ ideation

Title/tags/description tối ưu được sinh ở [[youtube-ideation]] và dùng ở [[youtube-publish]]:

- **Title**: từ khoá chính ở đầu, ≤ 60 ký tự hiển thị, có yếu tố gây tò mò (không clickbait sai sự thật).
- **Tags/keywords**: bám search intent; nghiên cứu xu hướng trước khi sinh.
- **Description**: 1-2 dòng đầu chứa từ khoá + CTA; phần sau bổ sung context, link.
- **Thumbnail**: tương phản cao, chữ lớn đọc được trên mobile (sinh ở [[youtube-render]]).

## Analytics & doanh thu

Sau upload, theo dõi qua YouTube Analytics API:

- CTR, average view duration, retention curve → tín hiệu chất lượng nội dung.
- Doanh thu (RPM/CPM), watch time đủ điều kiện monetization.
- Lưu metric vào `data/` để phân tích chuỗi thời gian.

## Feedback loop

Đóng vòng: analytics của video cũ → điều chỉnh prompt ideation cho video mới.
Thiết kế deterministic (rule rõ ràng) trước, dùng LLM cho phần phán đoán mở.

## Tuân thủ

- Theo YouTube Partner Program & content policy — tránh nội dung tái sử dụng/spam bị hạn chế monetization.
- Không tạo nội dung gây hiểu lầm; chất lượng thật là điều kiện kiếm tiền lâu dài.

## Checklist

- [ ] Title/tags/description tối ưu search intent, không clickbait sai
- [ ] Thumbnail đọc được trên mobile
- [ ] Metric lưu vào `data/` để phân tích
- [ ] Feedback loop có rule deterministic rõ ràng
