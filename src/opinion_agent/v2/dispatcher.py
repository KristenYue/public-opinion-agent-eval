"""Redis/ARQ queue adapter for V2 analysis jobs."""

from __future__ import annotations

from uuid import UUID


class ArqJobDispatcher:
    def __init__(self, redis_url: str, queue_name: str = "opinion-agent") -> None:
        if not redis_url.strip():
            raise ValueError("Redis URL must not be blank")
        self.redis_url = redis_url
        self.queue_name = queue_name
        self._pool = None

    async def _get_pool(self):
        if self._pool is None:
            try:
                from arq.connections import RedisSettings, create_pool
            except ImportError as exc:  # pragma: no cover - production extra
                raise RuntimeError(
                    "ARQ support requires: pip install -e '.[production]'"
                ) from exc
            self._pool = await create_pool(
                RedisSettings.from_dsn(self.redis_url),
                default_queue_name=self.queue_name,
            )
        return self._pool

    async def enqueue(self, job_id: UUID) -> None:
        pool = await self._get_pool()
        queued = await pool.enqueue_job(
            "run_analysis_job",
            str(job_id),
            _job_id=f"analysis-job:{job_id}",
        )
        if queued is None:
            raise RuntimeError("ARQ rejected a duplicate queue job identifier")

    async def ping(self) -> bool:
        pool = await self._get_pool()
        return bool(await pool.ping())

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.aclose()
            self._pool = None
