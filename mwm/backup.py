from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .config import Config
from .db import connect, initialize


def backup_database(config: Config, destination: Path | None = None) -> Path:
    initialize(config)
    destination = destination or Path("backups")
    if destination.suffix == ".db":
        target = destination
    else:
        target = destination / f"mwm-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.db"
    target = target.expanduser().resolve()
    source_path = config.database_path.expanduser().resolve()
    if target == source_path:
        raise ValueError("Backup destination must differ from the live database")
    target.parent.mkdir(parents=True, exist_ok=True)
    source = connect(source_path)
    destination_db = sqlite3.connect(target)
    try:
        source.backup(destination_db)
        if destination_db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("Backup integrity check failed")
    finally:
        destination_db.close()
        source.close()
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a consistent online SQLite backup")
    parser.add_argument("destination", nargs="?", type=Path, default=Path("backups"))
    args = parser.parse_args()
    print(backup_database(Config.from_env(), args.destination))


if __name__ == "__main__":
    main()
