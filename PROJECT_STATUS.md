# Project Status

First-run definition of done: **implemented and verified**.
Last verified 2026-09-19: 89 tests, clean type/compile checks, isolated wheel install, production health check, local database migration/integrity verification, seeded Docker volume persistence, an enriched 1,122-title catalog (1,045 matched from TMDB), and pixel-verified poster rendering (no cropping).


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
| Catalog enrichment | Complete | 1,045 of 1,122 titles matched from TMDB with artwork, synopsis, director, cast, genres; 77 held in review; curated overrides; worker, CLI, and admin console |
| Catalog display | Complete | Poster-on-top cards with metadata below, whole (uncropped) posters, home carousel with prev/next controls, teaser synopses; service worker refreshes shell assets so deploys reach returning visitors |

Outbound email remains intentionally disabled until SMTP is configured. Catalog enrichment is implemented and dormant until `METADATA_API_KEY` is set; core behavior does not depend on either.
