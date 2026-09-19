import json
from pathlib import Path

import pytest

from mwm.config import Config
from mwm.db import connect, initialize
from mwm.enrichment import (
    _lookup_with_override,
    enqueue_metadata,
    load_overrides,
    run_metadata_queue,
    work_metadata_one,
)
from mwm.metadata import MovieMetadata, TmdbClient, query_candidates

# ---------------------------------------------------------------------------
# Title normalization: real titles from the production catalog.
# ---------------------------------------------------------------------------


def test_query_candidates_for_shelf_numbered_series():
    candidates = query_candidates("01 Police Academy Comedy")
    assert candidates[0] == "Police Academy"
    assert "01 Police Academy Comedy" in candidates

    die_hard = query_candidates("02 Die Hard 2 Die Harder Bruce Willis Action")
    assert die_hard[0] == "Die Hard 2 Die Harder Bruce Willis"
    assert "02 Die Hard 2 Die Harder Bruce Willis Action" in die_hard


def test_query_candidates_keep_real_titles_intact():
    assert query_candidates("2 Fast 2 Furious")[0] == "2 Fast 2 Furious"
    assert "2 Fast 2 Furious" in query_candidates("2 Fast 2 Furious")
    assert query_candidates("21 & Over")[0] == "21 & Over"
    assert query_candidates("100 Rifles")[0] == "100 Rifles"


def test_query_candidates_strip_quality_suffixes_and_truncations():
    assert query_candidates("Annie Hall Hd")[0] == "Annie Hall"
    assert query_candidates("The Big Sleep Sd")[0] == "The Big Sleep"
    assert query_candidates("The Shawshank Redemption1080P")[0] == "The Shawshank Redemption"
    assert query_candidates("Garden State 720Phdtv")[0] == "Garden State"
    assert query_candidates("04 Police Academy 4 Citizens On Patrol Comed")[0] == (
        "Police Academy 4 Citizens On Patrol"
    )
    assert query_candidates("Twilight1")[0] == "Twilight"


def test_query_candidates_leave_unusable_rows_alone():
    assert query_candidates("128 0034") == ["128 0034"]
    assert query_candidates("622")[0] == "622"


# ---------------------------------------------------------------------------
# Scoring ladder.
# ---------------------------------------------------------------------------


def make_client(results):
    client = TmdbClient("test-token")
    calls = []

    def fake_get(path, params=None):
        calls.append((path, params or {}))
        if path == "/search/movie":
            return {"results": results}
        return details_for(results, path)

    client._get = fake_get  # type: ignore[method-assign]
    return client, calls


def details_for(results, path):
    provider_id = int(path.split("/")[-1])
    base = next((item for item in results if int(item["id"]) == provider_id), {})
    return {
        "id": provider_id,
        "title": base.get("title"),
        "release_date": base.get("release_date"),
        "overview": "Synopsis text.",
        "poster_path": "/poster.jpg",
        "genres": [{"name": "Comedy"}, {"name": "Adventure"}],
        "credits": {
            "crew": [{"job": "Director", "name": "Ada Director"}],
            "cast": [{"order": 1, "name": "Second Actor"}, {"order": 0, "name": "First Actor"}],
        },
        "external_ids": {"imdb_id": "tt1234567", "wikidata_id": "Q123"},
    }


def test_exact_match_with_year_scores_full_confidence():
    client, calls = make_client(
        [{"id": 7, "title": "Police Academy", "release_date": "1984-03-23", "popularity": 11.0}]
    )
    metadata = client.lookup("01 Police Academy Comedy", 1984)
    assert metadata is not None
    assert metadata.provider_id == 7
    assert metadata.confidence == 1.0
    assert metadata.matched_via == "search:exact"
    assert metadata.poster_url.endswith("/poster.jpg")
    assert metadata.director == "Ada Director"
    assert metadata.cast_text == "First Actor, Second Actor"
    assert metadata.genres == ("Comedy", "Adventure")
    assert metadata.external_ids["imdb"] == "tt1234567"
    # Search must not filter by year; scoring compares years instead.
    assert "primary_release_year" not in calls[0][1]
    assert calls[0][1]["include_adult"] == "false"


def test_year_gap_rejects_even_exact_titles():
    client, _ = make_client(
        [{"id": 7, "title": "Police Academy", "release_date": "1999-01-01", "popularity": 5.0}]
    )
    assert client.lookup("Police Academy", 1984) is None


def test_exact_match_without_stored_year_is_accepted():
    client, _ = make_client(
        [{"id": 7, "title": "Annie Hall", "release_date": "1977-04-20", "popularity": 9.0}]
    )
    metadata = client.lookup("Annie Hall Hd", None)
    assert metadata is not None
    assert metadata.confidence == 0.85


def test_truncated_filename_resolves():
    client, _ = make_client(
        [
            {
                "id": 9,
                "title": "To Wong Foo, Thanks for Everything! Julie Newmar",
                "release_date": "1995-09-08",
                "popularity": 4.0,
            }
        ]
    )
    metadata = client.lookup("To Wong Foo Thanks For Everything, Julie Newma", None)
    assert metadata is not None
    assert metadata.confidence == 0.78


def test_contained_title_requires_matching_year():
    results = [{"id": 11, "title": "Star Wars", "release_date": "1977-05-25", "popularity": 40.0}]
    client, _ = make_client(results)
    assert client.lookup("Star Wars Episode 4 A New Hope", 1977) is not None
    client, _ = make_client(results)
    assert client.lookup("Star Wars Episode 4 A New Hope", 2005) is None


def test_ambiguous_no_year_and_wrong_titles_are_left_for_review():
    client, _ = make_client(
        [{"id": 2, "title": "Die Hard 2", "release_date": "1990-07-04", "popularity": 20.0}]
    )
    # Long remainder without a stored year must not be guessed at.
    assert client.lookup("02 Die Hard 2 Die Harder Bruce Willis Action", None) is None
    client, _ = make_client(
        [{"id": 3, "title": "Something Else Entirely", "release_date": "1990-01-01", "popularity": 2.0}]
    )
    assert client.lookup("Die Hard 2", 1990) is None


def test_lookup_query_override_skips_candidate_generation():
    client, calls = make_client(
        [{"id": 8, "title": "Police Academy: Mission to Moscow", "release_date": "1994-06-10", "popularity": 3.0}]
    )
    metadata = client.lookup("07 Police Academy 7 Mission To Moscow Comedy", 1994, query="Police Academy Mission to Moscow")
    assert metadata is not None
    assert metadata.confidence == 1.0
    assert calls[0][1]["query"] == "Police Academy Mission to Moscow"


def test_pin_fetch_uses_provider_id_directly():
    client, calls = make_client(
        [{"id": 1571, "title": "Live Free or Die Hard", "release_date": "2007-06-20", "popularity": 12.0}]
    )
    metadata = client.fetch(1571, fallback_title="Die Hard 4", matched_via="override:pin")
    assert metadata is not None
    assert metadata.provider_id == 1571
    assert metadata.matched_via == "override:pin"
    assert calls[0][0] == "/movie/1571"


# ---------------------------------------------------------------------------
# Job pipeline.
# ---------------------------------------------------------------------------


def metadata_fixture():
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
        matched_query="Moon Movie",
        matched_via="search:exact",
    )


class FakeClient:
    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def lookup(self, title, year=None, *, query=None):
        self.calls.append((title, year, query))
        return self.result

    def fetch(self, provider_id, *, fallback_title="", matched_via="pin"):
        self.calls.append(("fetch", provider_id))
        return self.result


def seed_config(tmp_path, monkeypatch, name="metadata.db"):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / name))
    monkeypatch.setenv("METADATA_PROVIDER", "tmdb")
    monkeypatch.setenv("METADATA_API_KEY", "test-token")
    config = Config.from_env()
    initialize(config)
    return config


def test_metadata_job_populates_movie_and_genres(tmp_path, monkeypatch):
    config = seed_config(tmp_path, monkeypatch)
    db = connect(config.database_path)
    movie_id = db.execute(
        "INSERT INTO movies(stable_id,title,slug,release_year,parsing_confidence) "
        "VALUES ('metadata-movie','Moon Movie','moon-movie',1999,'high')"
    ).lastrowid
    db.close()

    assert enqueue_metadata(config) == 1
    assert work_metadata_one(config, FakeClient(metadata_fixture())) is True
    assert work_metadata_one(config, FakeClient(metadata_fixture())) is False

    db = connect(config.database_path)
    movie = db.execute("SELECT * FROM movies WHERE id=?", (movie_id,)).fetchone()
    assert movie["poster_url"].endswith("/poster.jpg")
    assert movie["synopsis"] == "A trip beyond the atmosphere."
    assert movie["director"] == "Ada Director"
    assert movie["cast_text"] == "First Actor, Second Actor"
    assert movie["enrichment_state"] == "enriched"
    assert json.loads(movie["external_ids_json"])["imdb"] == "tt1234567"
    genres = {
        row[0]
        for row in db.execute(
            "SELECT g.name FROM genres g JOIN movie_genres mg ON mg.genre_id=g.id WHERE mg.movie_id=?",
            (movie_id,),
        )
    }
    assert genres == {"Science Fiction", "Adventure"}
    job = db.execute("SELECT status,confidence,result_json FROM jobs").fetchone()
    assert job["status"] == "complete"
    assert job["confidence"] == 1.0
    result = json.loads(job["result_json"])
    assert result["previous_title"] == "Moon Movie"
    assert result["matched_via"] == "search:exact"
    db.close()


def test_metadata_job_marks_ambiguous_match_for_review(tmp_path, monkeypatch):
    config = seed_config(tmp_path, monkeypatch, "review.db")
    db = connect(config.database_path)
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('ambiguous','Unknown Movie','unknown-movie','medium')")
    db.close()
    assert enqueue_metadata(config) == 1
    assert work_metadata_one(config, FakeClient(None)) is True
    db = connect(config.database_path)
    assert db.execute("SELECT enrichment_state FROM movies").fetchone()[0] == "review"
    assert db.execute("SELECT status FROM jobs").fetchone()[0] == "review"
    db.close()


def test_review_rows_are_only_requeued_with_an_override(tmp_path, monkeypatch):
    config = seed_config(tmp_path, monkeypatch, "queue.db")
    db = connect(config.database_path)
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence,enrichment_state) VALUES ('plain','Plain Movie','plain-movie','medium','review')")
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence,enrichment_state) VALUES ('fixed','Fixed Movie','fixed-movie','medium','review')")
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('pending','Pending Movie','pending-movie','high')")
    db.close()

    monkeypatch.setattr("mwm.enrichment.load_overrides", lambda path=None: {"fixed": {"query": "Fixed Movie", "year": 1999}})
    assert enqueue_metadata(config) == 2  # pending + override-backed review row
    assert enqueue_metadata(config, include_review=True) == 1  # plain review row retried

    db = connect(config.database_path)
    states = dict(db.execute("SELECT stable_id,enrichment_state FROM movies"))
    assert states["fixed"] == "pending"
    assert states["plain"] == "pending"
    db.close()


def test_lookup_with_override_paths():
    client = FakeClient(metadata_fixture())
    _lookup_with_override(client, {"title": "X", "release_year": None}, None)
    assert client.calls[-1] == ("X", None, None)
    _lookup_with_override(client, {"title": "X", "release_year": 1999}, {"tmdb_id": 1571})
    assert client.calls[-1] == ("fetch", 1571)
    _lookup_with_override(client, {"title": "X", "release_year": 1999}, {"query": "Clean Title", "year": 1994})
    assert client.calls[-1] == ("X", 1994, "Clean Title")


def test_run_metadata_queue_processes_until_empty(tmp_path, monkeypatch):
    config = seed_config(tmp_path, monkeypatch, "loop.db")
    db = connect(config.database_path)
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('one','Moon Movie','moon-movie','high')")
    db.execute("INSERT INTO movies(stable_id,title,slug,parsing_confidence) VALUES ('two','Sun Movie','sun-movie','high')")
    db.close()
    processed = run_metadata_queue(config, client=FakeClient(metadata_fixture()), sleep=0)
    assert processed == 2
    db = connect(config.database_path)
    assert db.execute("SELECT count(*) FROM jobs WHERE status='queued'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM movies WHERE enrichment_state='enriched'").fetchone()[0] == 2
    db.close()


def test_load_overrides_ignores_metadata_keys(tmp_path):
    path = Path(tmp_path / "overrides.json")
    path.write_text(json.dumps({"_note": "ignored", "abc": {"query": "Title"}, "def": "not-a-dict"}))
    overrides = load_overrides(path)
    assert overrides == {"abc": {"query": "Title"}}
    assert load_overrides(Path(tmp_path / "missing.json")) == {}


def test_short_numeric_titles_need_year_evidence():
    # A bare "622" must not be handed a numeric-titled film on a plate.
    results = [{"id": 9, "title": "の・622", "release_date": "2018-05-05", "popularity": 3.0}]
    client, _ = make_client(results)
    assert client.lookup("622", None) is None
    client, _ = make_client(results)
    assert client.lookup("622", 2018) is not None


def test_accented_titles_fold_to_ascii():
    client, _ = make_client(
        [{"id": 5, "title": "Amélie", "release_date": "2001-04-25", "popularity": 30.0}]
    )
    metadata = client.lookup("Amelie", 2001)
    assert metadata is not None
    assert metadata.confidence == 1.0
    assert metadata.title == "Amélie"


def test_metadata_worker_off_by_default(monkeypatch):
    from mwm.config import Config
    from mwm.enrichment import start_metadata_worker

    monkeypatch.delenv("METADATA_WORKER", raising=False)
    config = Config.from_env()
    assert config.metadata_worker is False
    assert start_metadata_worker(config) is None


def test_metadata_worker_requires_key(monkeypatch):
    from mwm.config import Config
    from mwm.enrichment import start_metadata_worker

    monkeypatch.setenv("METADATA_WORKER", "1")
    monkeypatch.delenv("METADATA_API_KEY", raising=False)
    config = Config.from_env()
    assert start_metadata_worker(config) is None
