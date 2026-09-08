# Triển khai tuần 3 — CTA tăng trưởng trong system prompt

## Mục tiêu

Tăng tín hiệu phát triển kênh mà không hardcode câu thoại vào từng kịch bản:

- Mọi Short và Long đều có CTA dẫn người xem tới hành động cụ thể liên quan cơ chế của tập.
- Mọi Short và Long đều có lời mời like video và subscribe kênh ở phần kết.
- Short vẫn giữ CTA funnel trỏ về long-form/playlist đã khai báo; like và subscribe không được thay thế CTA funnel.

## Cách áp dụng

Quy tắc được đặt trong `SCRIPT_GENERATION_SYSTEM_PROMPT`, dùng chung cho:

- Sinh script mới qua local LLM.
- Repair script khi validation hoặc QA fail.
- Các vòng sinh lại từ system contract.

Không thêm câu CTA cố định vào script, renderer hay uploader. LLM phải viết CTA tự nhiên,
ngắn, đúng giọng kênh và gắn với chủ đề video.

## Cổng verify tuần 3

1. Final narration section có câu hành động bắt đầu bằng `Hãy `.
2. Có lời mời like.
3. Có lời mời subscribe kênh.
4. Short có funnel target thì vẫn có cầu nối sang long-form.
5. CTA không biến thành filler lặp lại hoặc lời hứa gây hiểu lầm.

Test contract nằm tại `tests/test_analytics_feedback.py` và phải pass trước khi mở batch tuần 3.
