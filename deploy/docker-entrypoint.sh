#!/bin/sh
set -eu

database_path="${DATABASE_PATH:-/app/data/mwm.db}"

if [ ! -e "$database_path" ]; then
    mkdir -p "$(dirname "$database_path")"
    cp /app/seed/mwm.db "$database_path"
fi

exec "$@"
