"""
A/B Testing Framework for PyFault AI framework.

Provides experimentation infrastructure for AI plugins:
- Experiment design and management
- Traffic splitting and assignment
- Statistical significance testing
- Metric collection and analysis
- Automated decision making
"""

import asyncio
import hashlib
import json
import logging
import math
import random
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional

import numpy as np
from scipy import stats

logger = logging.getLogger(__name__)


class ExperimentStatus(str, Enum):
    """Experiment status."""
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    STOPPED = "stopped"
    ARCHIVED = "archived"


class AssignmentStrategy(str, Enum):
    """Traffic assignment strategy."""
    RANDOM = "random"
    DETERMINISTIC = "deterministic"  # Based on user ID
    STICKY = "sticky"  # Cookie-based
    CONTEXTUAL = "contextual"  # Based on context features


class MetricType(str, Enum):
    """Metric types for evaluation."""
    CONVERSION = "conversion"  # Binary (0/1)
    CONTINUOUS = "continuous"  # Numeric value
    COUNT = "count"  # Event count
    RATIO = "ratio"  # Numerator/denominator


@dataclass
class ExperimentVariant:
    """Experiment variant (control or treatment)."""
    variant_id: str
    name: str
    description: str = ""
    traffic_allocation: float = 0.0  # 0.0 to 1.0
    config: dict[str, Any] = field(default_factory=dict)
    is_control: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "name": self.name,
            "description": self.description,
            "traffic_allocation": self.traffic_allocation,
            "config": self.config,
            "is_control": self.is_control,
        }


@dataclass
class ExperimentMetric:
    """Metric definition for experiment evaluation."""
    metric_id: str
    name: str
    metric_type: MetricType = MetricType.CONVERSION
    description: str = ""
    higher_is_better: bool = True
    minimum_detectable_effect: float = 0.01  # 1%
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "name": self.name,
            "metric_type": self.metric_type.value,
            "description": self.description,
            "higher_is_better": self.higher_is_better,
            "minimum_detectable_effect": self.minimum_detectable_effect,
        }


@dataclass
class Experiment:
    """A/B test experiment."""
    experiment_id: str
    name: str
    description: str = ""
    status: ExperimentStatus = ExperimentStatus.DRAFT
    variants: list[ExperimentVariant] = field(default_factory=list)
    metrics: list[ExperimentMetric] = field(default_factory=list)

    # Traffic assignment
    assignment_strategy: AssignmentStrategy = AssignmentStrategy.RANDOM
    assignment_key: str = "user_id"  # Context key for assignment

    # Targeting
    targeting_rules: list[dict[str, Any]] = field(default_factory=list)

    # Schedule
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    max_duration_days: int = 30

    # Statistical settings
    significance_level: float = 0.05  # 95% confidence
    power: float = 0.8  # 80% power
    minimum_sample_size: int = 100

    # Results
    results: dict[str, Any] = field(default_factory=dict)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    created_by: str = ""
    tags: list[str] = field(default_factory=list)

    def get_control_variant(self) -> Optional[ExperimentVariant]:
        for v in self.variants:
            if v.is_control:
                return v
        return None

    def get_treatment_variants(self) -> list[ExperimentVariant]:
        return [v for v in self.variants if not v.is_control]

    def get_total_allocation(self) -> float:
        return sum(v.traffic_allocation for v in self.variants)

    def is_active(self) -> bool:
        if self.status != ExperimentStatus.RUNNING:
            return False
        now = datetime.utcnow()
        if self.start_time and now < self.start_time:
            return False
        if self.end_time and now > self.end_time:
            return False
        return not (self.start_time and (now - self.start_time).days > self.max_duration_days)


@dataclass
class ExperimentAssignment:
    """User assignment to experiment variant."""
    assignment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    experiment_id: str = ""
    variant_id: str = ""
    assignment_key: str = ""
    assignment_value: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    assigned_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentEvent:
    """Event recorded during experiment."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    experiment_id: str = ""
    variant_id: str = ""
    assignment_id: str = ""
    metric_id: str = ""
    value: float = 0.0
    numerator: float = 0.0
    denominator: float = 1.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExperimentResult:
    """Experiment analysis result."""
    experiment_id: str
    variant_id: str
    metric_id: str
    sample_size: int = 0
    mean: float = 0.0
    std_dev: float = 0.0
    conversion_rate: float = 0.0
    confidence_interval: tuple[float, float] = (0.0, 0.0)
    p_value: float = 1.0
    significant: bool = False
    lift: float = 0.0
    lift_confidence_interval: tuple[float, float] = (0.0, 0.0)


class AssignmentEngine:
    """Handles user assignment to experiment variants."""

    def __init__(self) -> None:
        self._assignments: dict[str, ExperimentAssignment] = {}  # assignment_key -> assignment

    def assign(
        self,
        experiment: Experiment,
        assignment_key: str,
        assignment_value: str,
        context: Optional[dict[str, Any]] = None,
    ) -> ExperimentAssignment:
        """Assign user to variant."""
        # Check existing assignment
        key = f"{experiment.experiment_id}:{assignment_key}:{assignment_value}"
        if key in self._assignments:
            return self._assignments[key]

        # Check targeting rules
        if not self._matches_targeting(experiment, context or {}):
            # Not targeted, return control
            control = experiment.get_control_variant()
            if not control:
                raise ValueError("No control variant for experiment")
            variant_id = control.variant_id
        else:
            # Assign based on strategy
            variant_id = self._select_variant(experiment, assignment_value)

        assignment = ExperimentAssignment(
            experiment_id=experiment.experiment_id,
            variant_id=variant_id,
            assignment_key=assignment_key,
            assignment_value=assignment_value,
            context=context or {},
        )

        self._assignments[key] = assignment
        return assignment

    def _matches_targeting(self, experiment: Experiment, context: dict[str, Any]) -> bool:
        if not experiment.targeting_rules:
            return True

        for rule in experiment.targeting_rules:
            field = rule.get("field", "")
            operator = rule.get("operator", "")
            value: Any = rule.get("value")

            context_value = context.get(field)
            if context_value is None:
                return False

            if operator == "equals":
                matched = context_value == value
            elif operator == "in":
                matched = context_value in value
            elif operator == "not_in":
                matched = context_value not in value
            elif operator == "greater_than":
                matched = context_value > value
            elif operator == "less_than":
                matched = context_value < value
            elif operator == "contains":
                matched = value in str(context_value)
            else:
                # Unknown operator must not silently match everyone
                logger.warning(f"Unknown targeting operator: {operator}")
                return False

            if not matched:
                return False

        return True

    def _select_variant(self, experiment: Experiment, assignment_value: str) -> str:
        if experiment.assignment_strategy == AssignmentStrategy.RANDOM:
            # Weighted random
            rand = np.random.random()
            cumulative = 0.0
            for variant in experiment.variants:
                cumulative += variant.traffic_allocation
                if rand < cumulative:
                    return variant.variant_id
            return experiment.variants[-1].variant_id

        elif experiment.assignment_strategy == AssignmentStrategy.DETERMINISTIC:
            # Hash-based deterministic assignment
            hash_input = f"{experiment.experiment_id}:{assignment_value}"
            hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
            normalized = (hash_val % 10000) / 10000.0

            cumulative = 0.0
            for variant in experiment.variants:
                cumulative += variant.traffic_allocation
                if normalized < cumulative:
                    return variant.variant_id
            return experiment.variants[-1].variant_id

        elif experiment.assignment_strategy == AssignmentStrategy.STICKY:
            # Would use cookie/storage - fallback to deterministic
            return self._select_variant_deterministic(experiment, assignment_value)

        control = experiment.get_control_variant()
        if control is None:
            raise ValueError(f"Experiment '{experiment.experiment_id}' has no control variant")
        return control.variant_id

    def _select_variant_deterministic(self, experiment: Experiment, assignment_value: str) -> str:
        hash_input = f"{experiment.experiment_id}:{assignment_value}"
        hash_val = int(hashlib.md5(hash_input.encode()).hexdigest(), 16)
        normalized = (hash_val % 10000) / 10000.0

        cumulative = 0.0
        for variant in experiment.variants:
            cumulative += variant.traffic_allocation
            if normalized < cumulative:
                return variant.variant_id
        return experiment.variants[-1].variant_id

    def get_assignment(
        self,
        experiment_id: str,
        assignment_key: str,
        assignment_value: str,
    ) -> Optional[ExperimentAssignment]:
        key = f"{experiment_id}:{assignment_key}:{assignment_value}"
        return self._assignments.get(key)


class MetricCollector:
    """Collects and aggregates experiment metrics."""

    def __init__(self) -> None:
        self._events: list[ExperimentEvent] = []
        self._aggregates: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "count": 0,
            "sum": 0.0,
            "sum_sq": 0.0,
            "numerator": 0.0,
            "denominator": 0.0,
            "values": [],
        })

    def record_event(self, event: ExperimentEvent) -> None:
        self._events.append(event)

        # Update aggregates
        key = f"{event.experiment_id}:{event.variant_id}:{event.metric_id}"
        agg = self._aggregates[key]

        agg["count"] += 1
        agg["sum"] += event.value
        agg["sum_sq"] += event.value ** 2
        agg["numerator"] += event.numerator
        agg["denominator"] += event.denominator
        agg["values"].append(event.value)

    def record(
        self,
        experiment_id: str,
        variant_id: str,
        metric_id: str,
        value: float = 0.0,
        numerator: float = 0.0,
        denominator: float = 1.0,
        assignment_id: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        event = ExperimentEvent(
            experiment_id=experiment_id,
            variant_id=variant_id,
            metric_id=metric_id,
            assignment_id=assignment_id,
            value=value,
            numerator=numerator,
            denominator=denominator,
            context=context or {},
        )
        self.record_event(event)

    def get_aggregates(
        self,
        experiment_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Get aggregates for all variant/metric combinations."""
        result = {}
        prefix = f"{experiment_id}:"
        for key, agg in self._aggregates.items():
            if key.startswith(prefix):
                variant_metric = key[len(prefix):]
                count = agg["count"]
                if count > 0:
                    mean = agg["sum"] / count
                    variance = (agg["sum_sq"] / count) - (mean ** 2)
                    std_dev = math.sqrt(max(0, variance))

                    result[variant_metric] = {
                        "count": count,
                        "mean": mean,
                        "std_dev": std_dev,
                        "conversion_rate": agg["numerator"] / max(1, agg["denominator"]),
                        "numerator": agg["numerator"],
                        "denominator": agg["denominator"],
                    }
        return result

    def get_events(
        self,
        experiment_id: str,
        variant_id: Optional[str] = None,
        metric_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list[ExperimentEvent]:
        events = [e for e in self._events if e.experiment_id == experiment_id]

        if variant_id:
            events = [e for e in events if e.variant_id == variant_id]
        if metric_id:
            events = [e for e in events if e.metric_id == metric_id]
        if since:
            events = [e for e in events if e.timestamp >= since]

        return events


class StatisticalAnalyzer:
    """Statistical analysis for experiment results."""

    @staticmethod
    def analyze_conversion(
        control_conversions: int,
        control_total: int,
        treatment_conversions: int,
        treatment_total: int,
        alternative: str = "two-sided",
        significance_level: float = 0.05,
    ) -> dict[str, Any]:
        """Analyze conversion rate difference (proportion z-test)."""
        if control_total == 0 or treatment_total == 0:
            return {"error": "Insufficient sample size"}

        p1 = control_conversions / control_total
        p2 = treatment_conversions / treatment_total
        p_pool = (control_conversions + treatment_conversions) / (control_total + treatment_total)

        se = math.sqrt(p_pool * (1 - p_pool) * (1/control_total + 1/treatment_total))

        if se == 0:
            return {"error": "Zero standard error"}

        z = (p2 - p1) / se

        if alternative == "two-sided":
            p_value = 2 * (1 - stats.norm.cdf(abs(z)))
        elif alternative == "greater":
            p_value = 1 - stats.norm.cdf(z)
        else:
            p_value = stats.norm.cdf(z)

        # Confidence interval for difference
        z_alpha = stats.norm.ppf(1 - significance_level / 2)
        se_diff = math.sqrt(p1*(1-p1)/control_total + p2*(1-p2)/treatment_total)
        margin = z_alpha * se_diff
        diff = p2 - p1
        ci = (diff - margin, diff + margin)

        # Lift
        lift = diff / p1 if p1 > 0 else 0
        lift_se = se_diff / p1 if p1 > 0 else 0
        lift_ci = (lift - z_alpha * lift_se, lift + z_alpha * lift_se)

        return {
            "control_rate": p1,
            "treatment_rate": p2,
            "difference": diff,
            "lift": lift,
            "z_score": z,
            "p_value": p_value,
            # np.bool_ is not JSON-serializable and fails `is True` checks
            "significant": bool(p_value < significance_level),
            "confidence_interval": ci,
            "lift_confidence_interval": lift_ci,
            "control_sample": control_total,
            "treatment_sample": treatment_total,
        }

    @staticmethod
    def analyze_continuous(
        control_values: list[float],
        treatment_values: list[float],
        equal_var: bool = False,
        significance_level: float = 0.05,
    ) -> dict[str, Any]:
        """Analyze continuous metric difference (t-test)."""
        if len(control_values) < 2 or len(treatment_values) < 2:
            return {"error": "Insufficient sample size"}

        control_mean = np.mean(control_values)
        treatment_mean = np.mean(treatment_values)
        control_std = np.std(control_values, ddof=1)
        treatment_std = np.std(treatment_values, ddof=1)

        # Welch's t-test (unequal variance)
        t_stat, p_value = stats.ttest_ind(
            treatment_values, control_values, equal_var=equal_var
        )

        # Confidence interval for difference
        z_alpha = stats.norm.ppf(1 - significance_level / 2)
        diff = treatment_mean - control_mean
        se = math.sqrt(control_std**2/len(control_values) + treatment_std**2/len(treatment_values))
        margin = z_alpha * se
        ci = (diff - margin, diff + margin)

        # Effect size (Cohen's d)
        pooled_std = math.sqrt(
            ((len(control_values)-1)*control_std**2 + (len(treatment_values)-1)*treatment_std**2) /
            (len(control_values) + len(treatment_values) - 2)
        )
        cohens_d = diff / pooled_std if pooled_std > 0 else 0

        # Lift vs control (delta-method CI) — should_stop_early's futility
        # check reads lift_confidence_interval; without it the check would
        # default to (0, 0) and declare every significant continuous metric
        # futile regardless of how large the lift is.
        if control_mean != 0:
            lift = float(diff / control_mean)
            lift_se = se / abs(control_mean)
            lift_ci = (lift - z_alpha * lift_se, lift + z_alpha * lift_se)
        else:
            lift = 0.0
            lift_ci = (0.0, 0.0)

        return {
            "control_mean": control_mean,
            "treatment_mean": treatment_mean,
            "control_std": control_std,
            "treatment_std": treatment_std,
            "difference": diff,
            "lift": lift,
            "t_statistic": t_stat,
            "p_value": p_value,
            # np.bool_ is not JSON-serializable and fails `is True` checks
            "significant": bool(p_value < significance_level),
            "confidence_interval": ci,
            "cohens_d": cohens_d,
            "lift_confidence_interval": lift_ci,
            "control_sample": len(control_values),
            "treatment_sample": len(treatment_values),
        }

    @staticmethod
    def calculate_sample_size(
        baseline_rate: float,
        minimum_detectable_effect: float,
        significance_level: float = 0.05,
        power: float = 0.8,
        ratio: float = 1.0,
    ) -> int:
        """Calculate required sample size per variant."""
        # Using normal approximation for proportions
        z_alpha = stats.norm.ppf(1 - significance_level / 2)
        z_beta = stats.norm.ppf(power)

        p1 = baseline_rate
        p2 = baseline_rate * (1 + minimum_detectable_effect)

        # Variance
        var = p1 * (1 - p1) + p2 * (1 - p2) / ratio

        n = ((z_alpha + z_beta) ** 2 * var) / (p2 - p1) ** 2

        return int(math.ceil(n))


class ExperimentManager:
    """
    Manages A/B test experiments lifecycle.
    """

    def __init__(self) -> None:
        self._experiments: dict[str, Experiment] = {}
        self._assignment_engine = AssignmentEngine()
        self._metric_collector = MetricCollector()
        self._analyzer = StatisticalAnalyzer()
        self._running = False
        self._monitor_task: Optional[asyncio.Task] = None

    def create_experiment(self, experiment: Experiment) -> Experiment:
        """Create a new experiment."""
        if experiment.experiment_id in self._experiments:
            raise ValueError(f"Experiment already exists: {experiment.experiment_id}")

        # Validate
        if experiment.get_total_allocation() != 1.0:
            logger.warning(f"Experiment {experiment.experiment_id} allocation != 1.0: {experiment.get_total_allocation()}")

        control_count = sum(1 for v in experiment.variants if v.is_control)
        if control_count != 1:
            raise ValueError("Experiment must have exactly one control variant")

        self._experiments[experiment.experiment_id] = experiment
        logger.info(f"Created experiment: {experiment.name} ({experiment.experiment_id})")
        return experiment

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        return self._experiments.get(experiment_id)

    def list_experiments(
        self,
        status: Optional[ExperimentStatus] = None,
        tags: Optional[list[str]] = None,
    ) -> list[Experiment]:
        experiments = list(self._experiments.values())

        if status:
            experiments = [e for e in experiments if e.status == status]
        if tags:
            experiments = [e for e in experiments if any(t in e.tags for t in tags)]

        return experiments

    def update_experiment(self, experiment_id: str, updates: dict[str, Any]) -> bool:
        if experiment_id not in self._experiments:
            return False

        experiment = self._experiments[experiment_id]
        for key, value in updates.items():
            if hasattr(experiment, key):
                setattr(experiment, key, value)

        experiment.updated_at = datetime.utcnow()
        return True

    def delete_experiment(self, experiment_id: str) -> bool:
        if experiment_id in self._experiments:
            del self._experiments[experiment_id]
            return True
        return False

    def start_experiment(self, experiment_id: str) -> bool:
        if experiment_id not in self._experiments:
            return False

        experiment = self._experiments[experiment_id]
        experiment.status = ExperimentStatus.RUNNING
        experiment.start_time = experiment.start_time or datetime.utcnow()
        experiment.updated_at = datetime.utcnow()
        logger.info(f"Started experiment: {experiment.name}")
        return True

    def stop_experiment(self, experiment_id: str, reason: str = "") -> bool:
        if experiment_id not in self._experiments:
            return False

        experiment = self._experiments[experiment_id]
        experiment.status = ExperimentStatus.STOPPED
        experiment.end_time = datetime.utcnow()
        experiment.results["stop_reason"] = reason
        experiment.updated_at = datetime.utcnow()
        logger.info(f"Stopped experiment: {experiment.name} - {reason}")
        return True

    def pause_experiment(self, experiment_id: str) -> bool:
        if experiment_id not in self._experiments:
            return False

        experiment = self._experiments[experiment_id]
        experiment.status = ExperimentStatus.PAUSED
        experiment.updated_at = datetime.utcnow()
        return True

    def resume_experiment(self, experiment_id: str) -> bool:
        if experiment_id not in self._experiments:
            return False

        experiment = self._experiments[experiment_id]
        experiment.status = ExperimentStatus.RUNNING
        experiment.updated_at = datetime.utcnow()
        return True

    def assign_user(
        self,
        experiment_id: str,
        assignment_key: str,
        assignment_value: str,
        context: Optional[dict[str, Any]] = None,
    ) -> Optional[ExperimentAssignment]:
        """Assign user to experiment variant."""
        experiment = self.get_experiment(experiment_id)
        if not experiment or not experiment.is_active():
            return None

        return self._assignment_engine.assign(experiment, assignment_key, assignment_value, context)

    def record_event(
        self,
        experiment_id: str,
        variant_id: str,
        metric_id: str,
        value: float = 0.0,
        numerator: float = 0.0,
        denominator: float = 1.0,
        assignment_id: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record experiment event."""
        self._metric_collector.record(
            experiment_id, variant_id, metric_id,
            value, numerator, denominator, assignment_id, context
        )

    def record_conversion(
        self,
        experiment_id: str,
        variant_id: str,
        metric_id: str,
        converted: bool,
        assignment_id: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> None:
        """Record conversion event."""
        self.record_event(
            experiment_id, variant_id, metric_id,
            value=1.0 if converted else 0.0,
            numerator=1.0 if converted else 0.0,
            denominator=1.0,
            assignment_id=assignment_id,
            context=context,
        )

    def analyze_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Analyze experiment results."""
        experiment = self.get_experiment(experiment_id)
        if not experiment:
            return {"error": "Experiment not found"}

        aggregates = self._metric_collector.get_aggregates(experiment_id)
        control = experiment.get_control_variant()
        if not control:
            return {"error": "No control variant"}

        results: dict[str, Any] = {
            "experiment_id": experiment_id,
            "experiment_name": experiment.name,
            "status": experiment.status.value,
            "variants": [],
            "metrics": [metric.to_dict() for metric in experiment.metrics],
        }

        for variant in experiment.variants:
            variant_data: dict[str, Any] = {
                "variant_id": variant.variant_id,
                "name": variant.name,
                "is_control": variant.is_control,
                "allocation": variant.traffic_allocation,
                "metrics": {},
            }

            for metric in experiment.metrics:
                key = f"{variant.variant_id}:{metric.metric_id}"
                agg = aggregates.get(key, {})

                if not agg or agg["count"] < experiment.minimum_sample_size:
                    variant_data["metrics"][metric.metric_id] = {
                        "status": "insufficient_data",
                        "sample_size": agg.get("count", 0),
                    }
                    continue

                # Compare with control
                if variant.is_control:
                    metric_result = {
                        "sample_size": agg["count"],
                        "mean": agg["mean"],
                        "std_dev": agg["std_dev"],
                        "conversion_rate": agg["conversion_rate"],
                        "is_control": True,
                    }
                else:
                    control_key = f"{control.variant_id}:{metric.metric_id}"
                    control_agg = aggregates.get(control_key, {})

                    if not control_agg or control_agg["count"] < experiment.minimum_sample_size:
                        metric_result = {
                            "status": "insufficient_control_data",
                        }
                    else:
                        # Analyze based on metric type
                        if metric.metric_type == MetricType.CONVERSION:
                            analysis = self._analyzer.analyze_conversion(
                                int(control_agg["numerator"]),
                                int(control_agg["denominator"]),
                                int(agg["numerator"]),
                                int(agg["denominator"]),
                                significance_level=experiment.significance_level,
                            )
                        else:
                            # Get raw values for continuous analysis
                            control_events = self._metric_collector.get_events(
                                experiment_id, control.variant_id, metric.metric_id
                            )
                            treatment_events = self._metric_collector.get_events(
                                experiment_id, variant.variant_id, metric.metric_id
                            )
                            control_values = [e.value for e in control_events]
                            treatment_values = [e.value for e in treatment_events]

                            analysis = self._analyzer.analyze_continuous(
                                control_values, treatment_values,
                                significance_level=experiment.significance_level,
                            )

                        metric_result = {
                            "sample_size": agg["count"],
                            "mean": agg["mean"],
                            "std_dev": agg["std_dev"],
                            "conversion_rate": agg["conversion_rate"],
                            **analysis,
                        }

                variant_data["metrics"][metric.metric_id] = metric_result

            results["variants"].append(variant_data)

        return results

    def get_winner(
        self,
        experiment_id: str,
        metric_id: str,
    ) -> Optional[dict[str, Any]]:
        """Get winning variant for a metric."""
        analysis = self.analyze_experiment(experiment_id)

        if "error" in analysis:
            return None

        best_variant = None
        best_score = float('-inf')

        for variant in analysis["variants"]:
            if variant["is_control"]:
                continue

            metric_result = variant["metrics"].get(metric_id, {})
            if not metric_result.get("significant", False):
                continue

            lift = metric_result.get("lift", 0)
            if lift > best_score:
                best_score = lift
                best_variant = variant

        if best_variant:
            return {
                "variant_id": best_variant["variant_id"],
                "name": best_variant["name"],
                "lift": best_score,
            }

        return None

    def should_stop_early(
        self,
        experiment_id: str,
        futility_threshold: float = 0.01,
        harm_threshold: float = 0.01,
    ) -> tuple[bool, str]:
        """Check if experiment should stop early (futility or harm)."""
        experiment = self.get_experiment(experiment_id)
        if not experiment:
            return False, "Experiment not found"

        analysis = self.analyze_experiment(experiment_id)

        for variant in analysis["variants"]:
            if variant["is_control"]:
                continue

            for _metric_id, metric_result in variant["metrics"].items():
                if not metric_result.get("significant", False):
                    continue

                lift = metric_result.get("lift", 0)
                p_value = metric_result.get("p_value", 1)

                # Check for harm (significant negative lift)
                if lift < -harm_threshold and p_value < experiment.significance_level:
                    return True, f"Harm detected: {variant['name']} has {lift:.2%} lift (p={p_value:.4f})"

                # Check for futility (very small lift with high confidence)
                ci = metric_result.get("lift_confidence_interval", (0, 0))
                if ci[1] < futility_threshold:
                    return True, f"Futility: {variant['name']} max lift {ci[1]:.2%} below threshold"

        return False, ""


class ExperimentAutomation:
    """Automated experiment management."""

    def __init__(self, manager: ExperimentManager):
        self.manager = manager
        self._rules: list[dict[str, Any]] = []

    def add_automation_rule(
        self,
        name: str,
        condition: Callable[[Experiment], bool],
        action: Callable[[Experiment], None],
    ) -> None:
        self._rules.append({
            "name": name,
            "condition": condition,
            "action": action,
        })

    async def evaluate_rules(self) -> list[str]:
        """Evaluate all automation rules."""
        triggered = []

        for experiment in self.manager.list_experiments(ExperimentStatus.RUNNING):
            for rule in self._rules:
                try:
                    if rule["condition"](experiment):
                        rule["action"](experiment)
                        triggered.append(f"{rule['name']} -> {experiment.name}")
                except Exception as e:
                    logger.error(f"Automation rule {rule['name']} failed: {e}")

        return triggered

    async def run_automation_loop(self, interval: int = 300) -> None:
        """Run automation loop."""
        while True:
            try:
                triggered = await self.evaluate_rules()
                if triggered:
                    logger.info(f"Automation triggered: {triggered}")
            except Exception as e:
                logger.error(f"Automation loop error: {e}")

            await asyncio.sleep(interval)


# Pre-built experiment templates
def create_simple_ab_test(
    name: str,
    control_config: dict[str, Any],
    treatment_config: dict[str, Any],
    metric_name: str = "conversion",
    traffic_split: float = 0.5,
    **kwargs: Any
) -> Experiment:
    """Create a simple A/B test with control and one treatment."""
    control = ExperimentVariant(
        variant_id="control",
        name="Control",
        traffic_allocation=1 - traffic_split,
        config=control_config,
        is_control=True,
    )

    treatment = ExperimentVariant(
        variant_id="treatment",
        name="Treatment",
        traffic_allocation=traffic_split,
        config=treatment_config,
        is_control=False,
    )

    metric = ExperimentMetric(
        metric_id=metric_name,
        name=metric_name,
        metric_type=MetricType.CONVERSION,
        higher_is_better=True,
    )

    return Experiment(
        experiment_id=str(uuid.uuid4()),
        name=name,
        variants=[control, treatment],
        metrics=[metric],
        **kwargs
    )


def create_multivariate_test(
    name: str,
    variants: list[dict[str, Any]],
    metrics: list[dict[str, Any]],
    control_index: int = 0,
    **kwargs: Any
) -> Experiment:
    """Create a multivariate test."""
    exp_variants = []
    for i, v in enumerate(variants):
        exp_variants.append(ExperimentVariant(
            variant_id=v.get("id", f"variant_{i}"),
            name=v.get("name", f"Variant {i}"),
            traffic_allocation=v.get("allocation", 1.0 / len(variants)),
            config=v.get("config", {}),
            is_control=(i == control_index),
        ))

    exp_metrics = []
    for m in metrics:
        exp_metrics.append(ExperimentMetric(
            metric_id=m.get("id", m.get("name", "metric")),
            name=m.get("name", "metric"),
            metric_type=MetricType(m.get("type", "conversion")),
            higher_is_better=m.get("higher_is_better", True),
        ))

    return Experiment(
        experiment_id=str(uuid.uuid4()),
        name=name,
        variants=exp_variants,
        metrics=exp_metrics,
        **kwargs
    )


# Global manager
_experiment_manager: Optional[ExperimentManager] = None


def get_experiment_manager() -> ExperimentManager:
    global _experiment_manager
    if _experiment_manager is None:
        _experiment_manager = ExperimentManager()
    return _experiment_manager


# Alias for backward compatibility
get_experiment_manager = get_experiment_manager
