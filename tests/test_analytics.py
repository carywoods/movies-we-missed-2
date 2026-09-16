from mwm.auth import create_session, hash_password
from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request


def test_public_page_movie_and_genre_views_are_first_party(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "analytics.db"))
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    movie = db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('view','Viewed Movie','viewed-movie','high')").lastrowid
    genre = db.execute("SELECT id FROM genres WHERE slug='drama'").fetchone()[0]
    db.execute("INSERT INTO movie_genres(movie_id,genre_id) VALUES (?,?)", (movie, genre))
    db.close()
    request(app, "/")
    request(app, "/movies/viewed-movie")
    request(app, "/genres/drama")
    db = connect(app.config.database_path)
    counts = dict(db.execute("SELECT event_type,count(*) FROM analytics_events GROUP BY event_type"))
    assert counts["page_view"] == 3
    assert counts["movie_view"] == 1
    assert counts["genre_view"] == 1
    columns = [row[1] for row in db.execute("PRAGMA table_info(analytics_events)")]
    assert "ip_address" not in columns and "user_agent" not in columns
    db.close()


def test_admin_reporting_and_event_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "report.db"))
    app = create_app()
    db = connect(app.config.database_path)
    admin = db.execute("INSERT INTO members(email,password_hash,display_name,role) VALUES ('admin@example.com',?,'Admin','admin')", (hash_password("analytics admin password"),)).lastrowid
    db.close()
    token, _ = create_session(app.config, admin)
    status, _, body = request(app, "/admin/analytics", cookie=f"mwm_session={token}")
    assert status == 200
    for label in (b"PAGE VIEW", b"MOVIE VIEW", b"AMAZON CLICK", b"SPONSOR CLICK", b"MERCHANDISE CLICK"):
        assert label in body


def test_analytics_is_role_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "gate.db"))
    assert request(create_app(), "/admin/analytics")[0] == 403
