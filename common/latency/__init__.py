"""
Latency Optimization for PyFault framework.
"""

import asyncio
import heapq
import random
import statistics
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from pyfault.common.time import utc_now

T = TypeVar("T")


class LatencyPercentile(str, Enum):
    """Latency percentile."""
    P50 = "p50"
    P75 = "p75"
    P90 = "p90"
    P95 = "p95"
    P99 = "p99"
    P999 = "p999"


@dataclass
class LatencySample:
    """A single latency sample."""
    operation: str
    latency_ms: float
    timestamp: datetime = field(default_factory=utc_now)
    tags: dict[str, str] = field(default_factory=dict)
    success: bool = True


@dataclass
class LatencyStats:
    """Latency statistics."""
    count: int = 0
    min_ms: float = 0.0
    max_ms: float = 0.0
    mean_ms: float = 0.0
    median_ms: float = 0.0
    std_dev_ms: float = 0.0
    percentiles: dict[str, float] = field(default_factory=dict)
    error_count: int = 0
    error_rate: float = 0.0
    throughput_per_sec: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "min_ms": self.min_ms,
            "max_ms": self.max_ms,
            "mean_ms": self.mean_ms,
            "median_ms": self.median_ms,
            "std_dev_ms": self.std_dev_ms,
            "percentiles": self.percentiles,
            "error_count": self.error_count,
            "error_rate": self.error_rate,
            "throughput_per_sec": self.throughput_per_sec,
        }


class LatencyTracker:
    """
    Tracks latency statistics for operations.
    """

    def __init__(
        self,
        window_size: int = 10000,
        percentile_buckets: Optional[list[str]] = None,
    ):
        self.window_size = window_size
        self.percentile_buckets = percentile_buckets or [
            "p50", "p75", "p90", "p95", "p99", "p999"
        ]
        self._samples: list[LatencySample] = []
        self._lock = asyncio.Lock()

    def record(self, operation: str, latency_ms: float, success: bool = True, tags: Optional[dict[str, str]] = None) -> None:
        """Record a latency sample."""
        sample = LatencySample(
            operation=operation,
            latency_ms=latency_ms,
            success=success,
            tags=tags or {},
        )
        self._samples.append(sample)

        # Trim window to the configured size
        if len(self._samples) > self.window_size:
            self._samples = self._samples[-self.window_size:]

    def get_stats(self, operation: Optional[str] = None, since: Optional[datetime] = None) -> LatencyStats:
        """Get latency statistics."""
        samples = self._samples

        if operation:
            samples = [s for s in samples if s.operation == operation]

        if since:
            samples = [s for s in samples if s.timestamp >= since]

        if not samples:
            return LatencyStats()

        latencies = [s.latency_ms for s in samples if s.success]
        errors = [s for s in samples if not s.success]

        if not latencies:
            return LatencyStats(
                count=len(samples),
                error_count=len(errors),
                error_rate=len(errors) / len(samples) if samples else 0.0,
            )

        latencies.sort()
        count = len(latencies)

        stats = LatencyStats(
            count=count,
            min_ms=latencies[0],
            max_ms=latencies[-1],
            mean_ms=statistics.mean(latencies),
            median_ms=statistics.median(latencies),
            std_dev_ms=statistics.stdev(latencies) if count > 1 else 0.0,
            error_count=len([s for s in samples if not s.success]),
            error_rate=len([s for s in samples if not s.success]) / len(samples) if samples else 0.0,
        )

        # Calculate percentiles
        for p in ["p50", "p75", "p90", "p95", "p99", "p999"]:
            # p999 means the 99.9th percentile, not 999/100.
            percentile = 0.999 if p == "p999" else float(p[1:]) / 100
            index = int(len(latencies) * percentile)
            stats.percentiles[p] = latencies[min(index, len(latencies) - 1)]

        return stats

    def get_operation_stats(self) -> dict[str, LatencyStats]:
        """Get stats grouped by operation."""
        operations = defaultdict(list)
        for sample in self._samples:
            operations[sample.operation].append(sample)

        result = {}
        for op, samples in operations.items():
            latencies = [s.latency_ms for s in samples if s.success]
            if not latencies:
                continue

            latencies.sort()
            count = len(latencies)
            stats = LatencyStats(
                count=count,
                min_ms=latencies[0],
                max_ms=latencies[-1],
                mean_ms=statistics.mean(latencies),
                median_ms=statistics.median(latencies),
                std_dev_ms=statistics.stdev(latencies) if count > 1 else 0.0,
            )

            for p in ["p50", "p75", "p90", "p95", "p99", "p999"]:
                percentile = 0.999 if p == "p999" else float(p[1:]) / 100
                index = int(len(latencies) * percentile)
                stats.percentiles[p] = latencies[min(index, len(latencies) - 1)]

            result[op] = stats

        return result

    def clear(self) -> None:
        """Clear all samples."""
        self._samples.clear()

    def get_recent_samples(self, limit: int = 100) -> list[LatencySample]:
        """Get recent samples."""
        return self._samples[-limit:]


class LatencyTrackerManager:
    """
    Manages multiple latency trackers for different services/operations.
    """

    def __init__(self) -> None:
        self._trackers: dict[str, LatencyTracker] = {}

    def get_tracker(self, name: str) -> LatencyTracker:
        """Get or create a latency tracker."""
        if name not in self._trackers:
            self._trackers[name] = LatencyTracker()
        return self._trackers[name]

    def record(self, tracker_name: str, operation: str, latency_ms: float, success: bool = True, tags: Optional[dict[str, str]] = None) -> None:
        """Record a latency sample."""
        tracker = self.get_tracker(tracker_name)
        tracker.record(operation, latency_ms, success, tags)

    def get_stats(self, tracker_name: str, operation: Optional[str] = None) -> "LatencyStats":
        """Get stats for a tracker."""
        tracker = self._trackers.get(tracker_name)
        if not tracker:
            return LatencyStats()
        return tracker.get_stats(operation)

    def get_all_stats(self) -> dict[str, dict[str, "LatencyStats"]]:
        """Get stats for all trackers."""
        result = {}
        for name, tracker in self._trackers.items():
            result[name] = tracker.get_operation_stats()
        return result

    def clear(self, tracker_name: Optional[str] = None) -> None:
        """Clear trackers."""
        if tracker_name:
            self._trackers.pop(tracker_name, None)
        else:
            self._trackers.clear()


# Global latency tracker manager
_latency_manager: Optional["LatencyTrackerManager"] = None


def get_latency_manager() -> "LatencyTrackerManager":
    """Get the global latency tracker manager."""
    global _latency_manager
    if _latency_manager is None:
        _latency_manager = LatencyTrackerManager()
    return _latency_manager


# Context manager for timing operations
class LatencyTimer:
    """Context manager for timing operations."""

    def __init__(
        self,
        tracker_name: str,
        operation: str,
        success: bool = True,
        tags: Optional[dict[str, str]] = None,
    ):
        self.tracker_name = tracker_name
        self.operation = operation
        self.success = success
        self.tags = tags or {}
        self.start_time: Optional[float] = None

    def __enter__(self) -> "LatencyTimer":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        latency_ms = (time.perf_counter() - (self.start_time or 0.0)) * 1000
        success = exc_type is None
        record_latency(
            tracker_name=self.tracker_name,
            operation=self.operation,
            latency_ms=latency_ms,
            success=success,
            tags=self.tags,
        )


# Decorator for timing functions
# Latency budgets and alerts
class LatencyBudget:
    """Latency budget for operations."""

    def __init__(
        self,
        operation: str,
        budget_ms: float,
        percentile: str = "p99",
        alert_threshold: float = 0.8,
    ):
        self.operation = operation
        self.budget_ms = budget_ms
        self.percentile = percentile
        self.alert_threshold = alert_threshold
        self._violations = 0
        self._last_alert: Optional[datetime] = None

    def check(self, latency_ms: float) -> bool:
        """Check if latency exceeds budget."""
        return latency_ms > self.budget_ms

    def is_critical(self, latency_ms: float) -> bool:
        """Check if latency is critically over budget."""
        return latency_ms > self.budget_ms * (1 + (1 - self.alert_threshold))

    def record_violation(self, latency_ms: float) -> bool:
        """Record a budget violation."""
        self._violations += 1
        self._last_alert = utc_now()
        return self._violations > 10  # Alert after 10 violations

    def get_status(self) -> dict[str, Any]:
        return {
            "operation": self.operation,
            "budget_ms": self.budget_ms,
            "percentile": self.percentile,
            "violations": self._violations,
            "last_alert": self._last_alert.isoformat() if self._last_alert else None,
        }


class LatencyBudgetManager:
    """Manages latency budgets for operations."""

    def __init__(self) -> None:
        self._budgets: dict[str, LatencyBudget] = {}

    def set_budget(
        self,
        operation: str,
        budget_ms: float,
        percentile: str = "p99",
        alert_threshold: float = 0.8,
    ) -> LatencyBudget:
        """Set a latency budget for an operation."""
        budget = LatencyBudget(operation, budget_ms, percentile, alert_threshold)
        self._budgets[operation] = budget
        return budget

    def get_budget(self, operation: str) -> Optional[LatencyBudget]:
        """Get budget for an operation."""
        return self._budgets.get(operation)

    def check_latency(self, operation: str, latency_ms: float) -> bool:
        """Check if latency exceeds budget."""
        budget = self._budgets.get(operation)
        if budget:
            return budget.check(latency_ms)
        return False

    def record_latency(self, operation: str, latency_ms: float) -> None:
        """Record a latency measurement."""
        budget = self._budgets.get(operation)
        if budget and budget.check(latency_ms):
            budget.record_violation(latency_ms)

    def get_violations(self) -> list[dict[str, Any]]:
        """Get all budget violations."""
        return [b.get_status() for b in self._budgets.values() if b._violations > 0]

    def clear_violations(self, operation: Optional[str] = None) -> None:
        """Clear violations."""
        if operation:
            if operation in self._budgets:
                self._budgets[operation]._violations = 0
        else:
            for budget in self._budgets.values():
                budget._violations = 0


# Global budget manager
_budget_manager: Optional["LatencyBudgetManager"] = None


def get_budget_manager() -> "LatencyBudgetManager":
    """Get the global latency budget manager."""
    global _budget_manager
    if _budget_manager is None:
        _budget_manager = LatencyBudgetManager()
    return _budget_manager


# Convenience functions
def record_latency(
    operation: str,
    latency_ms: float,
    tracker_name: str = "default",
    success: bool = True,
    tags: Optional[dict[str, str]] = None,
) -> None:
    """Record a latency sample."""
    manager = get_latency_manager()
    manager.record(
        tracker_name=tracker_name,
        operation=operation,
        latency_ms=latency_ms,
        success=success,
        tags=tags,
    )


def set_latency_budget(
    operation: str,
    budget_ms: float,
    percentile: str = "p99",
    alert_threshold: float = 0.8,
) -> "LatencyBudget":
    """Set a latency budget for an operation."""
    manager = get_budget_manager()
    return manager.set_budget(operation, budget_ms, percentile, alert_threshold)


def check_latency_budget(operation: str, latency_ms: float) -> bool:
    """Check if latency exceeds budget."""
    manager = get_budget_manager()
    return manager.check_latency(operation, latency_ms)


def latency_timer(tracker_name: str, operation: Optional[str] = None) -> LatencyTimer:
    """Context manager for timing operations."""
    from pyfault.common.latency import LatencyTimer
    return LatencyTimer(tracker_name, operation or tracker_name)


def timed(tracker_name: str, operation: Optional[str] = None, tags: Optional[dict[str, str]] = None) -> Callable[..., Any]:
    """Decorator to time a function."""
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        op_name = operation or func.__name__

        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            success = True
            try:
                result = await func(*args, **kwargs)
                return result
            except BaseException:
                success = False
                raise
            finally:
                latency_ms = (time.perf_counter() - start) * 1000
                record_latency(
                    tracker_name=tracker_name,
                    operation=op_name,
                    latency_ms=latency_ms,
                    success=success,
                    tags=tags,
                )

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            success = True
            try:
                result = func(*args, **kwargs)
                return result
            except BaseException:
                success = False
                raise
            finally:
                latency_ms = (time.perf_counter() - start) * 1000
                record_latency(
                    tracker_name=tracker_name,
                    operation=op_name,
                    latency_ms=latency_ms,
                    success=success,
                    tags=tags,
                )

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator
