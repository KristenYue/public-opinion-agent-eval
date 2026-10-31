-- Worker crash detection and replay checkpoints.

ALTER TABLE analysis_jobs
    ADD COLUMN lease_owner VARCHAR(200),
    ADD COLUMN lease_expires_at TIMESTAMPTZ,
    ADD COLUMN last_heartbeat_at TIMESTAMPTZ,
    ADD COLUMN recovery_count INTEGER NOT NULL DEFAULT 0 CHECK (recovery_count >= 0);

CREATE INDEX idx_analysis_jobs_expired_lease
    ON analysis_jobs(status, lease_expires_at)
    WHERE status = 'running';

ALTER TABLE agent_runs
    ADD COLUMN worker_id VARCHAR(200),
    ADD COLUMN heartbeat_at TIMESTAMPTZ,
    ADD COLUMN recovery_reason TEXT;

CREATE TABLE run_checkpoints (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    sequence_no INTEGER NOT NULL CHECK (sequence_no >= 0),
    checkpoint_kind VARCHAR(32) NOT NULL CHECK (
        checkpoint_kind IN ('input_replay', 'completed', 'failure')
    ),
    node_name VARCHAR(100) NOT NULL,
    state JSONB NOT NULL,
    state_sha256 CHAR(64) NOT NULL CHECK (state_sha256 ~ '^[0-9a-f]{64}$'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (run_id, sequence_no)
);

COMMENT ON TABLE run_checkpoints IS
    'V2.0 stores replay boundaries, not LangGraph node-level resume checkpoints.';
