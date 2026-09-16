from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request


def test_imbh_site_placement_and_click_tracking(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sponsor.db"))
    monkeypatch.setenv("IMBH_BASE_URL", "https://itsmadebyhand.example/shop")
    app = create_app(Config.from_env())
    status, _, body = request(app, "/")
    assert status == 200
    assert b"It&#x27;s Made By Hand" in body
    db = connect(app.config.database_path)
    sponsor_id = db.execute("SELECT id FROM sponsors WHERE is_site_primary=1").fetchone()[0]
    db.close()
    status, headers, _ = request(app, f"/out/sponsor/{sponsor_id}", data={"placement": "site-footer"})
    assert status == 302
    assert headers["Location"] == "https://itsmadebyhand.example/shop/"
    db = connect(app.config.database_path)
    assert db.execute("SELECT count(*) FROM analytics_events WHERE event_type='sponsor_click'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM analytics_events WHERE event_type='imbh_click'").fetchone()[0] == 1
    db.close()


def test_placement_can_select_an_active_sponsor(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "placement.db"))
    app = create_app()
    db = connect(app.config.database_path)
    replacement = db.execute("INSERT INTO sponsors(name,destination_url,active) VALUES ('Local Sponsor','https://example.com',1)").lastrowid
    db.execute("INSERT INTO settings(key,value) VALUES ('sponsor_placement_site-footer',?)", (str(replacement),))
    db.close()
    assert app.sponsor_for("site-footer")["name"] == "Local Sponsor"
