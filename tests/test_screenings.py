from mwm.auth import create_session, hash_password
from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request


def screening_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "screenings.db"))
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    admin = db.execute("INSERT INTO members(email,password_hash,display_name,role) VALUES ('admin@example.com',?,'Admin','admin')", (hash_password("administrator password"),)).lastrowid
    member = db.execute("INSERT INTO members(email,password_hash,display_name) VALUES ('member@example.com',?,'Member')", (hash_password("member secure password"),)).lastrowid
    second = db.execute("INSERT INTO members(email,password_hash,display_name) VALUES ('second@example.com',?,'Second')", (hash_password("second secure password"),)).lastrowid
    movie = db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('screened','Screened Movie','screened-movie','high')").lastrowid
    db.close()
    sessions = []
    for identifier in (admin, member, second):
        token, session = create_session(app.config, identifier)
        sessions.append((f"mwm_session={token}", session["csrf_token"]))
    return app, movie, sessions


def create_screening(app, movie, admin):
    cookie, csrf = admin
    data = {"csrf": csrf, "movie_id": str(movie), "title": "Club Night", "description": "A conversation after the film.", "starts_at": "2099-10-15 19:00:00", "ends_at": "2099-10-15 22:00:00", "status": "rsvp_open", "venue_name": "Community Cinema", "address_line1": "123 Main Street", "city": "Indianapolis", "region": "IN", "postal_code": "46201", "capacity": "1", "cost_label": "Free"}
    assert request(app, "/admin/screenings/new", "POST", data, cookie)[0] == 303
    db = connect(app.config.database_path)
    screening = db.execute("SELECT * FROM screenings").fetchone()
    db.close()
    return screening


def test_admin_creation_and_public_routes(tmp_path, monkeypatch):
    app, movie, sessions = screening_fixture(tmp_path, monkeypatch)
    screening = create_screening(app, movie, sessions[0])
    assert request(app, "/screenings")[0] == 200
    status, _, body = request(app, f'/screenings/{screening["slug"]}')
    assert status == 200
    assert b"Community Cinema" in body and b"Screened Movie" in body
    assert request(app, f'/screenings/{screening["slug"]}/comments')[0] == 200


def test_capacity_waitlist_and_cancel(tmp_path, monkeypatch):
    app, movie, sessions = screening_fixture(tmp_path, monkeypatch)
    screening = create_screening(app, movie, sessions[0])
    first_cookie, first_csrf = sessions[1]
    second_cookie, second_csrf = sessions[2]
    path = f'/screenings/{screening["slug"]}/rsvp'
    assert request(app, path, "POST", {"csrf": first_csrf, "guest_count": "0"}, first_cookie)[0] == 303
    assert request(app, path, "POST", {"csrf": second_csrf, "guest_count": "0"}, second_cookie)[0] == 303
    db = connect(app.config.database_path)
    assert [r[0] for r in db.execute("SELECT status FROM rsvps ORDER BY id")] == ["going", "waitlisted"]
    db.close()
    cancel = f'/screenings/{screening["slug"]}/cancel-rsvp'
    assert request(app, cancel, "POST", {"csrf": first_csrf}, first_cookie)[0] == 303


def test_screening_admin_is_role_gated(tmp_path, monkeypatch):
    app, _, sessions = screening_fixture(tmp_path, monkeypatch)
    assert request(app, "/admin/screenings", cookie=sessions[1][0])[0] == 403
    assert request(app, "/admin/screenings", cookie=sessions[0][0])[0] == 200
