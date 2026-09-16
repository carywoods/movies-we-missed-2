# Decisions

## Architecture

- Retain the supplied SQLite schema/configuration and add small domain mixins around a dependency-free WSGI core.
- Use one application process for the SQLite first run. WAL, busy timeout, online backups, and a local persistent volume fit the intended scale.
- Keep external integrations explicitly configurable; missing email/metadata/model credentials disable only that integration.

## Identity and social model

- Store PBKDF2-SHA256 password hashes and only SHA-256 digests of opaque session tokens. Rotate sessions at authentication and require CSRF for mutations.
- Constrain follows to `movie` and `genre`; exclude person following from schema, routes, feed, and UI.

## Inventory and content

- Treat the supplied inventory as private operator input and keep it out of source control. Retain filenames for review, but hash source paths.
- Map `new` to storage status, `soft` to included/adult-labeled, `k and a` to Kids/Animation, `bc` to Black Cinema, and `someday` to Better With a Couple of Beers at lower editorial confidence.
- Exclude adult-labeled movies from anonymous catalog pages and the sitemap.

## Revenue and messaging

- Seed popcorn as a universal offer fallback. Centralize Amazon and sponsor exits, and use deterministic queued enrichment rather than model-driven bulk searches.
- Store exactly one sponsor per newsletter issue. IMBH is the house default; an active paid sponsor may replace it.
- Leave email delivery disabled without a provider while keeping subscriber, candidate, preview, and issue workflows usable.

## Privacy and operations

- Store first-party events with available object/member identifiers and a one-way session hash; never store IP addresses or user-agent strings.
- Run as non-root, bind `0.0.0.0`, configure port/database paths through environment, and require persistent local SQLite storage.
