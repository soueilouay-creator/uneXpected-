-- uneXpected Prompt Intelligence — additive version 3.
-- Prompt records are source-attributed, versioned and staged independently from activation.
BEGIN;

CREATE TABLE IF NOT EXISTS prompt_sources (
    source_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    record_json TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS prompts (
    prompt_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES prompt_sources(source_id),
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    category_id TEXT NOT NULL,
    status TEXT NOT NULL,
    active_version INTEGER,
    candidate_version INTEGER,
    created_at DOUBLE PRECISION NOT NULL,
    updated_at DOUBLE PRECISION NOT NULL,
    UNIQUE(source_id, external_id)
);
CREATE INDEX IF NOT EXISTS idx_prompts_status_category
    ON prompts(status, category_id);
CREATE INDEX IF NOT EXISTS idx_prompts_source
    ON prompts(source_id);

CREATE TABLE IF NOT EXISTS prompt_versions (
    prompt_id TEXT NOT NULL REFERENCES prompts(prompt_id),
    version INTEGER NOT NULL CHECK(version > 0),
    status TEXT NOT NULL,
    content_sha256 TEXT NOT NULL,
    body TEXT,
    record_json TEXT NOT NULL,
    created_at DOUBLE PRECISION NOT NULL,
    reviewed_at DOUBLE PRECISION,
    PRIMARY KEY(prompt_id, version)
);
CREATE INDEX IF NOT EXISTS idx_prompt_versions_status
    ON prompt_versions(status, created_at);

INSERT INTO schema_migrations(version, name, applied_at)
VALUES (3, '003_prompt_intelligence.sql', EXTRACT(EPOCH FROM clock_timestamp()))
ON CONFLICT(version) DO NOTHING;

COMMIT;
