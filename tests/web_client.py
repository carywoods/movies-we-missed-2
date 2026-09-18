from __future__ import annotations

from io import BytesIO
from urllib.parse import urlencode


def request(app, path: str, method: str = "GET", data: dict | None = None, cookie: str = "", environ_overrides: dict | None = None):
    query = ""
    body = b""
    if method == "GET" and data:
        query = urlencode(data)
    elif data:
        body = urlencode(data).encode()
    captured: dict = {}

    def start_response(status, headers):
        captured["status"] = int(status.split()[0])
        captured["headers"] = dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "CONTENT_LENGTH": str(len(body)),
        "CONTENT_TYPE": "application/x-www-form-urlencoded",
        "wsgi.input": BytesIO(body),
        "HTTP_COOKIE": cookie,
        "REMOTE_ADDR": "127.0.0.1",
    }
    if environ_overrides:
        environ.update(environ_overrides)
    response = b"".join(app(environ, start_response))
    return captured["status"], captured["headers"], response
