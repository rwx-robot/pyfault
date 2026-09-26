"""
Region Management for PyFault framework.
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from .compliance import (
    CCPA_RULES,
    GDPR_RULES,
    HIPAA_RULES,
    PCI_DSS_RULES,
    AuditLogger,
    ComplianceFramework,
    ComplianceManager,
    ComplianceRuleEngine,
    ComplianceViolation,
    CrossBorderTransfer,
    DataAsset,
    DataCategory,
    DataIsolationManager,
    DataProcessingPurpose,
    DataResidencyRule,
    TransferMechanism,
    get_audit_logger,
    get_compliance_manager,
)
from .discovery import (
    CapacityAwareStrategy,
    CompositeStrategy,
    DiscoveryStrategy,
    HealthScoreStrategy,
    LatencyAwareStrategy,
    RegionAffinityStrategy,
    RegionAwareDiscovery,
    ServiceEndpoint,
    ServiceInstance,
    ServiceMeshIntegration,
    ServiceRegistry,
    ServiceStatus,
    WeightedStrategy,
    get_discovery,
    get_service_registry,
)
from .health import (
    AvailabilityHealthChecker,
    CapacityHealthChecker,
    CircuitBreaker,
    CircuitBreakerState,
    CustomHealthChecker,
    DependencyHealthChecker,
    ErrorRateHealthChecker,
    HealthBasedRouter,
    HealthCheckResult,
    HealthDimension,
    HealthScorer,
    HealthStatus,
    LatencyHealthChecker,
    RegionHealthManager,
    RegionHealthReport,
    ThroughputHealthChecker,
    get_health_manager,
)


class RegionStatus(str, Enum):
    """Region status."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEGRADED = "degraded"
    MAINTENANCE = "maintenance"


@dataclass
class Region:
    """Region configuration."""
    id: str
    name: str
    code: str  # e.g., "us-east-1", "eu-west-1"
    provider: str = "aws"  # aws, gcp, azure, aliyun
    endpoint: str = ""
    status: RegionStatus = RegionStatus.ACTIVE
    latitude: float = 0.0
    longitude: float = 0.0
    timezone: str = "UTC"
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "code": self.code,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "status": self.status.value,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "timezone": self.timezone,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


class RegionManager:
    """
    Manages region configurations and health.
    """

    def __init__(self) -> None:
        self._regions: dict[str, Region] = {}
        self._default_region_id: Optional[str] = None
        self._health_checks: dict[str, asyncio.Task] = {}
        self._running = False

    def register_region(self, region: Region) -> None:
        """Register a new region."""
        self._regions[region.id] = region
        if self._default_region_id is None:
            self._default_region_id = region.id

    def unregister_region(self, region_id: str) -> bool:
        """Unregister a region."""
        if region_id in self._regions:
            del self._regions[region_id]
            if self._default_region_id == region_id:
                self._default_region_id = next(iter(self._regions.keys()), None)
            return True
        return False

    def get_region(self, region_id: str) -> Optional[Region]:
        """Get region by ID."""
        return self._regions.get(region_id)

    def get_region_by_code(self, code: str) -> Optional[Region]:
        """Get region by code."""
        for region in self._regions.values():
            if region.code == code:
                return region
        return None

    def list_regions(self, status: Optional[RegionStatus] = None) -> list[Region]:
        """List all regions, optionally filtered by status."""
        regions = list(self._regions.values())
        if status:
            regions = [r for r in regions if r.status == status]
        return regions

    def get_default_region(self) -> Optional[Region]:
        """Get the default region."""
        if self._default_region_id:
            return self._regions.get(self._default_region_id)
        return None

    def set_default_region(self, region_id: str) -> bool:
        """Set the default region."""
        if region_id in self._regions:
            self._default_region_id = region_id
            return True
        return False

    async def start_health_checks(self, interval: float = 30.0) -> None:
        """Start periodic health checks for all regions."""
        self._running = True
        for region_id in self._regions:
            task = asyncio.create_task(self._health_check_loop(region_id, interval))
            self._health_checks[region_id] = task

    async def stop_health_checks(self) -> None:
        """Stop health checks."""
        self._running = False
        for task in self._health_checks.values():
            task.cancel()
        self._health_checks.clear()

    async def _health_check_loop(self, region_id: str, interval: float) -> None:
        """Periodic health check loop for a region."""
        while self._running:
            try:
                region = self._regions.get(region_id)
                if region:
                    healthy = await self._check_region_health(region)
                    new_status = RegionStatus.ACTIVE if healthy else RegionStatus.DEGRADED
                    if region.status != new_status:
                        region.status = new_status
                        region.updated_at = datetime.utcnow()
            except Exception:
                pass
            await asyncio.sleep(interval)

    async def _check_region_health(self, region: Region) -> bool:
        """Check health of a region."""
        # In a real implementation, this would check the actual endpoint
        # For now, return True for active regions
        return region.status == RegionStatus.ACTIVE

    def get_region_stats(self) -> dict[str, Any]:
        """Get statistics about all regions."""
        total = len(self._regions)
        active = sum(1 for r in self._regions.values() if r.status == RegionStatus.ACTIVE)
        degraded = sum(1 for r in self._regions.values() if r.status == RegionStatus.DEGRADED)
        inactive = sum(1 for r in self._regions.values() if r.status == RegionStatus.INACTIVE)

        return {
            "total_regions": total,
            "active": active,
            "degraded": degraded,
            "inactive": inactive,
            "default_region": self._default_region_id,
        }


# Global region manager instance
_region_manager: Optional["RegionManager"] = None


def get_region_manager() -> "RegionManager":
    """Get the global region manager."""
    global _region_manager
    if _region_manager is None:
        _region_manager = RegionManager()
    return _region_manager


def set_region_manager(manager: "RegionManager") -> None:
    """Set the global region manager."""
    global _region_manager
    _region_manager = manager


# Pre-defined region configurations
DEFAULT_REGIONS = [
    Region(
        id="us-east-1",
        name="US East (N. Virginia)",
        code="us-east-1",
        provider="aws",
        endpoint="https://api.us-east-1.pyfault.io",
        latitude=39.0438,
        longitude=-77.4874,
        timezone="America/New_York",
    ),
    Region(
        id="us-west-2",
        name="US West (Oregon)",
        code="us-west-2",
        provider="aws",
        endpoint="https://api.us-west-2.pyfault.io",
        latitude=45.5231,
        longitude=-122.6765,
        timezone="America/Los_Angeles",
    ),
    Region(
        id="eu-west-1",
        name="EU (Ireland)",
        code="eu-west-1",
        provider="aws",
        endpoint="https://api.eu-west-1.pyfault.io",
        latitude=53.3498,
        longitude=-6.2603,
        timezone="Europe/Dublin",
    ),
    Region(
        id="ap-southeast-1",
        name="Asia Pacific (Singapore)",
        code="ap-southeast-1",
        provider="aws",
        endpoint="https://api.ap-southeast-1.pyfault.io",
        latitude=1.3521,
        longitude=103.8198,
        timezone="Asia/Singapore",
    ),
]


async def initialize_default_regions() -> RegionManager:
    """Initialize default regions."""
    manager = get_region_manager()
    for region in DEFAULT_REGIONS:
        manager.register_region(region)
    await manager.start_health_checks()
    return manager
