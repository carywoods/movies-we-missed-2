# Parked Handoff

Application work parked on 2026-09-19 after `82c2c09`; this handoff note is the only subsequent change.

## Verified state

- 56 tests pass.
- Mypy passes across 22 source files.
- The Docker image builds and starts in production mode.
- A fresh Docker volume is seeded with 1,122 catalog titles.
- `/health` and `/movies` respond successfully.
- Administrator bootstrap works through `ADMIN_EMAIL` and `ADMIN_PASSWORD`.
- A second container preserves changes made to the first container's volume.

## Data and taxonomy

- The local live database remains ignored at `data/mwm.db`.
- The pre-taxonomy local backup remains ignored under `backups/`.
- `deploy/mwm-seed.db` is the sanitized Coolify seed. It contains the catalog and public operational data but no members, password hashes, sessions, reset tokens, newsletter recipients, comments, RSVPs, follows, notifications, analytics events, or audit records.
- The seed SHA-256 is `f09c964f7de23557a2200b146e62088cf3bcc8f98b484a12611bdee588bec2a7`.
- There are no adult films in the database. Legacy `soft` sources are represented by the public Erotica collection, LGBQ Stories is public, and all movie adult-content flags are zero.

## Coolify restart point

1. Create or update the application from this repository using the root `Dockerfile`.
2. Mount a named persistent volume at `/app/data` and set `DATABASE_PATH=/app/data/mwm.db`.
3. Set `APP_ENV=production`, the final `SITE_URL`, and a unique `SESSION_SECRET` of at least 32 characters.
4. Set temporary `ADMIN_EMAIL` and `ADMIN_PASSWORD` values for first login, then remove `ADMIN_PASSWORD` from the environment.
5. Expose port 8080 and configure `/health` as the health check.
6. Deploy and verify `/`, `/movies`, `/collections`, `/admin`, and `/health`.

The entrypoint copies the sanitized catalog seed only when the database file does not exist. It never overwrites an existing persistent database. If an older test resource already has an empty database, remove only that test resource's volume after confirming it contains nothing needed, then redeploy.

## Remaining state

- No known code blocker remains before Coolify testing.
- SMTP, metadata enrichment, and model providers remain intentionally disabled until credentials are configured.
- `eval.md` is local and intentionally untracked.
