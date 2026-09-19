from pathlib import Path

from mwm.config import Config
from mwm.db import connect, initialize


def test_migrations_and_seed_are_idempotent(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "mwm.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    config = Config.from_env()

    assert initialize(config) == ["001_initial.sql", "002_public_story_taxonomy.sql", "003_newsletter_deliveries.sql", "004_password_resets.sql"]
    assert initialize(config) == []

    connection = connect(database)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("SELECT count(*) FROM genres").fetchone()[0] == 23
        assert connection.execute("SELECT adult_only FROM collections WHERE slug='erotica'").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM collections WHERE slug='lgbq-stories'").fetchone()[0] == 1
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


def test_story_taxonomy_migration_backfills_existing_imports(tmp_path: Path, monkeypatch) -> None:
    database = tmp_path / "upgrade.db"
    monkeypatch.setenv("DATABASE_PATH", str(database))
    connection = connect(database)
    connection.executescript(Path("migrations/001_initial.sql").read_text())
    connection.execute("INSERT INTO schema_migrations(version) VALUES ('001_initial.sql')")
    connection.execute(
        "INSERT INTO collections(name,slug,description,adult_only) VALUES ('Adult & Erotic Cinema','adult-erotic-cinema','Legacy label',1)"
    )
    categories = (("soft", 1), ("new", 0), ("comics", 0))
    for number, (category, adult_content) in enumerate(categories, 1):
        movie_id = connection.execute(
            "INSERT INTO movies(stable_id,title,slug,parsing_confidence,adult_content) VALUES (?,?,?,?,?)",
            (f"legacy-{number}", f"Legacy {category}", f"legacy-{category}", "high", adult_content),
        ).lastrowid
        connection.execute(
            "INSERT INTO movie_sources(movie_id,source_fingerprint,raw_filename,source_category) VALUES (?,?,?,?)",
            (movie_id, f"source-{number}", f"{category}.mkv", category),
        )
    connection.close()

    initialize(Config.from_env())
    connection = connect(database)
    try:
        assert connection.execute("SELECT adult_content FROM movies WHERE slug='legacy-soft'").fetchone()[0] == 0
        assert connection.execute("SELECT adult_only FROM collections WHERE slug='erotica'").fetchone()[0] == 0
        mapped = {
            row[0]
            for row in connection.execute(
                "SELECT c.slug FROM movie_collections mc JOIN collections c ON c.id=mc.collection_id"
            )
        }
        assert {"recent-additions", "comics-graphic-novels"} <= mapped
    finally:
        connection.close()
