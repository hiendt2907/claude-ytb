"""CLI: python -m ytb_pipeline "<đường dẫn/slug kịch bản>"

Kịch bản do Claude viết tay sẵn dưới scripts/*.json — lệnh này chỉ nạp + chạy
pipeline (voiceover -> render -> publish).
"""

import sys

from .ideation.approval import ScriptRevisionRequested
from .pipeline import run


def main() -> int:
    if len(sys.argv) < 2:
        print('Cách dùng: python -m ytb_pipeline "<đường dẫn/slug kịch bản>"', file=sys.stderr)
        return 1
    try:
        result = run(sys.argv[1])
    except ScriptRevisionRequested as exc:
        print(f"⏸  Dừng: user yêu cầu sửa kịch bản — {exc.instruction}", file=sys.stderr)
        return 2
    print(f"Xong: uploaded={result.uploaded} url={result.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
