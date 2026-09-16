import json

from mwm.config import Config
from mwm.web import create_app
from tests.web_client import request


def test_health(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    app = create_app(Config.from_env())

    status, headers, body = request(app, "/health")

    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body) == {"status": "ok", "service": "movies-we-missed"}


def test_missing_route(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "app.db"))
    status, _, _ = request(create_app(), "/missing")
    assert status == 404
