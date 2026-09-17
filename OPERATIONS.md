# Operations

## SQLite persistence

Set `DATABASE_PATH` to a file on a persistent volume. In Coolify, mount a volume at `/app/data` and use `DATABASE_PATH=/app/data/mwm.db`. Never place the live database in the image layer or a temporary directory.

SQLite runs in WAL mode. Keep the database, `-wal`, and `-shm` files on the same local filesystem. Do not put the live database on NFS/SMB. One application process is the supported first-run topology.

## Backups

Create a transactionally consistent online backup with:

```sh
mwm-backup /app/backups
```

Schedule it daily and copy the resulting timestamped `.db` file to separate storage. Test restores regularly:

```sh
DATABASE_PATH=/tmp/restored.db mwm-server
sqlite3 /tmp/restored.db 'PRAGMA integrity_check;'
```

Restore by stopping the application, retaining the current database for rollback, copying a verified backup to `DATABASE_PATH`, and restarting. The startup migration runner safely applies any newer schema migrations.

## Routine operation

- `/admin` links to movie/classification, import review, screenings, merchandise, moderation, newsletter, sponsors, and analytics.
- `mwm-import movie_inventory.csv` performs an idempotent inventory refresh.
- `mwm-enrich enqueue` queues missing merchandise enrichment and `mwm-enrich work --limit 25` processes small deterministic batches.
- `/health` is the liveness/readiness target.
- With TMDB configured, `mwm-enrich metadata-enqueue` queues missing catalog
  metadata and `mwm-enrich metadata-work --limit 25` processes it in batches.
