-- Project-scoped RBAC. Subjects are trusted identities supplied by the API
-- authentication boundary, not client-controlled request fields.

CREATE TABLE project_members (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    subject VARCHAR(200) NOT NULL,
    role VARCHAR(16) NOT NULL CHECK (role IN ('owner', 'analyst', 'viewer')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, subject)
);

CREATE INDEX idx_project_members_subject ON project_members(subject, project_id);
