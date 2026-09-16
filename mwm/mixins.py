from __future__ import annotations

import sqlite3
from typing import Any

from .config import Config


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
