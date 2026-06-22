"""Auth OAuth riêng cho Google Drive (token tách khỏi YouTube).

Kênh upload là brand account "1 Cốc Café 6h" — brand account KHÔNG có Drive.
Drive thuộc TÀI KHOẢN CÁ NHÂN danghien2907@gmail.com. Vì vậy Drive dùng token
riêng (secrets/drive_token.json), KHÔNG đụng tới youtube_token.json.

Script này mở browser cho bạn đồng ý quyền Drive:
  → CHỌN TÀI KHOẢN CÁ NHÂN danghien2907@gmail.com (KHÔNG chọn "1 Cốc Café 6h").
  → Tích đồng ý quyền Google Drive.
Token Drive ghi vào secrets/drive_token.json.

Chạy:  PYTHONPATH=src .venv/bin/python scripts/auth_drive.py
Sau khi xong, Drive đã BẬT mặc định (drive_backup=True): mỗi lần upload YouTube thật
xong sẽ MOVE video lên thư mục Drive "Claude-YTB" rồi xoá bản local.
"""

from ytb_pipeline.publish.youtube_auth import get_drive_client


def main() -> None:
    print("→ Mở browser để cấp quyền Google DRIVE (token riêng, không đụng YouTube).")
    print("→ QUAN TRỌNG: chọn TÀI KHOẢN CÁ NHÂN danghien2907@gmail.com,")
    print("  KHÔNG chọn kênh thương hiệu '1 Cốc Café 6h' (brand account không có Drive).")
    print("→ Tích đồng ý quyền Google Drive.\n")

    # get_drive_client tự chạy consent nếu chưa có secrets/drive_token.json
    drive = get_drive_client()
    about = drive.about().get(fields="user(emailAddress)").execute()
    print("✓ Drive OK cho tài khoản:", about["user"]["emailAddress"])
    print("\nXong. Upload YouTube thật xong sẽ tự move video lên Drive 'Claude-YTB'.")


if __name__ == "__main__":
    main()
