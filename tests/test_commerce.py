from mwm.commerce import amazon_affiliate_url
from mwm.config import Config
from mwm.db import connect
from mwm.enrichment import enqueue_missing, work_one
from mwm.web import create_app
from tests.web_client import request


def commerce_fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "commerce.db"))
    monkeypatch.setenv("AMAZON_ASSOCIATE_TAG", "movies-20")
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    for n in range(2):
        db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES (?,?,?,'high')", (f"m{n}", f"Movie {n}", f"movie-{n}"))
    fallback = db.execute("SELECT id FROM merchandise WHERE movie_id IS NULL").fetchone()[0]
    db.close()
    return app, fallback


def test_every_public_movie_resolves_an_offer(tmp_path, monkeypatch):
    app, _ = commerce_fixture(tmp_path, monkeypatch)
    db = connect(app.config.database_path)
    movie_ids = [row[0] for row in db.execute("SELECT id FROM movies WHERE published=1")]
    db.close()
    assert movie_ids
    assert all(app.offers_for_movie(movie_id) for movie_id in movie_ids)


def test_central_affiliate_redirect_and_tracking(tmp_path, monkeypatch):
    app, fallback = commerce_fixture(tmp_path, monkeypatch)
    status, headers, _ = request(app, f"/out/merchandise/{fallback}")
    assert status == 302
    assert "tag=movies-20" in headers["Location"]
    db = connect(app.config.database_path)
    assert db.execute("SELECT count(*) FROM analytics_events WHERE event_type='amazon_click'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM analytics_events WHERE event_type='merchandise_click'").fetchone()[0] == 1
    db.close()


def test_low_cost_enrichment_queue(tmp_path, monkeypatch):
    app, _ = commerce_fixture(tmp_path, monkeypatch)
    assert enqueue_missing(app.config) == 2
    assert work_one(app.config)
    db = connect(app.config.database_path)
    assert db.execute("SELECT count(*) FROM jobs WHERE status='complete'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM merchandise WHERE generated_by='deterministic_queue'").fetchone()[0] == 1
    db.close()


def test_affiliate_tag_only_applies_to_amazon():
    assert "tag=movies-20" in amazon_affiliate_url("https://www.amazon.com/s?k=popcorn", "movies-20")
    assert amazon_affiliate_url("https://example.com/product", "movies-20") == "https://example.com/product"
