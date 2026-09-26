"""
Edge Scheduler for PyFault framework.

Intelligent scheduling of edge functions based on:
- Geographic proximity and latency
- Resource availability and capacity
- Traffic patterns and load balancing
- Data residency and compliance
- Cost optimization
"""

import logging
import math
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class SchedulingStrategy(str, Enum):
    """Scheduling strategies."""
    LATENCY_BASED = "latency_based"
    PROXIMITY_BASED = "proximity_based"
    CAPACITY_BASED = "capacity_based"
    COST_BASED = "cost_based"
    COMPLIANCE_BASED = "compliance_based"
    HYBRID = "hybrid"
    CUSTOM = "custom"


class EdgeNodeStatus(str, Enum):
    """Edge node status."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"


@dataclass
class GeoLocation:
    """Geographic location."""
    latitude: float
    longitude: float
    region: str = ""
    country: str = ""
    city: str = ""
    timezone: str = ""

    def distance_to(self, other: "GeoLocation") -> float:
        """Calculate distance in kilometers using Haversine formula."""
        R = 6371  # Earth radius in km

        lat1, lon1 = math.radians(self.latitude), math.radians(self.longitude)
        lat2, lon2 = math.radians(other.latitude), math.radians(other.longitude)

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

        return R * c


@dataclass
class EdgeNode:
    """Edge compute node."""
    node_id: str
    name: str
    location: GeoLocation
    provider: str = "edge"
    capacity: dict[str, float] = field(default_factory=dict)  # cpu, memory, storage, network
    used: dict[str, float] = field(default_factory=dict)
    status: EdgeNodeStatus = EdgeNodeStatus.HEALTHY
    supported_runtimes: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)
    cost_per_hour: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def available_capacity(self, resource: str) -> float:
        return self.capacity.get(resource, 0) - self.used.get(resource, 0)

    def utilization(self, resource: str) -> float:
        cap = self.capacity.get(resource, 0)
        if cap == 0:
            return 0.0
        return self.used.get(resource, 0) / cap

    def can_schedule(self, requirements: dict[str, float]) -> bool:
        for resource, required in requirements.items():
            if self.available_capacity(resource) < required:
                return False
        return True

    def allocate(self, requirements: dict[str, float]) -> bool:
        if not self.can_schedule(requirements):
            return False
        for resource, required in requirements.items():
            self.used[resource] = self.used.get(resource, 0) + required
        return True

    def release(self, requirements: dict[str, float]) -> None:
        for resource, required in requirements.items():
            self.used[resource] = max(0, self.used.get(resource, 0) - required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "name": self.name,
            "location": {
                "latitude": self.location.latitude,
                "longitude": self.location.longitude,
                "region": self.location.region,
                "country": self.location.country,
                "city": self.location.city,
            },
            "provider": self.provider,
            "capacity": self.capacity,
            "used": self.used,
            "status": self.status.value,
            "supported_runtimes": self.supported_runtimes,
            "labels": self.labels,
            "cost_per_hour": self.cost_per_hour,
        }


@dataclass
class SchedulingRequest:
    """Function scheduling request."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    function_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    requirements: dict[str, float] = field(default_factory=dict)  # cpu, memory, etc.
    preferred_regions: list[str] = field(default_factory=list)
    excluded_regions: list[str] = field(default_factory=list)
    compliance_frameworks: list[str] = field(default_factory=list)
    max_latency_ms: Optional[float] = None
    priority: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    client_location: Optional[GeoLocation] = None


@dataclass
class SchedulingDecision:
    """Scheduling decision result."""
    request_id: str
    function_id: str
    selected_node: Optional[str] = None
    strategy: SchedulingStrategy = SchedulingStrategy.LATENCY_BASED
    score: float = 0.0
    latency_estimate_ms: float = 0.0
    alternatives: list[tuple[str, float]] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "function_id": self.function_id,
            "selected_node": self.selected_node,
            "strategy": self.strategy.value,
            "score": self.score,
            "latency_estimate_ms": self.latency_estimate_ms,
            "alternatives": self.alternatives,
            "reasoning": self.reasoning,
        }


class NodeRegistry:
    """Registry of edge nodes."""

    def __init__(self) -> None:
        self._nodes: dict[str, EdgeNode] = {}
        self._region_index: dict[str, set[str]] = defaultdict(set)
        self._label_index: dict[str, set[str]] = defaultdict(set)

    def register(self, node: EdgeNode) -> None:
        self._nodes[node.node_id] = node
        self._region_index[node.location.region].add(node.node_id)
        for label, value in node.labels.items():
            self._label_index[f"{label}:{value}"].add(node.node_id)

    def unregister(self, node_id: str) -> bool:
        if node_id not in self._nodes:
            return False
        node = self._nodes[node_id]
        self._region_index[node.location.region].discard(node_id)
        for label, value in node.labels.items():
            self._label_index[f"{label}:{value}"].discard(node_id)
        del self._nodes[node_id]
        return True

    def get_node(self, node_id: str) -> Optional[EdgeNode]:
        return self._nodes.get(node_id)

    def get_nodes_in_region(self, region: str) -> list[EdgeNode]:
        return [self._nodes[nid] for nid in self._region_index.get(region, set())]

    def get_nodes_by_label(self, label: str, value: str) -> list[EdgeNode]:
        return [self._nodes[nid] for nid in self._label_index.get(f"{label}:{value}", set())]

    def get_healthy_nodes(self) -> list[EdgeNode]:
        return [n for n in self._nodes.values() if n.status == EdgeNodeStatus.HEALTHY]

    def list_nodes(self) -> list[EdgeNode]:
        return list(self._nodes.values())

    def update_heartbeat(self, node_id: str) -> bool:
        if node_id in self._nodes:
            self._nodes[node_id].last_heartbeat = datetime.utcnow()
            return True
        return False

    def check_node_health(self, timeout_seconds: int = 60) -> list[str]:
        """Check for stale nodes."""
        cutoff = datetime.utcnow() - timedelta(seconds=timeout_seconds)
        stale = []
        for node in self._nodes.values():
            if node.last_heartbeat < cutoff and node.status != EdgeNodeStatus.OFFLINE:
                node.status = EdgeNodeStatus.UNHEALTHY
                stale.append(node.node_id)
        return stale


class SchedulingStrategyBase(ABC):
    """Base class for scheduling strategies."""

    @abstractmethod
    async def select_node(
        self,
        request: SchedulingRequest,
        candidates: list[EdgeNode],
        registry: NodeRegistry,
    ) -> SchedulingDecision:
        pass


class LatencyBasedStrategy(SchedulingStrategyBase):
    """Schedule to node with lowest estimated latency."""

    def __init__(self, latency_matrix: Optional[dict[str, dict[str, float]]] = None):
        self.latency_matrix = latency_matrix or {}

    async def select_node(
        self,
        request: SchedulingRequest,
        candidates: list[EdgeNode],
        registry: NodeRegistry,
    ) -> SchedulingDecision:
        if not candidates:
            return SchedulingDecision(
                request_id=request.request_id,
                function_id=request.function_id,
                reasoning="No candidates available",
            )

        best_node = None
        best_latency = float('inf')
        scores = []

        for node in candidates:
            latency = self._estimate_latency(request, node)
            scores.append((node.node_id, latency))

            if latency < best_latency:
                best_latency = latency
                best_node = node

        scores.sort(key=lambda x: x[1])

        return SchedulingDecision(
            request_id=request.request_id,
            function_id=request.function_id,
            selected_node=best_node.node_id if best_node else None,
            strategy=SchedulingStrategy.LATENCY_BASED,
            score=1.0 / (1.0 + best_latency) if best_latency != float('inf') else 0,
            latency_estimate_ms=best_latency,
            alternatives=scores[:5],
            reasoning=f"Selected node with lowest latency: {best_latency:.1f}ms",
        )

    def _estimate_latency(self, request: SchedulingRequest, node: EdgeNode) -> float:
        # Check latency matrix
        if request.client_location:
            return request.client_location.distance_to(node.location) * 0.5  # ~0.5ms/km

        # Default: intra-region ~5ms, cross-region ~50-200ms
        if request.preferred_regions and node.location.region in request.preferred_regions:
            return 5.0
        return 100.0


class ProximityBasedStrategy(SchedulingStrategyBase):
    """Schedule to geographically closest node."""

    async def select_node(
        self,
        request: SchedulingRequest,
        candidates: list[EdgeNode],
        registry: NodeRegistry,
    ) -> SchedulingDecision:
        if not candidates:
            return SchedulingDecision(
                request_id=request.request_id,
                function_id=request.function_id,
                reasoning="No candidates available",
            )

        if not request.client_location:
            return await LatencyBasedStrategy().select_node(request, candidates, registry)

        best_node = None
        best_distance = float('inf')
        scores = []

        for node in candidates:
            distance = request.client_location.distance_to(node.location)
            scores.append((node.node_id, distance))

            if distance < best_distance:
                best_distance = distance
                best_node = node

        scores.sort(key=lambda x: x[1])

        return SchedulingDecision(
            request_id=request.request_id,
            function_id=request.function_id,
            selected_node=best_node.node_id if best_node else None,
            strategy=SchedulingStrategy.PROXIMITY_BASED,
            score=1.0 / (1.0 + best_distance / 1000),
            latency_estimate_ms=best_distance * 0.5,
            alternatives=scores[:5],
            reasoning=f"Selected closest node: {best_distance:.1f}km",
        )


class CapacityBasedStrategy(SchedulingStrategyBase):
    """Schedule to node with most available capacity."""

    def __init__(self, resource_weights: Optional[dict[str, float]] = None):
        self.resource_weights = resource_weights or {"cpu": 0.5, "memory": 0.3, "network": 0.2}

    async def select_node(
        self,
        request: SchedulingRequest,
        candidates: list[EdgeNode],
        registry: NodeRegistry,
    ) -> SchedulingDecision:
        if not candidates:
            return SchedulingDecision(
                request_id=request.request_id,
                function_id=request.function_id,
                reasoning="No candidates available",
            )

        best_node = None
        best_score = -1.0
        scores = []

        for node in candidates:
            score = 0.0
            for resource, weight in self.resource_weights.items():
                avail = node.available_capacity(resource)
                cap = node.capacity.get(resource, 1)
                if cap > 0:
                    score += weight * (avail / cap)

            scores.append((node.node_id, score))

            if score > best_score:
                best_score = score
                best_node = node

        scores.sort(key=lambda x: x[1], reverse=True)

        return SchedulingDecision(
            request_id=request.request_id,
            function_id=request.function_id,
            selected_node=best_node.node_id if best_node else None,
            strategy=SchedulingStrategy.CAPACITY_BASED,
            score=best_score,
            latency_estimate_ms=0,
            alternatives=scores[:5],
            reasoning=f"Selected node with most capacity: {best_score:.2f}",
        )


class CostBasedStrategy(SchedulingStrategyBase):
    """Schedule to lowest cost node."""

    async def select_node(
        self,
        request: SchedulingRequest,
        candidates: list[EdgeNode],
        registry: NodeRegistry,
    ) -> SchedulingDecision:
        if not candidates:
            return SchedulingDecision(
                request_id=request.request_id,
                function_id=request.function_id,
                reasoning="No candidates available",
            )

        # Filter by budget if specified
        viable = [n for n in candidates if n.cost_per_hour >= 0]
        if not viable:
            viable = candidates

        # Sort by cost
        viable.sort(key=lambda n: n.cost_per_hour)
        best_node = viable[0]

        scores = [(n.node_id, 1.0 / (1.0 + n.cost_per_hour)) for n in viable]

        return SchedulingDecision(
            request_id=request.request_id,
            function_id=request.function_id,
            selected_node=best_node.node_id,
            strategy=SchedulingStrategy.COST_BASED,
            score=1.0 / (1.0 + best_node.cost_per_hour),
            latency_estimate_ms=0,
            alternatives=scores[:5],
            reasoning=f"Selected lowest cost node: ${best_node.cost_per_hour}/hr",
        )


class ComplianceBasedStrategy(SchedulingStrategyBase):
    """Schedule based on data residency/compliance requirements."""

    def __init__(self, compliance_rules: Optional[dict[str, list[str]]] = None):
        self.compliance_rules = compliance_rules or {}

    async def select_node(
        self,
        request: SchedulingRequest,
        candidates: list[EdgeNode],
        registry: NodeRegistry,
    ) -> SchedulingDecision:
        if not candidates:
            return SchedulingDecision(
                request_id=request.request_id,
                function_id=request.function_id,
                reasoning="No candidates available",
            )

        # Filter by compliance
        compliant = []
        for node in candidates:
            if self._is_compliant(request, node):
                compliant.append(node)

        if not compliant:
            # Fall back to any node with warning
            logger.warning(f"No compliant nodes for {request.function_id}")
            compliant = candidates

        # Among compliant, prefer closest
        if request.client_location:
            client_location = request.client_location
            distances = {
                node.node_id: client_location.distance_to(node.location)
                for node in compliant
            }
            compliant.sort(key=lambda n: distances[n.node_id])
        else:
            # Prefer preferred regions
            compliant.sort(
                key=lambda n: 0 if n.location.region in request.preferred_regions else 1
            )

        best_node = compliant[0]

        return SchedulingDecision(
            request_id=request.request_id,
            function_id=request.function_id,
            selected_node=best_node.node_id,
            strategy=SchedulingStrategy.COMPLIANCE_BASED,
            score=1.0,
            latency_estimate_ms=0,
            alternatives=[(n.node_id, 1.0) for n in compliant[:5]],
            reasoning=f"Selected compliant node in {best_node.location.region}",
        )

    def _is_compliant(self, request: SchedulingRequest, node: EdgeNode) -> bool:
        # Check excluded regions
        if node.location.region in request.excluded_regions:
            return False

        # Check preferred regions (soft preference)
        if request.preferred_regions and node.location.region not in request.preferred_regions:
            # Not a hard failure, but lower priority
            pass

        # Check compliance frameworks
        for framework in request.compliance_frameworks:
            allowed_regions = self.compliance_rules.get(framework, [])
            if allowed_regions and node.location.region not in allowed_regions:
                return False

        return True


class HybridStrategy(SchedulingStrategyBase):
    """Combine multiple strategies with weights."""

    def __init__(
        self,
        strategies: Optional[dict[SchedulingStrategy, float]] = None,
    ):
        self.strategies = strategies or {
            SchedulingStrategy.LATENCY_BASED: 0.4,
            SchedulingStrategy.CAPACITY_BASED: 0.3,
            SchedulingStrategy.COST_BASED: 0.2,
            SchedulingStrategy.COMPLIANCE_BASED: 0.1,
        }
        # Normalize
        total = sum(self.strategies.values())
        self.strategies = {k: v/total for k, v in self.strategies.items()}

        # Initialize sub-strategies
        self._strategy_impls = {
            SchedulingStrategy.LATENCY_BASED: LatencyBasedStrategy(),
            SchedulingStrategy.PROXIMITY_BASED: ProximityBasedStrategy(),
            SchedulingStrategy.CAPACITY_BASED: CapacityBasedStrategy(),
            SchedulingStrategy.COST_BASED: CostBasedStrategy(),
            SchedulingStrategy.COMPLIANCE_BASED: ComplianceBasedStrategy(),
        }

    async def select_node(
        self,
        request: SchedulingRequest,
        candidates: list[EdgeNode],
        registry: NodeRegistry,
    ) -> SchedulingDecision:
        if not candidates:
            return SchedulingDecision(
                request_id=request.request_id,
                function_id=request.function_id,
                reasoning="No candidates available",
            )

        # Score each candidate
        node_scores: defaultdict[str, float] = defaultdict(float)
        strategy_results = {}

        for strategy, weight in self.strategies.items():
            impl = self._strategy_impls.get(strategy)
            if not impl:
                continue

            try:
                decision = await impl.select_node(request, candidates, registry)
                if decision.selected_node:
                    strategy_results[strategy] = decision
                    # Add weighted score
                    for node_id, alt_score in decision.alternatives:
                        node_scores[node_id] += alt_score * weight
                    if decision.selected_node not in node_scores:
                        node_scores[decision.selected_node] += decision.score * weight
            except Exception as e:
                logger.error(f"Strategy {strategy} failed: {e}")

        if not node_scores:
            # Fallback
            return SchedulingDecision(
                request_id=request.request_id,
                function_id=request.function_id,
                selected_node=candidates[0].node_id,
                strategy=SchedulingStrategy.HYBRID,
                score=0.5,
                reasoning="Fallback to first candidate",
            )

        # Select best
        best_node_id = max(node_scores.items(), key=lambda x: x[1])[0]
        sorted_scores = sorted(node_scores.items(), key=lambda x: x[1], reverse=True)

        return SchedulingDecision(
            request_id=request.request_id,
            function_id=request.function_id,
            selected_node=best_node_id,
            strategy=SchedulingStrategy.HYBRID,
            score=node_scores[best_node_id],
            latency_estimate_ms=0,
            alternatives=sorted_scores[:5],
            reasoning=f"Hybrid score: {node_scores[best_node_id]:.3f}",
        )


class EdgeScheduler:
    """
    Main edge scheduler.
    """

    def __init__(
        self,
        registry: Optional[NodeRegistry] = None,
        strategy: SchedulingStrategy = SchedulingStrategy.HYBRID,
    ):
        self.registry = registry or NodeRegistry()
        self.strategy = strategy
        self._strategy_impls: dict[SchedulingStrategy, SchedulingStrategyBase] = {
            SchedulingStrategy.LATENCY_BASED: LatencyBasedStrategy(),
            SchedulingStrategy.PROXIMITY_BASED: ProximityBasedStrategy(),
            SchedulingStrategy.CAPACITY_BASED: CapacityBasedStrategy(),
            SchedulingStrategy.COST_BASED: CostBasedStrategy(),
            SchedulingStrategy.COMPLIANCE_BASED: ComplianceBasedStrategy(),
            SchedulingStrategy.HYBRID: HybridStrategy(),
        }
        self._decisions: list[SchedulingDecision] = []
        self._max_history = 10000

    def set_strategy(self, strategy: SchedulingStrategy) -> None:
        self.strategy = strategy

    def add_strategy(self, name: SchedulingStrategy, impl: SchedulingStrategyBase) -> None:
        self._strategy_impls[name] = impl

    async def schedule(
        self,
        request: SchedulingRequest,
        strategy: Optional[SchedulingStrategy] = None,
    ) -> SchedulingDecision:
        """Schedule a function to an edge node."""
        strategy = strategy or self.strategy

        # Get healthy candidate nodes
        candidates = self.registry.get_healthy_nodes()

        # Filter by requirements
        candidates = [n for n in candidates if n.can_schedule(request.requirements)]

        # Filter by runtime support
        # Would need function config to check runtime

        # Filter by excluded regions
        if request.excluded_regions:
            candidates = [n for n in candidates if n.location.region not in request.excluded_regions]

        # Apply strategy
        impl = self._strategy_impls.get(strategy)
        if not impl:
            raise ValueError(f"Unknown strategy: {strategy}")

        decision = await impl.select_node(request, candidates, self.registry)

        # Reserve resources if node selected
        if decision.selected_node:
            node = self.registry.get_node(decision.selected_node)
            if node:
                node.allocate(request.requirements)

        # Record decision
        self._decisions.append(decision)
        if len(self._decisions) > self._max_history:
            self._decisions = self._decisions[-self._max_history:]

        return decision

    def release_resources(self, node_id: str, requirements: dict[str, float]) -> None:
        """Release resources after function completes."""
        node = self.registry.get_node(node_id)
        if node:
            node.release(requirements)

    def get_scheduling_stats(self) -> dict[str, Any]:
        total = len(self._decisions)
        if total == 0:
            return {}

        by_strategy: defaultdict[str, int] = defaultdict(int)
        by_node: defaultdict[str, int] = defaultdict(int)
        for d in self._decisions:
            by_strategy[d.strategy.value] += 1
            if d.selected_node:
                by_node[d.selected_node] += 1

        return {
            "total_decisions": total,
            "by_strategy": dict(by_strategy),
            "by_node": dict(by_node),
            "avg_score": sum(d.score for d in self._decisions) / total,
        }

    def get_node_utilization(self) -> dict[str, dict[str, Any]]:
        result = {}
        for node in self.registry.list_nodes():
            result[node.node_id] = {
                "cpu": node.utilization("cpu"),
                "memory": node.utilization("memory"),
                "status": node.status.value,
            }
        return result


class GeoRouter:
    """
    Geographic router for directing traffic to nearest edge.
    """

    def __init__(self, registry: Optional[NodeRegistry] = None):
        self.registry = registry or NodeRegistry()
        self._routes: dict[str, list[str]] = defaultdict(list)  # region -> node_ids
        self._dns_cache: dict[str, str] = {}  # hostname -> node_id

    def add_route(self, region: str, node_id: str) -> None:
        if node_id not in self._routes[region]:
            self._routes[region].append(node_id)

    def remove_route(self, region: str, node_id: str) -> bool:
        if node_id in self._routes.get(region, []):
            self._routes[region].remove(node_id)
            return True
        return False

    def route_request(
        self,
        client_location: GeoLocation,
        function_id: Optional[str] = None,
    ) -> Optional[str]:
        """Route request to best edge node."""
        # Find closest region
        regions = list(self._routes.keys())
        if not regions:
            return None

        # Simple: find closest region with healthy nodes
        best_region = None
        best_distance = float('inf')

        for region in regions:
            nodes = self.registry.get_nodes_in_region(region)
            healthy = [n for n in nodes if n.status == EdgeNodeStatus.HEALTHY]
            if not healthy:
                continue

            # Use region center for distance
            region_center = self._get_region_center(region)
            if region_center:
                distance = client_location.distance_to(region_center)
                if distance < best_distance:
                    best_distance = distance
                    best_region = region

        if best_region and self._routes[best_region]:
            # Return first healthy node in region
            for node_id in self._routes[best_region]:
                node = self.registry.get_node(node_id)
                if node and node.status == EdgeNodeStatus.HEALTHY:
                    return node_id

        return None

    def _get_region_center(self, region: str) -> Optional[GeoLocation]:
        """Get approximate center of region."""
        region_centers = {
            "us-east-1": GeoLocation(39.0, -77.5, "us-east-1", "US", "Virginia"),
            "us-west-2": GeoLocation(45.5, -122.7, "us-west-2", "US", "Oregon"),
            "eu-west-1": GeoLocation(53.3, -6.3, "eu-west-1", "IE", "Dublin"),
            "ap-southeast-1": GeoLocation(1.3, 103.8, "ap-southeast-1", "SG", "Singapore"),
        }
        return region_centers.get(region)

    def resolve_dns(self, hostname: str) -> Optional[str]:
        """Resolve DNS to edge node."""
        return self._dns_cache.get(hostname)

    def set_dns_record(self, hostname: str, node_id: str) -> None:
        self._dns_cache[hostname] = node_id


# Global instances
_edge_scheduler: Optional[EdgeScheduler] = None
_geo_router: Optional[GeoRouter] = None


def get_edge_scheduler(registry: Optional[NodeRegistry] = None) -> EdgeScheduler:
    global _edge_scheduler
    if _edge_scheduler is None:
        _edge_scheduler = EdgeScheduler(registry)
    return _edge_scheduler


def get_geo_router(registry: Optional[NodeRegistry] = None) -> GeoRouter:
    global _geo_router
    if _geo_router is None:
        _geo_router = GeoRouter(registry)
    return _geo_router


