"""FastAPI routes for durable asynchronous V2 jobs."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status

from opinion_agent.governance import RequestBudgetExceeded, SecurityPolicyError
from opinion_agent.observability import V2_JOB_SUBMISSIONS

from .auth import AuthenticationError, Principal, StaticTokenAuthenticator
from .jobs import (
    IdempotencyConflictError,
    JobDispatchError,
    JobRecord,
    JobService,
    JobSubmission,
    JobTrace,
    ProjectAuthorizationError,
)


def create_v2_router(
    service: JobService,
    authenticator: StaticTokenAuthenticator,
) -> APIRouter:
    router = APIRouter(prefix="/v2", tags=["v2-jobs"])

    def require_principal(
        api_key: str | None = Header(default=None, alias="X-API-Key"),
    ) -> Principal:
        try:
            return authenticator.authenticate(api_key)
        except AuthenticationError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="authentication required",
                headers={"WWW-Authenticate": "ApiKey"},
            ) from exc

    @router.post(
        "/jobs",
        response_model=JobRecord,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_job(
        submission: JobSubmission,
        response: Response,
        principal: Principal = Depends(require_principal),
        idempotency_key: str = Header(
            min_length=1,
            max_length=200,
            alias="Idempotency-Key",
        ),
    ) -> JobRecord:
        try:
            result = await service.submit(submission, idempotency_key, principal)
        except RequestBudgetExceeded as exc:
            V2_JOB_SUBMISSIONS.labels("request_budget_exceeded").inc()
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except SecurityPolicyError as exc:
            V2_JOB_SUBMISSIONS.labels("security_policy_rejected").inc()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except IdempotencyConflictError as exc:
            V2_JOB_SUBMISSIONS.labels("idempotency_conflict").inc()
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except JobDispatchError as exc:
            V2_JOB_SUBMISSIONS.labels("queue_failed").inc()
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ProjectAuthorizationError as exc:
            raise HTTPException(status_code=403, detail="project access denied") from exc
        V2_JOB_SUBMISSIONS.labels("replayed" if not result.created else "created").inc()
        response.headers["Idempotency-Replayed"] = str(not result.created).lower()
        return result.job

    @router.get("/jobs/{job_id}", response_model=JobRecord)
    async def get_job(
        job_id: UUID,
        principal: Principal = Depends(require_principal),
    ) -> JobRecord:
        try:
            job = await service.get(job_id, principal)
        except ProjectAuthorizationError as exc:
            raise HTTPException(status_code=403, detail="project access denied") from exc
        if job is None:
            raise HTTPException(status_code=404, detail="analysis job not found")
        return job

    @router.get("/jobs/{job_id}/trace", response_model=JobTrace)
    async def get_job_trace(
        job_id: UUID,
        principal: Principal = Depends(require_principal),
    ) -> JobTrace:
        try:
            trace = await service.get_trace(job_id, principal)
        except ProjectAuthorizationError as exc:
            raise HTTPException(status_code=403, detail="project access denied") from exc
        if trace is None:
            raise HTTPException(status_code=404, detail="analysis job not found")
        return trace

    return router
