CREATE TABLE IF NOT EXISTS newsletter_deliveries (
    id INTEGER PRIMARY KEY,
    issue_id INTEGER NOT NULL REFERENCES newsletter_issues(id) ON DELETE CASCADE,
    subscriber_id INTEGER NOT NULL REFERENCES newsletter_subscribers(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','sent','failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    sent_at TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(issue_id, subscriber_id)
);

CREATE INDEX IF NOT EXISTS idx_newsletter_deliveries_issue
ON newsletter_deliveries(issue_id, status);
