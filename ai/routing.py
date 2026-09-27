"""
AI Routing for PyFault framework.
"""

import logging
import random
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class RoutingStrategy(str, Enum):
    """Routing strategy."""
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    WEIGHTED = "weighted"
    LATENCY_BASED = "latency_based"
    REGION_AFFINITY = "region_affinity"
    HEALTH_BASED = "health_based"
    COST_BASED = "cost_based"
    CUSTOM = "custom"


@dataclass
class RouteTarget:
    """Route target."""
    target_id: str
    endpoint: str
    weight: int = 1
    healthy: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)
    capacity: int = 100
    current_load: int = 0
    latency_ms: float = 0.0
    error_rate: float = 0.0
    # per-target rolling counters (updated by IntelligentRouter.release;
    # strategies read error_rate / latency_ms which must only reflect THIS
    # target's own traffic)
    release_count: int = field(default=0, init=False, repr=False, compare=False)
    release_error_count: int = field(default=0, init=False, repr=False, compare=False)
    release_latency_ms: float = field(default=0.0, init=False, repr=False, compare=False)


class RoutingStrategyBase(ABC):
    """Base class for routing strategies."""

    @abstractmethod
    async def select_target(
        self,
        targets: list[RouteTarget],
        context: "RoutingContext",
    ) -> Optional[RouteTarget]:
        pass


class RoundRobinStrategy:
    """Round-robin routing."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: "RoutingContext",
    ) -> Optional[RouteTarget]:
        healthy = [t for t in targets if t.healthy]
        if not healthy:
            return None

        key = context.source_region or "default"
        index = self._counters[key] % len(healthy)
        self._counters[key] = (index + 1) % len(healthy)
        return healthy[index]


class LeastConnectionsStrategy:
    """Least connections routing."""

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: "RoutingContext",
    ) -> Optional[RouteTarget]:
        healthy = [t for t in targets if t.healthy and t.current_load < t.capacity]
        if not healthy:
            return None
        return min(healthy, key=lambda t: t.current_load)


class WeightedStrategy:
    """Weighted routing."""

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: "RoutingContext",
    ) -> Optional[RouteTarget]:
        healthy = [t for t in targets if t.healthy]
        if not healthy:
            return None

        total_weight = sum(t.weight for t in healthy)
        if total_weight == 0:
            # all healthy targets weigh nothing -> pick among healthy only
            # (choosing from `targets` could return an unhealthy one)
            return random.choice(healthy)

        rand = random.randint(1, total_weight)
        current = 0
        selected: Optional[RouteTarget] = None
        for target in healthy:
            current += target.weight
            if selected is None and rand <= current:
                selected = target
        # rand is in [1, total_weight] and the cumulative sum ends at
        # total_weight, so selection is guaranteed by the last element
        return selected


class LatencyBasedStrategy:
    """Latency-based routing."""

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: "RoutingContext",
    ) -> Optional[RouteTarget]:
        healthy = [t for t in targets if t.healthy]
        if not healthy:
            return None
        # Prefer lowest measured latency; targets without measurements yet
        # (latency_ms == 0, the dataclass default) are last resort instead of
        # being excluded entirely — otherwise the default strategy could
        # never route to a freshly registered target.
        return min(
            healthy,
            key=lambda t: t.latency_ms if t.latency_ms > 0 else float("inf"),
        )


class HealthBasedStrategy:
    """Health-based routing."""

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: "RoutingContext",
    ) -> Optional[RouteTarget]:
        healthy = [t for t in targets if t.healthy]
        if not healthy:
            return None
        # Prefer targets with lowest error rate
        return min(healthy, key=lambda t: t.error_rate)


class CostBasedStrategy:
    """Cost-based routing."""

    def __init__(self, cost_per_region: Optional[dict[str, float]] = None):
        self.cost_per_region = cost_per_region or {}

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: "RoutingContext",
    ) -> Optional[RouteTarget]:
        healthy = [t for t in targets if t.healthy]
        if not healthy:
            return None

        return min(healthy, key=lambda t: self.cost_per_region.get(t.metadata.get("region", ""), 1.0))


class CustomRoutingStrategy:
    """Custom routing with user-defined function."""

    def __init__(self, selector: Callable[[list[RouteTarget], "RoutingContext"], Optional[RouteTarget]]):
        self._selector = selector

    async def select_target(
        self,
        targets: list[RouteTarget],
        context: "RoutingContext",
    ) -> Optional[RouteTarget]:
        return self._selector(targets, context)


class RoutingContext:
    """Routing context with request information."""

    def __init__(
        self,
        source_region: str = "",
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ):
        self.source_region = source_region
        self.user_id = user_id
        self.session_id = session_id
        self.headers = headers or {}
        self.metadata = metadata or {}
        self.request_id = str(uuid.uuid4())
        self.timestamp = datetime.utcnow()


class IntelligentRouter:
    """
    Intelligent router with multiple strategies.
    """

    def __init__(self) -> None:
        self._strategies: dict[str, Any] = {
            "round_robin": RoundRobinStrategy(),
            "least_connections": LeastConnectionsStrategy(),
            "weighted": WeightedStrategy(),
            "latency_based": LatencyBasedStrategy(),
            "health_based": HealthBasedStrategy(),
            "cost_based": CostBasedStrategy(),
        }
        self._custom_strategies: dict[str, Any] = {}
        self._default_strategy = "latency_based"
        self._targets: dict[str, list[RouteTarget]] = defaultdict(list)
        self._stats: dict[str, dict] = defaultdict(lambda: {
            "total_requests": 0,
            "success_count": 0,
            "error_count": 0,
            "total_latency_ms": 0.0,
        })

    def register_target(self, service: str, target: RouteTarget) -> None:
        """Register a route target."""
        self._targets[service].append(target)

    def unregister_target(self, service: str, target_id: str) -> bool:
        targets = self._targets.get(service, [])
        for i, target in enumerate(targets):
            if target.target_id == target_id:
                targets.pop(i)
                return True
        return False

    def set_default_strategy(self, strategy: str) -> None:
        if strategy in self._strategies:
            self._default_strategy = strategy

    def add_custom_strategy(self, name: str, strategy: Any) -> None:
        self._custom_strategies[name] = strategy

    async def route(
        self,
        service: str,
        context: "RoutingContext",
        strategy: Optional[str] = None,
    ) -> Optional[RouteTarget]:
        """Route a request to a target."""
        targets = self._targets.get(service, [])
        if not targets:
            return None

        strategy_name = strategy or self._default_strategy
        strategy_impl = self._strategies.get(strategy_name) or self._custom_strategies.get(strategy_name)

        if not strategy_impl:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        target: Optional[RouteTarget] = await strategy_impl.select_target(
            self._targets[service],
            context,
        )

        if target:
            target.current_load += 1

        return target

    def release(self, service: str, target_id: str, success: bool = True, latency_ms: float = 0, error: bool = False) -> None:
        """Release a target after request completion."""
        targets = self._targets.get(service, [])
        for target in targets:
            if target.target_id == target_id:
                target.current_load = max(0, target.current_load - 1)

                # per-target rolling stats: latency_based / health_based read
                # target.latency_ms and target.error_rate, so they must only
                # reflect this target's own releases — not the service-wide
                # average (which let one slow target poison every other).
                target.release_count += 1
                target.release_latency_ms += latency_ms
                if not success:
                    target.release_error_count += 1
                target.error_rate = (
                    target.release_error_count / target.release_count)
                target.latency_ms = (
                    target.release_latency_ms / target.release_count)

                # service-level stats (total_requests counts completions,
                # incremented here only — it used to also be incremented in
                # route(), double-counting every request and halving
                # error_rate / latency averages)
                self._stats[service]["total_requests"] += 1
                if success:
                    self._stats[service]["success_count"] += 1
                else:
                    self._stats[service]["error_count"] += 1
                self._stats[service]["total_latency_ms"] += latency_ms
                break

    def get_stats(self, service: Optional[str] = None) -> dict:
        if service:
            return self._stats.get(service, {})
        return dict(self._stats)

    def get_targets(self, service: str) -> list[RouteTarget]:
        return self._targets.get(service, [])


class AIRouter:
    """
    AI-powered intelligent router.
    """

    def __init__(self) -> None:
        self.router = IntelligentRouter()
        self._models: dict[str, Any] = {}
        self._feature_store: dict[str, Any] = {}

    def register_model(self, name: str, model: Any) -> None:
        self._models[name] = model

    async def predict_best_route(
        self,
        service: str,
        context: "RoutingContext",
        features: dict[str, Any],
    ) -> Optional[RouteTarget]:
        """Use ML model to predict best route."""
        # This would use a trained ML model to predict best route
        # For now, fall back to latency-based
        return await self.router.route(service, context, "latency_based")

    def record_outcome(
        self,
        service: str,
        target_id: str,
        context: RoutingContext,
        success: bool,
        latency_ms: float,
    ) -> None:
        """Record routing outcome for learning."""
        self.router.release(service, target_id, success, latency_ms, error=False)

    def get_routing_stats(self, service: Optional[str] = None) -> dict:
        return self.router.get_stats(service)
