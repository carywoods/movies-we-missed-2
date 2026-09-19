# Coolify deployment

## Docker deployment (recommended)

1. Create a Coolify resource from this Git repository and select the Dockerfile build pack. The repository-root `Dockerfile` is the build file; no custom build command is required.
2. Add a named volume with destination `/app/data`. Set `DATABASE_PATH=/app/data/mwm.db`. On the first boot, the image copies its sanitized 1,122-title catalog snapshot into an empty volume. Later deployments keep the volume's database and never overwrite it.
3. Copy `.env.example` into Coolify’s environment settings. Set `SITE_URL` to the final HTTPS origin and generate a unique `SESSION_SECRET` of at least 32 characters.
4. Set the container port to `8080`, or choose another `PORT` and expose that same value. The application binds `0.0.0.0`.
5. Configure the health check path as `/health` with expected HTTP status 200.
6. Deploy and confirm `/`, `/movies`, and `/health`. If this resource already created an empty database before catalog seeding was added, remove only that test resource's database volume and redeploy, or restore the seed into the volume manually. Never remove a production volume without a verified backup.
7. For outbound newsletters and password recovery, set `EMAIL_PROVIDER=smtp` plus the SMTP variables in `.env.example`; otherwise email remains safely disabled.

The image runs as non-root UID 10001. Ensure the Coolify volume is writable by that user. Use one replica for the SQLite first run.

The bundled seed contains catalog, taxonomy, sponsor, merchandise, and import-review data from the local database. It excludes members, password hashes, sessions, reset tokens, newsletter recipients and deliveries, comments, reports, RSVPs, follows, notifications, analytics events, and audit records.

## Administrator login

- Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` in the environment. On every boot the application ensures that account exists with role `admin` and re-applies the configured password, so the environment value is always the current password. Changing `ADMIN_PASSWORD` and redeploying is the recovery path; remove it only if you want the password to stop tracking the environment.
- Log in at `/login` (or `/admin/login`, which redirects there). Anonymous visits to `/admin` redirect to the login form and return to `/admin` after a successful login. Members without the `editor`/`admin` role receive `403`.
- The admin area includes a Catalog enrichment console at `/admin/enrichment` with state counts, a batch runner, the review queue, and recent job history.

## Catalog metadata (TMDB)

Titles, artwork, synopses, and credits are enriched from TMDB.

1. Create a TMDB API key and use its **API Read Access Token (v4)** as `METADATA_API_KEY`. Set `METADATA_PROVIDER=tmdb`.
2. Set `METADATA_WORKER=1` to run enrichment in the background of the web process. The worker starts one pass at boot and wakes every 30 minutes for new rows; it never blocks or crashes the web application.
3. Without the worker, run the same work from a shell inside the container:

   ```sh
   mwm-enrich metadata-enqueue
   mwm-enrich metadata-work --all
   ```

   Or click through batches in `/admin/enrichment`. Rows that cannot be matched confidently are held in `review` and are only retried when explicitly re-queued (admin button, `--include-review`, or a curated entry in `mwm/enrichment-overrides.json` keyed by `stable_id`).
4. An already-populated volume is not replaced by a new seed. It fills itself via the worker, the CLI, or the admin console. A fresh volume starts from the pre-enriched seed snapshot.
5. The catalog pages show the TMDB attribution line whenever `METADATA_PROVIDER=tmdb`. Keep it — it is required by the TMDB terms of use.

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
