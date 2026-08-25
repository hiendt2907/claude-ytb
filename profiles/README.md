# Content profiles

Mỗi thư mục con là một chủ đề độc lập chạy trên cùng workflow DAG. `profile.json`
khai báo format, provider, voice cast, content rules và renderer; `prompts/` giữ
quy tắc biên tập; `assets/` giữ hình local; các file bible/ledger là memory của
series. Không thêm `if profile_id == ...` vào pipeline.

Chạy một profile:

```bash
bin/ytb batch start -n 1 --type-of-vid short \
  --profile ban-so-6 --batch-key shorts_funnel_batch_ban_so_6
bin/ytb batch run --batch-key shorts_funnel_batch_ban_so_6
```

`batch run` vẫn dry-run nếu không có `--publish`. Batch item lưu `profile_id`
để từng subprocess tự nhận đúng LLM/TTS/render/B-roll/cast mà không thay đổi
cấu hình toàn cục của item khác.
