import sqlite3

from mwm.auth import create_session, hash_password
from mwm.backup import backup_database
from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request


def admin_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "admin.db"))
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    admin = db.execute("INSERT INTO members(email,password_hash,display_name,role) VALUES ('admin@example.com',?,'Admin','admin')", (hash_password("operations admin password"),)).lastrowid
    movie = db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('admin-movie','Admin Movie','admin-movie','high')").lastrowid
    genre = db.execute("SELECT id FROM genres WHERE slug='drama'").fetchone()[0]
    collection = db.execute("SELECT id FROM collections WHERE slug='classics'").fetchone()[0]
    db.close()
    token, session = create_session(app.config, admin)
    return app, f"mwm_session={token}", session["csrf_token"], movie, genre, collection


def test_operator_dashboard_and_domain_pages(tmp_path, monkeypatch):
    app, cookie, _, _, _, _ = admin_fixture(tmp_path, monkeypatch)
    for path in ("/admin", "/admin/movies", "/admin/import-review", "/admin/screenings", "/admin/merchandise", "/admin/comments", "/admin/newsletter", "/admin/sponsors", "/admin/analytics"):
        assert request(app, path, cookie=cookie)[0] == 200, path


def test_movie_edit_and_classification(tmp_path, monkeypatch):
    app, cookie, csrf, movie, genre, collection = admin_fixture(tmp_path, monkeypatch)
    data = {"csrf": csrf, "title": "Edited Movie", "release_year": "2001", "synopsis": "Edited synopsis", "published": "1", "featured": "1", f"genre_{genre}": "1", f"collection_{collection}": "1"}
    assert request(app, f"/admin/movies/{movie}/edit", "POST", data, cookie)[0] == 303
    db = connect(app.config.database_path)
    updated = db.execute("SELECT title,featured FROM movies WHERE id=?", (movie,)).fetchone()
    assert tuple(updated) == ("Edited Movie", 1)
    assert db.execute("SELECT count(*) FROM movie_genres WHERE movie_id=? AND genre_id=?", (movie, genre)).fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM movie_collections WHERE movie_id=? AND collection_id=?", (movie, collection)).fetchone()[0] == 1
    db.close()


def test_add_merchandise_and_sponsor(tmp_path, monkeypatch):
    app, cookie, csrf, movie, _, _ = admin_fixture(tmp_path, monkeypatch)
    merchandise = {"csrf": csrf, "movie_id": str(movie), "merchant": "Local Shop", "display_label": "Movie poster", "product_type": "poster", "destination_url": "https://shop.example/poster", "match_type": "specific"}
    assert request(app, "/admin/merchandise", "POST", merchandise, cookie)[0] == 303
    sponsor = {"csrf": csrf, "name": "Paid Partner", "destination_url": "https://partner.example", "label": "Sponsored by", "paid": "1"}
    assert request(app, "/admin/sponsors", "POST", sponsor, cookie)[0] == 303
    db = connect(app.config.database_path)
    assert db.execute("SELECT count(*) FROM merchandise WHERE merchant='Local Shop'").fetchone()[0] == 1
    assert db.execute("SELECT paid FROM sponsors WHERE name='Paid Partner'").fetchone()[0] == 1
    db.close()


def test_consistent_sqlite_backup(tmp_path, monkeypatch):
    app, _, _, _, _, _ = admin_fixture(tmp_path, monkeypatch)
    target = backup_database(app.config, tmp_path / "snapshot.db")
    assert target.exists()
    restored = sqlite3.connect(target)
    assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert restored.execute("SELECT count(*) FROM movies").fetchone()[0] == 1
    restored.close()


def test_admin_is_role_gated(tmp_path, monkeypatch):
    app, _, _, _, _, _ = admin_fixture(tmp_path, monkeypatch)
    assert request(app, "/admin")[0] == 403
