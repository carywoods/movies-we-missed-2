from mwm.config import Config
from mwm.web import create_app
from tests.web_client import request


def test_production_environment_and_health(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SITE_URL", "https://movies.example")
    monkeypatch.setenv("SESSION_SECRET", "a-production-secret-that-is-long-enough")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "volume" / "mwm.db"))
    monkeypatch.setenv("PORT", "9123")
    config = Config.from_env()
    assert config.port == 9123
    assert config.database_path.parent.name == "volume"
    assert request(create_app(config), "/health")[0] == 200


def test_invalid_port_is_rejected(monkeypatch):
    monkeypatch.setenv("PORT", "70000")
    try:
        Config.from_env()
    except RuntimeError as exc:
        assert "PORT" in str(exc)
    else:
        raise AssertionError("invalid port accepted")
