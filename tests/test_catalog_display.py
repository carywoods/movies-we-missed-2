import re

from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request

POSTER = "https://image.tmdb.org/t/p/w500/poster.jpg"


def display_fixture(tmp_path, monkeypatch, provider="tmdb"):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "display.db"))
    monkeypatch.setenv("METADATA_PROVIDER", provider)
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    movie = db.execute(
        "INSERT INTO movies(stable_id,title,slug,release_year,synopsis,poster_url,director,cast_text,external_ids_json,parsing_confidence,enrichment_state) "
        "VALUES ('display-movie','Clean Title','clean-title',1984,'A cleaned synopsis.',?,'Ada Director','First Actor, Second Actor',?, 'high','enriched')",
        (POSTER, '{"imdb": "tt1234567", "tmdb": 101}'),
    ).lastrowid
    genre = db.execute("SELECT id FROM genres WHERE slug='comedy'").fetchone()[0]
    db.execute("INSERT INTO movie_genres(movie_id,genre_id,source,confidence) VALUES (?,?,'tmdb',1.0)", (movie, genre))
    db.close()
    return app


def test_catalog_cards_show_artwork_and_credits(tmp_path, monkeypatch):
    app = display_fixture(tmp_path, monkeypatch)
    status, _, body = request(app, "/movies")
    assert status == 200
    assert POSTER.encode() in body
    assert b"Directed by Ada Director" in body


def test_movie_detail_shows_metadata_and_links(tmp_path, monkeypatch):
    app = display_fixture(tmp_path, monkeypatch)
    status, _, body = request(app, "/movies/clean-title")
    assert status == 200
    for needle in (
        POSTER.encode(),
        b"Directed by Ada Director",
        b"Starring First Actor, Second Actor",
        b"https://www.imdb.com/title/tt1234567/",
        b"https://www.themoviedb.org/movie/101",
        b'"@type":"Movie"',
        b"not endorsed or certified by TMDB",
        b'property="og:image" content="' + POSTER.encode(),
    ):
        assert needle in body, needle


def test_attribution_is_omitted_without_the_tmdb_provider(tmp_path, monkeypatch):
    app = display_fixture(tmp_path, monkeypatch, provider="disabled")
    _, _, body = request(app, "/movies/clean-title")
    assert b"not endorsed or certified by TMDB" not in body


def test_fallback_tile_for_missing_artwork(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "plain.db"))
    monkeypatch.setenv("METADATA_PROVIDER", "disabled")
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('plain','Plain Movie','plain-movie','high')")
    db.close()
    _, _, body = request(app, "/movies")
    assert b"Plain Movie" in body
    assert b"image.tmdb.org" not in body


def test_card_synopsis_is_trimmed_to_a_teaser(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "teaser.db"))
    monkeypatch.setenv("METADATA_PROVIDER", "disabled")
    app = create_app(Config.from_env())
    long_text = " ".join(f"word{index}" for index in range(80))
    db = connect(app.config.database_path)
    db.execute(
        "INSERT INTO movies(stable_id,title,slug,synopsis,parsing_confidence) "
        "VALUES ('teaser','Long Synopsis Movie','long-synopsis-movie',?,'high')",
        (long_text,),
    )
    db.close()
    _, _, body = request(app, "/movies")
    text = body.decode()
    assert "Long Synopsis Movie" in text
    assert "…" in text
    assert "word79" not in text
    assert 'class="summary"' in text


def test_home_shows_only_artwork_ready_movies(tmp_path, monkeypatch):
    app = display_fixture(tmp_path, monkeypatch)
    db = connect(app.config.database_path)
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('noposter','No Poster Movie','no-poster-movie','high')")
    db.close()
    _, _, body = request(app, "/")
    text = body.decode()
    assert "Clean Title" in text
    assert "No Poster Movie" not in text


def test_home_renders_a_carousel_with_controls(tmp_path, monkeypatch):
    app = display_fixture(tmp_path, monkeypatch)
    _, _, body = request(app, "/")
    text = body.decode()
    assert 'class="carousel"' in text
    assert 'data-carousel="recent-track"' in text
    assert 'data-dir="prev"' in text and 'data-dir="next"' in text
    assert '<article class="card">' in text


def test_cards_stack_metadata_under_the_poster(tmp_path, monkeypatch):
    app = display_fixture(tmp_path, monkeypatch)
    _, _, body = request(app, "/movies")
    text = body.decode()
    card = text[text.index('<article class="card">'):]
    card = card[:card.index("</article>")]
    assert card.index("poster-link") < card.index("card-body") < card.index("<h3>")
    assert "Directed by Ada Director" in card
    assert 'class="summary"' in card


def test_carousel_script_is_served_and_linked(tmp_path, monkeypatch):
    app = display_fixture(tmp_path, monkeypatch)
    status, headers, body = request(app, "/static/site.js")
    assert status == 200
    assert headers["Content-Type"].startswith("application/javascript")
    assert b"data-carousel" in body
    _, _, page_body = request(app, "/")
    assert b'<script src="/static/site.js" defer></script>' in page_body
