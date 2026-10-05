"""
Сумісність: реекспорт з модулю facebook.parser.
"""
from facebook.parser import FacebookParser, parse_cookie_string, DEFAULT_HEADERS

__all__ = ["FacebookParser", "parse_cookie_string", "DEFAULT_HEADERS"]
