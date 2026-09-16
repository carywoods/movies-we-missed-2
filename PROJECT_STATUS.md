# Project Status

First-run definition of done: **implemented and verified**.

| Area | Status | Evidence |
|---|---|---|
| SQLite/config foundation | Complete | Idempotent migrations, seeds, integrity tests |
| Runnable application | Complete | WSGI startup and `/health` |
| Inventory importer | Complete | Actual 1,625-row validation and rule tests |
| Public catalog | Complete | Home, search, movie, genre, collection routes |
| Members/interests | Complete | Auth/session/CSRF and movie/genre-only follows |
| Comments | Complete | Five-item threads, expansion, reports, moderation |
| Screenings | Complete | Lifecycle, venues, RSVP/waitlist, admin |
| Commerce/sponsors | Complete | Universal offers and measured redirects |
| Newsletter | Complete | Subscribers, cadence, candidates, one sponsor, provider |
| Analytics | Complete | Required event catalog and reporting |
| SEO/PWA | Complete | Metadata, sitemap, manifest, worker, offline |
| Admin/operations | Complete | Unified dashboard, backups, persistence docs |
| Coolify | Complete | Docker/env/volume/health documentation |

External enrichment and outbound email remain intentionally disabled until optional providers are configured. Core behavior does not depend on them.
