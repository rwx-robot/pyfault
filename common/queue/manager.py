"""
Task Queue for PyFault framework.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional


class TaskStatus(str, Enum):
    """Task status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """Task data class."""
    id: str
    name: str
    status: TaskStatus
    result: Any = None
    error: Optional[str] = None
    created_at: float = 0
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


class TaskQueue:
    """Task queue for background processing."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}
        self._handlers: dict[str, Callable] = {}
        self._queue: asyncio.Queue = asyncio.Queue()

    def register_handler(self, name: str, handler: Callable) -> None:
        """Register a task handler."""
        self._handlers[name] = handler

    def task(self, name: Optional[str] = None) -> Callable[[Callable], Callable]:
        """Decorator for registering a task."""
        def decorator(func: Callable) -> Callable:
            task_name = name or func.__name__
            self._handlers[task_name] = func

            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                return await self.execute(task_name, *args, **kwargs)
            return wrapper
        return decorator

    async def execute(self, name: str, *args: Any, **kwargs: Any) -> str:
        """Execute a task."""
        task_id = str(uuid.uuid4())
        task = Task(
            id=task_id,
            name=name,
            status=TaskStatus.PENDING,
            created_at=time.time()
        )
        self._tasks[task_id] = task

        # Add to queue
        await self._queue.put((task_id, name, args, kwargs))

        return task_id

    async def process_next(self) -> None:
        """Process next task in queue."""
        if self._queue.empty():
            return

        task_id, name, args, kwargs = await self._queue.get()
        task = self._tasks.get(task_id)

        if not task or name not in self._handlers:
            return

        try:
            task.status = TaskStatus.RUNNING
            task.started_at = time.time()

            result = await self._handlers[name](*args, **kwargs)

            task.status = TaskStatus.COMPLETED
            task.result = result
            task.completed_at = time.time()
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            task.completed_at = time.time()

    def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        return self._tasks.get(task_id)

    def get_status(self, task_id: str) -> Optional[TaskStatus]:
        """Get task status."""
        task = self.get_task(task_id)
        return task.status if task else None


class QueueModule:
    """Queue module for dependency injection."""

    def __init__(self) -> None:
        self.queue = TaskQueue()

    def get_queue(self) -> TaskQueue:
        """Get task queue."""
        return self.queue
