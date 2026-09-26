"""
Region-aware routing for PyFault framework.
"""

import inspect
import random
import time
from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from pyfault.common.region import (
    Region,
    RegionManager,
    RegionStatus,
    get_region_manager,
)

T = TypeVar("T")


class RoutingStrategy(str, Enum):
    """Routing strategy."""
    RANDOM = "random"
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    LATENCY_BASED = "latency_based"
    REGION_AFFINITY = "region_affinity"
    CUSTOM = "custom"


@dataclass
class RouteTarget:
    """A routing target."""
    region_id: str
    endpoint: str
    weight: int = 1
    healthy: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_weight(self) -> int:
        return self.weight if self.healthy else 0


@dataclass
class RoutingContext:
    """Context for routing decisions."""
    region_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


class RoutingStrategyBase(ABC):
    """Base class for routing strategies."""

    @abstractmethod
    async def select_target(
        self,
        targets: list[RouteTarget],
        context: RoutingContext,
    ) -> Optional[RouteTarget]:
        """Select a target from the available targets."""
        pass


class RandomRoutingStrategy(RoutingStrategyBase):
    """Random routing strategy."""

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: RoutingContext,
    ) -> Optional[RouteTarget]:
        healthy_targets = [t for t in targets if t.healthy and t.effective_weight > 0]
        if not healthy_targets:
            return None
        return random.choice(healthy_targets)


class RoundRobinRoutingStrategy(RoutingStrategyBase):
    """Round-robin routing strategy."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: RoutingContext,
    ) -> Optional[RouteTarget]:
        healthy_targets = [t for t in targets if t.healthy and t.effective_weight > 0]
        if not healthy_targets:
            return None

        key = f"{context.region_id or 'default'}"
        index = self._counters[key] % len(healthy_targets)
        self._counters[key] = (self._counters[key] + 1) % len(healthy_targets)
        return healthy_targets[index]


class WeightedRoutingStrategy(RoutingStrategyBase):
    """Weighted routing strategy."""

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: RoutingContext,
    ) -> Optional[RouteTarget]:
        healthy_targets = [t for t in targets if t.healthy and t.effective_weight > 0]
        if not healthy_targets:
            return None

        total_weight = sum(t.effective_weight for t in healthy_targets)
        if total_weight == 0:
            return random.choice(healthy_targets)

        rand = random.randint(1, total_weight)
        current = 0
        for target in healthy_targets:
            current += target.effective_weight
            if rand <= current:
                return target
        return healthy_targets[-1]


class LatencyBasedRoutingStrategy(RoutingStrategyBase):
    """Latency-based routing strategy."""

    def __init__(self, latency_provider: Optional[Callable[[str, str], Awaitable[float]]] = None) -> None:
        self._latency_provider = latency_provider or self._default_latency_provider
        self._latency_cache: dict[str, float] = {}
        self._cache_expiry: dict[str, datetime] = {}

    async def _default_latency_provider(self, from_region: str, to_region: str) -> float:
        """Default latency provider - returns simulated latency."""
        # In a real implementation, this would query actual latency metrics
        return random.uniform(10, 200)  # ms

    async def get_latency(self, from_region: str, to_region: str) -> float:
        """Get latency between regions."""
        cache_key = f"{from_region}:{to_region}"

        if (
            cache_key in self._latency_cache
            and cache_key in self._cache_expiry
            and self._cache_expiry[cache_key] > datetime.utcnow()
        ):
            return self._latency_cache[cache_key]

        latency = await self._latency_provider(from_region, to_region)
        self._latency_cache[cache_key] = latency
        # Expire at the start of the next minute. The previous code stored
        # the start of the *current* minute, which is always in the past,
        # so the cache never produced a hit.
        self._cache_expiry[cache_key] = datetime.utcnow().replace(
            second=0, microsecond=0
        ) + timedelta(minutes=1)
        return latency

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: RoutingContext,
    ) -> Optional[RouteTarget]:
        healthy_targets = [t for t in targets if t.healthy and t.effective_weight > 0]
        if not healthy_targets:
            return None

        source_region = context.region_id or "unknown"
        latencies = {}

        for target in healthy_targets:
            # Extract region from target endpoint or metadata
            target_region = target.metadata.get("region", "unknown")
            latency = await self.get_latency(source_region, target_region)
            latencies[target.region_id] = latency

        # Select target with lowest latency
        if latencies:
            best_region = min(latencies, key=lambda region: latencies[region])
            for target in healthy_targets:
                if target.region_id == best_region:
                    return target

        return random.choice(healthy_targets)


class RegionAffinityRoutingStrategy(RoutingStrategyBase):
    """Region affinity routing strategy - prefers same region."""

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: RoutingContext,
    ) -> Optional[RouteTarget]:
        healthy_targets = [t for t in targets if t.healthy and t.effective_weight > 0]
        if not healthy_targets:
            return None

        # Prefer same region
        if context.region_id:
            same_region = [t for t in healthy_targets if t.metadata.get("region") == context.region_id]
            if same_region:
                return random.choice(same_region)

        # Fall back to random
        return random.choice(healthy_targets)


class CustomRoutingStrategy(RoutingStrategyBase):
    """Custom routing strategy with user-defined logic."""

    def __init__(
        self,
        selector: Callable[
            [list[RouteTarget], RoutingContext],
            Optional[RouteTarget] | Awaitable[Optional[RouteTarget]],
        ],
    ) -> None:
        self._selector = selector

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: RoutingContext,
    ) -> Optional[RouteTarget]:
        selected = self._selector(targets, context)
        if inspect.isawaitable(selected):
            return await selected
        return selected


class RegionAwareRouter:
    """
    Region-aware router that routes requests based on region awareness.
    """

    def __init__(self, region_manager: Optional[RegionManager] = None):
        self.region_manager = region_manager or get_region_manager()
        self._strategies: dict[str, RoutingStrategyBase] = {}
        self._default_strategy = RoutingStrategy.LATENCY_BASED
        self._service_routes: dict[str, list[RouteTarget]] = defaultdict(list)

        # Register default strategies
        self._strategies[RoutingStrategy.RANDOM] = RandomRoutingStrategy()
        self._strategies[RoutingStrategy.ROUND_ROBIN] = RoundRobinRoutingStrategy()
        self._strategies[RoutingStrategy.WEIGHTED] = WeightedRoutingStrategy()
        self._strategies[RoutingStrategy.LATENCY_BASED] = LatencyBasedRoutingStrategy()
        self._strategies[RoutingStrategy.REGION_AFFINITY] = RegionAffinityRoutingStrategy()

    def register_strategy(self, name: str, strategy: RoutingStrategyBase) -> None:
        """Register a custom routing strategy."""
        self._strategies[name] = strategy

    def set_default_strategy(self, strategy: RoutingStrategy) -> None:
        """Set the default routing strategy."""
        self._default_strategy = strategy

    def add_route(self, service: str, target: RouteTarget) -> None:
        """Add a route target for a service."""
        self._service_routes[service].append(target)

    def remove_route(self, service: str, region_id: str) -> bool:
        """Remove a route target."""
        targets = self._service_routes.get(service, [])
        for i, target in enumerate(targets):
            if target.region_id == region_id:
                targets.pop(i)
                return True
        return False

    async def route(
        self,
        service: str,
        context: Optional[RoutingContext] = None,
        strategy: Optional[RoutingStrategy] = None,
    ) -> Optional[RouteTarget]:
        """Route a request to a target."""
        context = context or RoutingContext()
        strategy_name = strategy or self._default_strategy
        strategy_impl = self._strategies.get(strategy_name)

        if not strategy_impl:
            raise ValueError(f"Unknown routing strategy: {strategy_name}")

        targets = self._service_routes.get(service, [])
        if not targets:
            return None

        return await strategy_impl.select_target(list(targets), context)

    def get_available_targets(self, service: str) -> list[RouteTarget]:
        """Get all available targets for a service."""
        return list(self._service_routes.get(service, []))

    def get_strategy(self, name: str) -> Optional[RoutingStrategyBase]:
        """Get a routing strategy by name."""
        return self._strategies.get(name)


def create_region_aware_router(
    region_manager: Optional[RegionManager] = None,
    default_strategy: RoutingStrategy = RoutingStrategy.LATENCY_BASED,
) -> RegionAwareRouter:
    """Create a region-aware router with default configuration."""
    router = RegionAwareRouter(region_manager)
    router.set_default_strategy(RoutingStrategy(default_strategy))
    return router
