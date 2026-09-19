# Parked Handoff

Application work parked on 2026-09-19 after `82c2c09`; catalog enrichment (TMDB artwork, metadata, clean titles) landed on `main` the same day — see `DEPLOYMENT.md` § Catalog metadata.

## Verified state

- 84 tests pass.
- Mypy passes across 23 source files.
- The Docker image builds and starts in production mode.
- A fresh Docker volume is seeded with 1,122 enriched catalog titles (1,045 matched from TMDB).
- `/health` and `/movies` respond successfully.
- Administrator bootstrap works through `ADMIN_EMAIL` and `ADMIN_PASSWORD`, and the configured password is re-applied on every boot.
- A second container preserves changes made to the first container's volume.

## Data and taxonomy

- The local live database remains ignored at `data/mwm.db`.
- The pre-taxonomy local backup remains ignored under `backups/`.
- `deploy/mwm-seed.db` is the sanitized Coolify seed. It contains the catalog (enriched titles, artwork URLs, synopses, credits, genres, and the metadata job history) and public operational data but no members, password hashes, sessions, reset tokens, newsletter recipients, comments, RSVPs, follows, notifications, analytics events, or audit records.
- The seed SHA-256 is `95dbfb04971acfa5088472c7e6c58d1973c70f7d70dada1ab234873e664392df`.
- 1,045 of 1,122 titles carry a TMDB match; the remaining 77 sit in the `review` state (numbered series, non-film inventory, and ambiguous titles) and are visible in the admin Catalog enrichment console.
- There are no adult films in the database. Legacy `soft` sources are represented by the public Erotica collection, LGBQ Stories is public, and all movie adult-content flags are zero.

## Coolify restart point

1. Create or update the application from this repository using the root `Dockerfile`.
2. Mount a named persistent volume at `/app/data` and set `DATABASE_PATH=/app/data/mwm.db`.
3. Set `APP_ENV=production`, the final `SITE_URL`, and a unique `SESSION_SECRET` of at least 32 characters.
4. Set `ADMIN_EMAIL` and `ADMIN_PASSWORD`. The account is ensured with role `admin` on every boot and the configured password is re-applied, so keep the environment value as the current password (or remove it to freeze the last one).
5. Expose port 8080 and configure `/health` as the health check.
6. Deploy and verify `/`, `/movies`, `/collections`, `/admin`, and `/health`.

The entrypoint copies the sanitized catalog seed only when the database file does not exist. It never overwrites an existing persistent database. If an older test resource already has an empty database, remove only that test resource's volume after confirming it contains nothing needed, then redeploy.

## Remaining state

- No known code blocker remains before Coolify testing.
- SMTP and model providers remain intentionally disabled until credentials are configured.
- Catalog enrichment is implemented: set `METADATA_API_KEY` (TMDB read token) and optionally `METADATA_WORKER=1` to keep filling the live database in place; a fresh volume already starts from the enriched seed.
- `eval.md` is local and intentionally untracked.
