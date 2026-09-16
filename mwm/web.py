from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from typing import Callable, Iterable
from urllib.parse import parse_qs

from .config import Config
from .db import connect, initialize


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    environ: dict


@dataclass
class Response:
    body: bytes
    status: int = 200
    content_type: str = "text/plain; charset=utf-8"
    headers: tuple[tuple[str, str], ...] = ()

    @classmethod
    def json(cls, payload: object, status: int = 200) -> "Response":
        return cls(json.dumps(payload, separators=(",", ":")).encode(), status, "application/json")


Handler = Callable[[Request], Response]


class Application:
    def __init__(self, config: Config):
        self.config = config
        initialize(config)
        self.routes: dict[tuple[str, str], Handler] = {
            ("GET", "/health"): self.health,
        }

    def health(self, request: Request) -> Response:
        connection = connect(self.config.database_path)
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
        return Response.json({"status": "ok", "service": "movies-we-missed"})

    def __call__(self, environ: dict, start_response: Callable) -> Iterable[bytes]:
        request = Request(
            method=environ.get("REQUEST_METHOD", "GET").upper(),
            path=environ.get("PATH_INFO", "/") or "/",
            query=parse_qs(environ.get("QUERY_STRING", ""), keep_blank_values=True),
            environ=environ,
        )
        handler = self.routes.get((request.method, request.path))
        response = handler(request) if handler else Response(b"Not found", 404)
        phrase = HTTPStatus(response.status).phrase
        headers = [("Content-Type", response.content_type), ("Content-Length", str(len(response.body))), *response.headers]
        start_response(f"{response.status} {phrase}", headers)
        return [response.body]


def create_app(config: Config | None = None) -> Application:
    return Application(config or Config.from_env())
