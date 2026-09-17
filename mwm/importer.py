from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import Config
from .db import connect, initialize


YEAR_RE = re.compile(r"(?<!\d)((?:18|19|20)\d{2})(?!\d)")
NOISE_RE = re.compile(
    r"\b(?:2160p|1080p|720p|480p|bluray|brrip|webrip|web-dl|dvdrip|hdrip|xvid|x264|x265|h264|h265|hevc|aac|dts|yify|yts|rarbg|uncut|extended|proper|readnfo|remastered|eng|english)\b.*",
    re.IGNORECASE,
)
LEADING_RE = re.compile(r"^(?:18\+\s*|\[[^]]+\]\s*)", re.IGNORECASE)

GENRE_MAP = {
    "action": ("Action",),
    "comedy": ("Comedy",),
    "drama": ("Drama",),
    "sci-fi": ("Science Fiction",),
    "indie": ("Independent",),
    "foreign": ("International",),
    "sports": ("Sports",),
    "docs": ("Documentary",),
    "musicals": ("Musical",),
    "k and a": ("Kids", "Animation"),
    "comics": ("Action", "Science Fiction"),
}
COLLECTION_MAP = {
    "bc": ("Black Cinema",),
    "classics": ("Classics",),
    "k and a": ("Kids and Animation",),
    "soft": ("Adult & Erotic Cinema",),
    "someday": ("Better With a Couple of Beers",),
    "new": ("Recent Additions",),
    "comics": ("Comic Book Movies",),
}


@dataclass
class ImportReport:
    total_rows: int = 0
    imported: int = 0
    updated: int = 0
    excluded_educational: int = 0
    quarantined: int = 0
    duplicates: int = 0
    soft_included: int = 0
    new_included: int = 0
    someday_mapped: int = 0
    someday_review: int = 0
    kids_included: int = 0


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return value or "untitled"


def parse_filename(filename: str) -> tuple[str, int | None, str]:
    stem = Path(filename).stem
    stem = LEADING_RE.sub("", stem).replace("_", " ").replace(".", " ")
    year_matches = list(YEAR_RE.finditer(stem))
    match = year_matches[-1] if year_matches else None
    year = int(match.group(1)) if match else None
    title_part = stem[: match.start()] if match else stem
    title_part = NOISE_RE.sub("", title_part)
    title = re.sub(r"[\[({].*$", "", title_part)
    title = re.sub(r"\s+", " ", title.replace("-", " ")).strip(" ._-[]()")
    if not title:
        title = "Untitled"
    confidence = "high" if year and title != "Untitled" else "medium" if title != "Untitled" else "low"
    return title.title(), year, confidence


def _digest(value: str, length: int = 40) -> str:
    return hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()[:length]


def import_inventory(csv_path: Path, config: Config | None = None) -> ImportReport:
    config = config or Config.from_env()
    initialize(config)
    connection = connect(config.database_path)
    report = ImportReport()
    run_id = connection.execute(
        "INSERT INTO import_runs(source_file) VALUES (?)", (csv_path.name,)
    ).lastrowid
    genre_ids = {row["name"]: row["id"] for row in connection.execute("SELECT id,name FROM genres")}
    collection_ids = {row["name"]: row["id"] for row in connection.execute("SELECT id,name FROM collections")}
    seen_keys: set[str] = set()
    try:
        with csv_path.open(newline="", encoding="utf-8-sig") as source:
            for raw in csv.DictReader(source):
                report.total_rows += 1
                category = (raw.get("category") or "uncategorized").strip().lower()
                filename = Path(raw.get("filename") or "").name
                full_path = raw.get("full_path") or filename
                if category == "educational":
                    report.excluded_educational += 1
                    continue
                title, year, confidence = parse_filename(filename)
                normalized = re.sub(r"[^a-z0-9]", "", title.lower())
                identity = f"{normalized}|{year or ''}"
                stable_id = _digest(identity, 24)
                source_fingerprint = _digest(f"{category}|{full_path}")
                if identity in seen_keys:
                    report.duplicates += 1
                seen_keys.add(identity)
                existing = connection.execute("SELECT id FROM movies WHERE stable_id=?", (stable_id,)).fetchone()
                if existing:
                    movie_id = existing["id"]
                    report.updated += 1
                else:
                    unique_slug = f"{slugify(title)}-{year or 'unknown'}-{stable_id[:6]}"
                    movie_id = connection.execute(
                        "INSERT INTO movies(stable_id,title,slug,release_year,parsing_confidence,enrichment_state,storage_status,adult_content,family_content,published) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (
                            stable_id,
                            title,
                            unique_slug,
                            year,
                            confidence,
                            "review" if confidence == "low" else "pending",
                            "new" if category == "new" else None,
                            int(category == "soft"),
                            int(category == "k and a"),
                            int(confidence != "low"),
                        ),
                    ).lastrowid
                    report.imported += 1
                connection.execute(
                    "INSERT INTO movie_sources(movie_id,source_fingerprint,raw_filename,source_category,path_fingerprint) VALUES (?,?,?,?,?) "
                    "ON CONFLICT(source_fingerprint) DO UPDATE SET movie_id=excluded.movie_id,raw_filename=excluded.raw_filename,source_category=excluded.source_category,updated_at=CURRENT_TIMESTAMP",
                    (movie_id, source_fingerprint, filename, category, _digest(full_path)),
                )
                for name in GENRE_MAP.get(category, ()):
                    connection.execute(
                        "INSERT OR IGNORE INTO movie_genres(movie_id,genre_id,source,confidence) VALUES (?,?,?,?)",
                        (movie_id, genre_ids[name], "inventory-category", 1.0),
                    )
                for name in COLLECTION_MAP.get(category, ()):
                    confidence_value = 0.65 if category == "someday" else 1.0
                    connection.execute(
                        "INSERT OR IGNORE INTO movie_collections(movie_id,collection_id,source,confidence) VALUES (?,?,?,?)",
                        (movie_id, collection_ids[name], "inventory-category", confidence_value),
                    )
                if confidence == "low":
                    report.quarantined += 1
                    connection.execute(
                        "INSERT OR IGNORE INTO import_review(import_run_id,source_fingerprint,raw_filename,source_category,parsed_title,parsed_year,reason) VALUES (?,?,?,?,?,?,?)",
                        (run_id, source_fingerprint, filename, category, title, year, "Filename could not be parsed confidently"),
                    )
                report.soft_included += int(category == "soft")
                report.new_included += int(category == "new")
                report.someday_mapped += int(category == "someday")
                report.kids_included += int(category == "k and a")
        payload = asdict(report)
        connection.execute(
            "UPDATE import_runs SET finished_at=CURRENT_TIMESTAMP,total_rows=?,imported=?,updated=?,excluded_educational=?,quarantined=?,duplicates=?,soft_included=?,new_included=?,someday_mapped=?,someday_review=?,kids_included=?,report_json=? WHERE id=?",
            (*payload.values(), json.dumps(payload, sort_keys=True), run_id),
        )
        return report
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import a Movies We Missed inventory CSV")
    parser.add_argument("csv_path", nargs="?", type=Path, default=Path("movie_inventory.csv"))
    args = parser.parse_args()
    print(json.dumps(asdict(import_inventory(args.csv_path)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
