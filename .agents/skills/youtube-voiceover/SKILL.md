---
name: youtube-voiceover
description: Khâu 2 — TTS chuyển kịch bản thành giọng đọc, trừu tượng hoá provider (edge-tts miễn phí / ElevenLabs). Dùng khi làm việc với voiceover/tts.py hoặc thêm/đổi provider TTS. Liên quan [[youtube-pipeline-core]].
version: 1.0.0
source: project-architecture
---

# YouTube Voiceover (TTS)

Khâu 2: `Script → Voiceover`. File: `voiceover/tts.py`.

## Trừu tượng hoá provider

`settings.tts_provider` chọn backend:

- `edge` — edge-tts, MIỄN PHÍ, không cần key (mặc định, tốt để dev/test)
- `elevenlabs` — chất lượng cao, cần `settings.elevenlabs_api_key`

Thiết kế theo Repository/Strategy: một interface `synthesize_audio(text) -> path`,
nhiều implementation. Thêm provider mới = thêm một strategy, không sửa khâu.

## Đầu ra

- Audio → `assets/audio/` (gitignored)
- Đo `duration_sec` (cần cho khâu render khớp timeline)
- Trả `Voiceover` làm giàu từ `script` qua `replace()` (gồm `audio_path`, `duration_sec`)

## Nguyên tắc

- Chia script dài thành đoạn nếu provider giới hạn độ dài; ghép audio lại.
- Cache theo nội dung (hash text) để khỏi gọi TTS lại khi script không đổi — tiết kiệm chi phí ElevenLabs.
- Xử lý lỗi provider tường minh (quota, mạng); cân nhắc fallback edge-tts.

## Pattern

```python
def synthesize(script: Script) -> Voiceover:
    backend = get_tts_backend(settings.tts_provider)
    path, dur = backend.render(script.body)
    return replace(Voiceover(**vars(script)), audio_path=path, duration_sec=dur)
```

## Checklist

- [ ] Provider chọn qua `settings`, dễ thêm strategy mới
- [ ] Audio vào `assets/audio/`, không commit
- [ ] Đo duration cho khâu render
- [ ] Trả bản sao làm giàu ([[youtube-pipeline-core]])
