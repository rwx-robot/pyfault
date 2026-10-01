"""
Advanced Region Health Scoring for PyFault framework.

Provides comprehensive health assessment with:
- Multi-dimensional health scoring
- Circuit breaker integration
- Automatic degradation and recovery
- Health-based traffic routing
- Predictive health analysis
"""

import asyncio
import contextlib
import logging
import statistics
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional

from pyfault.common.time import utc_now

logger = logging.getLogger(__name__)


class HealthDimension(str, Enum):
    """Health check dimensions."""
    LATENCY = "latency"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"
    CAPACITY = "capacity"
    AVAILABILITY = "availability"
    DEPENDENCY = "dependency"
    CUSTOM = "custom"


class HealthStatus(str, Enum):
    """Overall health status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Individual health check result."""
    check_id: str
    dimension: HealthDimension
    service_name: str
    region_id: str
    timestamp: datetime = field(default_factory=utc_now)
    value: float = 0.0
    threshold: float = 0.0
    healthy: bool = True
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "dimension": self.dimension.value,
            "service_name": self.service_name,
            "region_id": self.region_id,
            "timestamp": self.timestamp.isoformat(),
            "value": self.value,
            "threshold": self.threshold,
            "healthy": self.healthy,
            "message": self.message,
            "metadata": self.metadata,
        }


@dataclass
class RegionHealthReport:
    """Comprehensive region health report."""
    region_id: str
    service_name: str
    overall_status: HealthStatus = HealthStatus.UNKNOWN
    overall_score: float = 0.0
    dimension_scores: dict[str, float] = field(default_factory=dict)
    checks: list[HealthCheckResult] = field(default_factory=list)
    last_updated: datetime = field(default_factory=utc_now)
    trend: str = "stable"  # improving, stable, degrading
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "service_name": self.service_name,
            "overall_status": self.overall_status.value,
            "overall_score": self.overall_score,
            "dimension_scores": self.dimension_scores,
            "checks": [c.to_dict() for c in self.checks],
            "last_updated": self.last_updated.isoformat(),
            "trend": self.trend,
            "metadata": self.metadata,
        }


class HealthChecker(ABC):
    """Abstract health checker."""

    @abstractmethod
    async def check(
        self,
        service_name: str,
        region_id: str,
    ) -> list[HealthCheckResult]:
        pass

    @abstractmethod
    def get_dimension(self) -> HealthDimension:
        pass


class LatencyHealthChecker:
    """Latency-based health checker."""

    def __init__(
        self,
        threshold_ms: float = 500.0,
        percentile: str = "p99",
        window_size: int = 100,
    ):
        self.threshold_ms = threshold_ms
        self.percentile = percentile
        self.window_size = window_size
        self._latencies: dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

    def record_latency(self, service_name: str, region_id: str, latency_ms: float) -> None:
        key = f"{service_name}:{region_id}"
        self._latencies[key].append(latency_ms)

    async def check(
        self,
        service_name: str,
        region_id: str,
    ) -> list[HealthCheckResult]:
        key = f"{service_name}:{region_id}"
        latencies = self._latencies.get(key, deque())

        if not latencies:
            return [HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.LATENCY,
                service_name=service_name,
                region_id=region_id,
                value=0.0,
                threshold=self.threshold_ms,
                healthy=True,
                message="No latency data available",
            )]

        latencies_list = sorted(latencies)
        p = float(self.percentile[1:]) / 100
        index = int(len(latencies_list) * p)
        percentile_value = latencies_list[min(index, len(latencies_list) - 1)]

        healthy = percentile_value <= self.threshold_ms

        return [HealthCheckResult(
            check_id=str(uuid.uuid4()),
            dimension=HealthDimension.LATENCY,
            service_name=service_name,
            region_id=region_id,
            value=percentile_value,
            threshold=self.threshold_ms,
            healthy=healthy,
            message=f"{self.percentile} latency: {percentile_value:.1f}ms (threshold: {self.threshold_ms}ms)",
            metadata={
                "percentile": self.percentile,
                "sample_count": len(latencies_list),
                "min": latencies_list[0],
                "max": latencies_list[-1],
                "mean": statistics.mean(latencies_list),
            },
        )]

    def get_dimension(self) -> HealthDimension:
        return HealthDimension.LATENCY


class ErrorRateHealthChecker:
    """Error rate health checker."""

    def __init__(
        self,
        threshold: float = 0.05,  # 5%
        window_size: int = 1000,
    ):
        self.threshold = threshold
        self.window_size = window_size
        self._requests: dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))

    def record_request(
        self,
        service_name: str,
        region_id: str,
        success: bool,
    ) -> None:
        key = f"{service_name}:{region_id}"
        self._requests[key].append(1 if success else 0)

    async def check(
        self,
        service_name: str,
        region_id: str,
    ) -> list[HealthCheckResult]:
        key = f"{service_name}:{region_id}"
        requests = self._requests.get(key, deque())

        if not requests:
            return [HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.ERROR_RATE,
                service_name=service_name,
                region_id=region_id,
                value=0.0,
                threshold=self.threshold,
                healthy=True,
                message="No request data available",
            )]

        error_count = sum(1 for r in requests if r == 0)
        error_rate = error_count / len(requests)
        healthy = error_rate <= self.threshold

        return [HealthCheckResult(
            check_id=str(uuid.uuid4()),
            dimension=HealthDimension.ERROR_RATE,
            service_name=service_name,
            region_id=region_id,
            value=error_rate,
            threshold=self.threshold,
            healthy=healthy,
            message=f"Error rate: {error_rate:.2%} (threshold: {self.threshold:.2%})",
            metadata={
                "total_requests": len(requests),
                "error_count": error_count,
                "success_count": len(requests) - error_count,
            },
        )]

    def get_dimension(self) -> HealthDimension:
        return HealthDimension.ERROR_RATE


class ThroughputHealthChecker:
    """Throughput health checker."""

    def __init__(
        self,
        min_throughput: float = 10.0,  # requests/sec
        window_seconds: int = 60,
    ):
        self.min_throughput = min_throughput
        self.window_seconds = window_seconds
        self._requests: dict[str, deque] = defaultdict(deque)

    def record_request(
        self,
        service_name: str,
        region_id: str,
        timestamp: Optional[datetime] = None,
    ) -> None:
        key = f"{service_name}:{region_id}"
        ts = timestamp or utc_now()
        self._requests[key].append(ts)
        # Clean old entries
        cutoff = utc_now() - timedelta(seconds=self.window_seconds)
        while self._requests[key] and self._requests[key][0] < cutoff:
            self._requests[key].popleft()

    async def check(
        self,
        service_name: str,
        region_id: str,
    ) -> list[HealthCheckResult]:
        key = f"{service_name}:{region_id}"
        requests = self._requests.get(key, deque())

        # Clean old entries
        cutoff = utc_now() - timedelta(seconds=self.window_seconds)
        while requests and requests[0] < cutoff:
            requests.popleft()

        if not requests:
            return [HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.THROUGHPUT,
                service_name=service_name,
                region_id=region_id,
                value=0.0,
                threshold=self.min_throughput,
                healthy=False,
                message="No throughput data available",
            )]

        throughput = len(requests) / self.window_seconds
        healthy = throughput >= self.min_throughput

        return [HealthCheckResult(
            check_id=str(uuid.uuid4()),
            dimension=HealthDimension.THROUGHPUT,
            service_name=service_name,
            region_id=region_id,
            value=throughput,
            threshold=self.min_throughput,
            healthy=healthy,
            message=f"Throughput: {throughput:.1f} req/s (min: {self.min_throughput} req/s)",
            metadata={
                "request_count": len(requests),
                "window_seconds": self.window_seconds,
            },
        )]

    def get_dimension(self) -> HealthDimension:
        return HealthDimension.THROUGHPUT


class CapacityHealthChecker:
    """Capacity/Resource health checker."""

    def __init__(
        self,
        cpu_threshold: float = 0.85,
        memory_threshold: float = 0.85,
        connection_threshold: float = 0.90,
    ):
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.connection_threshold = connection_threshold
        self._metrics: dict[str, dict[str, float]] = {}

    def update_metrics(
        self,
        service_name: str,
        region_id: str,
        cpu_usage: Optional[float] = None,
        memory_usage: Optional[float] = None,
        connection_usage: Optional[float] = None,
    ) -> None:
        key = f"{service_name}:{region_id}"
        if key not in self._metrics:
            self._metrics[key] = {}
        if cpu_usage is not None:
            self._metrics[key]["cpu"] = cpu_usage
        if memory_usage is not None:
            self._metrics[key]["memory"] = memory_usage
        if connection_usage is not None:
            self._metrics[key]["connections"] = connection_usage

    async def check(
        self,
        service_name: str,
        region_id: str,
    ) -> list[HealthCheckResult]:
        key = f"{service_name}:{region_id}"
        metrics = self._metrics.get(key, {})

        results = []

        # CPU check
        if "cpu" in metrics:
            cpu = metrics["cpu"]
            healthy = cpu <= self.cpu_threshold
            results.append(HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.CAPACITY,
                service_name=service_name,
                region_id=region_id,
                value=cpu,
                threshold=self.cpu_threshold,
                healthy=healthy,
                message=f"CPU usage: {cpu:.1%} (threshold: {self.cpu_threshold:.1%})",
                metadata={"resource": "cpu"},
            ))

        # Memory check
        if "memory" in metrics:
            mem = metrics["memory"]
            healthy = mem <= self.memory_threshold
            results.append(HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.CAPACITY,
                service_name=service_name,
                region_id=region_id,
                value=mem,
                threshold=self.memory_threshold,
                healthy=healthy,
                message=f"Memory usage: {mem:.1%} (threshold: {self.memory_threshold:.1%})",
                metadata={"resource": "memory"},
            ))

        # Connection check
        if "connections" in metrics:
            conn = metrics["connections"]
            healthy = conn <= self.connection_threshold
            results.append(HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.CAPACITY,
                service_name=service_name,
                region_id=region_id,
                value=conn,
                threshold=self.connection_threshold,
                healthy=healthy,
                message=f"Connection usage: {conn:.1%} (threshold: {self.connection_threshold:.1%})",
                metadata={"resource": "connections"},
            ))

        if not results:
            results.append(HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.CAPACITY,
                service_name=service_name,
                region_id=region_id,
                value=0.0,
                threshold=1.0,
                healthy=True,
                message="No capacity data available",
            ))

        return results

    def get_dimension(self) -> HealthDimension:
        return HealthDimension.CAPACITY


class AvailabilityHealthChecker:
    """Availability health checker (uptime/downtime)."""

    def __init__(
        self,
        uptime_threshold: float = 0.999,  # 99.9%
        window_hours: int = 24,
    ):
        self.uptime_threshold = uptime_threshold
        self.window_hours = window_hours
        self._downtimes: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
        self._current_downtime: dict[str, Optional[datetime]] = {}

    def record_downtime_start(
        self,
        service_name: str,
        region_id: str,
        timestamp: Optional[datetime] = None,
    ) -> None:
        key = f"{service_name}:{region_id}"
        ts = timestamp or utc_now()
        self._current_downtime[key] = ts

    def record_downtime_end(
        self,
        service_name: str,
        region_id: str,
        timestamp: Optional[datetime] = None,
    ) -> None:
        key = f"{service_name}:{region_id}"
        ts = timestamp or utc_now()
        start = self._current_downtime.get(key)
        if start:
            self._downtimes[key].append((start, ts))
            self._current_downtime[key] = None

    async def check(
        self,
        service_name: str,
        region_id: str,
    ) -> list[HealthCheckResult]:
        key = f"{service_name}:{region_id}"
        now = utc_now()
        window_start = now - timedelta(hours=self.window_hours)

        # Calculate total downtime in window
        total_downtime = timedelta(0)
        for start, end in self._downtimes.get(key, []):
            if end >= window_start:
                actual_start = max(start, window_start)
                total_downtime += end - actual_start

        # Check current ongoing downtime
        current_start = self._current_downtime.get(key)
        if current_start and current_start >= window_start:
            total_downtime += now - current_start
        elif current_start and current_start < window_start:
            total_downtime += now - window_start

        total_window = timedelta(hours=self.window_hours)
        uptime = 1.0 - (total_downtime.total_seconds() / total_window.total_seconds())
        uptime = max(0.0, min(1.0, uptime))
        healthy = uptime >= self.uptime_threshold

        return [HealthCheckResult(
            check_id=str(uuid.uuid4()),
            dimension=HealthDimension.AVAILABILITY,
            service_name=service_name,
            region_id=region_id,
            value=uptime,
            threshold=self.uptime_threshold,
            healthy=healthy,
            message=f"Uptime: {uptime:.3%} (threshold: {self.uptime_threshold:.3%})",
            metadata={
                "downtime_seconds": total_downtime.total_seconds(),
                "window_hours": self.window_hours,
                "currently_down": current_start is not None,
            },
        )]

    def get_dimension(self) -> HealthDimension:
        return HealthDimension.AVAILABILITY


class DependencyHealthChecker:
    """Dependency health checker (downstream services)."""

    def __init__(self) -> None:
        self._dependencies: dict[str, list[tuple[str, str]]] = defaultdict(list)  # service -> [(dep_service, dep_region)]
        self._dependency_health: dict[str, bool] = {}

    def add_dependency(
        self,
        service_name: str,
        region_id: str,
        dep_service: str,
        dep_region: str,
    ) -> None:
        key = f"{service_name}:{region_id}"
        self._dependencies[key].append((dep_service, dep_region))

    def update_dependency_health(
        self,
        dep_service: str,
        dep_region: str,
        healthy: bool,
    ) -> None:
        key = f"{dep_service}:{dep_region}"
        self._dependency_health[key] = healthy

    async def check(
        self,
        service_name: str,
        region_id: str,
    ) -> list[HealthCheckResult]:
        key = f"{service_name}:{region_id}"
        deps = self._dependencies.get(key, [])

        if not deps:
            return [HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.DEPENDENCY,
                service_name=service_name,
                region_id=region_id,
                value=1.0,
                threshold=1.0,
                healthy=True,
                message="No dependencies configured",
            )]

        healthy_count = 0
        total_count = len(deps)
        unhealthy_deps = []

        for dep_service, dep_region in deps:
            dep_key = f"{dep_service}:{dep_region}"
            healthy = self._dependency_health.get(dep_key, True)
            if healthy:
                healthy_count += 1
            else:
                unhealthy_deps.append(f"{dep_service}:{dep_region}")

        health_ratio = healthy_count / total_count if total_count > 0 else 1.0
        healthy = health_ratio >= 0.8  # 80% dependencies healthy

        return [HealthCheckResult(
            check_id=str(uuid.uuid4()),
            dimension=HealthDimension.DEPENDENCY,
            service_name=service_name,
            region_id=region_id,
            value=health_ratio,
            threshold=0.8,
            healthy=healthy,
            message=f"Dependencies healthy: {healthy_count}/{total_count}",
            metadata={
                "total_dependencies": total_count,
                "healthy_dependencies": healthy_count,
                "unhealthy_dependencies": unhealthy_deps,
            },
        )]

    def get_dimension(self) -> HealthDimension:
        return HealthDimension.DEPENDENCY


class CustomHealthChecker(HealthChecker):
    """Custom health checker with user-defined function."""

    def __init__(
        self,
        name: str,
        checker_func: Callable[[str, str], Any],
        threshold: float = 0.5,
    ):
        self.name = name
        self.checker_func = checker_func
        self.threshold = threshold

    async def check(
        self,
        service_name: str,
        region_id: str,
    ) -> list[HealthCheckResult]:
        try:
            if asyncio.iscoroutinefunction(self.checker_func):
                result = await self.checker_func(service_name, region_id)
            else:
                result = self.checker_func(service_name, region_id)

            if isinstance(result, dict):
                value = result.get("value", 0.0)
                healthy = result.get("healthy", True)
                message = result.get("message", "")
                metadata = result.get("metadata", {})
            else:
                value = float(result)
                healthy = value >= self.threshold
                message = f"Custom check: {value}"
                metadata = {}

            return [HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.CUSTOM,
                service_name=service_name,
                region_id=region_id,
                value=value,
                threshold=self.threshold,
                healthy=healthy,
                message=message,
                metadata={"custom_check": self.name, **metadata},
            )]
        except Exception as e:
            return [HealthCheckResult(
                check_id=str(uuid.uuid4()),
                dimension=HealthDimension.CUSTOM,
                service_name=service_name,
                region_id=region_id,
                value=0.0,
                threshold=self.threshold,
                healthy=False,
                message=f"Custom check failed: {e}",
                metadata={"custom_check": self.name, "error": str(e)},
            )]

    def get_dimension(self) -> HealthDimension:
        return HealthDimension.CUSTOM


class HealthScorer:
    """
    Calculates weighted health scores from multiple dimensions.
    """

    def __init__(self, weights: Optional[dict[HealthDimension, float]] = None):
        self.weights = weights or {
            HealthDimension.LATENCY: 0.25,
            HealthDimension.ERROR_RATE: 0.25,
            HealthDimension.THROUGHPUT: 0.15,
            HealthDimension.CAPACITY: 0.15,
            HealthDimension.AVAILABILITY: 0.15,
            HealthDimension.DEPENDENCY: 0.05,
        }
        # Normalize weights
        total = sum(self.weights.values())
        if total > 0:
            self.weights = {k: v / total for k, v in self.weights.items()}

    def calculate_score(
        self,
        checks: list[HealthCheckResult],
    ) -> tuple[float, dict[str, float]]:
        """Calculate overall score and dimension scores."""
        dimension_scores: dict[HealthDimension, list[float]] = {}

        # Group checks by dimension
        for check in checks:
            dim = check.dimension
            if dim not in dimension_scores:
                dimension_scores[dim] = []
            # Normalize: 1.0 for healthy, 0.0 for unhealthy
            # For healthy checks, score based on how far from threshold
            if check.healthy:
                if check.threshold > 0:
                    # For latency/error_rate: lower is better
                    if dim in (HealthDimension.LATENCY, HealthDimension.ERROR_RATE):
                        score = 1.0 - min(check.value / check.threshold, 1.0)
                    # For throughput/availability: higher is better
                    else:
                        score = min(check.value / check.threshold, 1.0) if check.threshold > 0 else 1.0
                else:
                    score = 1.0
            else:
                score = 0.0
            dimension_scores[dim].append(score)

        # Average scores per dimension
        final_dimension_scores = {}
        for dim, scores in dimension_scores.items():
            final_dimension_scores[dim.value] = statistics.mean(scores) if scores else 1.0

        # Weighted overall score
        overall_score = 0.0
        for dim, weight in self.weights.items():
            if dim.value in final_dimension_scores:
                overall_score += final_dimension_scores[dim.value] * weight

        return overall_score, final_dimension_scores

    def determine_status(self, score: float) -> HealthStatus:
        """Determine overall health status from score."""
        if score >= 0.9:
            return HealthStatus.HEALTHY
        elif score >= 0.7:
            return HealthStatus.DEGRADED
        elif score >= 0.4:
            return HealthStatus.UNHEALTHY
        else:
            return HealthStatus.CRITICAL


class CircuitBreakerState(str, Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """
    Circuit breaker for region-level fault isolation.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        success_threshold: int = 2,
        timeout: float = 30.0,
        half_open_requests: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.success_threshold = success_threshold
        self.timeout = timeout
        self.half_open_requests = half_open_requests

        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._half_open_successes = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitBreakerState:
        return self._state

    @property
    def is_available(self) -> bool:
        if self._state == CircuitBreakerState.CLOSED:
            return True
        elif self._state == CircuitBreakerState.OPEN:
            # Check if timeout elapsed
            if self._last_failure_time:
                elapsed = (utc_now() - self._last_failure_time).total_seconds()
                if elapsed >= self.timeout:
                    return True  # Allow transition to half-open
            return False
        else:  # HALF_OPEN
            return True

    async def record_success(self) -> None:
        async with self._lock:
            if self._state == CircuitBreakerState.HALF_OPEN:
                self._half_open_successes += 1
                if self._half_open_successes >= self.success_threshold:
                    self._state = CircuitBreakerState.CLOSED
                    self._failure_count = 0
                    self._half_open_successes = 0
                    logger.info("Circuit breaker CLOSED (recovered)")
            elif self._state == CircuitBreakerState.CLOSED:
                self._failure_count = 0

    async def record_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = utc_now()

            if self._state == CircuitBreakerState.HALF_OPEN:
                self._state = CircuitBreakerState.OPEN
                self._half_open_successes = 0
                logger.warning("Circuit breaker OPEN (half-open failed)")
            elif self._state == CircuitBreakerState.CLOSED:
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitBreakerState.OPEN
                    logger.warning(f"Circuit breaker OPEN (threshold reached: {self._failure_count})")

    async def allow_request(self) -> bool:
        """Check if request should be allowed."""
        if self._state == CircuitBreakerState.CLOSED:
            return True
        elif self._state == CircuitBreakerState.OPEN:
            # Check timeout
            if self._last_failure_time:
                elapsed = (utc_now() - self._last_failure_time).total_seconds()
                if elapsed >= self.timeout:
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._half_open_successes = 0
                    logger.info("Circuit breaker HALF_OPEN (testing recovery)")
                    return True
            return False
        else:  # HALF_OPEN
            return True

    def get_status(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "half_open_successes": self._half_open_successes,
            "is_available": self.is_available,
        }


class RegionHealthManager:
    """
    Manages health assessment for all regions and services.
    """

    def __init__(
        self,
        check_interval: int = 30,
        scorer: Optional[HealthScorer] = None,
    ):
        self.check_interval = check_interval
        self.scorer = scorer or HealthScorer()
        self._checkers: list[HealthChecker] = []
        self._custom_checkers: dict[str, CustomHealthChecker] = {}
        self._reports: dict[str, RegionHealthReport] = {}  # service:region -> report
        self._circuit_breakers: dict[str, CircuitBreaker] = {}  # service:region -> breaker
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._callbacks: list[Callable] = []

    def add_checker(self, checker: HealthChecker) -> None:
        self._checkers.append(checker)

    def add_custom_checker(self, name: str, checker: CustomHealthChecker) -> None:
        self._custom_checkers[name] = checker

    def get_circuit_breaker(self, service_name: str, region_id: str) -> CircuitBreaker:
        key = f"{service_name}:{region_id}"
        if key not in self._circuit_breakers:
            self._circuit_breakers[key] = CircuitBreaker()
        return self._circuit_breakers[key]

    async def check_health(
        self,
        service_name: str,
        region_id: str,
    ) -> RegionHealthReport:
        """Run all health checks for a service in a region."""
        all_checks = []

        # Run built-in checkers
        for checker in self._checkers:
            try:
                results = await checker.check(service_name, region_id)
                all_checks.extend(results)
            except Exception as e:
                logger.error(f"Health check failed for {checker.get_dimension()}: {e}")
                all_checks.append(HealthCheckResult(
                    check_id=str(uuid.uuid4()),
                    dimension=checker.get_dimension(),
                    service_name=service_name,
                    region_id=region_id,
                    value=0.0,
                    threshold=0.0,
                    healthy=False,
                    message=f"Check failed: {e}",
                ))

        # Run custom checkers
        for name, checker in self._custom_checkers.items():
            try:
                results = await checker.check(service_name, region_id)
                all_checks.extend(results)
            except Exception as e:
                logger.error(f"Custom health check {name} failed: {e}")

        # Calculate score and status
        overall_score, dimension_scores = self.scorer.calculate_score(all_checks)
        overall_status = self.scorer.determine_status(overall_score)

        # Determine trend
        key = f"{service_name}:{region_id}"
        self._history[key].append(overall_score)
        trend = "stable"
        if len(self._history[key]) >= 5:
            recent = list(self._history[key])[-5:]
            if recent[-1] > recent[0] + 0.1:
                trend = "improving"
            elif recent[-1] < recent[0] - 0.1:
                trend = "degrading"

        # Create report
        report = RegionHealthReport(
            region_id=region_id,
            service_name=service_name,
            overall_status=overall_status,
            overall_score=overall_score,
            dimension_scores=dimension_scores,
            checks=all_checks,
            trend=trend,
        )

        self._reports[key] = report

        # Check circuit breaker
        breaker = self.get_circuit_breaker(service_name, region_id)
        if overall_status in (HealthStatus.UNHEALTHY, HealthStatus.CRITICAL):
            await breaker.record_failure()
        elif overall_status == HealthStatus.HEALTHY:
            await breaker.record_success()

        # Notify callbacks
        for callback in self._callbacks:
            try:
                await callback(report)
            except Exception as e:
                logger.error(f"Health callback error: {e}")

        return report

    async def check_all(self, services: list[tuple[str, str]]) -> list[RegionHealthReport]:
        """Check health for multiple service-region pairs."""
        tasks = [self.check_health(svc, reg) for svc, reg in services]
        return await asyncio.gather(*tasks)

    def get_report(self, service_name: str, region_id: str) -> Optional[RegionHealthReport]:
        key = f"{service_name}:{region_id}"
        return self._reports.get(key)

    def get_all_reports(self) -> dict[str, RegionHealthReport]:
        return self._reports.copy()

    def get_service_health(self, service_name: str) -> list[RegionHealthReport]:
        return [
            r for k, r in self._reports.items()
            if k.startswith(f"{service_name}:")
        ]

    def get_region_health(self, region_id: str) -> list[RegionHealthReport]:
        return [
            r for k, r in self._reports.items()
            if k.endswith(f":{region_id}")
        ]

    def add_callback(self, callback: Callable) -> None:
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start periodic health checks."""
        self._running = True
        self._task = asyncio.create_task(self._check_loop())
        logger.info("Region health manager started")

    async def stop(self) -> None:
        """Stop health checks."""
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Region health manager stopped")

    async def _check_loop(self) -> None:
        while self._running:
            try:
                # This would need a list of services to check
                # In practice, you'd register services to monitor
                pass
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
            await asyncio.sleep(self.check_interval)


class HealthBasedRouter:
    """
    Routes traffic based on health scores.
    """

    def __init__(self, health_manager: RegionHealthManager):
        self.health_manager = health_manager
        self._min_health_score = 0.5

    async def select_region(
        self,
        service_name: str,
        available_regions: list[str],
        strategy: str = "best_health",
    ) -> Optional[str]:
        """Select best region based on health."""
        reports = []
        for region_id in available_regions:
            report = self.health_manager.get_report(service_name, region_id)
            if report:
                reports.append((region_id, report))

        if not reports:
            return available_regions[0] if available_regions else None

        # Filter by circuit breaker
        available = []
        for region_id, report in reports:
            breaker = self.health_manager.get_circuit_breaker(service_name, region_id)
            if breaker.is_available:
                available.append((region_id, report))

        if not available:
            # All circuits open, return primary or first
            return reports[0][0]

        if strategy == "best_health":
            available.sort(key=lambda x: x[1].overall_score, reverse=True)
            return available[0][0]
        elif strategy == "healthy_only":
            healthy = [(r, rep) for r, rep in available if rep.overall_score >= self._min_health_score]
            if healthy:
                healthy.sort(key=lambda x: x[1].overall_score, reverse=True)
                return healthy[0][0]
            return available[0][0]
        elif strategy == "round_robin_healthy":
            healthy = [(r, rep) for r, rep in available if rep.overall_score >= self._min_health_score]
            if not healthy:
                return available[0][0]
            # Simple round-robin (would need state in practice)
            return healthy[0][0]

        return available[0][0]


# Global instances
_health_manager: Optional[RegionHealthManager] = None


def get_health_manager() -> RegionHealthManager:
    global _health_manager
    if _health_manager is None:
        _health_manager = RegionHealthManager()
    return _health_manager


def set_health_manager(manager: RegionHealthManager) -> None:
    global _health_manager
    _health_manager = manager


