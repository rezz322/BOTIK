"""
Сумісність: реекспорт з модулю facebook.storage.
"""
from facebook.storage import Storage, normalize_url

__all__ = ["Storage", "normalize_url"]
