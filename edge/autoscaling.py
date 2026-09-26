"""
Edge Autoscaling for PyFault framework.

Rapid autoscaling for edge workloads with:
- Sub-second scale-up for burst traffic
- Predictive scaling based on traffic patterns
- Multi-region capacity management
- Cost-aware scaling decisions
- Cold start aware scaling
"""

import asyncio
import contextlib
import logging
import math
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class ScalingDirection(str, Enum):
    """Scaling direction."""
    UP = "up"
    DOWN = "down"
    STABLE = "stable"


class ScalingTrigger(str, Enum):
    """What triggers scaling."""
    CPU = "cpu"
    MEMORY = "memory"
    REQUEST_RATE = "request_rate"
    LATENCY = "latency"
    QUEUE_DEPTH = "queue_depth"
    ERROR_RATE = "error_rate"
    COLD_START_RATE = "cold_start_rate"
    PREDICTIVE = "predictive"
    SCHEDULED = "scheduled"
    CUSTOM = "custom"


class ScalingPolicyType(str, Enum):
    """Scaling policy types."""
    TARGET_TRACKING = "target_tracking"
    STEP_SCALING = "step_scaling"
    SIMPLE_SCALING = "simple_scaling"
    PREDICTIVE = "predictive"


@dataclass
class EdgeScalingPolicy:
    """Edge autoscaling policy."""
    policy_id: str
    name: str
    function_id: str
    policy_type: ScalingPolicyType = ScalingPolicyType.TARGET_TRACKING

    # Target tracking
    target_metric: str = "request_rate"
    target_value: float = 100.0  # requests per second per instance

    # Step scaling
    step_adjustments: list[dict[str, Any]] = field(default_factory=list)

    # Limits
    min_capacity: int = 1
    max_capacity: int = 100
    desired_capacity: Optional[int] = None

    # Cooldowns
    scale_up_cooldown: int = 60  # seconds
    scale_down_cooldown: int = 300

    # Edge-specific
    regions: list[str] = field(default_factory=list)  # empty = all regions
    exclude_regions: list[str] = field(default_factory=list)
    prefer_warm_instances: bool = True
    max_cold_start_rate: float = 0.1  # 10%

    # Cost control
    max_cost_per_hour: Optional[float] = None
    cost_aware: bool = True

    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ScalingActivity:
    """Record of a scaling activity."""
    activity_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    policy_id: str = ""
    function_id: str = ""
    region: str = ""
    direction: ScalingDirection = ScalingDirection.STABLE
    previous_capacity: int = 0
    new_capacity: int = 0
    trigger: ScalingTrigger = ScalingTrigger.CUSTOM
    trigger_value: float = 0.0
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    success: bool = True
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_id": self.activity_id,
            "policy_id": self.policy_id,
            "function_id": self.function_id,
            "region": self.region,
            "direction": self.direction.value,
            "previous_capacity": self.previous_capacity,
            "new_capacity": self.new_capacity,
            "trigger": self.trigger.value,
            "trigger_value": self.trigger_value,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "success": self.success,
            "error_message": self.error_message,
        }


@dataclass
class RegionCapacity:
    """Capacity information for a region."""
    region: str
    function_id: str
    current_instances: int = 0
    warm_instances: int = 0
    cold_instances: int = 0
    max_instances: int = 100
    target_instances: int = 0
    pending_scale_up: int = 0
    pending_scale_down: int = 0
    last_scaled: Optional[datetime] = None
    scale_up_cooldown_until: Optional[datetime] = None
    scale_down_cooldown_until: Optional[datetime] = None
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def available_capacity(self) -> int:
        return self.max_instances - self.current_instances

    @property
    def cold_start_rate(self) -> float:
        if self.current_instances == 0:
            return 0.0
        return self.cold_instances / self.current_instances


class MetricCollector:
    """Collects and aggregates metrics for scaling decisions."""

    def __init__(self, window_seconds: int = 300):
        self.window_seconds = window_seconds
        self._metrics: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._collectors: dict[str, Callable] = {}

    def register_collector(self, name: str, collector: Callable) -> None:
        self._collectors[name] = collector

    async def collect(
        self,
        function_id: str,
        region: str,
        metric_names: Optional[list[str]] = None,
    ) -> dict[str, float]:
        """Collect metrics for a function in a region."""
        results = {}
        key = f"{function_id}:{region}"
        names = metric_names or list(self._collectors.keys())

        for name in names:
            collector = self._collectors.get(name)
            if not collector:
                continue

            try:
                if asyncio.iscoroutinefunction(collector):
                    value = await collector(function_id, region)
                else:
                    value = collector(function_id, region)

                timestamp = datetime.utcnow()
                self._metrics[f"{key}:{name}"].append((timestamp, value))
                results[name] = value
            except Exception as e:
                logger.error(f"Metric collection failed for {name}: {e}")

        return results

    def get_metric_history(
        self,
        function_id: str,
        region: str,
        metric_name: str,
        duration: Optional[int] = None,
    ) -> list[tuple[datetime, float]]:
        duration = duration or self.window_seconds
        cutoff = datetime.utcnow() - timedelta(seconds=duration)
        key = f"{function_id}:{region}:{metric_name}"
        return [(ts, val) for ts, val in self._metrics.get(key, []) if ts >= cutoff]

    def get_average(
        self,
        function_id: str,
        region: str,
        metric_name: str,
        duration: int = 60,
    ) -> Optional[float]:
        history = self.get_metric_history(function_id, region, metric_name, duration)
        if not history:
            return None
        return sum(v for _, v in history) / len(history)

    def get_rate(
        self,
        function_id: str,
        region: str,
        metric_name: str,
        duration: int = 60,
    ) -> Optional[float]:
        """Get rate of change per second."""
        history = self.get_metric_history(function_id, region, metric_name, duration)
        if len(history) < 2:
            return None

        first_ts, first_val = history[0]
        last_ts, last_val = history[-1]
        time_diff = (last_ts - first_ts).total_seconds()

        if time_diff <= 0:
            return None

        return (last_val - first_val) / time_diff


class ScalingStrategy(ABC):
    """Base class for scaling strategies."""

    @abstractmethod
    async def evaluate(
        self,
        policy: EdgeScalingPolicy,
        capacity: RegionCapacity,
        metrics: dict[str, float],
    ) -> tuple[ScalingDirection, int, str]:
        """Returns (direction, target_capacity, reason)."""
        pass


class TargetTrackingStrategy(ScalingStrategy):
    """Target tracking scaling (like AWS Application Auto Scaling)."""

    async def evaluate(
        self,
        policy: EdgeScalingPolicy,
        capacity: RegionCapacity,
        metrics: dict[str, float],
    ) -> tuple[ScalingDirection, int, str]:
        current_value = metrics.get(policy.target_metric, 0)

        if current_value == 0:
            # No traffic, scale to minimum
            if capacity.current_instances > policy.min_capacity:
                return ScalingDirection.DOWN, policy.min_capacity, "No traffic, scaling to minimum"
            return ScalingDirection.STABLE, capacity.current_instances, "No traffic, at minimum"

        # Calculate desired capacity
        if policy.target_value > 0:
            desired = max(
                policy.min_capacity,
                min(
                    policy.max_capacity,
                    int(math.ceil(capacity.current_instances * current_value / policy.target_value))
                ),
            )
        else:
            desired = policy.min_capacity

        if desired > capacity.current_instances:
            return ScalingDirection.UP, desired, f"Metric {current_value:.1f} > target {policy.target_value}"
        elif desired < capacity.current_instances:
            return ScalingDirection.DOWN, desired, f"Metric {current_value:.1f} < target {policy.target_value}"

        return ScalingDirection.STABLE, capacity.current_instances, "At target"


class StepScalingStrategy(ScalingStrategy):
    """Step scaling based on metric thresholds."""

    async def evaluate(
        self,
        policy: EdgeScalingPolicy,
        capacity: RegionCapacity,
        metrics: dict[str, float],
    ) -> tuple[ScalingDirection, int, str]:
        metric_value = metrics.get(policy.target_metric, 0)

        # Sort adjustments by threshold
        adjustments = sorted(
            policy.step_adjustments,
            key=lambda a: a.get("metric_threshold", 0)
        )

        for adj in adjustments:
            threshold = adj.get("metric_threshold", 0)
            adjustment = adj.get("adjustment", 0)
            adjustment_type = adj.get("adjustment_type", "percent")  # percent or absolute

            if metric_value >= threshold:
                if adjustment_type == "percent":
                    change = int(capacity.current_instances * adjustment / 100)
                else:
                    change = adjustment

                new_capacity = max(
                    policy.min_capacity,
                    min(policy.max_capacity, capacity.current_instances + change)
                )

                if new_capacity > capacity.current_instances:
                    return ScalingDirection.UP, new_capacity, f"Metric {metric_value} >= threshold {threshold}"
                elif new_capacity < capacity.current_instances:
                    return ScalingDirection.DOWN, new_capacity, f"Metric {metric_value} >= threshold {threshold}"

        return ScalingDirection.STABLE, capacity.current_instances, "No threshold breached"


class PredictiveScalingStrategy(ScalingStrategy):
    """Predictive scaling using time series forecasting."""

    def __init__(self, prediction_horizon: int = 300):
        self.prediction_horizon = prediction_horizon
        self._history: dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))

    def record(self, function_id: str, region: str, value: float) -> None:
        key = f"{function_id}:{region}"
        self._history[key].append((datetime.utcnow(), value))

    async def evaluate(
        self,
        policy: EdgeScalingPolicy,
        capacity: RegionCapacity,
        metrics: dict[str, float],
    ) -> tuple[ScalingDirection, int, str]:
        key = f"{policy.function_id}:{capacity.region}"
        history = self._history.get(key, deque())

        if len(history) < 10:
            return ScalingDirection.STABLE, capacity.current_instances, "Insufficient history"

        # Simple linear trend prediction
        values = [v for _, v in history]
        n = len(values)
        x = list(range(n))

        # Linear regression
        x_mean = sum(x) / n
        y_mean = sum(values) / n

        numerator = sum((x[i] - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n))

        if denominator == 0:
            return ScalingDirection.STABLE, capacity.current_instances, "No trend"

        slope = numerator / denominator

        # Predict future value
        predicted = values[-1] + slope * (self.prediction_horizon / 60)  # per minute

        if predicted > policy.target_value * 1.2:
            # Scale up proactively
            desired = max(
                policy.min_capacity,
                min(policy.max_capacity, int(math.ceil(predicted / policy.target_value * capacity.current_instances)))
            )
            return ScalingDirection.UP, desired, f"Predicted {predicted:.1f} > target {policy.target_value}"
        elif predicted < policy.target_value * 0.5:
            desired = max(policy.min_capacity, int(predicted / policy.target_value * capacity.current_instances))
            return ScalingDirection.DOWN, desired, f"Predicted {predicted:.1f} < target {policy.target_value}"

        return ScalingDirection.STABLE, capacity.current_instances, "Predicted within bounds"


class EdgeAutoscaler:
    """
    Main edge autoscaler.
    """

    def __init__(
        self,
        runtime: Any,
        scheduler: Any,
        coldstart_optimizer: Any,
        metric_collector: Optional[MetricCollector] = None,
    ):
        self.runtime = runtime
        self.scheduler = scheduler
        self.coldstart = coldstart_optimizer
        self.metric_collector = metric_collector or MetricCollector()
        self._policies: dict[str, EdgeScalingPolicy] = {}
        self._capacities: dict[str, RegionCapacity] = {}  # function_id:region -> capacity
        self._activities: list[ScalingActivity] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._strategies: dict[ScalingPolicyType, ScalingStrategy] = {
            ScalingPolicyType.TARGET_TRACKING: TargetTrackingStrategy(),
            ScalingPolicyType.STEP_SCALING: StepScalingStrategy(),
            ScalingPolicyType.PREDICTIVE: PredictiveScalingStrategy(),
        }
        self._last_evaluation: dict[str, datetime] = {}

    def add_policy(self, policy: EdgeScalingPolicy) -> None:
        policy.updated_at = datetime.utcnow()
        self._policies[policy.policy_id] = policy

        # Initialize capacities for regions
        if not policy.regions:
            # Will be initialized on first evaluation
            pass

    def remove_policy(self, policy_id: str) -> bool:
        if policy_id in self._policies:
            del self._policies[policy_id]
            return True
        return False

    def get_policy(self, policy_id: str) -> Optional[EdgeScalingPolicy]:
        return self._policies.get(policy_id)

    def list_policies(self, function_id: Optional[str] = None) -> list[EdgeScalingPolicy]:
        policies = list(self._policies.values())
        if function_id:
            policies = [p for p in policies if p.function_id == function_id]
        return policies

    def get_capacity(self, function_id: str, region: str) -> RegionCapacity:
        key = f"{function_id}:{region}"
        if key not in self._capacities:
            self._capacities[key] = RegionCapacity(
                region=region,
                function_id=function_id,
            )
        return self._capacities[key]

    def update_capacity(
        self,
        function_id: str,
        region: str,
        current: Optional[int] = None,
        warm: Optional[int] = None,
        cold: Optional[int] = None,
    ) -> None:
        capacity = self.get_capacity(function_id, region)
        if current is not None:
            capacity.current_instances = current
        if warm is not None:
            capacity.warm_instances = warm
        if cold is not None:
            capacity.cold_instances = cold

    async def evaluate_policies(self) -> list[ScalingActivity]:
        """Evaluate all policies and execute scaling."""
        activities = []

        for policy in self._policies.values():
            if not policy.enabled:
                continue

            # Determine regions to evaluate
            regions = policy.regions
            if not regions:
                # Get all regions where function is deployed
                function = self.runtime.get_function(policy.function_id)
                if function:
                    regions = [function.region] if hasattr(function, 'region') else ["us-east-1"]

            for region in regions:
                if region in policy.exclude_regions:
                    continue

                activity = await self._evaluate_policy_for_region(policy, region)
                if activity:
                    activities.append(activity)

        return activities

    async def _evaluate_policy_for_region(
        self,
        policy: EdgeScalingPolicy,
        region: str,
    ) -> Optional[ScalingActivity]:
        capacity = self.get_capacity(policy.function_id, region)

        # Check cooldowns
        now = datetime.utcnow()
        if capacity.scale_up_cooldown_until and now < capacity.scale_up_cooldown_until:
            return None
        if capacity.scale_down_cooldown_until and now < capacity.scale_down_cooldown_until:
            return None

        # Collect metrics
        metrics = await self.metric_collector.collect(
            policy.function_id,
            region,
            [policy.target_metric, "cpu", "memory", "latency", "error_rate", "cold_start_rate"],
        )

        # Add cold start rate from capacity
        metrics["cold_start_rate"] = capacity.cold_start_rate

        # Record for predictive strategy
        if ScalingPolicyType.PREDICTIVE in self._strategies:
            pred_strategy = self._strategies[ScalingPolicyType.PREDICTIVE]
            if isinstance(pred_strategy, PredictiveScalingStrategy):
                pred_strategy.record(policy.function_id, region, metrics.get(policy.target_metric, 0))

        # Get strategy
        strategy = self._strategies.get(policy.policy_type)
        if not strategy:
            logger.warning(f"No strategy for policy type: {policy.policy_type}")
            return None

        # Evaluate
        direction, target, reason = await strategy.evaluate(policy, capacity, metrics)

        if direction == ScalingDirection.STABLE or target == capacity.current_instances:
            return None

        # Check cold start rate constraint
        if (
            direction == ScalingDirection.UP
            and policy.prefer_warm_instances
            and capacity.cold_start_rate > policy.max_cold_start_rate
        ):
            # Pre-warm instances first
            await self.coldstart.ensure_warm(policy.function_id, target)

        # Check cost constraint
        if policy.cost_aware and policy.max_cost_per_hour:
            estimated_cost = target * self._estimate_instance_cost(region)
            if estimated_cost > policy.max_cost_per_hour:
                target = int(policy.max_cost_per_hour / self._estimate_instance_cost(region))
                target = max(policy.min_capacity, target)
                if target == capacity.current_instances:
                    return None
                reason += f" (cost-limited to {target})"

        # Execute scaling
        return await self._execute_scaling(policy, capacity, region, direction, target, reason, metrics)

    def _estimate_instance_cost(self, region: str) -> float:
        # Rough cost estimates per region per hour
        costs = {
            "us-east-1": 0.02,
            "us-west-2": 0.022,
            "eu-west-1": 0.025,
            "ap-southeast-1": 0.028,
        }
        return costs.get(region, 0.03)

    async def _execute_scaling(
        self,
        policy: EdgeScalingPolicy,
        capacity: RegionCapacity,
        region: str,
        direction: ScalingDirection,
        target: int,
        reason: str,
        metrics: dict[str, float],
    ) -> ScalingActivity:
        activity = ScalingActivity(
            policy_id=policy.policy_id,
            function_id=policy.function_id,
            region=region,
            direction=direction,
            previous_capacity=capacity.current_instances,
            new_capacity=target,
            trigger=ScalingTrigger(policy.target_metric.upper()) if policy.target_metric.upper() in [t.value for t in ScalingTrigger] else ScalingTrigger.CUSTOM,
            trigger_value=metrics.get(policy.target_metric, 0),
            reason=reason,
        )

        try:
            if direction == ScalingDirection.UP:
                success = await self._scale_up(policy, capacity, region, target)
            else:
                success = await self._scale_down(policy, capacity, region, target)

            activity.success = success
            activity.completed_at = datetime.utcnow()

            if success:
                # Update cooldowns
                if direction == ScalingDirection.UP:
                    capacity.scale_up_cooldown_until = datetime.utcnow() + timedelta(seconds=policy.scale_up_cooldown)
                else:
                    capacity.scale_down_cooldown_until = datetime.utcnow() + timedelta(seconds=policy.scale_down_cooldown)

                capacity.last_scaled = datetime.utcnow()
                logger.info(f"Scaled {direction.value} {policy.function_id} in {region}: {capacity.current_instances} -> {target}")

        except Exception as e:
            activity.success = False
            activity.error_message = str(e)
            activity.completed_at = datetime.utcnow()
            logger.error(f"Scaling failed: {e}")

        self._activities.append(activity)
        if len(self._activities) > 1000:
            self._activities = self._activities[-1000:]

        return activity

    async def _scale_up(
        self,
        policy: EdgeScalingPolicy,
        capacity: RegionCapacity,
        region: str,
        target: int,
    ) -> bool:
        """Scale up function instances."""
        # Deploy additional instances
        # In practice, this would create new function instances in the region
        # For now, update capacity and warm instances
        if policy.prefer_warm_instances:
            warmed = await self.coldstart.ensure_warm(policy.function_id, target)
            capacity.warm_instances = max(capacity.warm_instances, warmed)

        capacity.current_instances = target
        capacity.target_instances = target
        return True

    async def _scale_down(
        self,
        policy: EdgeScalingPolicy,
        capacity: RegionCapacity,
        region: str,
        target: int,
    ) -> bool:
        """Scale down function instances."""
        # In practice, would terminate instances
        # Keep warm instances for potential scale up
        capacity.current_instances = target
        capacity.target_instances = target

        # Don't reduce warm instances below target
        capacity.warm_instances = min(capacity.warm_instances, target)
        return True

    async def force_scale(
        self,
        function_id: str,
        region: str,
        target: int,
    ) -> ScalingActivity:
        """Manually force scaling."""
        policy = self._policies.get(f"{function_id}-manual")
        if not policy:
            policy = EdgeScalingPolicy(
                policy_id=f"{function_id}-manual",
                name="Manual Scale",
                function_id=function_id,
                min_capacity=1,
                max_capacity=100,
            )
            self._policies[policy.policy_id] = policy

        capacity = self.get_capacity(function_id, region)
        direction = ScalingDirection.UP if target > capacity.current_instances else ScalingDirection.DOWN

        return await self._execute_scaling(
            policy, capacity, region, direction, target,
            "Manual scaling", {}
        )

    def get_scaling_history(
        self,
        function_id: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 100,
    ) -> list[ScalingActivity]:
        activities = self._activities

        if function_id:
            activities = [a for a in activities if a.function_id == function_id]
        if region:
            activities = [a for a in activities if a.region == region]

        return activities[-limit:]

    def get_status(self, function_id: Optional[str] = None) -> dict[str, Any]:
        if function_id:
            policies = self.list_policies(function_id)
            capacities = {
                f"{k.split(':')[1]}": v.to_dict() if hasattr(v, 'to_dict') else vars(v)
                for k, v in self._capacities.items()
                if k.startswith(f"{function_id}:")
            }
            return {
                "function_id": function_id,
                "policies": [vars(p) for p in policies],
                "capacities": capacities,
            }

        return {
            "total_policies": len(self._policies),
            "total_capacities": len(self._capacities),
            "recent_activities": len(self._activities),
            "running": self._running,
        }

    async def start(self, interval: int = 30) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run_loop(interval))
        logger.info("Edge autoscaler started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Edge autoscaler stopped")

    async def _run_loop(self, interval: int) -> None:
        while self._running:
            try:
                await self.evaluate_policies()
            except Exception as e:
                logger.error(f"Autoscaler loop error: {e}")
            await asyncio.sleep(interval)


class CapacityPlanner:
    """Long-term capacity planning for edge functions."""

    def __init__(self, autoscaler: EdgeAutoscaler):
        self.autoscaler = autoscaler
        self._forecasts: dict[str, dict[str, Any]] = {}

    async def generate_forecast(
        self,
        function_id: str,
        region: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """Generate capacity forecast."""
        # Get historical activities
        activities = self.autoscaler.get_scaling_history(function_id, region, 1000)

        # Simple forecast based on recent trends
        if not activities:
            return {
                "function_id": function_id,
                "region": region,
                "forecast_days": days,
                "predicted_peak": 0,
                "recommended_max": 10,
                "confidence": "low",
            }

        # Analyze scaling patterns
        scale_ups = [a for a in activities if a.direction == ScalingDirection.UP]
        scale_downs = [a for a in activities if a.direction == ScalingDirection.DOWN]

        avg_scale_up = sum(a.new_capacity for a in scale_ups) / len(scale_ups) if scale_ups else 5
        avg_scale_down = sum(a.new_capacity for a in scale_downs) / len(scale_downs) if scale_downs else 2

        current = self.autoscaler.get_capacity(function_id, region).current_instances

        return {
            "function_id": function_id,
            "region": region,
            "forecast_days": days,
            "current_capacity": current,
            "predicted_peak": int(avg_scale_up * 1.5),
            "recommended_max": min(100, int(avg_scale_up * 2)),
            "avg_scale_up": avg_scale_up,
            "avg_scale_down": avg_scale_down,
            "scaling_frequency_per_day": len(activities) / max(1, days),
            "confidence": "medium" if len(activities) > 50 else "low",
        }

    def recommend_policies(
        self,
        function_id: str,
        region: str,
    ) -> list[EdgeScalingPolicy]:
        """Recommend scaling policies based on forecast."""
        forecast = asyncio.run(self.generate_forecast(function_id, region))

        recommendations = []

        # Target tracking policy
        recommendations.append(EdgeScalingPolicy(
            policy_id=f"{function_id}-target-tracking",
            name="Target Tracking",
            function_id=function_id,
            policy_type=ScalingPolicyType.TARGET_TRACKING,
            target_metric="request_rate",
            target_value=100,
            min_capacity=forecast.get("current_capacity", 2),
            max_capacity=forecast.get("recommended_max", 20),
            regions=[region],
        ))

        # Predictive policy for predictable workloads
        if forecast.get("confidence") == "medium":
            recommendations.append(EdgeScalingPolicy(
                policy_id=f"{function_id}-predictive",
                name="Predictive Scaling",
                function_id=function_id,
                policy_type=ScalingPolicyType.PREDICTIVE,
                target_metric="request_rate",
                target_value=100,
                min_capacity=forecast.get("current_capacity", 2),
                max_capacity=forecast.get("recommended_max", 20),
                regions=[region],
            ))

        return recommendations


# Global autoscaler
_edge_autoscaler: Optional[EdgeAutoscaler] = None


def get_edge_autoscaler(
    runtime: Any = None,
    scheduler: Any = None,
    coldstart: Any = None,
) -> EdgeAutoscaler:
    global _edge_autoscaler
    if _edge_autoscaler is None:
        from pyfault.edge.coldstart import get_coldstart_optimizer
        from pyfault.edge.runtime import get_runtime
        from pyfault.edge.scheduler import get_edge_scheduler
        _edge_autoscaler = EdgeAutoscaler(
            runtime or get_runtime(),
            scheduler or get_edge_scheduler(),
            coldstart or get_coldstart_optimizer(),
        )
    return _edge_autoscaler


