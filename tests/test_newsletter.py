import re

from mwm.auth import create_session, hash_password
from mwm.config import Config
from mwm.db import connect
from mwm.emailer import DisabledEmailProvider, get_email_provider
from mwm.web import create_app
from tests.web_client import request


def csrf(body):
    return re.search(rb'name="csrf" value="([^"]+)"', body).group(1).decode()


def newsletter_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "newsletter.db"))
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    admin = db.execute("INSERT INTO members(email,password_hash,display_name,role) VALUES ('admin@example.com',?,'Admin','admin')", (hash_password("admin newsletter password"),)).lastrowid
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('news','Newsletter Movie','newsletter-movie','high')")
    db.close()
    token, session = create_session(app.config, admin)
    return app, f"mwm_session={token}", session["csrf_token"]


def test_signup_and_one_click_unsubscribe(tmp_path, monkeypatch):
    app, _, _ = newsletter_fixture(tmp_path, monkeypatch)
    _, headers, form = request(app, "/newsletter")
    cookie = headers["Set-Cookie"].split(";", 1)[0]
    status, _, body = request(app, "/newsletter", "POST", {"csrf": csrf(form), "email": "reader@example.com", "cadence": "monthly"}, cookie)
    assert status == 200
    token = re.search(rb"token=([^\"]+)", body).group(1).decode()
    assert request(app, "/newsletter/unsubscribe", data={"token": token})[0] == 200
    db = connect(app.config.database_path)
    assert db.execute("SELECT status FROM newsletter_subscribers WHERE email='reader@example.com'").fetchone()[0] == "unsubscribed"
    assert db.execute("SELECT count(*) FROM analytics_events WHERE event_type='newsletter_signup'").fetchone()[0] == 1
    db.close()


def test_issue_candidates_cadence_sponsor_and_preview(tmp_path, monkeypatch):
    app, cookie, token = newsletter_fixture(tmp_path, monkeypatch)
    db = connect(app.config.database_path)
    sponsor = db.execute("SELECT id FROM sponsors WHERE is_site_primary=1").fetchone()[0]
    db.close()
    data = {"csrf": token, "subject": "September movies", "intro": "This month at the club.", "cadence": "weekly", "sponsor_id": str(sponsor), "make_default": "1"}
    status, headers, _ = request(app, "/admin/newsletter/new", "POST", data, cookie)
    assert status == 303
    preview_path = headers["Location"]
    status, _, preview = request(app, preview_path, cookie=cookie)
    assert status == 200
    assert b"Newsletter Movie" in preview and b"It&#x27;s Made By Hand" in preview
    db = connect(app.config.database_path)
    issue = db.execute("SELECT * FROM newsletter_issues").fetchone()
    assert issue["sponsor_id"] == sponsor
    assert db.execute("SELECT value FROM settings WHERE key='newsletter_cadence'").fetchone()[0] == "weekly"
    db.close()


def test_missing_email_credentials_do_not_block_operations(tmp_path, monkeypatch):
    app, cookie, token = newsletter_fixture(tmp_path, monkeypatch)
    assert isinstance(get_email_provider(app.config), DisabledEmailProvider)
    db = connect(app.config.database_path)
    issue = db.execute("INSERT INTO newsletter_issues(subject,slug) VALUES ('Ready','ready')").lastrowid
    db.close()
    status, _, body = request(app, f"/admin/newsletter/{issue}/send", "POST", {"csrf": token}, cookie)
    assert status == 200
    assert b"provider disabled" in body
