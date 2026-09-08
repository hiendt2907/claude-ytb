# Pre-publish quality report schema

`ytb_pipeline.analytics.quality_report` tạo báo cáo chất lượng **local-first** trước publish. Module không gọi LLM, không đọc media, không gọi mạng và không đổi queue/batch. Render, audio và script QA hiện hữu chỉ cần đưa evidence/finding của chúng vào đây.

## Input

Tạo `QualityReportInput` với:

- `slug`, `video_type` (`short` hoặc `long`), `title`, `thumbnail_text`, `hook_text`.
- `sections`: tuple `ScriptSection(caption, narration, purpose)`. Short yêu cầu các `purpose`: `situation`, `core_answer`, `application`, `payoff`; Long thêm `evidence`.
- `render`: `RenderEvidence(width, height, duration_sec=None)`. Short phải dọc; Long phải ngang.
- `upstream_findings`: list/tuple các `QualityFinding` hoặc object có `source`, `rule`, `severity`, `message` và tùy chọn `excerpt`, `section_index`. `source="video"` được chuẩn hóa thành `render`.

Rubric packaging dùng token đã bỏ dấu tiếng Việt và bỏ stop-word. Nó báo warning khi title không có keyword chung với hook, hoặc thumbnail không có keyword chung với title/hook. Không có title, hook hay mô tả thumbnail là error vì không thể kiểm tra alignment một cách xác định.

## Output

`evaluate_pre_publish_quality()` trả `PrePublishQualityReport` schema version `1`:

```json
{
  "schema_version": 1,
  "slug": "nao-ne-viec-kho",
  "video_type": "short",
  "status": "pass",
  "counts": {"error": 0, "warning": 0, "info": 0},
  "findings": [
    {
      "source": "audio",
      "rule": "audio.silence_ratio",
      "severity": "warning",
      "message": "Tỷ lệ khoảng lặng cao.",
      "excerpt": "...",
      "section_index": 1
    }
  ]
}
```

- Bất kỳ `error` nào: `status="blocked"`.
- Không error nhưng có `warning`: `status="needs_review"`.
- Còn lại: `status="pass"`.

`write_quality_report(report, output_dir)` ghi `<slug>.quality.json` và `<slug>.quality.md`; caller chọn `output_dir` (thường là `assets/quality_reports/`). `build_repair_brief()` chỉ đưa các error/warning ưu tiên cao nhất và cắt excerpt theo `max_excerpt_chars`, để một repair workflow nhận đúng phạm vi cần sửa.

## Local STT (optional)

Đặt `QUALITY_STT_MODEL_PATH` thành đường dẫn thư mục model Faster-Whisper đã có sẵn trên máy để bật transcript diff. Để trống thì gate chỉ ghi warning `STT_UNAVAILABLE`; pipeline không tải model, không nhận model ID/URL và không gọi cloud. Cache audio tự bỏ khi đường dẫn/model local, trạng thái adapter hoặc ngưỡng quality thay đổi.
