from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable

from .config import Config


ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "migrations"


def connect(path: Path | str) -> sqlite3.Connection:
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    applied = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    completed: list[str] = []
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        if migration.name in applied:
            continue
        sql = migration.read_text(encoding="utf-8")
        conn.executescript("BEGIN IMMEDIATE;\n" + sql + f"\nINSERT INTO schema_migrations(version) VALUES ('{migration.name}');\nCOMMIT;")
        completed.append(migration.name)
    return completed


def seed(conn: sqlite3.Connection, config: Config) -> None:
    settings = {
        "newsletter_cadence": "monthly",
        "site_name": "Movies We Missed",
        "site_tagline": "Find the film. Join the conversation. Meet at the movies.",
    }
    conn.executemany(
        "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO NOTHING",
        settings.items(),
    )
    genres = [
        ("Action", "action", "Movies driven by momentum, danger, and physical stakes."),
        ("Animation", "animation", "Stories brought to life frame by frame."),
        ("Comedy", "comedy", "Movies made to be enjoyed—and argued about—together."),
        ("Documentary", "documentary", "Nonfiction cinema and the conversations it opens."),
        ("Drama", "drama", "Character, conflict, and choices that stay with us."),
        ("Family", "family", "Movies selected for shared family viewing."),
        ("Independent", "independent", "Distinctive films made beyond the usual studio paths."),
        ("International", "international", "Cinema from around the world."),
        ("Kids", "kids", "Age-appropriate movies for younger film fans."),
        ("Musical", "musical", "Stories where music carries the feeling forward."),
        ("Science Fiction", "science-fiction", "Ideas, futures, worlds, and what-ifs."),
        ("Sports", "sports", "Competition, teams, athletes, and the lives around them."),
    ]
    conn.executemany(
        "INSERT INTO genres(name,slug,description) VALUES (?,?,?) ON CONFLICT(slug) DO UPDATE SET description=excluded.description",
        genres,
    )
    collections = [
        ("Black Cinema", "black-cinema", "A growing collection celebrating Black stories, filmmakers, performers, and movie culture.", 0, 0),
        ("Classics", "classics", "Movies that reward another look—or the first look we somehow missed.", 0, 0),
        ("Kids and Animation", "kids-and-animation", "Family-minded discoveries, animated favorites, and movies for younger audiences.", 0, 1),
        ("Better With a Couple of Beers", "better-with-a-couple-of-beers", "Goofy, pulpy, cultish, action-heavy, and cheerfully low-stakes movie-night choices.", 0, 0),
        ("Adult & Erotic Cinema", "adult-erotic-cinema", "Adult-oriented cinema presented with clear labeling and without stigma.", 1, 0),
    ]
    conn.executemany(
        "INSERT INTO collections(name,slug,description,adult_only,family_safe) VALUES (?,?,?,?,?) "
        "ON CONFLICT(slug) DO UPDATE SET description=excluded.description,adult_only=excluded.adult_only,family_safe=excluded.family_safe",
        collections,
    )
    conn.execute(
        "INSERT INTO sponsors(name,label,destination_url,paid,active,is_site_primary,notes) "
        "SELECT ?,?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM sponsors WHERE is_site_primary=1)",
        ("It's Made By Hand", "Primary sponsor", config.imbh_base_url, 0, 1, 1, "Owned sister property and default site/newsletter sponsor."),
    )
    conn.execute(
        "INSERT INTO merchandise(movie_id,merchant,product_type,display_label,destination_url,match_type,audience,priority,generated_by) "
        "SELECT NULL,'Amazon','movie-night','Popcorn for movie night','https://www.amazon.com/s?k=movie+night+popcorn','fallback','general',0,'deterministic_rule' "
        "WHERE NOT EXISTS (SELECT 1 FROM merchandise WHERE movie_id IS NULL AND match_type='fallback')"
    )


def initialize(config: Config) -> list[str]:
    conn = connect(config.database_path)
    try:
        applied = migrate(conn)
        seed(conn, config)
        conn.execute("DELETE FROM sessions WHERE expires_at < CURRENT_TIMESTAMP")
        return applied
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, sql: str, params: Iterable[object] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)))

