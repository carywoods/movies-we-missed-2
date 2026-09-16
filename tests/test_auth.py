import re

from mwm.auth import hash_password, verify_password
from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request


def cookie_value(headers):
    return headers["Set-Cookie"].split(";", 1)[0]


def csrf(body):
    return re.search(rb'name="csrf" value="([^"]+)"', body).group(1).decode()


def test_password_hashing():
    encoded = hash_password("a long passphrase")
    assert "a long passphrase" not in encoded
    assert verify_password("a long passphrase", encoded)
    assert not verify_password("wrong passphrase", encoded)


def test_registration_session_profile_and_logout(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "auth.db"))
    app = create_app(Config.from_env())
    status, headers, body = request(app, "/register")
    anonymous_cookie = cookie_value(headers)

    status, headers, _ = request(
        app,
        "/register",
        "POST",
        {"csrf": csrf(body), "display_name": "Movie Fan", "email": "fan@example.com", "password": "correct horse battery"},
        anonymous_cookie,
    )
    assert status == 303
    member_cookie = cookie_value(headers)
    status, _, profile = request(app, "/profile", cookie=member_cookie)
    assert status == 200
    assert b"Movie Fan" in profile

    status, headers, _ = request(app, "/logout", "POST", {"csrf": csrf(profile)}, member_cookie)
    assert status == 303
    assert "Max-Age=0" in headers["Set-Cookie"]


def test_login_and_csrf_rejection(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "login.db"))
    app = create_app()
    db = connect(app.config.database_path)
    db.execute("INSERT INTO members(email,password_hash,display_name) VALUES (?,?,?)", ("member@example.com", hash_password("very secure password"), "Member"))
    db.close()
    _, headers, body = request(app, "/login")
    cookie = cookie_value(headers)
    assert request(app, "/login", "POST", {"csrf": "bad", "email": "member@example.com", "password": "very secure password"}, cookie)[0] == 403
    status, headers, _ = request(app, "/login", "POST", {"csrf": csrf(body), "email": "member@example.com", "password": "very secure password"}, cookie)
    assert status == 303
    assert "HttpOnly" in headers["Set-Cookie"]
    assert "SameSite=Lax" in headers["Set-Cookie"]


def test_no_person_following_schema(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "scope.db"))
    app = create_app()
    sql = connect(app.config.database_path).execute("SELECT sql FROM sqlite_master WHERE name='follows'").fetchone()[0]
    assert "'movie','genre'" in sql
    assert "user" not in sql and "member'" not in sql
