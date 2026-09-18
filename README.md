# Movies We Missed

Movies We Missed is a self-contained movie-club application: catalog discovery, movie/genre interests, comments, screenings and RSVP, commerce, sponsorship, newsletters, first-party analytics, SEO/PWA support, and an operator console.

The first run uses Python’s standard-library WSGI server and SQLite, with no required runtime packages beyond Python 3.11+.

## Run locally

```sh
python -m pip install -e .
APP_ENV=development DATABASE_PATH=data/mwm.db mwm-server
```

Open <http://localhost:8080> and verify <http://localhost:8080/health>.

Import the private operator inventory (the CSV is intentionally Git-ignored):

```sh
DATABASE_PATH=data/mwm.db mwm-import movie_inventory.csv
```

The importer excludes `educational`, preserves category provenance, deduplicates title/year identities, quarantines uncertain rows, and stores source paths only as one-way fingerprints.

## Administrator bootstrap

Set `ADMIN_EMAIL` and `ADMIN_PASSWORD` for first boot. After confirming `/admin` access, remove `ADMIN_PASSWORD` from the deployment environment. Passwords use PBKDF2-SHA256; sessions are opaque, server-side, rotated at authentication, CSRF-protected, HttpOnly, and SameSite.

## Commands

```sh
mwm-server                       # bind 0.0.0.0:$PORT
mwm-import movie_inventory.csv   # idempotent inventory import
mwm-enrich enqueue               # queue deterministic merchandise work
mwm-enrich work --limit 25       # process a small batch
mwm-backup backups               # consistent online SQLite backup
python -m pytest -q              # complete test suite
```

## Configuration and deployment

See `.env.example`. Email supports disabled, console, and standard SMTP providers; metadata and model providers remain optional. Credentials are never required for startup.

For production, set an HTTPS `SITE_URL`, a unique 32+ character `SESSION_SECRET`, and `DATABASE_PATH` on a persistent local volume. See [DEPLOYMENT.md](DEPLOYMENT.md) for Coolify and [OPERATIONS.md](OPERATIONS.md) for persistence and backup procedures.

## Product boundaries

- Members follow movies and genres only; no person-following graph exists.
- Erotica and LGBQ Stories are public editorial collections; the inventory contains no adult-film category.
- Every public movie resolves at least the universal popcorn offer.
- Analytics do not retain IP addresses or user-agent strings.
- Sponsor and merchandise exits are centralized, validated, and measured.
