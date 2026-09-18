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


def test_login_is_throttled_after_repeated_failures(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "throttle.db"))
    app = create_app()
    db = connect(app.config.database_path)
    db.execute("INSERT INTO members(email,password_hash,display_name) VALUES (?,?,?)", ("member@example.com", hash_password("very secure password"), "Member"))
    db.close()
    _, headers, body = request(app, "/login")
    cookie = cookie_value(headers)
    invalid = {"csrf": csrf(body), "email": "member@example.com", "password": "wrong password"}
    for _ in range(5):
        assert request(app, "/login", "POST", invalid, cookie)[0] == 200
    assert request(app, "/login", "POST", invalid, cookie)[0] == 429


def test_password_reset_sends_single_use_link(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "reset.db"))
    monkeypatch.setenv("SITE_URL", "https://movies.example")
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    db.execute("INSERT INTO members(email,password_hash,display_name) VALUES (?,?,?)", ("member@example.com", hash_password("old secure password"), "Member"))
    db.close()

    class CapturingProvider:
        name = "capturing"

        def __init__(self):
            self.messages = []

        def send(self, message):
            self.messages.append(message)
            return True

    provider = CapturingProvider()
    monkeypatch.setattr("mwm.member.get_email_provider", lambda config: provider)
    _, headers, form = request(app, "/forgot-password")
    cookie = cookie_value(headers)
    status, _, body = request(app, "/forgot-password", "POST", {"csrf": csrf(form), "email": "member@example.com"}, cookie)
    assert status == 200 and b"If an active account" in body
    assert len(provider.messages) == 1
    token = re.search(r"token=([^\"]+)", provider.messages[0].html).group(1)

    status, _, reset_form = request(app, "/reset-password", data={"token": token}, cookie=cookie)
    assert status == 200
    status, headers, _ = request(app, "/reset-password", "POST", {"csrf": csrf(reset_form), "token": token, "password": "new secure password"}, cookie)
    assert status == 303 and headers["Location"] == "/login"
    db = connect(app.config.database_path)
    password_hash = db.execute("SELECT password_hash FROM members WHERE email='member@example.com'").fetchone()[0]
    assert verify_password("new secure password", password_hash)
    assert db.execute("SELECT used_at IS NOT NULL FROM password_reset_tokens").fetchone()[0] == 1
    db.close()
    assert request(app, "/reset-password", "POST", {"csrf": csrf(reset_form), "token": token, "password": "another secure password"}, cookie)[0] == 400
