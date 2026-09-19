# Coolify deployment

## Docker deployment (recommended)

1. Create a Coolify resource from this Git repository and select Dockerfile build pack. The repository-root `Dockerfile` is the build file; no custom build command is required.
2. Add a named volume with destination `/app/data`. Set `DATABASE_PATH=/app/data/mwm.db`. On the first boot, the image copies its sanitized 1,122-title catalog snapshot into an empty volume. Later deployments keep the volume's database and never overwrite it.
3. Copy `.env.example` into Coolify’s environment settings. Set `SITE_URL` to the final HTTPS origin and generate a unique `SESSION_SECRET` of at least 32 characters. Leave optional providers `disabled` until credentials are available.
4. Set the container port to `8080`, or choose another `PORT` and expose that same value. The application binds `0.0.0.0`.
5. Configure the health check path as `/health` with expected HTTP status 200.
6. Deploy and confirm `/`, `/movies`, and `/health`. If this resource already created an empty database before catalog seeding was added, remove only that test resource's database volume and redeploy, or restore the seed into the volume manually. Never remove a production volume without a verified backup.
7. For outbound newsletters and password recovery, set `EMAIL_PROVIDER=smtp` plus the SMTP variables in `.env.example`; otherwise email remains safely disabled.

The image runs as non-root UID 10001. Ensure the Coolify volume is writable by that user. Use one replica for the SQLite first run.

The bundled seed contains catalog, taxonomy, sponsor, merchandise, and import-review data from the local database. It excludes members, password hashes, sessions, reset tokens, newsletter recipients and deliveries, comments, reports, RSVPs, follows, notifications, analytics events, and audit records. Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` for the test deployment; remove `ADMIN_PASSWORD` after the first successful administrator login.

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
