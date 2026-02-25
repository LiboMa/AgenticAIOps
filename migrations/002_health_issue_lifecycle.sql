-- Migration 002: HealthIssue 7-state lifecycle tables
-- Version: 2

CREATE TABLE IF NOT EXISTS health_issues (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'medium',
    status TEXT NOT NULL DEFAULT 'open',
    issue_type TEXT NOT NULL DEFAULT 'unknown',
    namespace TEXT DEFAULT '',
    resource TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_health_issues_status ON health_issues(status);
CREATE INDEX IF NOT EXISTS idx_health_issues_severity ON health_issues(severity);
CREATE INDEX IF NOT EXISTS idx_health_issues_namespace ON health_issues(namespace);
CREATE INDEX IF NOT EXISTS idx_health_issues_created_at ON health_issues(created_at);

CREATE TABLE IF NOT EXISTS fix_plans (
    id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    steps TEXT DEFAULT '[]',
    risk_level TEXT DEFAULT 'low',
    confidence REAL DEFAULT 0.0,
    created_by TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    rejection_reason TEXT,
    FOREIGN KEY (issue_id) REFERENCES health_issues(id)
);

CREATE INDEX IF NOT EXISTS idx_fix_plans_issue_id ON fix_plans(issue_id);
CREATE INDEX IF NOT EXISTS idx_fix_plans_status ON fix_plans(status);

CREATE TABLE IF NOT EXISTS rca_results (
    id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL,
    root_cause TEXT NOT NULL,
    confidence REAL DEFAULT 0.0,
    evidence TEXT DEFAULT '[]',
    network_context TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT DEFAULT 'agent',
    FOREIGN KEY (issue_id) REFERENCES health_issues(id)
);

CREATE INDEX IF NOT EXISTS idx_rca_results_issue_id ON rca_results(issue_id);

CREATE TABLE IF NOT EXISTS timeline_events (
    id TEXT PRIMARY KEY,
    issue_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    from_status TEXT,
    to_status TEXT,
    details TEXT DEFAULT '{}',
    FOREIGN KEY (issue_id) REFERENCES health_issues(id)
);

CREATE INDEX IF NOT EXISTS idx_timeline_events_issue_id ON timeline_events(issue_id);
CREATE INDEX IF NOT EXISTS idx_timeline_events_timestamp ON timeline_events(timestamp);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- Record this migration
INSERT OR IGNORE INTO schema_version (version, applied_at)
VALUES (2, datetime('now'));

-- Status migration mapping (for reference, applied in Python code):
-- detected      → open
-- analyzing     → investigating
-- pending_fix   → fix_planned
-- fixing        → fix_executed
-- fixed         → resolved
-- failed        → open
-- acknowledged  → investigating
-- closed        → resolved
