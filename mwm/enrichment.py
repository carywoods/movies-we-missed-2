from __future__ import annotations

import argparse
import json
from urllib.parse import urlencode

from .config import Config
from .db import connect, initialize


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Queue or process low-cost movie enrichment jobs")
    parser.add_argument("command", choices=("enqueue", "work"))
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    config = Config.from_env()
    if args.command == "enqueue":
        print(json.dumps({"queued": enqueue_missing(config)}))
    else:
        processed = sum(1 for _ in range(max(0, args.limit)) if work_one(config))
        print(json.dumps({"processed": processed}))


if __name__ == "__main__":
    main()
