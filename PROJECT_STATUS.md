# Project Status

First-run definition of done: **implemented and verified**.
Last verified 2026-09-18: 56 tests, clean type/compile checks, isolated wheel install, production health check, local database migration/integrity verification, and seeded Docker volume persistence.


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
| Coolify | Complete | Sanitized 1,122-title seed, Docker/env/volume contract, health and redeploy-persistence checks |

External enrichment and outbound email remain intentionally disabled until optional providers are configured. Core behavior does not depend on them.
