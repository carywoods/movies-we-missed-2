from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from .config import Config
from .db import connect, initialize
from .metadata import TmdbClient

# Curated corrections for catalog rows whose shelf filenames defeat automatic
# matching (numbered series, truncated names, and similar). Keyed by the
# movie's stable_id so the mapping survives database rebuilds.
OVERRIDES_PATH = Path(__file__).resolve().parent / "enrichment-overrides.json"


def load_overrides(path: Path | None = None) -> dict[str, dict[str, object]]:
    target = path or OVERRIDES_PATH
    if not target.exists():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    overrides: dict[str, dict[str, object]] = {}
    for stable_id, value in payload.items():
        if str(stable_id).startswith("_") or not isinstance(value, dict):
            continue
        overrides[str(stable_id)] = dict(value)
    return overrides


def enqueue_missing(config: Config) -> int:
    initialize(config)
    db = connect(config.database_path)
    try:
        movies = list(db.execute("SELECT id,title FROM movies m WHERE published=1 AND NOT EXISTS (SELECT 1 FROM merchandise x WHERE x.movie_id=m.id AND x.active=1) AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.job_type='merchandise_enrichment' AND j.object_id=m.id AND j.status IN ('queued','running','complete'))"))
        for movie in movies:
            db.execute("INSERT INTO jobs(job_type,object_type,object_id,provider,payload_json) VALUES ('merchandise_enrichment','movie',?,'deterministic',?)", (movie["id"], json.dumps({"title": movie["title"]})))
        return len(movies)
    finally:
        db.close()


def work_one(config: Config) -> bool:
    initialize(config)
    db = connect(config.database_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute("SELECT * FROM jobs WHERE job_type='merchandise_enrichment' AND status='queued' AND available_at<=CURRENT_TIMESTAMP ORDER BY id LIMIT 1").fetchone()
        if not job:
            db.execute("COMMIT")
            return False
        db.execute("UPDATE jobs SET status='running',locked_at=CURRENT_TIMESTAMP,attempts=attempts+1 WHERE id=?", (job["id"],))
        movie = db.execute("SELECT id,title FROM movies WHERE id=?", (job["object_id"],)).fetchone()
        if not movie:
            db.execute("UPDATE jobs SET status='failed',last_error='Movie no longer exists' WHERE id=?", (job["id"],))
        else:
            url = "https://www.amazon.com/s?" + urlencode({"k": f'{movie["title"]} movie'})
            db.execute("INSERT INTO merchandise(movie_id,merchant,product_type,display_label,destination_url,match_type,confidence,priority,generated_by) VALUES (?,'Amazon','movie','Shop for this movie',?,'contextual',0.6,10,'deterministic_queue')", (movie["id"], url))
            db.execute("UPDATE jobs SET status='complete',result_json=? WHERE id=?", (json.dumps({"rule": "title-search", "offer_created": True}), job["id"]))
        db.execute("COMMIT")
        return True
    except Exception:
        db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def _metadata_client(config: Config) -> TmdbClient:
    if config.metadata_provider != "tmdb":
        raise RuntimeError("METADATA_PROVIDER must be set to tmdb")
    if not config.metadata_api_key:
        raise RuntimeError("METADATA_API_KEY must contain a TMDB API read access token")
    return TmdbClient(config.metadata_api_key)


def enqueue_metadata(config: Config, *, include_review: bool = False) -> int:
    """Queue movie_metadata jobs for catalog rows that lack artwork.

    Rows held in ``review`` are only re-queued when ``include_review`` is set
    or when a curated override exists for them; this keeps the automatic
    worker from re-searching the same ambiguous titles on every boot.
    """
    _metadata_client(config)
    initialize(config)
    db = connect(config.database_path)
    try:
        base_sql = (
            "SELECT id,title,release_year,stable_id,enrichment_state FROM movies m "
            "WHERE published=1 AND adult_content=0 AND poster_url IS NULL "
            "AND enrichment_state {state_clause} "
            "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.job_type='movie_metadata' "
            "AND j.object_id=m.id AND j.status IN ('queued','running'))"
        )
        rows = list(db.execute(base_sql.format(state_clause="NOT IN ('review','enriched')")))
        review_rows = list(db.execute(base_sql.format(state_clause="= 'review'")))
        if include_review:
            rows += review_rows
        else:
            overrides = load_overrides()
            if overrides:
                for row in review_rows:
                    if str(row["stable_id"]) in overrides:
                        rows.append(row)
        queued = 0
        seen: set[int] = set()
        for movie in rows:
            if movie["id"] in seen:
                continue
            seen.add(movie["id"])
            if movie["enrichment_state"] == "review":
                db.execute("UPDATE movies SET enrichment_state='pending',updated_at=CURRENT_TIMESTAMP WHERE id=?", (movie["id"],))
            payload = {"title": movie["title"], "release_year": movie["release_year"]}
            db.execute("INSERT INTO jobs(job_type,object_type,object_id,provider,payload_json) VALUES ('movie_metadata','movie',?,'tmdb',?)", (movie["id"], json.dumps(payload, sort_keys=True)))
            queued += 1
        return queued
    finally:
        db.close()


def _lookup_with_override(client: TmdbClient, movie, override: dict[str, object] | None):
    if override:
        tmdb_id = override.get("tmdb_id")
        if isinstance(tmdb_id, str) and tmdb_id.isdigit():
            tmdb_id = int(tmdb_id)
        if isinstance(tmdb_id, int):
            return client.fetch(tmdb_id, fallback_title=str(movie["title"]), matched_via="override:pin")
        query = override.get("query")
        if isinstance(query, str) and query.strip():
            year = override.get("year")
            year = year if isinstance(year, int) else movie["release_year"]
            return client.lookup(str(movie["title"]), year, query=query.strip())
    return client.lookup(str(movie["title"]), movie["release_year"])


def work_metadata_one(config: Config, client: TmdbClient | None = None) -> bool:
    client = client or _metadata_client(config)
    initialize(config)
    db = connect(config.database_path)
    try:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute("SELECT * FROM jobs WHERE job_type='movie_metadata' AND status='queued' AND available_at<=CURRENT_TIMESTAMP ORDER BY id LIMIT 1").fetchone()
        if not job:
            db.execute("COMMIT")
            return False
        db.execute("UPDATE jobs SET status='running',locked_at=CURRENT_TIMESTAMP,attempts=attempts+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (job["id"],))
        movie = db.execute("SELECT id,title,release_year,stable_id FROM movies WHERE id=?", (job["object_id"],)).fetchone()
        db.execute("COMMIT")
        if not movie:
            db.execute("UPDATE jobs SET status='failed',last_error='Movie no longer exists',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job["id"],))
            return True

        override = load_overrides().get(str(movie["stable_id"]))
        try:
            metadata = _lookup_with_override(client, movie, override)
        except Exception as exc:
            final_attempt = job["attempts"] + 1 >= job["max_attempts"]
            status = "failed" if final_attempt else "queued"
            db.execute("UPDATE jobs SET status=?,last_error=?,available_at=CASE WHEN ?='queued' THEN datetime('now','+5 minutes') ELSE available_at END,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, str(exc)[:1000], status, job["id"]))
            db.execute("UPDATE movies SET enrichment_state=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", ("failed" if final_attempt else "pending", movie["id"]))
            return True

        if metadata is None:
            db.execute("UPDATE jobs SET status='review',last_error='No confident TMDB match',updated_at=CURRENT_TIMESTAMP WHERE id=?", (job["id"],))
            db.execute("UPDATE movies SET enrichment_state='review',updated_at=CURRENT_TIMESTAMP WHERE id=?", (movie["id"],))
            return True

        db.execute("BEGIN IMMEDIATE")
        db.execute(
            "UPDATE movies SET title=?,release_year=COALESCE(?,release_year),"
            "synopsis=COALESCE(NULLIF(?,''),synopsis),"
            "poster_url=COALESCE(?,poster_url),"
            "director=COALESCE(NULLIF(?,''),director),"
            "cast_text=COALESCE(NULLIF(?,''),cast_text),"
            "external_ids_json=?,enrichment_state='enriched',"
            "updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (
                metadata.title,
                metadata.release_year,
                metadata.synopsis,
                metadata.poster_url,
                metadata.director,
                metadata.cast_text,
                json.dumps(metadata.external_ids, sort_keys=True),
                movie["id"],
            ),
        )
        db.execute("DELETE FROM movie_genres WHERE movie_id=? AND source='tmdb'", (movie["id"],))
        genre_ids = {row["name"]: row["id"] for row in db.execute("SELECT id,name FROM genres")}
        for genre_name in metadata.genres:
            genre_id = genre_ids.get(genre_name)
            if genre_id:
                db.execute("INSERT OR IGNORE INTO movie_genres(movie_id,genre_id,source,confidence) VALUES (?,?,'tmdb',?)", (movie["id"], genre_id, metadata.confidence))
        result = {
            "provider_id": metadata.provider_id,
            "poster_url": metadata.poster_url,
            "genres": list(metadata.genres),
            "previous_title": str(movie["title"]),
            "matched_query": metadata.matched_query,
            "matched_via": metadata.matched_via,
        }
        db.execute("UPDATE jobs SET status='complete',result_json=?,confidence=?,last_error=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?", (json.dumps(result, sort_keys=True), metadata.confidence, job["id"]))
        db.execute("COMMIT")
        return True
    except Exception:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


def run_metadata_queue(
    config: Config,
    *,
    client: TmdbClient | None = None,
    limit: int | None = None,
    sleep: float = 0.15,
    include_review: bool = False,
) -> int:
    """Enqueue missing artwork work and process it (the background worker)."""
    client = client or _metadata_client(config)
    enqueue_metadata(config, include_review=include_review)
    processed = 0
    while limit is None or processed < limit:
        if not work_metadata_one(config, client):
            break
        processed += 1
        if sleep:
            time.sleep(sleep)
    return processed


def start_metadata_worker(config: Config) -> threading.Thread | None:
    """Run catalog enrichment in the background of the web process.

    Enabled with METADATA_WORKER=1. One pass runs at startup; afterwards the
    worker wakes every 30 minutes to pick up new rows. Failures are logged and
    never take the web application down.
    """
    if not config.metadata_worker:
        return None
    if config.metadata_provider != "tmdb" or not config.metadata_api_key:
        print("metadata worker: set METADATA_PROVIDER=tmdb and METADATA_API_KEY to enable enrichment", flush=True)
        return None
    thread = threading.Thread(target=_metadata_worker_loop, args=(config,), name="metadata-worker", daemon=True)
    thread.start()
    print("metadata worker: started", flush=True)
    return thread


def _metadata_worker_loop(config: Config) -> None:
    while True:
        try:
            processed = run_metadata_queue(config)
            if processed:
                print(f"metadata worker: processed {processed} movie(s)", flush=True)
        except Exception as exc:  # pragma: no cover - resilience path
            print(f"metadata worker: pass failed: {exc}", flush=True)
        time.sleep(1800)


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue or process movie enrichment jobs")
    parser.add_argument("command", choices=("enqueue", "work", "metadata-enqueue", "metadata-work"))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--all", action="store_true", help="metadata-work: process the queue until it is empty")
    parser.add_argument("--include-review", action="store_true", help="metadata commands: also retry rows held in review")
    args = parser.parse_args()
    config = Config.from_env()
    if args.command == "enqueue":
        print(json.dumps({"queued": enqueue_missing(config)}))
    elif args.command == "work":
        processed = sum(1 for _ in range(max(0, args.limit)) if work_one(config))
        print(json.dumps({"processed": processed}))
    elif args.command == "metadata-enqueue":
        print(json.dumps({"queued": enqueue_metadata(config, include_review=args.include_review)}))
    else:
        processed = run_metadata_queue(config, limit=None if args.all else args.limit, include_review=args.include_review)
        print(json.dumps({"processed": processed}))


if __name__ == "__main__":
    main()