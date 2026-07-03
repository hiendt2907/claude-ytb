"""Lỗi dùng chung cho hệ provider (voice/render/publish/image)."""


class ProviderUnavailableError(Exception):
    """Raised when a provider's is_available() returns False but generate() is called."""


class ProviderRegistrationError(Exception):
    """Raised when registering a provider with a name that conflicts."""
