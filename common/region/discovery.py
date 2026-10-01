"""
Advanced Region Discovery for PyFault framework.

Provides service discovery across regions with:
- Region-aware service registration
- Health-based service routing
- Capacity-aware load balancing
- Cross-region service mesh integration
"""

import logging
import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from pyfault.common.time import utc_now

logger = logging.getLogger(__name__)


class ServiceStatus(str, Enum):
    """Service instance status."""
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    STARTING = "starting"
    STOPPING = "stopping"
    MAINTENANCE = "maintenance"


class DiscoveryStrategy(str, Enum):
    """Service discovery strategy."""
    DNS = "dns"
    CONSUL = "consul"
    ETCD = "etcd"
    KUBERNETES = "kubernetes"
    CUSTOM = "custom"


@dataclass
class ServiceEndpoint:
    """Service endpoint information."""
    service_id: str
    service_name: str
    region_id: str
    host: str
    port: int
    protocol: str = "http"
    path: str = "/"
    metadata: dict[str, Any] = field(default_factory=dict)
    status: ServiceStatus = ServiceStatus.STARTING
    weight: int = 100
    priority: int = 0
    tags: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    last_health_check: Optional[datetime] = None
    health_check_interval: int = 30  # seconds

    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}{self.path}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "service_id": self.service_id,
            "service_name": self.service_name,
            "region_id": self.region_id,
            "host": self.host,
            "port": self.port,
            "protocol": self.protocol,
            "path": self.path,
            "metadata": self.metadata,
            "status": self.status.value,
            "weight": self.weight,
            "priority": self.priority,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "last_health_check": self.last_health_check.isoformat() if self.last_health_check else None,
            "health_check_interval": self.health_check_interval,
        }


@dataclass
class ServiceInstance:
    """Service instance with health and capacity info."""
    endpoint: ServiceEndpoint
    current_connections: int = 0
    max_connections: int = 1000
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    request_rate: float = 0.0
    error_rate: float = 0.0
    avg_latency_ms: float = 0.0
    healthy: bool = True

    @property
    def capacity_available(self) -> float:
        if self.max_connections == 0:
            return 1.0
        return 1.0 - (self.current_connections / self.max_connections)

    @property
    def health_score(self) -> float:
        if not self.healthy:
            return 0.0
        # Weighted geometric mean of 0..1 quality factors: a perfect
        # instance scores 1.0, and each factor keeps its own scale.
        # (The previous multiplicative constants capped a perfect score
        # at 0.012, which made health negligible in CompositeStrategy.)
        error_factor = 1.0 - min(self.error_rate, 1.0)
        cpu_factor = 1.0 - min(self.cpu_usage, 1.0)
        memory_factor = 1.0 - min(self.memory_usage, 1.0)
        latency_factor = 1.0 - min(self.avg_latency_ms / 1000.0, 1.0)
        score = (
            error_factor
            * math.pow(cpu_factor, 0.3)
            * math.pow(memory_factor, 0.2)
            * math.pow(latency_factor, 0.2)
        )
        return max(0.0, min(1.0, score))


class ServiceRegistry:
    """
    Region-aware service registry.
    """

    def __init__(self) -> None:
        self._services: dict[str, dict[str, ServiceInstance]] = defaultdict(dict)  # service_name -> region_id -> instance
        self._region_services: dict[str, set[str]] = defaultdict(set)  # region_id -> service_names
        self._callbacks: list[Callable] = []

    def register(self, instance: ServiceInstance) -> None:
        """Register a service instance."""
        service_name = instance.endpoint.service_name
        region_id = instance.endpoint.region_id

        self._services[service_name][region_id] = instance
        self._region_services[region_id].add(service_name)

        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback("register", instance)
            except Exception as e:
                logger.error(f"Callback error: {e}")

    def unregister(self, service_name: str, region_id: str) -> bool:
        """Unregister a service instance."""
        if service_name in self._services and region_id in self._services[service_name]:
            del self._services[service_name][region_id]
            self._region_services[region_id].discard(service_name)

            if not self._services[service_name]:
                del self._services[service_name]

            return True
        return False

    def get_service(self, service_name: str, region_id: Optional[str] = None) -> Optional[ServiceInstance]:
        """Get a service instance."""
        if service_name not in self._services:
            return None

        if region_id:
            return self._services[service_name].get(region_id)

        # Return first healthy instance
        for instance in self._services[service_name].values():
            if instance.healthy:
                return instance
        return None

    def get_all_instances(self, service_name: str) -> list[ServiceInstance]:
        """Get all instances of a service."""
        if service_name not in self._services:
            return []
        return list(self._services[service_name].values())

    def get_healthy_instances(self, service_name: str) -> list[ServiceInstance]:
        """Get healthy instances of a service."""
        return [i for i in self.get_all_instances(service_name) if i.healthy]

    def get_services_in_region(self, region_id: str) -> list[str]:
        """Get service names in a region."""
        return list(self._region_services.get(region_id, set()))

    def list_all_services(self) -> list[str]:
        """List all registered service names."""
        return list(self._services.keys())

    def add_callback(self, callback: Callable) -> None:
        """Add a registration callback."""
        self._callbacks.append(callback)


class RegionAwareDiscovery:
    """
    Region-aware service discovery with intelligent routing.
    """

    def __init__(self, registry: Optional[ServiceRegistry] = None):
        self.registry = registry or ServiceRegistry()
        self._strategies: dict[str, BaseDiscoveryStrategy] = {}
        self._cache: dict[str, list[ServiceInstance]] = {}
        self._cache_ttl = 30  # seconds
        self._cache_timestamps: dict[str, datetime] = {}

    def register_strategy(self, name: str, strategy: "BaseDiscoveryStrategy") -> None:
        self._strategies[name] = strategy

    async def discover(
        self,
        service_name: str,
        preferred_region: Optional[str] = None,
        strategy: str = "latency_aware",
        filters: Optional[dict[str, Any]] = None,
    ) -> list[ServiceInstance]:
        """Discover service instances."""
        cache_key = f"{service_name}:{preferred_region}:{strategy}"
        # Filters change the result set, so they must be part of the cache
        # key; otherwise a second discover() with different filters would
        # be served the first call's filtered results.
        if filters:
            cache_key += f":{filters!r}"

        # Check cache
        if cache_key in self._cache:
            cached_time = self._cache_timestamps.get(cache_key)
            if cached_time and (utc_now() - cached_time).total_seconds() < self._cache_ttl:
                return self._cache[cache_key]

        instances = self.registry.get_all_instances(service_name)

        if not instances:
            return []

        # Filter by region if preferred
        if preferred_region:
            instances = [i for i in instances if i.endpoint.region_id == preferred_region]

        # Apply filters
        if filters:
            instances = self._apply_filters(instances, filters)

        # Apply strategy
        strategy_impl = self._strategies.get(strategy)
        if strategy_impl:
            instances = await strategy_impl.select(instances, preferred_region)

        # Cache results
        self._cache[cache_key] = instances
        self._cache_timestamps[cache_key] = utc_now()

        return instances

    def _apply_filters(self, instances: list[ServiceInstance], filters: dict[str, Any]) -> list[ServiceInstance]:
        result = instances

        if "healthy_only" in filters and filters["healthy_only"]:
            result = [i for i in result if i.healthy]

        if "min_capacity" in filters:
            result = [i for i in result if i.capacity_available >= filters["min_capacity"]]

        if "max_latency_ms" in filters:
            result = [i for i in result if i.avg_latency_ms <= filters["max_latency_ms"]]

        if "tags" in filters:
            for tag_key, tag_value in filters["tags"].items():
                result = [i for i in result if i.endpoint.tags.get(tag_key) == tag_value]

        return result

    def invalidate_cache(self, service_name: Optional[str] = None) -> None:
        """Invalidate discovery cache."""
        if service_name:
            keys_to_remove = [k for k in self._cache if k.startswith(f"{service_name}:")]
            for k in keys_to_remove:
                del self._cache[k]
                del self._cache_timestamps[k]
        else:
            self._cache.clear()
            self._cache_timestamps.clear()


class BaseDiscoveryStrategy:
    """Base class for discovery strategies."""

    async def select(
        self,
        instances: list[ServiceInstance],
        preferred_region: Optional[str] = None,
    ) -> list[ServiceInstance]:
        raise NotImplementedError


class LatencyAwareStrategy:
    """Select instances based on latency."""

    async def select(
        self,
        instances: list[ServiceInstance],
        preferred_region: Optional[str] = None,
    ) -> list[ServiceInstance]:
        healthy = [i for i in instances if i.healthy]
        if not healthy:
            return instances

        # Sort by latency
        healthy.sort(key=lambda i: i.avg_latency_ms)
        return healthy


class CapacityAwareStrategy:
    """Select instances based on available capacity."""

    async def select(
        self,
        instances: list[ServiceInstance],
        preferred_region: Optional[str] = None,
    ) -> list[ServiceInstance]:
        healthy = [i for i in instances if i.healthy]
        if not healthy:
            return instances

        # Sort by capacity (descending)
        healthy.sort(key=lambda i: i.capacity_available, reverse=True)
        return healthy


class RegionAffinityStrategy:
    """Prefer instances in the same region."""

    async def select(
        self,
        instances: list[ServiceInstance],
        preferred_region: Optional[str] = None,
    ) -> list[ServiceInstance]:
        if not preferred_region:
            return instances

        # Prefer same region
        same_region = [i for i in instances if i.endpoint.region_id == preferred_region and i.healthy]
        other_regions = [i for i in instances if i.endpoint.region_id != preferred_region and i.healthy]

        return same_region + other_regions


class HealthScoreStrategy:
    """Select instances based on health score."""

    async def select(
        self,
        instances: list[ServiceInstance],
        preferred_region: Optional[str] = None,
    ) -> list[ServiceInstance]:
        healthy = [i for i in instances if i.healthy]
        if not healthy:
            return instances

        # Sort by health score (descending)
        healthy.sort(key=lambda i: i.health_score, reverse=True)
        return healthy


class WeightedStrategy:
    """Select based on endpoint weights."""

    async def select(
        self,
        instances: list[ServiceInstance],
        preferred_region: Optional[str] = None,
    ) -> list[ServiceInstance]:
        healthy = [i for i in instances if i.healthy]
        if not healthy:
            return instances

        # Sort by weight (descending)
        healthy.sort(key=lambda i: i.endpoint.weight, reverse=True)
        return healthy


class CompositeStrategy:
    """Combine multiple strategies with weights."""

    def __init__(self, strategies: dict[str, float]):
        self.strategies = strategies  # strategy_name -> weight

    async def select(
        self,
        instances: list[ServiceInstance],
        preferred_region: Optional[str] = None,
    ) -> list[ServiceInstance]:
        # Score each instance
        scored = []
        for instance in instances:
            if not instance.healthy:
                continue

            score = 0.0
            total_weight = 0.0

            for strategy_name, weight in self.strategies.items():
                strategy = DISCOVERY_STRATEGIES.get(strategy_name)
                if strategy:
                    # Get score from strategy
                    if strategy_name == "latency":
                        score += weight * (1.0 / (1.0 + instance.avg_latency_ms / 100.0))
                    elif strategy_name == "capacity":
                        score += weight * instance.capacity_available
                    elif strategy_name == "health":
                        score += weight * instance.health_score
                    elif strategy_name == "weight":
                        score += weight * (instance.endpoint.weight / 100.0)
                    elif (
                        strategy_name == "region_affinity"
                        and preferred_region
                        and instance.endpoint.region_id == preferred_region
                    ):
                        score += weight

                    total_weight += weight

            if total_weight > 0:
                score /= total_weight
            scored.append((instance, score))

        # Sort by composite score
        scored.sort(key=lambda x: x[1], reverse=True)
        return [i for i, _ in scored]


# Pre-defined strategies
DISCOVERY_STRATEGIES = {
    "latency": LatencyAwareStrategy(),
    "capacity": CapacityAwareStrategy(),
    "region_affinity": RegionAffinityStrategy(),
    "health": HealthScoreStrategy(),
    "weight": WeightedStrategy(),
}


class ServiceMeshIntegration:
    """
    Integration with service mesh (Istio, Linkerd, Consul Connect).
    """

    def __init__(self, mesh_type: str = "istio"):
        self.mesh_type = mesh_type
        self._config: dict[str, Any] = {}

    async def configure_traffic_split(
        self,
        service_name: str,
        splits: dict[str, float],  # region -> percentage
    ) -> bool:
        """Configure traffic split across regions."""
        logger.info(f"Configuring traffic split for {service_name}: {splits}")
        # Would integrate with Istio VirtualService, etc.
        return True

    async def configure_fault_injection(
        self,
        service_name: str,
        region: str,
        delay_ms: int = 0,
        abort_percent: float = 0.0,
    ) -> bool:
        """Configure fault injection for testing."""
        logger.info(f"Configuring fault injection for {service_name} in {region}")
        return True

    async def configure_circuit_breaker(
        self,
        service_name: str,
        region: str,
        consecutive_errors: int = 5,
        interval: str = "10s",
        base_ejection_time: str = "30s",
    ) -> bool:
        """Configure circuit breaker."""
        logger.info(f"Configuring circuit breaker for {service_name} in {region}")
        return True


# Global registry
_service_registry: Optional[ServiceRegistry] = None
_discovery: Optional[RegionAwareDiscovery] = None


def get_service_registry() -> ServiceRegistry:
    global _service_registry
    if _service_registry is None:
        _service_registry = ServiceRegistry()
    return _service_registry


def get_discovery() -> RegionAwareDiscovery:
    global _discovery
    if _discovery is None:
        _discovery = RegionAwareDiscovery(get_service_registry())
    return _discovery


