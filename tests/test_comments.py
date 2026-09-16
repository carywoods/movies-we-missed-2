from mwm.auth import create_session, hash_password
from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request


def comment_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "comments.db"))
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    member = db.execute("INSERT INTO members(email,password_hash,display_name) VALUES ('fan@example.com',?,'Fan')", (hash_password("secure password value"),)).lastrowid
    admin = db.execute("INSERT INTO members(email,password_hash,display_name,role) VALUES ('admin@example.com',?,'Admin','admin')", (hash_password("secure admin password"),)).lastrowid
    movie = db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('commented','Commented Movie','commented-movie','high')").lastrowid
    for number in range(6):
        db.execute("INSERT INTO comments(member_id,object_type,object_id,body) VALUES (?,?,?,?)", (member, "movie", movie, f"Comment number {number}"))
    db.close()
    member_token, member_session = create_session(app.config, member)
    admin_token, admin_session = create_session(app.config, admin)
    return app, f"mwm_session={member_token}", member_session["csrf_token"], f"mwm_session={admin_token}", admin_session["csrf_token"]


def test_five_comments_then_view_more(tmp_path, monkeypatch):
    app, cookie, _, _, _ = comment_fixture(tmp_path, monkeypatch)
    status, _, body = request(app, "/movies/commented-movie/comments", cookie=cookie)
    assert status == 200
    assert body.count(b'class="comment"') == 5
    assert b"View more comments" in body
    _, _, all_body = request(app, "/movies/commented-movie/comments", data={"all": "1"}, cookie=cookie)
    assert all_body.count(b'class="comment"') == 6


def test_add_comment_and_moderate(tmp_path, monkeypatch):
    app, cookie, csrf, admin_cookie, admin_csrf = comment_fixture(tmp_path, monkeypatch)
    assert request(app, "/movies/commented-movie/comments", "POST", {"csrf": csrf, "body": "A fresh thought"}, cookie)[0] == 303
    db = connect(app.config.database_path)
    comment_id = db.execute("SELECT id FROM comments WHERE body='A fresh thought'").fetchone()[0]
    db.close()
    assert request(app, f"/admin/comments/{comment_id}/hidden", "POST", {"csrf": admin_csrf, "note": "Review"}, admin_cookie)[0] == 303
    db = connect(app.config.database_path)
    assert db.execute("SELECT status FROM comments WHERE id=?", (comment_id,)).fetchone()[0] == "hidden"
    db.close()


def test_moderation_is_role_gated(tmp_path, monkeypatch):
    app, cookie, csrf, _, _ = comment_fixture(tmp_path, monkeypatch)
    assert request(app, "/admin/comments", cookie=cookie)[0] == 403
    assert request(app, "/admin/comments/1/hidden", "POST", {"csrf": csrf}, cookie)[0] == 403
