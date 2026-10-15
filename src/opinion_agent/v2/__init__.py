"""Production V2 contracts for durable, auditable agent execution."""

from .contracts import (
    JobStatus,
    RunVersionSnapshot,
    VersionedComponent,
    assert_job_transition,
    can_transition_job,
)
from .jobs import JobRecord, JobService, JobSubmission
from .shadow import RuntimeAdapterShadowRunner, ShadowExecutor, ShadowRecord

__all__ = [
    "JobStatus",
    "RunVersionSnapshot",
    "VersionedComponent",
    "assert_job_transition",
    "can_transition_job",
    "JobRecord",
    "JobService",
    "JobSubmission",
    "ShadowExecutor",
    "ShadowRecord",
    "RuntimeAdapterShadowRunner",
]
