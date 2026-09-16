# Coolify deployment

## Docker deployment (recommended)

1. Create a Coolify resource from this Git repository and select Dockerfile build pack. The repository-root `Dockerfile` is the build file; no custom build command is required.
2. Add persistent storage with destination `/app/data`. Set `DATABASE_PATH=/app/data/mwm.db`. The volume is required: deployments without it lose SQLite data when a container is replaced.
3. Copy `.env.example` into Coolify’s environment settings. Set `SITE_URL` to the final HTTPS origin and generate a unique `SESSION_SECRET` of at least 32 characters. Leave optional providers `disabled` until credentials are available.
4. Set the container port to `8080`, or choose another `PORT` and expose that same value. The application binds `0.0.0.0`.
5. Configure the health check path as `/health` with expected HTTP status 200.
6. Deploy, run `mwm-import movie_inventory.csv` once if the inventory is mounted/copied into the container, then confirm `/`, `/movies`, and `/health`.

The image runs as non-root UID 10001. Ensure the Coolify volume is writable by that user. Use one replica for the SQLite first run.

## Nixpacks/Python alternative

- Build command: `python -m pip install .`
- Start command: `mwm-server`
- Health path: `/health`

The same persistent volume and environment requirements apply.

## Production checks

```sh
python -m pip wheel --no-deps . -w dist
APP_ENV=production SITE_URL=https://movies.example.com \
SESSION_SECRET='replace-with-a-real-32-character-secret' \
DATABASE_PATH=/app/data/mwm.db PORT=8080 mwm-server
```

Back up the database with `mwm-backup /app/backups`; see `OPERATIONS.md` for restore guidance.
