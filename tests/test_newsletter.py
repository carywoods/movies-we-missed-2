import hashlib
import re

from mwm.auth import create_session, hash_password
from mwm.config import Config
from mwm.db import connect
from mwm.emailer import DisabledEmailProvider, EmailMessage, SMTPEmailProvider, get_email_provider
from mwm.web import create_app
from tests.web_client import request


def csrf(body):
    return re.search(rb'name="csrf" value="([^"]+)"', body).group(1).decode()


class CapturingEmailProvider:
    name = "capturing"

    def __init__(self):
        self.messages = []

    def send(self, message):
        self.messages.append(message)
        return True


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
    assert request(app, "/newsletter/unsubscribe", "POST", {"token": token})[0] == 200
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
    assert f'/out/sponsor/{sponsor}?placement=newsletter'.encode() in preview
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


def test_send_delivers_curated_content_and_rotates_personal_tokens(tmp_path, monkeypatch):
    app, cookie, csrf_token = newsletter_fixture(tmp_path, monkeypatch)
    db = connect(app.config.database_path)
    movie_id = db.execute("SELECT id FROM movies WHERE slug='newsletter-movie'").fetchone()[0]
    db.execute(
        "INSERT INTO screenings(movie_id,slug,title,starts_at,venue_name,address_line1,city,region,postal_code,status) VALUES (?,?,?,datetime('now','+1 day'),?,?,?,?,?,'announced')",
        (movie_id, "newsletter-screening", "Newsletter Screening", "Club Cinema", "1 Main St", "Indianapolis", "IN", "46204"),
    )
    sponsor = db.execute("SELECT id FROM sponsors WHERE is_site_primary=1").fetchone()[0]
    old_tokens = {
        "reader-one@example.com": "old-token-one",
        "reader-two@example.com": "old-token-two",
    }
    for email, raw_token in old_tokens.items():
        db.execute(
            "INSERT INTO newsletter_subscribers(email,status,cadence,unsubscribe_token_hash) VALUES (?,'active','monthly',?)",
            (email, hashlib.sha256(raw_token.encode()).hexdigest()),
        )
    db.close()

    data = {
        "csrf": csrf_token,
        "subject": "Complete issue",
        "intro": "Everything in one email.",
        "cadence": "monthly",
        "sponsor_id": str(sponsor),
    }
    status, headers, _ = request(app, "/admin/newsletter/new", "POST", data, cookie)
    assert status == 303
    preview_path = headers["Location"]
    status, _, preview = request(app, preview_path, cookie=cookie)
    assert status == 200
    sponsor_link = f'/out/sponsor/{sponsor}?placement=newsletter'
    assert b"Newsletter Movie" in preview and b"Newsletter Screening" in preview
    assert sponsor_link.encode() in preview

    provider = CapturingEmailProvider()
    monkeypatch.setattr("mwm.newsletter.get_email_provider", lambda config: provider)
    send_path = preview_path.removesuffix("/preview") + "/send"
    status, _, _ = request(app, send_path, "POST", {"csrf": csrf_token}, cookie)
    assert status == 303
    messages = {message.to: message for message in provider.messages}
    assert set(messages) == set(old_tokens)

    tokens = {}
    for email, message in messages.items():
        assert "Newsletter Movie" in message.html
        assert "Newsletter Screening" in message.html
        assert sponsor_link in message.html
        match = re.search(r'href="([^"]+/newsletter/unsubscribe\?token=([^"]+))"', message.html)
        assert match
        assert match.group(1).startswith("http://localhost:8080/")
        tokens[email] = match.group(2)
        assert message.headers["List-Unsubscribe"] == f"<{match.group(1)}>"
        assert message.headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert len(set(tokens.values())) == 2

    db = connect(app.config.database_path)
    rows = db.execute("SELECT email,unsubscribe_token_hash FROM newsletter_subscribers").fetchall()
    hashes_after = {row["email"]: row["unsubscribe_token_hash"] for row in rows}
    for email, old_token in old_tokens.items():
        assert hashes_after[email] != hashlib.sha256(old_token.encode()).hexdigest()
        assert hashes_after[email] == hashlib.sha256(tokens[email].encode()).hexdigest()
    assert db.execute("SELECT count(*) FROM newsletter_deliveries WHERE status='sent'").fetchone()[0] == 2
    issue_status = db.execute("SELECT status,send_count FROM newsletter_issues").fetchone()
    assert tuple(issue_status) == ("sent", 2)
    db.close()
    status, _, body = request(app, "/newsletter/unsubscribe", data={"token": old_tokens["reader-one@example.com"]})
    assert status == 404
    assert request(app, send_path, "POST", {"csrf": csrf_token}, cookie)[0] == 409
    assert len(provider.messages) == 2
    assert b"invalid or expired" in body.lower()
    assert request(app, "/newsletter/unsubscribe", data={"token": tokens["reader-one@example.com"]})[0] == 200
    db = connect(app.config.database_path)
    statuses = dict(db.execute("SELECT email,status FROM newsletter_subscribers"))
    db.close()
    assert statuses == {"reader-one@example.com": "unsubscribed", "reader-two@example.com": "active"}


def test_newsletter_sponsor_click_logs_imbh_event(tmp_path, monkeypatch):
    app, _, _ = newsletter_fixture(tmp_path, monkeypatch)
    db = connect(app.config.database_path)
    sponsor = db.execute("SELECT id FROM sponsors WHERE is_site_primary=1").fetchone()[0]
    db.close()
    status, _, _ = request(app, f"/out/sponsor/{sponsor}", data={"placement": "newsletter"})
    assert status == 302
    db = connect(app.config.database_path)
    events = dict(db.execute("SELECT event_type,count(*) FROM analytics_events WHERE source='newsletter' GROUP BY event_type"))
    db.close()
    assert events["sponsor_click"] == 1
    assert events["imbh_click"] == 1


def test_smtp_provider_builds_html_message_with_headers(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("EMAIL_FROM", "Movies We Missed <club@example.com>")
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.example", 587, 20)
            self.started_tls = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def starttls(self, context):
            self.started_tls = True

        def login(self, username, password):
            assert self.started_tls
            assert (username, password) == ("mailer", "secret")

        def send_message(self, message):
            sent.append(message)

    monkeypatch.setattr("mwm.emailer.smtplib.SMTP", FakeSMTP)
    provider = get_email_provider(Config.from_env())
    assert isinstance(provider, SMTPEmailProvider)
    assert provider.send(EmailMessage("reader@example.com", "Issue", "<h1>Hello</h1>", {"List-Unsubscribe": "<https://movies.example/unsubscribe>"}))
    assert sent[0]["To"] == "reader@example.com"
    assert sent[0]["List-Unsubscribe"] == "<https://movies.example/unsubscribe>"
    assert "<h1>Hello</h1>" in sent[0].get_body(preferencelist=("html",)).get_content()
