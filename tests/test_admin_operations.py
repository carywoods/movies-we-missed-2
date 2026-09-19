import sqlite3
import re

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
    for path in ("/admin", "/admin/movies", "/admin/enrichment", "/admin/import-review", "/admin/screenings", "/admin/merchandise", "/admin/comments", "/admin/newsletter", "/admin/sponsors", "/admin/analytics"):
        status, _, body = request(app, path, cookie=cookie)
        assert status == 200, path
        assert body.lower().count(b"<!doctype html>") == 1, path
        assert b'href="/admin"' in body


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
    status, headers, _ = request(app, "/admin")
    assert status == 303
    assert headers["Location"] == "/login?next=/admin"
    db = connect(app.config.database_path)
    member = db.execute("INSERT INTO members(email,password_hash,display_name,role) VALUES ('fan@example.com',?,'Fan','member')", (hash_password("member password long enough"),)).lastrowid
    db.close()
    token, _ = create_session(app.config, member)
    assert request(app, "/admin", cookie=f"mwm_session={token}")[0] == 403


def test_admin_login_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "admin-login.db"))
    monkeypatch.setenv("ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "operations-grade-password")
    app = create_app(Config.from_env())

    status, headers, _ = request(app, "/admin")
    assert status == 303
    assert headers["Location"] == "/login?next=/admin"

    status, headers, _ = request(app, "/admin/login")
    assert status == 303
    assert headers["Location"] == "/login?next=/admin"

    status, headers, body = request(app, "/login", data={"next": "/admin"})
    assert status == 200
    assert b'name="next" value="/admin"' in body
    anonymous_cookie = headers["Set-Cookie"].split(";", 1)[0]
    csrf_token = re.search(rb'name="csrf" value="([^"]+)"', body).group(1).decode()
    status, headers, _ = request(
        app,
        "/login",
        "POST",
        {"csrf": csrf_token, "email": "owner@example.com", "password": "operations-grade-password", "next": "/admin"},
        anonymous_cookie,
    )
    assert status == 303
    assert headers["Location"] == "/admin"
    session_cookie = headers["Set-Cookie"].split(";", 1)[0]
    status, _, dashboard = request(app, "/admin", cookie=session_cookie)
    assert status == 200
    assert b"Operations" in dashboard
