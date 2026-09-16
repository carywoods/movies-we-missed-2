from pathlib import Path

from mwm.config import Config
from mwm.db import connect, initialize


def test_migrations_and_seed_are_idempotent(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "mwm.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    config = Config.from_env()

    assert initialize(config) == ["001_initial.sql"]
    assert initialize(config) == []

    connection = connect(database)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM genres").fetchone()[0] == 12
        assert connection.execute("SELECT count(*) FROM sponsors").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM merchandise").fetchone()[0] == 1
    finally:
        connection.close()


def test_production_requires_a_strong_session_secret(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("SESSION_SECRET", "short")

    try:
        Config.from_env()
    except RuntimeError as exc:
        assert "SESSION_SECRET" in str(exc)
    else:
        raise AssertionError("weak production secret was accepted")
