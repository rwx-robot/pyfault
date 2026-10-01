"""
Adaptive Autoscaling for PyFault AI framework.
"""

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional

from pyfault.common.time import utc_now

logger = logging.getLogger(__name__)


class ScalingDirection(str, Enum):
    """Scaling direction."""
    UP = "up"
    DOWN = "down"
    STABLE = "stable"


class ScalingTrigger(str, Enum):
    """Scaling trigger type."""
    CPU = "cpu"
    MEMORY = "memory"
    REQUEST_RATE = "request_rate"
    LATENCY = "latency"
    QUEUE_DEPTH = "queue_depth"
    CUSTOM = "custom"
    PREDICTIVE = "predictive"


@dataclass
class ScalingMetric:
    """Scaling metric."""
    name: str
    value: float
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScalingPolicy:
    """Scaling policy."""
    policy_id: str
    name: str
    resource_type: str
    min_replicas: int = 1
    max_replicas: int = 100
    target_utilization: float = 70.0
    scale_up_threshold: float = 80.0
    scale_down_threshold: float = 30.0
    scale_up_cooldown: int = 300
    scale_down_cooldown: int = 600
    metrics: list[str] = field(default_factory=list)
    enabled: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ScalingAction:
    """Scaling action."""
    policy_id: str
    resource_id: str
    direction: ScalingDirection
    current_replicas: int
    desired_replicas: int
    reason: str
    action_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)


class MetricsCollector:
    """Collects and manages scaling metrics."""

    def __init__(self, window_size: int = 300):
        self._metrics: dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self._collectors: dict[str, Callable] = {}
        self.window_size = window_size

    def register_collector(self, name: str, collector: Callable) -> None:
        self._collectors[name] = collector

    async def collect(self, name: Optional[str] = None) -> dict[str, ScalingMetric]:
        results = {}
        if name:
            if name not in self._collectors:
                # Unknown names used to raise a raw KeyError from outside the
                # per-collector try/except, bypassing this method's own
                # error-handling contract.
                logger.error(f"Unknown metric collector: {name}")
                return {}
            collectors = {name: self._collectors[name]}
        else:
            collectors = self._collectors

        for metric_name, collector in collectors.items():
            try:
                value = await collector() if asyncio.iscoroutinefunction(collector) else collector()
                metric = ScalingMetric(name=metric_name, value=value)
                self._metrics[metric_name].append(metric)
                results[metric_name] = metric
            except Exception as e:
                logger.error(f"Failed to collect metric {metric_name}: {e}")

        return results

    def get_metric_history(self, name: str, duration: int = 300) -> list[ScalingMetric]:
        now = utc_now()
        cutoff = now - timedelta(seconds=duration)
        return [m for m in self._metrics[name] if m.timestamp >= cutoff]

    def get_latest(self, name: str) -> Optional[ScalingMetric]:
        metrics: list[ScalingMetric] = list(self._metrics.get(name, []))
        return metrics[-1] if metrics else None

    def get_average(self, name: str, duration: int = 60) -> Optional[float]:
        history = self.get_metric_history(name, duration)
        if not history:
            return None
        return sum(m.value for m in history) / len(history)

    def get_percentile(self, name: str, percentile: float, duration: int = 60) -> Optional[float]:
        history = self.get_metric_history(name, duration)
        if not history:
            return None
        values = sorted(m.value for m in history)
        index = int(len(values) * percentile / 100)
        return values[min(index, len(values) - 1)]


class ScalingStrategy(ABC):
    """Base class for scaling strategies."""

    @abstractmethod
    async def evaluate(
        self,
        policy: ScalingPolicy,
        metrics: dict[str, ScalingMetric],
        current_replicas: int,
    ) -> Optional[ScalingAction]:
        pass


class ThresholdScalingStrategy(ScalingStrategy):
    """Simple threshold-based scaling."""

    async def evaluate(
        self,
        policy: ScalingPolicy,
        metrics: dict[str, ScalingMetric],
        current_replicas: int,
    ) -> Optional[ScalingAction]:
        if not policy.enabled:
            return None

        # Get primary metric
        primary_metric = metrics.get(policy.metrics[0]) if policy.metrics else None
        if not primary_metric:
            return None

        utilization = primary_metric.value

        # Scale up
        if utilization > policy.scale_up_threshold and current_replicas < policy.max_replicas:
            desired = min(current_replicas + 1, policy.max_replicas)
            return ScalingAction(
                policy_id=policy.policy_id,
                resource_id="",
                direction=ScalingDirection.UP,
                current_replicas=current_replicas,
                desired_replicas=desired,
                reason=f"Utilization {utilization:.1f}% > scale up threshold {policy.scale_up_threshold}%",
            )

        # Scale down
        if utilization < policy.scale_down_threshold and current_replicas > policy.min_replicas:
            desired = max(current_replicas - 1, policy.min_replicas)
            return ScalingAction(
                policy_id=policy.policy_id,
                resource_id="",
                direction=ScalingDirection.DOWN,
                current_replicas=current_replicas,
                desired_replicas=desired,
                reason=f"Utilization {utilization:.1f}% < scale down threshold {policy.scale_down_threshold}%",
            )

        return None


class PredictiveScalingStrategy(ScalingStrategy):
    """Predictive scaling using trend analysis."""

    def __init__(self, lookback_window: int = 600,
                 collector: Optional[MetricsCollector] = None):
        self.lookback_window = lookback_window
        self.collector = collector

    async def evaluate(
        self,
        policy: ScalingPolicy,
        metrics: dict[str, ScalingMetric],
        current_replicas: int,
    ) -> Optional[ScalingAction]:
        if not policy.enabled or not policy.metrics:
            return None

        primary_metric = metrics.get(policy.metrics[0])
        if not primary_metric:
            return None

        # Prefer history attached to the metric; otherwise read it from the
        # shared MetricsCollector. Without the collector fallback this
        # strategy could never fire at all: ScalingMetric carries no
        # `history` field, so getattr always returned the default [] and
        # evaluate() bailed out before ever predicting anything.
        history = getattr(primary_metric, 'history', None)
        if not history and self.collector is not None:
            history = self.collector.get_metric_history(
                primary_metric.name, self.lookback_window)
        if not history:
            return None

        if len(history) < 10:
            return None

        # Simple linear trend
        values = [m.value for m in history]
        n = len(values)
        x_sum = sum(range(n))
        y_sum = sum(values)
        xy_sum = sum(i * v for i, v in enumerate(values))
        x2_sum = sum(i * i for i in range(n))

        slope = (n * xy_sum - x_sum * y_sum) / (n * x2_sum - x_sum * x_sum)

        # Predict next value
        predicted = values[-1] + slope * 60  # Predict 60 seconds ahead

        if predicted > policy.scale_up_threshold and current_replicas < policy.max_replicas:
            desired = min(current_replicas + 1, policy.max_replicas)
            return ScalingAction(
                policy_id=policy.policy_id,
                resource_id="",
                direction=ScalingDirection.UP,
                current_replicas=current_replicas,
                desired_replicas=desired,
                reason=f"Predicted utilization {predicted:.1f}% > threshold {policy.scale_up_threshold}%",
            )

        if predicted < policy.scale_down_threshold and current_replicas > policy.min_replicas:
            desired = max(current_replicas - 1, policy.min_replicas)
            return ScalingAction(
                policy_id=policy.policy_id,
                resource_id="",
                direction=ScalingDirection.DOWN,
                current_replicas=current_replicas,
                desired_replicas=desired,
                reason=f"Predicted utilization {predicted:.1f}% < threshold {policy.scale_down_threshold}%",
            )

        return None


class AdaptiveScaler:
    """
    Adaptive autoscaler with multiple strategies.
    """

    def __init__(self, metrics_collector: Optional[MetricsCollector] = None) -> None:
        self.metrics_collector = metrics_collector or MetricsCollector()
        self._policies: dict[str, ScalingPolicy] = {}
        self._strategies: dict[str, ScalingStrategy] = {
            "threshold": ThresholdScalingStrategy(),
            # Wire the collector in: PredictiveScalingStrategy reads metric
            # history through it (ScalingMetric itself carries no history).
            "predictive": PredictiveScalingStrategy(
                collector=self.metrics_collector),
        }
        self._resources: dict[str, dict[str, Any]] = {}
        self._last_action: dict[str, datetime] = {}
        self._action_history: list[ScalingAction] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def add_policy(self, policy: ScalingPolicy) -> None:
        self._policies[policy.policy_id] = policy

    def remove_policy(self, policy_id: str) -> bool:
        if policy_id in self._policies:
            del self._policies[policy_id]
            return True
        return False

    def register_resource(
        self,
        resource_id: str,
        resource_type: str,
        current_replicas: int,
        scaler: Callable,
        getter: Optional[Callable] = None,
    ) -> None:
        self._resources[resource_id] = {
            "type": resource_type,
            "current_replicas": current_replicas,
            "scaler": scaler,
            "getter": getter,
        }

    def add_strategy(self, name: str, strategy: ScalingStrategy) -> None:
        self._strategies[name] = strategy

    async def evaluate(self, resource_id: str) -> list[ScalingAction]:
        """Evaluate all policies for a resource."""
        resource = self._resources.get(resource_id)
        if not resource:
            return []

        current_replicas = resource["current_replicas"]
        if resource["getter"]:
            try:
                current_replicas = await resource["getter"]()
            except Exception as e:
                logger.error(f"Failed to get current replicas: {e}")

        actions = []
        metrics = await self.metrics_collector.collect()

        for policy in self._policies.values():
            if policy.resource_type != resource["type"]:
                continue

            # Try each strategy
            for strategy_name, strategy in self._strategies.items():
                try:
                    action = await strategy.evaluate(policy, metrics, current_replicas)
                    if not action:
                        continue

                    # Check cooldown for this action's direction
                    last = self._last_action.get(f"{resource_id}:{policy.policy_id}")
                    if last:
                        elapsed = (utc_now() - last).total_seconds()
                        cooldown = (
                            policy.scale_up_cooldown
                            if action.direction == ScalingDirection.UP
                            else policy.scale_down_cooldown
                        )
                        if elapsed < cooldown:
                            break

                    action.resource_id = resource_id
                    actions.append(action)
                    break
                except Exception as e:
                    logger.error(f"Strategy {strategy_name} failed: {e}")

        return actions

    async def execute(self, action: ScalingAction) -> bool:
        """Execute a scaling action."""
        resource = self._resources.get(action.resource_id)
        if not resource:
            return False

        try:
            success = await resource["scaler"](action.desired_replicas)
            if success:
                resource["current_replicas"] = action.desired_replicas
                self._last_action[f"{action.resource_id}:{action.policy_id}"] = utc_now()
                self._action_history.append(action)
                logger.info(f"Scaled {action.resource_id}: {action.current_replicas} -> {action.desired_replicas} ({action.reason})")
                return True
        except Exception as e:
            logger.error(f"Scaling failed: {e}")

        return False

    async def run_loop(self, interval: int = 30) -> None:
        """Run the autoscaling loop."""
        self._running = True
        while self._running:
            try:
                for resource_id in self._resources:
                    actions = await self.evaluate(resource_id)
                    for action in actions:
                        await self.execute(action)
            except Exception as e:
                logger.error(f"Autoscaler loop error: {e}")

            await asyncio.sleep(interval)

    def start(self, interval: int = 30) -> None:
        if self._task:
            return
        self._task = asyncio.create_task(self.run_loop(interval))

    def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    def get_history(self, limit: int = 100) -> list[ScalingAction]:
        # list[-0:] == list[0:] -> a limit of 0 used to return the entire
        # history instead of nothing.
        if limit <= 0:
            return []
        return self._action_history[-limit:]

    def get_status(self, resource_id: Optional[str] = None) -> dict:
        if resource_id:
            resource = self._resources.get(resource_id, {})
            return {
                "resource_id": resource_id,
                "type": resource.get("type"),
                "current_replicas": resource.get("current_replicas"),
                "policies": [
                    {
                        "policy_id": p.policy_id,
                        "name": p.name,
                        "enabled": p.enabled,
                        "target_utilization": p.target_utilization,
                    }
                    for p in self._policies.values()
                    if p.resource_type == resource.get("type")
                ],
            }

        return {
            "running": self._running,
            "resources": {rid: self.get_status(rid) for rid in self._resources},
            "total_policies": len(self._policies),
            "recent_actions": len(self._action_history),
        }


class ResourceScaler:
    """
    Resource-specific scaler implementations.
    """

    @staticmethod
    async def kubernetes_deployment(namespace: str, deployment: str, replicas: int) -> bool:
        """Scale Kubernetes deployment."""
        try:
            from kubernetes import client, config
            config.load_incluster_config()
            apps_v1 = client.AppsV1Api()
            apps_v1.patch_namespaced_deployment_scale(
                name=deployment,
                namespace=namespace,
                body={"spec": {"replicas": replicas}},
            )
            return True
        except Exception as e:
            logger.error(f"Kubernetes scaling failed: {e}")
            return False

    @staticmethod
    async def docker_compose(service: str, replicas: int) -> bool:
        """Scale Docker Compose service."""
        try:
            import subprocess
            subprocess.run(["docker", "compose", "up", "-d", "--scale", f"{service}={replicas}"], check=True)
            return True
        except Exception as e:
            logger.error(f"Docker Compose scaling failed: {e}")
            return False

    @staticmethod
    async def process_pool(pool: Any, replicas: int) -> bool:
        """Scale process pool."""
        try:
            pool._adjust_process_count(replicas)
            return True
        except Exception as e:
            logger.error(f"Process pool scaling failed: {e}")
            return False


# Global instances
_adaptive_scaler: Optional[AdaptiveScaler] = None
_metrics_collector: Optional[MetricsCollector] = None


def get_adaptive_scaler(collector: Optional[MetricsCollector] = None) -> AdaptiveScaler:
    global _adaptive_scaler
    if _adaptive_scaler is None:
        _adaptive_scaler = AdaptiveScaler(collector or get_metrics_collector())
    return _adaptive_scaler


def get_metrics_collector() -> MetricsCollector:
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


