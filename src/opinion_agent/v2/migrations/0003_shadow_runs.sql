-- Runtime candidate output is isolated from official agent_runs state.

CREATE TABLE shadow_runs (
    id UUID PRIMARY KEY,
    job_id UUID NOT NULL REFERENCES analysis_jobs(id) ON DELETE CASCADE,
    official_run_id UUID NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    trace_id VARCHAR(64) NOT NULL,
    candidate_name VARCHAR(200) NOT NULL,
    status VARCHAR(32) NOT NULL CHECK (
        status IN ('succeeded', 'failed', 'timed_out')
    ),
    duration_ms DOUBLE PRECISION NOT NULL CHECK (duration_ms >= 0),
    result_payload JSONB,
    error_type VARCHAR(200),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (official_run_id, candidate_name)
);

CREATE INDEX idx_shadow_runs_job_created
    ON shadow_runs(job_id, created_at DESC);

COMMENT ON TABLE shadow_runs IS
    'Candidate-only audit records; never used to update official Job status or result.';
