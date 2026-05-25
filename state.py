"""In-memory task state manager with concurrency limit."""

import threading
import time
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    QUEUED = "queued"
    GENERATING_IMAGE = "generating_image"
    GENERATING_VIDEO = "generating_video"
    PACKAGING = "packaging"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    status: TaskStatus
    step_index: str = ""
    progress_message: str = ""
    download_url: str | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)
    ip: str = ""
    prompt_hash: str = ""


MAX_CONCURRENT = 10


class StateManager:
    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._lock = threading.Lock()

    @property
    def active_count(self) -> int:
        with self._lock:
            return sum(
                1
                for t in self._tasks.values()
                if t.status not in (TaskStatus.DONE, TaskStatus.FAILED)
            )

    def create(self, task_id: str, ip: str, prompt_hash: str) -> Task:
        if self.active_count >= MAX_CONCURRENT:
            raise RuntimeError("Service is busy. Please try again later.")
        task = Task(
            task_id=task_id,
            status=TaskStatus.QUEUED,
            step_index="0/3",
            progress_message="正在排队…",
            ip=ip,
            prompt_hash=prompt_hash,
        )
        with self._lock:
            self._tasks[task_id] = task
        return task

    def update(
        self,
        task_id: str,
        status: TaskStatus,
        step_index: str = "",
        progress_message: str = "",
        download_url: str | None = None,
        error: str | None = None,
    ) -> Task | None:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            return None
        task.status = status
        if step_index:
            task.step_index = step_index
        if progress_message:
            task.progress_message = progress_message
        if download_url:
            task.download_url = download_url
        if error:
            task.error = error
        return task

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    def find_by_ip_prompt(self, ip: str, prompt_hash: str, window: int = 300) -> Task | None:
        """Return existing task from same IP+prompt within window seconds."""
        cutoff = time.time() - window
        with self._lock:
            for t in self._tasks.values():
                if (
                    t.ip == ip
                    and t.prompt_hash == prompt_hash
                    and t.created_at >= cutoff
                    and t.status not in (TaskStatus.DONE, TaskStatus.FAILED)
                ):
                    return t
        return None

    def cleanup_stale(self, ttl: int = 1800) -> int:
        """Remove completed tasks older than TTL seconds."""
        cutoff = time.time() - ttl
        to_remove = [
            tid
            for tid, t in self._tasks.items()
            if t.created_at < cutoff
        ]
        with self._lock:
            for tid in to_remove:
                del self._tasks[tid]
        return len(to_remove)
