from mwm.config import Config
from mwm.db import connect
from mwm.web import create_app
from tests.web_client import request


def catalog_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "catalog.db"))
    app = create_app(Config.from_env())
    db = connect(app.config.database_path)
    movie_id = db.execute("INSERT INTO movies(stable_id,title,slug,release_year,synopsis,parsing_confidence) VALUES ('one','Moon Movie','moon-movie-1999',1999,'A trip to the moon.','high')").lastrowid
    genre_id = db.execute("SELECT id FROM genres WHERE slug='science-fiction'").fetchone()[0]
    db.execute("INSERT INTO movie_genres(movie_id,genre_id) VALUES (?,?)", (movie_id, genre_id))
    db.close()
    return app


def test_public_catalog_routes(tmp_path, monkeypatch):
    app = catalog_app(tmp_path, monkeypatch)
    for path in ["/", "/movies", "/movies/moon-movie-1999", "/genres", "/genres/science-fiction", "/collections"]:
        status, _, body = request(app, path)
        assert status == 200, path
        assert b"Movies We Missed" in body


def test_search_and_canonical(tmp_path, monkeypatch):
    app = catalog_app(tmp_path, monkeypatch)
    _, _, found = request(app, "/movies", data={"q": "Moon"})
    _, _, missing = request(app, "/movies", data={"q": "Sun"})
    assert b"Moon Movie" in found
    assert b"Moon Movie" not in missing
    assert b'rel="canonical"' in found


def test_adult_movies_are_not_public_by_default(tmp_path, monkeypatch):
    app = catalog_app(tmp_path, monkeypatch)
    db = connect(app.config.database_path)
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence,adult_content) VALUES ('adult','Private Movie','private-movie','high',1)")
    db.close()
    assert request(app, "/movies/private-movie")[0] == 404
