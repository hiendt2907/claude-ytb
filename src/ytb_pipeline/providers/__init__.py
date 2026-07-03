"""Provider registry system — Phase 1 của migration plan.

Mỗi capability (voice/render/publish) là một Protocol + registry. Adapter
module tự đăng ký vào registry khi import (xem `providers/voice/__init__.py`
và tương tự cho render/publish).
"""
