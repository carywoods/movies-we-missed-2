import sqlite3
from pathlib import Path

from mwm.config import Config
from mwm.web import create_app
from mwm.db import MIGRATIONS
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


def test_migration_is_packaged_with_application():
    root = __import__("pathlib").Path("migrations")
    packaged = {path.name: path.read_text() for path in MIGRATIONS.glob("*.sql")}
    source = {path.name: path.read_text() for path in root.glob("*.sql")}
    assert packaged == source


def test_coolify_seed_has_catalog_without_private_data():
    seed = Path("deploy/mwm-seed.db")
    assert seed.is_file()
    db = sqlite3.connect(seed)
    try:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT count(*) FROM movies").fetchone()[0] == 1122
        assert db.execute("SELECT count(*) FROM movies WHERE adult_content=1").fetchone()[0] == 0
        private_tables = (
            "analytics_events",
            "audit_log",
            "comment_reports",
            "comments",
            "follows",
            "members",
            "newsletter_deliveries",
            "newsletter_subscribers",
            "notifications",
            "password_reset_tokens",
            "rsvps",
            "sessions",
        )
        for table in private_tables:
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    finally:
        db.close()


def test_docker_entrypoint_seeds_only_a_missing_database():
    dockerfile = Path("Dockerfile").read_text()
    entrypoint = Path("deploy/docker-entrypoint.sh").read_text()
    assert "COPY deploy/mwm-seed.db /app/seed/mwm.db" in dockerfile
    assert 'if [ ! -e "$database_path" ]; then' in entrypoint
