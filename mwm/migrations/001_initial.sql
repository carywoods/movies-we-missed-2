PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL,
    avatar_url TEXT,
    role TEXT NOT NULL DEFAULT 'member' CHECK (role IN ('member','moderator','editor','admin')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','suspended','deleted')),
    email_verified_at TEXT,
    interests_public INTEGER NOT NULL DEFAULT 1 CHECK (interests_public IN (0,1)),
    show_adult INTEGER NOT NULL DEFAULT 0 CHECK (show_adult IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
    csrf_token TEXT NOT NULL,
    adult_ok INTEGER NOT NULL DEFAULT 0 CHECK (adult_ok IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_member ON sessions(member_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS genres (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    slug TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    adult_only INTEGER NOT NULL DEFAULT 0 CHECK (adult_only IN (0,1)),
    family_safe INTEGER NOT NULL DEFAULT 0 CHECK (family_safe IN (0,1)),
    editorial INTEGER NOT NULL DEFAULT 1 CHECK (editorial IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY,
    stable_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    release_year INTEGER CHECK (release_year BETWEEN 1888 AND 2100),
    synopsis TEXT,
    poster_url TEXT,
    director TEXT,
    cast_text TEXT,
    external_ids_json TEXT NOT NULL DEFAULT '{}',
    parsing_confidence TEXT NOT NULL CHECK (parsing_confidence IN ('high','medium','low')),
    enrichment_state TEXT NOT NULL DEFAULT 'pending' CHECK (enrichment_state IN ('pending','enriched','failed','review')),
    storage_status TEXT,
    adult_content INTEGER NOT NULL DEFAULT 0 CHECK (adult_content IN (0,1)),
    family_content INTEGER NOT NULL DEFAULT 0 CHECK (family_content IN (0,1)),
    published INTEGER NOT NULL DEFAULT 1 CHECK (published IN (0,1)),
    featured INTEGER NOT NULL DEFAULT 0 CHECK (featured IN (0,1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_movies_public ON movies(published, adult_content, title);
CREATE INDEX IF NOT EXISTS idx_movies_year ON movies(release_year);

CREATE TABLE IF NOT EXISTS movie_sources (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    source_fingerprint TEXT NOT NULL UNIQUE,
    raw_filename TEXT NOT NULL,
    source_category TEXT NOT NULL,
    path_fingerprint TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_movie_sources_movie ON movie_sources(movie_id);
CREATE INDEX IF NOT EXISTS idx_movie_sources_category ON movie_sources(source_category);

CREATE TABLE IF NOT EXISTS movie_genres (
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    genre_id INTEGER NOT NULL REFERENCES genres(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'import',
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (movie_id, genre_id)
);

CREATE TABLE IF NOT EXISTS movie_collections (
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'import',
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    PRIMARY KEY (movie_id, collection_id)
);

CREATE TABLE IF NOT EXISTS follows (
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    target_type TEXT NOT NULL CHECK (target_type IN ('movie','genre')),
    target_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (member_id, target_type, target_id)
);
CREATE INDEX IF NOT EXISTS idx_follows_target ON follows(target_type, target_id);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    object_type TEXT NOT NULL CHECK (object_type IN ('movie','screening')),
    object_id INTEGER NOT NULL,
    body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 4000),
    status TEXT NOT NULL DEFAULT 'visible' CHECK (status IN ('visible','hidden','deleted')),
    moderated_by INTEGER REFERENCES members(id),
    moderated_at TEXT,
    moderation_note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_comments_object ON comments(object_type, object_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_comments_member ON comments(member_id, created_at DESC);

CREATE TABLE IF NOT EXISTS comment_reports (
    id INTEGER PRIMARY KEY,
    comment_id INTEGER NOT NULL REFERENCES comments(id) ON DELETE CASCADE,
    reporter_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','reviewed','dismissed')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(comment_id, reporter_id)
);

CREATE TABLE IF NOT EXISTS screenings (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id),
    slug TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    starts_at TEXT NOT NULL,
    ends_at TEXT,
    timezone TEXT NOT NULL DEFAULT 'America/Indiana/Indianapolis',
    venue_name TEXT NOT NULL,
    address_line1 TEXT NOT NULL,
    address_line2 TEXT,
    city TEXT NOT NULL,
    region TEXT NOT NULL,
    postal_code TEXT NOT NULL,
    country TEXT NOT NULL DEFAULT 'US',
    latitude REAL,
    longitude REAL,
    capacity INTEGER CHECK (capacity IS NULL OR capacity > 0),
    organizer TEXT NOT NULL DEFAULT 'Movies We Missed',
    sponsor_id INTEGER REFERENCES sponsors(id),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','announced','rsvp_open','full','completed','cancelled')),
    cost_label TEXT NOT NULL DEFAULT 'Free',
    information_url TEXT,
    ticket_url TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_screenings_upcoming ON screenings(status, starts_at);
CREATE INDEX IF NOT EXISTS idx_screenings_location ON screenings(city, region, starts_at);

CREATE TABLE IF NOT EXISTS rsvps (
    id INTEGER PRIMARY KEY,
    screening_id INTEGER NOT NULL REFERENCES screenings(id) ON DELETE CASCADE,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    guest_count INTEGER NOT NULL DEFAULT 0 CHECK (guest_count BETWEEN 0 AND 4),
    status TEXT NOT NULL DEFAULT 'going' CHECK (status IN ('going','waitlisted','cancelled','attended','no_show')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(screening_id, member_id)
);
CREATE INDEX IF NOT EXISTS idx_rsvps_screening ON rsvps(screening_id, status);

CREATE TABLE IF NOT EXISTS sponsors (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'Presented by',
    destination_url TEXT NOT NULL,
    creative_url TEXT,
    starts_on TEXT,
    ends_on TEXT,
    paid INTEGER NOT NULL DEFAULT 0 CHECK (paid IN (0,1)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    is_site_primary INTEGER NOT NULL DEFAULT 0 CHECK (is_site_primary IN (0,1)),
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS merchandise (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER REFERENCES movies(id) ON DELETE CASCADE,
    merchant TEXT NOT NULL,
    product_type TEXT NOT NULL,
    display_label TEXT NOT NULL,
    destination_url TEXT NOT NULL,
    affiliate_url TEXT,
    match_type TEXT NOT NULL CHECK (match_type IN ('specific','contextual','fallback')),
    audience TEXT NOT NULL DEFAULT 'general' CHECK (audience IN ('general','family','adult')),
    confidence REAL NOT NULL DEFAULT 1.0 CHECK (confidence BETWEEN 0 AND 1),
    priority INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    generated_by TEXT NOT NULL DEFAULT 'deterministic_rule',
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_merch_movie ON merchandise(movie_id, active, priority DESC);

CREATE TABLE IF NOT EXISTS newsletter_subscribers (
    id INTEGER PRIMARY KEY,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','unsubscribed','bounced')),
    cadence TEXT NOT NULL DEFAULT 'monthly' CHECK (cadence IN ('monthly','weekly')),
    consent_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    unsubscribe_token_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS newsletter_issues (
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    intro TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','ready','sending','sent','cancelled')),
    cadence TEXT NOT NULL DEFAULT 'monthly' CHECK (cadence IN ('monthly','weekly')),
    sponsor_id INTEGER REFERENCES sponsors(id),
    content_json TEXT NOT NULL DEFAULT '{}',
    scheduled_for TEXT,
    sent_at TEXT,
    send_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analytics_events (
    id INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL,
    object_type TEXT,
    object_id INTEGER,
    member_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    session_hash TEXT,
    source TEXT,
    campaign TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_analytics_type_time ON analytics_events(event_type, occurred_at);
CREATE INDEX IF NOT EXISTS idx_analytics_object ON analytics_events(object_type, object_id, event_type);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    destination_url TEXT,
    read_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_notifications_member ON notifications(member_id, read_at, created_at DESC);

CREATE TABLE IF NOT EXISTS enrichment_records (
    id INTEGER PRIMARY KEY,
    movie_id INTEGER NOT NULL REFERENCES movies(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    retrieved_at TEXT,
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    state TEXT NOT NULL CHECK (state IN ('pending','complete','failed','review')),
    payload_json TEXT NOT NULL DEFAULT '{}',
    error_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    job_type TEXT NOT NULL,
    object_type TEXT NOT NULL,
    object_id INTEGER,
    provider TEXT NOT NULL DEFAULT 'unassigned',
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT,
    confidence REAL CHECK (confidence BETWEEN 0 AND 1),
    status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','review','complete','failed','cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    locked_at TEXT,
    last_error TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(status, available_at, job_type);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY,
    source_file TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    total_rows INTEGER NOT NULL DEFAULT 0,
    imported INTEGER NOT NULL DEFAULT 0,
    updated INTEGER NOT NULL DEFAULT 0,
    excluded_educational INTEGER NOT NULL DEFAULT 0,
    quarantined INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    soft_included INTEGER NOT NULL DEFAULT 0,
    new_included INTEGER NOT NULL DEFAULT 0,
    someday_mapped INTEGER NOT NULL DEFAULT 0,
    someday_review INTEGER NOT NULL DEFAULT 0,
    kids_included INTEGER NOT NULL DEFAULT 0,
    report_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS import_review (
    id INTEGER PRIMARY KEY,
    import_run_id INTEGER REFERENCES import_runs(id) ON DELETE SET NULL,
    source_fingerprint TEXT NOT NULL,
    raw_filename TEXT NOT NULL,
    source_category TEXT NOT NULL,
    parsed_title TEXT,
    parsed_year INTEGER,
    review_type TEXT NOT NULL DEFAULT 'ambiguous_title',
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','approved','rejected','resolved')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_fingerprint, review_type)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    actor_id INTEGER REFERENCES members(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    object_type TEXT,
    object_id INTEGER,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

