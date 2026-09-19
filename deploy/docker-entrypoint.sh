#!/bin/sh
set -eu

database_path="${DATABASE_PATH:-/app/data/mwm.db}"

seed_database() {
    mkdir -p "$(dirname "$database_path")"
    # Remove a previous database and any WAL/SHM sidecars. On a file-type mount
    # the unlink of the database itself can fail (busy mountpoint); the copy
    # below then overwrites the file in place, so the failure is tolerated.
    rm -f "$database_path" "$database_path-wal" "$database_path-shm" 2>/dev/null || true
    cp /app/seed/mwm.db "$database_path"
}

if [ "${FORCE_SEED:-0}" = "1" ]; then
    echo "entrypoint: FORCE_SEED=1 - replacing ${database_path} with the bundled catalog snapshot"
    seed_database
elif [ ! -e "$database_path" ]; then
    echo "entrypoint: seeding ${database_path} from the bundled catalog snapshot"
    seed_database
fi

exec "$@"
