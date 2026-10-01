"""
Failover Management for PyFault framework.
"""

import asyncio
import contextlib
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar

from pyfault.common.time import utc_now

logger = logging.getLogger(__name__)


class FailoverStatus(str, Enum):
    """Failover status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILING = "failing"
    FAILED = "failed"
    RECOVERING = "recovering"
    FAILOVER_IN_PROGRESS = "failover_in_progress"
    FAILOVER_COMPLETED = "failover_completed"
    FAILOVER_FAILED = "failover_failed"


class FailoverTrigger(str, Enum):
    """Failover trigger type."""
    HEALTH_CHECK_FAILURE = "health_check_failure"
    LATENCY_THRESHOLD = "latency_threshold"
    ERROR_RATE_THRESHOLD = "error_rate_threshold"
    CAPACITY_THRESHOLD = "capacity_threshold"
    MANUAL = "manual"
    NETWORK_PARTITION = "network_partition"


@dataclass
class FailoverConfig:
    """Failover configuration."""
    service_name: str
    primary_region: str
    backup_regions: list[str]
    health_check_interval_ms: int = 10000
    failure_threshold: int = 3
    recovery_threshold: int = 2
    latency_threshold_ms: int = 5000
    error_rate_threshold: float = 0.05  # 5%
    capacity_threshold: float = 0.9  # 90%
    failover_timeout_ms: int = 30000
    auto_failback: bool = True
    failback_delay_ms: int = 60000
    health_check_timeout_ms: int = 5000


@dataclass
class FailoverEvent:
    """Failover event record."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    service_name: str = ""
    trigger: FailoverTrigger = FailoverTrigger.MANUAL
    from_region: str = ""
    to_region: str = ""
    timestamp: datetime = field(default_factory=utc_now)
    duration_ms: Optional[int] = None
    success: bool = False
    error_message: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheckResult:
    """Health check result."""
    service_name: str
    region: str
    timestamp: datetime
    healthy: bool
    latency_ms: float
    error_rate: float
    capacity_used: float
    error_message: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


class HealthChecker(ABC):
    """Abstract health checker."""

    @abstractmethod
    async def check(
        self, service_name: str, region: str, endpoint: str
    ) -> HealthCheckResult:
        """Perform health check."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the health checker."""
        pass


class HTTPHealthChecker(HealthChecker):
    """HTTP-based health checker."""

    def __init__(self, timeout_ms: int = 5000):
        self.timeout_ms = timeout_ms

    async def check(self, service_name: str, region: str, endpoint: str) -> "HealthCheckResult":
        """Perform HTTP health check."""
        import aiohttp
        start = time.time()

        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout_ms / 1000)
            ) as session, session.get(f"{endpoint}/health") as response:
                latency_ms = (time.time() - start) * 1000

                if response.status == 200:
                    return HealthCheckResult(
                        service_name=service_name,
                        region=region,
                        timestamp=utc_now(),
                        healthy=True,
                        latency_ms=latency_ms,
                        error_rate=0.0,
                        capacity_used=0.0,
                    )
                else:
                    return HealthCheckResult(
                        service_name=service_name,
                        region=region,
                        timestamp=utc_now(),
                        healthy=False,
                        latency_ms=latency_ms,
                        error_rate=1.0,
                        capacity_used=0.0,
                        error_message=f"HTTP {response.status}",
                    )
        except asyncio.TimeoutError:
            return HealthCheckResult(
                service_name=service_name,
                region=region,
                timestamp=utc_now(),
                healthy=False,
                latency_ms=self.timeout_ms,
                error_rate=1.0,
                capacity_used=0.0,
                error_message="Timeout",
            )
        except Exception as e:
            return HealthCheckResult(
                service_name=service_name,
                region=region,
                timestamp=utc_now(),
                healthy=False,
                latency_ms=(time.time() - start) * 1000,
                error_rate=1.0,
                capacity_used=0.0,
                error_message=str(e),
            )

    async def close(self) -> None:
        pass


class FailoverPolicy(ABC):
    """Abstract failover policy."""

    @abstractmethod
    async def should_failover(
        self,
        service_name: str,
        current_region: str,
        health_results: dict[str, "HealthCheckResult"],
        config: "FailoverConfig",
    ) -> Optional[str]:
        """Determine if failover should occur and to which region."""
        pass

    @abstractmethod
    async def should_failback(
        self,
        service_name: str,
        current_region: str,
        original_region: str,
        health_results: dict[str, "HealthCheckResult"],
        config: "FailoverConfig",
    ) -> bool:
        """Determine if failback should occur."""
        pass


class PriorityFailoverPolicy:
    """Priority-based failover policy."""

    async def should_failover(
        self,
        service_name: str,
        current_region: str,
        health_results: dict[str, "HealthCheckResult"],
        config: "FailoverConfig",
    ) -> Optional[str]:
        """Failover to the first healthy backup region."""
        if current_region not in health_results:
            return None

        current_health = health_results[current_region]
        if not current_health.healthy:
            # Find first healthy backup region
            for backup_region in config.backup_regions:
                if backup_region in health_results:
                    backup_health = health_results[backup_region]
                    if backup_health.healthy:
                        return backup_region

        # Check if current region is degrading
        if not current_health.healthy:
            # Check failure thresholds
            failure_count = 0
            for _region, health in health_results.items():
                if not health.healthy:
                    failure_count += 1

            if failure_count >= config.failure_threshold:
                # Find first healthy backup
                for backup_region in config.backup_regions:
                    if backup_region in health_results and health_results[backup_region].healthy:
                        return backup_region

        return None

    async def should_failback(
        self,
        service_name: str,
        current_region: str,
        original_region: str,
        health_results: dict[str, "HealthCheckResult"],
        config: "FailoverConfig",
    ) -> bool:
        if not config.auto_failback:
            return False

        original_health = health_results.get(original_region)
        # Check if original region has been healthy for the required period
        # This would need state tracking in a real implementation
        return bool(original_health and original_health.healthy)


class LatencyBasedFailoverPolicy:
    """Latency-based failover policy."""

    async def should_failover(
        self,
        service_name: str,
        current_region: str,
        health_results: dict[str, "HealthCheckResult"],
        config: "FailoverConfig",
    ) -> Optional[str]:
        current_health = health_results.get(current_region)
        if not current_health:
            return None

        # Check latency threshold
        if current_health.latency_ms > config.latency_threshold_ms:
            # Find region with lowest latency
            best_region = None
            best_latency = float('inf')

            for region, health in health_results.items():
                if region == current_region:
                    continue
                if (
                    health.healthy
                    and health.latency_ms < config.latency_threshold_ms
                    and health.latency_ms < best_latency
                ):
                    best_latency = health.latency_ms
                    best_region = region

            return best_region

        return None

    async def should_failback(
        self,
        service_name: str,
        current_region: str,
        original_region: str,
        health_results: dict[str, "HealthCheckResult"],
        config: "FailoverConfig",
    ) -> bool:
        if not config.auto_failback:
            return False

        original_health = health_results.get(original_region)
        if not original_health or not original_health.healthy:
            return False

        current_health = health_results.get(current_region)
        if current_health and current_health.latency_ms <= config.latency_threshold_ms:
            return True

        if current_health is None:
            return False

        return original_health.latency_ms < current_health.latency_ms


class FailoverManager:
    """
    Manages failover for services across regions.
    """

    def __init__(
        self,
        config: FailoverConfig,
        health_checker: Optional[Any] = None,
        policy: Optional[FailoverPolicy] = None,
    ):
        self.config = config
        self.health_checker = health_checker or HTTPHealthChecker()
        self.policy = policy or PriorityFailoverPolicy()
        self._current_region = config.primary_region
        self._original_region = config.primary_region
        self._health_history: dict[str, list[HealthCheckResult]] = defaultdict(list)
        self._failover_events: list[FailoverEvent] = []
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._state = FailoverStatus.HEALTHY
        self._failure_count = 0
        self._success_count = 0
        self._last_failover_time: Optional[datetime] = None
        self._failback_timer: Optional[asyncio.Task] = None

    @property
    def current_region(self) -> str:
        return self._current_region

    @property
    def state(self) -> FailoverStatus:
        return self._state

    @property
    def is_failed_over(self) -> bool:
        return self._current_region != self.config.primary_region

    async def start(self) -> None:
        """Start the failover manager."""
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        logger.info(f"Failover manager started for service: {self.config.service_name}")

    async def stop(self) -> None:
        """Stop the failover manager."""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor_task
        if self._failback_timer:
            self._failback_timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._failback_timer
            self._failback_timer = None
        await self.health_checker.close()
        logger.info(f"Failover manager stopped for service: {self.config.service_name}")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while True:
            try:
                await self._check_health()
                await asyncio.sleep(self.config.health_check_interval_ms / 1000)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")
                await asyncio.sleep(1)

    async def _check_health(self) -> None:
        """Check health of all regions."""
        health_results = {}

        # Check all regions (primary + backups)
        regions_to_check = [self.config.primary_region] + self.config.backup_regions

        for region in regions_to_check:
            try:
                # Use a default endpoint based on region
                endpoint = f"https://api.{region}.pyfault.io"
                result = await self.health_checker.check(self.config.service_name, region, endpoint)
                health_results[region] = result
            except Exception as e:
                logger.error(f"Health check failed for {region}: {e}")
                health_results[region] = HealthCheckResult(
                    service_name=self.config.service_name,
                    region=region,
                    timestamp=utc_now(),
                    healthy=False,
                    latency_ms=0,
                    error_rate=1.0,
                    capacity_used=0.0,
                    error_message=str(e),
                )

        # Check if failover is needed
        if self._state == FailoverStatus.HEALTHY or self._state == FailoverStatus.DEGRADED:
            new_region = await self.policy.should_failover(
                self.config.service_name,
                self._current_region,
                health_results,
                self.config,
            )

            if new_region and new_region != self._current_region:
                await self._perform_failover(new_region, health_results)

        # Check if failback is needed
        elif self._state in (FailoverStatus.FAILOVER_COMPLETED, FailoverStatus.RECOVERING):
            if self.config.auto_failback:
                should_failback = await self.policy.should_failback(
                    self.config.service_name,
                    self._current_region,
                    self.config.primary_region,
                    health_results,
                    self.config,
                )

                if should_failback:
                    await self._perform_failback(health_results)

    async def _perform_failover(
        self,
        target_region: str,
        health_results: dict[str, "HealthCheckResult"],
        trigger: FailoverTrigger = FailoverTrigger.HEALTH_CHECK_FAILURE,
    ) -> None:
        """Perform failover to target region."""
        logger.warning(f"Initiating failover from {self._current_region} to {target_region}")

        self._state = FailoverStatus.FAILOVER_IN_PROGRESS
        start_time = time.time()

        event = FailoverEvent(
            service_name=self.config.service_name,
            trigger=trigger,
            from_region=self._current_region,
            to_region=target_region,
            timestamp=utc_now(),
        )

        try:
            # In a real implementation, this would:
            # 1. Update DNS/load balancer
            # 2. Update service discovery
            # 3. Drain connections from old region
            # 4. Warm up new region
            # 4. Switch traffic

            # Simulate failover delay
            await asyncio.sleep(0.1)

            old_region = self._current_region
            self._current_region = target_region
            self._state = FailoverStatus.FAILOVER_COMPLETED
            self._failure_count = 0
            self._last_failover_time = utc_now()

            event.success = True
            event.duration_ms = int((time.time() - start_time) * 1000)
            event.to_region = target_region
            self._failover_events.append(event)

            logger.info(f"Failover completed from {old_region} to {target_region}")

            # Schedule failback if enabled
            if self.config.auto_failback:
                self._schedule_failback()

        except Exception as e:
            self._state = FailoverStatus.FAILOVER_FAILED
            event.success = False
            event.error_message = str(e)
            event.duration_ms = int((time.time() - start_time) * 1000)
            self._failover_events.append(event)
            logger.error(f"Failover failed: {e}")

    async def _perform_failback(self, health_results: dict[str, "HealthCheckResult"]) -> None:
        """Perform failback to primary region."""
        logger.info(f"Initiating failback to {self.config.primary_region}")

        self._state = FailoverStatus.RECOVERING
        start_time = time.time()

        event = FailoverEvent(
            service_name=self.config.service_name,
            trigger=FailoverTrigger.MANUAL,
            from_region=self._current_region,
            to_region=self.config.primary_region,
            timestamp=utc_now(),
        )

        try:
            # Simulate failback delay
            await asyncio.sleep(0.1)

            self._current_region = self.config.primary_region
            self._state = FailoverStatus.HEALTHY
            self._success_count = 0
            self._failure_count = 0

            event.success = True
            event.duration_ms = int((time.time() - start_time) * 1000)
            self._failover_events.append(event)

            logger.info(f"Failback completed to {self.config.primary_region}")

        except Exception as e:
            self._state = FailoverStatus.FAILOVER_FAILED
            event.success = False
            event.error_message = str(e)
            event.duration_ms = int((time.time() - start_time) * 1000)
            self._failover_events.append(event)
            logger.error(f"Failback failed: {e}")

    def _schedule_failback(self) -> None:
        """Schedule automatic failback."""
        if self._failback_timer:
            self._failback_timer.cancel()

        async def failback_after_delay() -> None:
            await asyncio.sleep(self.config.failback_delay_ms / 1000)
            if self._state in (FailoverStatus.FAILOVER_COMPLETED, FailoverStatus.RECOVERING):
                # This would need actual health checks
                # For now, just trigger the check
                await self._check_health()

        self._failback_timer = asyncio.create_task(failback_after_delay())

    def get_status(self) -> dict[str, Any]:
        """Get current failover status."""
        return {
            "service_name": self.config.service_name,
            "state": self._state.value,
            "current_region": self._current_region,
            "primary_region": self.config.primary_region,
            "backup_regions": self.config.backup_regions,
            "failure_count": self._failure_count,
            "success_count": self._success_count,
            "last_failover": self._last_failover_time.isoformat() if self._last_failover_time else None,
            "failover_events": len(self._failover_events),
        }

    def get_failover_history(self) -> list[dict[str, Any]]:
        """Get failover event history."""
        return [
            {
                "event_id": e.event_id,
                "service_name": e.service_name,
                "trigger": e.trigger.value,
                "from_region": e.from_region,
                "to_region": e.to_region,
                "timestamp": e.timestamp.isoformat(),
                "duration_ms": e.duration_ms,
                "success": e.success,
                "error_message": e.error_message,
            }
            for e in self._failover_events
        ]

    async def force_failover(self, target_region: str) -> bool:
        """Manually trigger failover to a specific region."""
        if target_region not in self.config.backup_regions:
            return False

        # Create dummy health results
        health_results = {self.config.primary_region: HealthCheckResult(
            service_name=self.config.service_name,
            region=self.config.primary_region,
            timestamp=utc_now(),
            healthy=False,
            latency_ms=9999,
            error_rate=1.0,
            capacity_used=1.0,
        )}

        await self._perform_failover(target_region, health_results, trigger=FailoverTrigger.MANUAL)
        return True

    async def force_failback(self) -> bool:
        """Manually trigger failback to primary region."""
        if self._current_region == self.config.primary_region:
            return True

        health_results = {
            self.config.primary_region: HealthCheckResult(
                service_name=self.config.service_name,
                region=self.config.primary_region,
                timestamp=utc_now(),
                healthy=True,
                latency_ms=100,
                error_rate=0.0,
                capacity_used=0.3,
            )
        }

        await self._perform_failback(health_results)
        return True

    async def close(self) -> None:
        await self.stop()


# Global failover manager registry
_failover_managers: dict[str, "FailoverManager"] = {}


def get_failover_manager(service_name: str) -> Optional["FailoverManager"]:
    """Get failover manager for a service."""
    return _failover_managers.get(service_name)


def create_failover_manager(
    service_name: str,
    primary_region: str,
    backup_regions: list[str],
    health_checker: Optional[Any] = None,
    policy: Optional[FailoverPolicy] = None,
    **config_kwargs: Any
) -> "FailoverManager":
    """Create a failover manager for a service."""
    config = FailoverConfig(
        service_name=service_name,
        primary_region=primary_region,
        backup_regions=backup_regions,
        **config_kwargs
    )
    manager = FailoverManager(config, health_checker=health_checker, policy=policy)
    _failover_managers[service_name] = manager
    return manager


def get_all_failover_managers() -> dict[str, "FailoverManager"]:
    """Get all failover managers."""
    return _failover_managers.copy()


async def shutdown_all_failover_managers() -> None:
    """Shutdown all failover managers."""
    for manager in _failover_managers.values():
        await manager.stop()
    _failover_managers.clear()


__all__ = [
    "FailoverStatus",
    "FailoverTrigger",
    "FailoverConfig",
    "FailoverEvent",
    "HealthCheckResult",
    "HealthChecker",
    "HTTPHealthChecker",
    "FailoverPolicy",
    "PriorityFailoverPolicy",
    "LatencyBasedFailoverPolicy",
    "FailoverManager",
    "get_failover_manager",
    "create_failover_manager",
    "get_all_failover_managers",
    "shutdown_all_failover_managers",
]
