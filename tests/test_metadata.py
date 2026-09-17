from mwm.config import Config
from mwm.db import connect, initialize
from mwm.enrichment import enqueue_metadata, work_metadata_one
from mwm.metadata import MovieMetadata, TmdbClient


def test_tmdb_lookup_matches_title_year_and_maps_artwork_and_credits():
    client = TmdbClient("test-token")
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params))
        if path == "/search/movie":
            return {
                "results": [
                    {
                        "id": 1,
                        "title": "Moon Movie",
                        "original_title": "Moon Movie",
                        "release_date": "2004-01-01",
                    },
                    {
                        "id": 2,
                        "title": "Moon Movie",
                        "original_title": "Moon Movie",
                        "release_date": "1999-06-11",
                        "poster_path": "/search.jpg",
                    },
                ]
            }
        assert path == "/movie/2"
        return {
            "id": 2,
            "title": "Moon Movie",
            "release_date": "1999-06-11",
            "overview": "A trip beyond the atmosphere.",
            "poster_path": "/poster.jpg",
            "genres": [{"name": "Science Fiction"}, {"name": "Adventure"}],
            "credits": {
                "crew": [{"job": "Director", "name": "Ada Director"}],
                "cast": [
                    {"order": 1, "name": "Second Actor"},
                    {"order": 0, "name": "First Actor"},
                ],
            },
            "external_ids": {
                "imdb_id": "tt1234567",
                "wikidata_id": "Q123",
            },
        }

    client._get = fake_get
    metadata = client.lookup("Moon Movie", 1999)

    assert metadata is not None
    assert metadata.provider_id == 2
    assert metadata.poster_url == "https://image.tmdb.org/t/p/w500/poster.jpg"
    assert metadata.director == "Ada Director"
    assert metadata.cast_text == "First Actor, Second Actor"
    assert metadata.genres == ("Science Fiction", "Adventure")
    assert metadata.external_ids == {
        "tmdb": 2,
        "imdb": "tt1234567",
        "wikidata": "Q123",
    }
    assert calls[0][1]["primary_release_year"] == 1999
    assert calls[1][1]["append_to_response"] == "credits,external_ids"


def test_metadata_job_populates_movie_and_genres(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "metadata.db"))
    monkeypatch.setenv("METADATA_PROVIDER", "tmdb")
    monkeypatch.setenv("METADATA_API_KEY", "test-token")
    config = Config.from_env()
    initialize(config)
    db = connect(config.database_path)
    movie_id = db.execute(
        "INSERT INTO movies(stable_id,title,slug,release_year,parsing_confidence) "
        "VALUES ('metadata-movie','Moon Movie','moon-movie',1999,'high')"
    ).lastrowid
    db.close()

    assert enqueue_metadata(config) == 1

    class FakeClient:
        def lookup(self, title, year):
            assert (title, year) == ("Moon Movie", 1999)
            return MovieMetadata(
                provider_id=2,
                title="Moon Movie",
                release_year=1999,
                synopsis="A trip beyond the atmosphere.",
                poster_url="https://image.tmdb.org/t/p/w500/poster.jpg",
                director="Ada Director",
                cast_text="First Actor, Second Actor",
                genres=("Science Fiction", "Adventure"),
                external_ids={"tmdb": 2, "imdb": "tt1234567"},
                confidence=1.0,
            )

    assert work_metadata_one(config, FakeClient()) is True
    assert work_metadata_one(config, FakeClient()) is False

    db = connect(config.database_path)
    movie = db.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
    assert movie["poster_url"].endswith("/poster.jpg")
    assert movie["synopsis"] == "A trip beyond the atmosphere."
    assert movie["director"] == "Ada Director"
    assert movie["cast_text"] == "First Actor, Second Actor"
    assert movie["enrichment_state"] == "enriched"
    genres = {
        row[0]
        for row in db.execute(
            "SELECT g.name FROM genres g JOIN movie_genres mg ON mg.genre_id=g.id "
            "WHERE mg.movie_id=?",
            (movie_id,),
        )
    }
    assert genres == {"Science Fiction", "Adventure"}
    job = db.execute("SELECT status,confidence FROM jobs").fetchone()
    assert tuple(job) == ("complete", 1.0)
    db.close()


def test_metadata_job_marks_ambiguous_match_for_review(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "review.db"))
    monkeypatch.setenv("METADATA_PROVIDER", "tmdb")
    monkeypatch.setenv("METADATA_API_KEY", "test-token")
    config = Config.from_env()
    initialize(config)
    db = connect(config.database_path)
    db.execute(
        "INSERT INTO movies(stable_id,title,slug,parsing_confidence) "
        "VALUES ('ambiguous','Unknown Movie','unknown-movie','medium')"
    )
    db.close()
    assert enqueue_metadata(config) == 1

    class NoMatchClient:
        def lookup(self, title, year):
            return None

    assert work_metadata_one(config, NoMatchClient()) is True
    db = connect(config.database_path)
    assert db.execute("SELECT enrichment_state FROM movies").fetchone()[0] == "review"
    assert db.execute("SELECT status FROM jobs").fetchone()[0] == "review"
    db.close()
