"""In-process async job runner with progress, persisted in SQLite (architecture ② "long fetches run as jobs").

A job is a coroutine factory `fn(progress) -> dict`. Status flow:
queued -> fetching -> processing -> done | error.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Awaitable, Callable

from ..storage.db import Database
from ..timeseries.service import classify_error

log = logging.getLogger("etd.jobs")
JobFn = Callable[[Callable[[float, str], Awaitable[None]]], Awaitable[dict]]


class JobManager:
    def __init__(self, db: Database, max_concurrent: int = 4):
        self.db = db
        self.sem = asyncio.Semaphore(max_concurrent)
        self.tasks: dict[str, asyncio.Task] = {}

    def submit(self, kind: str, request: dict, fn: JobFn) -> str:
        job_id = f"j_{uuid.uuid4().hex[:16]}"
        self.db.create_job(job_id, kind, request)
        self.tasks[job_id] = asyncio.create_task(self._run(job_id, fn))
        return job_id

    async def _run(self, job_id: str, fn: JobFn) -> None:
        last = {"t": 0.0}

        async def progress(frac: float, msg: str) -> None:
            now = time.monotonic()
            status = "fetching" if frac < 0.85 else "processing"
            if now - last["t"] > 0.25 or frac >= 1.0:   # throttle DB writes
                last["t"] = now
                self.db.update_job(job_id, status=status, progress=round(min(max(frac, 0.0), 1.0), 3), message=msg)

        try:
            async with self.sem:
                self.db.update_job(job_id, status="fetching", progress=0.01, message="started")
                result = await fn(progress)
            self.db.update_job(job_id, status="done", progress=1.0, message="done", result=result)
        except asyncio.CancelledError:
            self.db.update_job(job_id, status="error", error={"code": "cancelled", "message": "Job cancelled"})
            raise
        except Exception as exc:  # noqa: BLE001 - every failure is reported on the job
            log.exception("job %s failed", job_id)
            self.db.update_job(job_id, status="error", error=classify_error(exc))
        finally:
            self.tasks.pop(job_id, None)

    async def wait(self, job_id: str, timeout: float = 30.0) -> dict | None:
        t = self.tasks.get(job_id)
        if t:
            try:
                await asyncio.wait_for(asyncio.shield(t), timeout)
            except asyncio.TimeoutError:
                pass
        return self.db.get_job(job_id)

    async def shutdown(self) -> None:
        for t in list(self.tasks.values()):
            t.cancel()
        await asyncio.gather(*self.tasks.values(), return_exceptions=True)
