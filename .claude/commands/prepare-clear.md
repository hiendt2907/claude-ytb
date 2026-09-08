---
description: Chuẩn bị an toàn trước khi /clear — cập nhật memory, ledger và chốt trạng thái repo.
---

Bạn đang chuẩn bị kết thúc phiên để người dùng chạy `/clear`. Thực hiện tuần tự:

1. **Dừng mọi implementation mới.** Không bắt đầu tính năng hay refactor nào nữa.
2. **Kiểm tra Git state:** chạy `git status --short`, `git branch --show-current`, `git log --oneline -5`.
3. **Cập nhật memory system** tại
   `/Users/hiendang/.claude/projects/-Users-hiendang-claude-ytb/memory/`:
   - Nếu phiên này tạo ra fact/quyết định/feedback đáng nhớ cho phiên sau (theo 4 loại
     `user`/`feedback`/`project`/`reference` — xem hướng dẫn auto-memory), ghi hoặc cập nhật
     memory file tương ứng (frontmatter `name`/`description`/`metadata.type`) rồi thêm đúng
     1 dòng trỏ tới nó trong `MEMORY.md`.
   - Nếu một memory cũ đã bị việc vừa làm làm cho lỗi thời/sai, sửa hoặc xoá luôn — không để
     memory stale lại cho phiên sau.
   - Không tạo memory cho state tạm thời/ephemeral của riêng phiên này (task đang dở, chi
     tiết debug) — loại đó thuộc bước 4, không phải memory.
4. **Nếu có video/project vừa hoàn thành hoặc đổi trạng thái** trong batch đang chạy, xác
   nhận `data/ledger.md` đã được `batch_cli`/pipeline tự ghi đúng dòng mới nhất (không tự tay
   thêm dòng — ledger được ghi write-through bởi code, chỉ kiểm tra không sửa tay).
5. **Cập nhật tài liệu bị ảnh hưởng** nếu implementation đụng tới kiến trúc: các file trong
   `docs/constitution/`, `CLAUDE.md`, `docs/CONTENT_CONTRACT.md`, `docs/RECOVERY_CONTRACT.md`
   — theo đúng Documentation Rules trong `CLAUDE.md` (doc drift = bug).
6. **Chạy verification tối thiểu cần thiết** — thường là
   `.venv/bin/pytest -q --no-cov` (hoặc phạm vi hẹp hơn nếu thay đổi nhỏ và rõ ràng độc lập).
   Báo kết quả pass/fail rõ ràng, không suy đoán.
7. **Không tự commit** trừ khi người dùng đã cho phép rõ ràng trong phiên này. Nếu chưa, chỉ
   báo thay đổi đã sẵn sàng để commit (liệt kê file qua `git status --short`).
8. **Báo cáo checkpoint (≤ 20 dòng):**
   - Memory đã cập nhật/tạo (tên file, hoặc "không có gì đáng nhớ mới").
   - Branch, HEAD commit, tóm tắt working tree.
   - Kết quả pytest (số pass/fail).
   - Việc còn dở (nếu có) — mô tả đủ để phiên sau đọc `MEMORY.md` là tiếp tục được ngay,
     không cần hỏi lại.
9. Kết thúc bằng một câu: người dùng có thể chạy `/clear` một cách an toàn.

Lưu ý: command này **không** tự chạy `/clear` — Claude Code không hỗ trợ tự trigger. Việc
`/clear` do người dùng thực hiện thủ công. Phiên sau sẽ dùng skill `start-new-task` (đọc
`MEMORY.md` trước khi làm việc mới) — vì vậy chất lượng bước 3 ở đây quyết định trực tiếp
phiên sau bắt đầu nhanh hay chậm.
