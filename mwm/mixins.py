from __future__ import annotations

import sqlite3
from typing import Any
from urllib.parse import urlsplit

from .config import Config

def safe_redirect_target(value: str | None, fallback: str) -> str:
    """Return only a same-origin absolute path suitable for a Location header."""
    if not value or "\r" in value or "\n" in value:
        return fallback
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/") or parsed.path.startswith("//"):
        return fallback
    return value


class AppMixin:
    """Typing contract supplied by the composed WSGI application."""

    config: Config

    def db(self) -> sqlite3.Connection:
        raise NotImplementedError

    def html(self, title: str, content: str, **kwargs: Any) -> Any:
        raise NotImplementedError

    def redirect(self, location: str, headers: tuple[tuple[str, str], ...] = ()) -> Any:
        raise NotImplementedError

    def valid_csrf(self, request: Any) -> bool:
        raise NotImplementedError

    def form_page(self, request: Any, title: str, fields: str, action: str, error: str = "") -> Any:
        raise NotImplementedError

    def form_markup(self, request: Any, title: str, fields: str, action: str, error: str = "") -> str:
        raise NotImplementedError

    def auth_rate_limited(self, request: Any) -> bool:
        raise NotImplementedError

    def record_auth_failure(self, request: Any) -> None:
        raise NotImplementedError

    def clear_auth_failures(self, request: Any) -> None:
        raise NotImplementedError
