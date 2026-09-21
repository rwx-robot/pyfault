"""
Performance Utilities for PyFault framework.
"""

import time
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Optional


@dataclass
class PerformanceMetrics:
    """Performance metrics."""
    total_time: float = 0
    call_count: int = 0
    avg_time: float = 0
    min_time: float = float('inf')
    max_time: float = 0


class PerformanceMonitor:
    """Performance monitoring utility."""

    def __init__(self):
        self._metrics: dict[str, PerformanceMetrics] = {}

    def record(self, operation: str, duration: float):
        """Record performance metric."""
        if operation not in self._metrics:
            self._metrics[operation] = PerformanceMetrics()

        metrics = self._metrics[operation]
        metrics.total_time += duration
        metrics.call_count += 1
        metrics.avg_time = metrics.total_time / metrics.call_count
        metrics.min_time = min(metrics.min_time, duration)
        metrics.max_time = max(metrics.max_time, duration)

    def get_metrics(self, operation: str) -> Optional[PerformanceMetrics]:
        """Get metrics for operation."""
        return self._metrics.get(operation)

    def get_all_metrics(self) -> dict[str, PerformanceMetrics]:
        """Get all metrics."""
        return self._metrics.copy()

    def clear(self):
        """Clear all metrics."""
        self._metrics.clear()


class RateLimiter:
    """Rate limiter using token bucket algorithm."""

    def __init__(self, max_requests: int, window_seconds: int):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = {}

    def is_allowed(self, key: str) -> bool:
        """Check if request is allowed."""
        now = time.time()

        if key not in self._requests:
            self._requests[key] = []

        # Remove old requests outside window
        self._requests[key] = [
            req_time for req_time in self._requests[key]
            if now - req_time < self.window_seconds
        ]

        if len(self._requests[key]) < self.max_requests:
            self._requests[key].append(now)
            return True

        return False

    def get_remaining(self, key: str) -> int:
        """Get remaining requests."""
        now = time.time()

        if key not in self._requests:
            return self.max_requests

        # Remove old requests outside window
        self._requests[key] = [
            req_time for req_time in self._requests[key]
            if now - req_time < self.window_seconds
        ]

        return self.max_requests - len(self._requests[key])


def monitor(operation: str = None):
    """Decorator for monitoring function performance."""
    def decorator(func: Callable):
        op_name = operation or func.__name__

        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            result = await func(*args, **kwargs)
            duration = time.time() - start

            # Record to global monitor
            performance_monitor.record(op_name, duration)

            return result
        return wrapper
    return decorator


def rate_limit(max_requests: int, window_seconds: int):
    """Decorator for rate limiting."""
    limiter = RateLimiter(max_requests, window_seconds)

    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

            if not limiter.is_allowed(key):
                from pyfault.common.errors.handler import ConflictException
                raise ConflictException("Rate limit exceeded")

            return await func(*args, **kwargs)
        return wrapper
    return decorator


# Global performance monitor
performance_monitor = PerformanceMonitor()
