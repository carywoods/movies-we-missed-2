import re

from mwm.auth import create_session, hash_password
from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request


def setup_member_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "interest.db"))
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    member_id = db.execute("INSERT INTO members(email,password_hash,display_name) VALUES ('fan@example.com',?,'Fan')", (hash_password("very long password"),)).lastrowid
    movie_id = db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('m1','Interest Movie','interest-movie','high')").lastrowid
    genre_id = db.execute("SELECT id FROM genres WHERE slug='drama'").fetchone()[0]
    db.execute("INSERT INTO movie_genres(movie_id,genre_id) VALUES (?,?)", (movie_id, genre_id))
    db.close()
    token, session = create_session(app.config, member_id)
    return app, f"mwm_session={token}", session["csrf_token"], movie_id, genre_id


def test_follow_unfollow_movie_and_genre(tmp_path, monkeypatch):
    app, cookie, csrf, movie_id, genre_id = setup_member_app(tmp_path, monkeypatch)
    assert request(app, f"/movies/{movie_id}/follow", "POST", {"csrf": csrf}, cookie)[0] == 303
    assert request(app, f"/genres/{genre_id}/follow", "POST", {"csrf": csrf}, cookie)[0] == 303
    status, _, feed = request(app, "/discover", cookie=cookie)
    assert status == 200
    assert b"Interest Movie" in feed and b"Drama" in feed
    assert request(app, f"/movies/{movie_id}/unfollow", "POST", {"csrf": csrf}, cookie)[0] == 303
    db = connect(app.config.database_path)
    assert db.execute("SELECT count(*) FROM follows WHERE target_type='movie'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM follows WHERE target_type='genre'").fetchone()[0] == 1
    db.close()


def test_follows_require_member_and_csrf(tmp_path, monkeypatch):
    app, cookie, _, movie_id, _ = setup_member_app(tmp_path, monkeypatch)
    assert request(app, f"/movies/{movie_id}/follow", "POST", {"csrf": "bad"}, cookie)[0] == 403
    assert request(app, f"/movies/{movie_id}/follow", "POST", {})[0] == 303


def test_only_movie_and_genre_targets_are_supported(tmp_path, monkeypatch):
    app, cookie, csrf, _, _ = setup_member_app(tmp_path, monkeypatch)
    assert request(app, "/members/1/follow", "POST", {"csrf": csrf}, cookie)[0] == 404
