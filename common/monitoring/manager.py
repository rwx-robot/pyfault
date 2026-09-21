"""
Monitoring Module for PyFault framework.
"""

import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class HealthStatus:
    """Health status."""
    status: str
    timestamp: datetime
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class Metric:
    """Metric data."""
    name: str
    value: float
    timestamp: datetime
    tags: dict[str, str] = field(default_factory=dict)


class HealthCheck:
    """Health check manager."""

    def __init__(self):
        self._checks: dict[str, Any] = {}

    def register_check(self, name: str, check_fn):
        """Register a health check."""
        self._checks[name] = check_fn

    def HealthCheck(self, name: str):
        """Decorator for registering a health check."""
        def decorator(func):
            self._checks[name] = func
            return func
        return decorator

    async def check(self) -> HealthStatus:
        """Run all health checks."""
        details = {}
        all_healthy = True

        for name, check_fn in self._checks.items():
            try:
                result = await check_fn()
                details[name] = {"status": "healthy", "details": result}
            except Exception as e:
                details[name] = {"status": "unhealthy", "error": str(e)}
                all_healthy = False

        return HealthStatus(
            status="healthy" if all_healthy else "unhealthy",
            timestamp=datetime.now(),
            details=details
        )


class MetricsCollector:
    """Metrics collector."""

    def __init__(self):
        self._metrics: list[Metric] = []

    def record(self, name: str, value: float, tags: dict[str, str] = None):
        """Record a metric."""
        metric = Metric(
            name=name,
            value=value,
            timestamp=datetime.now(),
            tags=tags or {}
        )
        self._metrics.append(metric)

    def counter(self, name: str, tags: dict[str, str] = None):
        """Decorator for counting function calls."""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                result = await func(*args, **kwargs)
                self.record(name, 1, tags)
                return result
            return wrapper
        return decorator

    def histogram(self, name: str, tags: dict[str, str] = None):
        """Decorator for measuring function duration."""
        def decorator(func):
            async def wrapper(*args, **kwargs):
                start = time.time()
                result = await func(*args, **kwargs)
                duration = time.time() - start
                self.record(name, duration, tags)
                return result
            return wrapper
        return decorator

    def get_metrics(self, name: str = None) -> list[Metric]:
        """Get metrics."""
        if name:
            return [m for m in self._metrics if m.name == name]
        return self._metrics


class MonitoringModule:
    """Monitoring module for dependency injection."""

    def __init__(self):
        self.health_check = HealthCheck()
        self.metrics = MetricsCollector()

    def get_health_check(self) -> HealthCheck:
        """Get health check."""
        return self.health_check

    def get_metrics(self) -> MetricsCollector:
        """Get metrics collector."""
        return self.metrics
