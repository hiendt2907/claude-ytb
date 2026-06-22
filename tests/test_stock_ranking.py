"""Test xếp hạng B-roll: giữ thứ tự relevance Pexels, không sắp lại theo độ phân giải."""

from ytb_pipeline.render import stock


def _video(link: str, w: int, h: int) -> dict:
    return {"video_files": [
        {"file_type": "video/mp4", "width": w, "height": h, "link": link}
    ]}


def test_rank_preserves_pexels_relevance_order():
    # Pexels trả [A (khớp nhất, nét vừa), B (nét hơn)] -> phải GIỮ A trước B,
    # KHÔNG vì B nét hơn mà đẩy lên trước (đó là lỗi 'video 1 đường voice 1 nẻo').
    videos = [
        _video("A", 1080, 1920),   # khớp từ khoá nhất, đúng kích thước Short
        _video("B", 2160, 3840),   # 4K nét hơn nhưng kém liên quan
    ]
    links = stock._rank_links(videos, landscape=False)
    assert links == ["A", "B"]


def test_rank_dedups_links():
    videos = [_video("A", 1080, 1920), _video("A", 1080, 1920)]
    assert stock._rank_links(videos, landscape=False) == ["A"]


def test_rank_skips_videos_without_usable_file():
    videos = [{"video_files": []}, _video("A", 1080, 1920)]
    assert stock._rank_links(videos, landscape=False) == ["A"]
