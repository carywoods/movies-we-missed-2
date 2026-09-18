import csv
from pathlib import Path

from mwm.config import Config
from mwm.db import connect
from mwm.importer import import_inventory, parse_filename


def test_filename_normalization():
    assert parse_filename("Clueless.1995.720p.BluRay.x264.mp4") == ("Clueless", 1995, "high")
    assert parse_filename("18+ The Overnight 2015 UNCENSORED.mkv")[:2] == ("The Overnight", 2015)
    assert parse_filename("1984.1984.BluRay.mkv")[:2] == ("1984", 1984)
    assert parse_filename("2001 A Space Odyssey 1968.mkv")[:2] == ("2001 A Space Odyssey", 1968)
    assert parse_filename("1917.mkv") == ("1917", None, "medium")


def test_import_rules_and_path_privacy(tmp_path: Path, monkeypatch):
    inventory = tmp_path / "inventory.csv"
    rows = [
        ("educational", "Course.2020.mp4", "private://library/Course.2020.mp4"),
        ("new", "Clueless.1995.720p.mp4", "private://library/new/Clueless.1995.720p.mp4"),
        ("bc", "Clueless.1995.other.mkv", "private://library/bc/Clueless.1995.other.mkv"),
        ("soft", "After Hours.2019.mp4", "private://library/soft/After Hours.2019.mp4"),
        ("k and a", "Toy Story.1995.mp4", "private://library/k/Toy Story.1995.mp4"),
        ("someday", "Road House.1989.mp4", "private://library/someday/Road House.1989.mp4"),
    ]
    with inventory.open("w", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(["category", "filename", "extension", "full_path"])
        for category, filename, path in rows:
            writer.writerow([category, filename, Path(filename).suffix[1:], path])
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "mwm.db"))
    config = Config.from_env()

    report = import_inventory(inventory, config)
    db = connect(config.database_path)
    try:
        assert report.total_rows == 6
        assert report.excluded_educational == 1
        assert report.imported == 4
        assert report.updated == 1
        assert report.duplicates == 1
        assert db.execute("SELECT storage_status FROM movies WHERE title='Clueless'").fetchone()[0] == "new"
        assert db.execute("SELECT adult_content FROM movies WHERE title='After Hours'").fetchone()[0] == 0
        stored = " ".join(row[0] or "" for row in db.execute("SELECT path_fingerprint FROM movie_sources"))
        assert "private://" not in stored
        assert db.execute("SELECT count(*) FROM movie_collections mc JOIN collections c ON c.id=mc.collection_id JOIN movies m ON m.id=mc.movie_id WHERE c.slug='erotica' AND m.title='After Hours'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM movie_collections mc JOIN collections c ON c.id=mc.collection_id JOIN movies m ON m.id=mc.movie_id WHERE c.slug='recent-additions' AND m.title='Clueless'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM movie_sources WHERE source_category='bc'").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM movie_collections mc JOIN collections c ON c.id=mc.collection_id WHERE c.slug='better-with-a-couple-of-beers'").fetchone()[0] == 1
    finally:
        db.close()


def test_actual_inventory_import(tmp_path: Path, monkeypatch):
    if not Path("movie_inventory.csv").exists():
        import pytest
        pytest.skip("private operator inventory is not checked into source control")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "actual.db"))
    report = import_inventory(Path("movie_inventory.csv"), Config.from_env())
    assert report.total_rows == 1625
    assert report.excluded_educational == 493
    assert report.soft_included == 46
    assert report.new_included == 436
    assert report.kids_included == 9
