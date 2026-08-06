from __future__ import annotations

import asyncio
import contextlib
from collections import deque

from .pipeline import PipelineRunner
from .schemas import JobEvent, JobRecord, JobStatus
from .storage import LocalStore, utc_now


class SerialGPUQueue:
    """Exactly one worker executes generation at a time.

    The API itself never imports model weights. Serial dispatch still matters for
    a locally running server/CLI: it prevents simultaneous GPU requests and is
    the memory-safety boundary for 6–16 GB profiles.
    """

    def __init__(self, store: LocalStore, runner: PipelineRunner) -> None:
        self.store = store
        self.runner = runner
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._pending_ids: deque[str] = deque()
        self._scheduled: set[str] = set()
        self._worker: asyncio.Task[None] | None = None
        self._active_job_id: str | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._worker = asyncio.create_task(self._work(), name="local3d-serial-gpu-worker")
        for job_id in self.store.recover_unfinished_jobs():
            await self.enqueue(job_id)

    async def stop(self) -> None:
        self._started = False
        if self._worker and not self._worker.done():
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker
        self._worker = None

    async def enqueue(self, job_id: str) -> bool:
        if job_id in self._scheduled:
            return False
        self._scheduled.add(job_id)
        self._pending_ids.append(job_id)
        await self._queue.put(job_id)
        self._refresh_queue_positions()
        return True

    async def _work(self) -> None:
        while True:
            job_id = await self._queue.get()
            self._active_job_id = job_id
            with contextlib.suppress(ValueError):
                self._pending_ids.remove(job_id)
            self._refresh_queue_positions()
            try:
                await self.runner.run(job_id)
            except Exception as exc:  # Runner normally persists errors; this keeps the worker alive if storage itself misbehaves.
                try:
                    self.runner._mark_failed(job_id, exc)
                except Exception:
                    pass
            finally:
                self._active_job_id = None
                self._scheduled.discard(job_id)
                self._refresh_queue_positions()
                self._queue.task_done()

    def _refresh_queue_positions(self) -> None:
        """Expose actual queue order without inventing a progress percentage."""

        if self._active_job_id:
            with contextlib.suppress(Exception):
                self.store.set_queue_position(self._active_job_id, 0)
        position = 1
        for job_id in self._pending_ids:
            try:
                job = self.store.get_job(job_id)
                self.store.set_queue_position(job_id, position if job.status == JobStatus.QUEUED else None)
                if job.status == JobStatus.QUEUED:
                    position += 1
            except Exception:
                continue

    def cancel(self, job_id: str) -> JobRecord:
        def mutate(job: JobRecord) -> None:
            if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return
            now = utc_now()
            job.status = JobStatus.CANCELLED
            job.stage = "cancelled"
            job.current_stage = "cancelled"
            job.stage_started_at = now
            job.queue_position = None
            job.progress_indeterminate = False
            job.eta_seconds = 0
            job.completed_at = now
            message = "Job cancelado antes da execução." if job.id != self._active_job_id else (
                "Cancelamento solicitado. O processo externo em curso pode levar até o timeout configurado para terminar."
            )
            job.events.append(JobEvent(at=now, stage="cancelled", message=message, progress=job.progress))
            job.events = job.events[-80:]

        result = self.store.mutate_job(job_id, mutate)
        self._refresh_queue_positions()
        return result

    def snapshot(self) -> dict:
        return {
            "policy": "serial-gpu",
            "concurrency": 1,
            "pending": sum(
                1
                for job_id in self._pending_ids
                if self.store.get_job(job_id).status == JobStatus.QUEUED
            ),
            "active_job_id": self._active_job_id,
            "worker_started": self._started,
        }
