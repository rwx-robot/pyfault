"""
Model Performance Monitoring for PyFault framework.

Real-time monitoring of ML model performance:
- Accuracy, precision, recall, F1 tracking
- Latency and throughput metrics
- Custom business metrics
- Automated alerting and SLA monitoring
"""

import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union, cast

import numpy as np
import pandas as pd

from pyfault.common.time import utc_now

logger = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Types of performance metrics."""
    ACCURACY = "accuracy"
    PRECISION = "precision"
    RECALL = "recall"
    F1 = "f1"
    AUC_ROC = "auc_roc"
    AUC_PR = "auc_pr"
    LOG_LOSS = "log_loss"
    BRIER_SCORE = "brier_score"
    LATENCY_P50 = "latency_p50"
    LATENCY_P95 = "latency_p95"
    LATENCY_P99 = "latency_p99"
    THROUGHPUT = "throughput"
    ERROR_RATE = "error_rate"
    CUSTOM = "custom"


class AlertSeverity(str, Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class PerformanceMetric:
    """A single performance metric measurement."""
    metric_id: str
    model_id: str
    metric_type: MetricType
    value: float
    timestamp: datetime = field(default_factory=utc_now)
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "model_id": self.model_id,
            "metric_type": self.metric_type.value,
            "value": self.value,
            "timestamp": self.timestamp.isoformat(),
            "tags": self.tags,
            "metadata": self.metadata,
        }


@dataclass
class SLAConfig:
    """SLA configuration for a metric."""
    metric_type: MetricType
    threshold: float
    comparison: str = "lt"  # lt, gt, lte, gte
    window_minutes: int = 60
    severity: AlertSeverity = AlertSeverity.WARNING
    description: str = ""

    def check(self, value: float) -> bool:
        """Check if value violates SLA."""
        if self.comparison == "lt":
            return value < self.threshold
        elif self.comparison == "gt":
            return value > self.threshold
        elif self.comparison == "lte":
            return value <= self.threshold
        elif self.comparison == "gte":
            return value >= self.threshold
        return False


@dataclass
class Alert:
    """Performance alert."""
    alert_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    model_id: str = ""
    metric_type: MetricType = MetricType.CUSTOM
    severity: AlertSeverity = AlertSeverity.WARNING
    message: str = ""
    value: float = 0.0
    threshold: float = 0.0
    timestamp: datetime = field(default_factory=utc_now)
    acknowledged: bool = False
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "model_id": self.model_id,
            "metric_type": self.metric_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
            "timestamp": self.timestamp.isoformat(),
            "acknowledged": self.acknowledged,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "acknowledged_by": self.acknowledged_by,
        }


@dataclass
class ModelPerformanceSnapshot:
    """Snapshot of model performance at a point in time."""
    model_id: str
    timestamp: datetime
    metrics: dict[MetricType, float] = field(default_factory=dict)
    sample_count: int = 0
    latency_stats: dict[str, float] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)


class MetricsCollector:
    """
    Collects and aggregates performance metrics.
    """

    def __init__(
        self,
        window_size: int = 10000,
        flush_interval: int = 60,
    ):
        self.window_size = window_size
        self.flush_interval = flush_interval

        # In-memory storage
        self._metrics: dict[str, deque] = defaultdict(lambda: deque(maxlen=window_size))
        self._sliding_windows: dict[str, deque[float]] = defaultdict(lambda: deque())
        self._sla_configs: dict[str, list[SLAConfig]] = defaultdict(list)
        self._alerts: list[Alert] = []
        self._alert_callbacks: list[Callable] = []

        # Aggregation
        self._aggregates: dict[str, dict[str, float]] = defaultdict(dict)
        self._last_flush = utc_now()

        # Background tasks
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        self._sla_task: Optional[asyncio.Task] = None

    def record_metric(
        self,
        model_id: str,
        metric_type: MetricType,
        value: float,
        tags: Optional[dict[str, str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> PerformanceMetric:
        """Record a single metric."""
        metric = PerformanceMetric(
            metric_id=str(uuid.uuid4()),
            model_id=model_id,
            metric_type=metric_type,
            value=value,
            tags=tags or {},
            metadata=metadata or {},
        )

        key = f"{model_id}:{metric_type.value}"
        self._metrics[key].append(metric)

        # Update sliding window (full date+hour+minute key: minute-of-hour alone
        # collided across hours, replaying old data into every hour's bucket)
        window_key = (
            f"{model_id}:{metric_type.value}:"
            f"{utc_now().strftime('%Y%m%d%H%M')}"
        )
        self._sliding_windows[window_key].append(value)

        # Check SLA
        self._check_sla(model_id, metric_type, value)

        return metric

    def record_batch(
        self,
        model_id: str,
        metrics: list[tuple[MetricType, float, dict[str, str]]],
    ) -> list[PerformanceMetric]:
        """Record multiple metrics at once."""
        results = []
        for metric_type, value, tags in metrics:
            results.append(self.record_metric(model_id, metric_type, value, tags))
        return results

    def record_prediction(
        self,
        model_id: str,
        y_true: Union[int, float, np.ndarray],
        y_pred: Union[int, float, np.ndarray],
        y_prob: Optional[np.ndarray] = None,
        latency_ms: Optional[float] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> dict[MetricType, float]:
        """Record metrics from a prediction."""
        tags = tags or {}
        results = {}

        # Classification metrics
        if isinstance(y_true, (int, np.integer)) or (isinstance(y_true, np.ndarray) and y_true.ndim == 1):
            y_true = np.atleast_1d(np.asarray(y_true))
            y_pred = np.atleast_1d(np.asarray(y_pred))

            if len(cast(np.ndarray, y_true)) > 0:
                # Accuracy
                acc = np.mean(y_true == y_pred)
                self.record_metric(model_id, MetricType.ACCURACY, acc, tags)
                results[MetricType.ACCURACY] = acc

                # Binary classification metrics
                unique_labels = np.unique(np.concatenate([y_true, y_pred]))
                if len(unique_labels) == 2:
                    # Precision, Recall, F1 for positive class
                    pos_label = unique_labels[1]
                    tp = np.sum((y_true == pos_label) & (y_pred == pos_label))
                    fp = np.sum((y_true != pos_label) & (y_pred == pos_label))
                    fn = np.sum((y_true == pos_label) & (y_pred != pos_label))

                    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
                    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
                    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

                    self.record_metric(model_id, MetricType.PRECISION, precision, tags)
                    self.record_metric(model_id, MetricType.RECALL, recall, tags)
                    self.record_metric(model_id, MetricType.F1, f1, tags)
                    results[MetricType.PRECISION] = precision
                    results[MetricType.RECALL] = recall
                    results[MetricType.F1] = f1

                # AUC if probabilities provided
                if y_prob is not None:
                    try:
                        from sklearn.metrics import (
                            average_precision_score,
                            roc_auc_score,
                        )
                        if len(np.unique(y_true)) == 2:
                            auc = roc_auc_score(y_true, y_prob)
                            self.record_metric(model_id, MetricType.AUC_ROC, auc, tags)
                            results[MetricType.AUC_ROC] = auc

                            ap = average_precision_score(y_true, y_prob)
                            self.record_metric(model_id, MetricType.AUC_PR, ap, tags)
                            results[MetricType.AUC_PR] = ap
                    except Exception:
                        pass

        # Latency
        if latency_ms is not None:
            self.record_metric(model_id, MetricType.LATENCY_P50, latency_ms, tags)
            results[MetricType.LATENCY_P50] = latency_ms

        return results

    def _check_sla(self, model_id: str, metric_type: MetricType, value: float) -> None:
        """Check SLA and create alerts if violated."""
        configs = self._sla_configs.get(model_id, [])

        for config in configs:
            if config.metric_type == metric_type and config.check(value):
                alert = Alert(
                    model_id=model_id,
                    metric_type=metric_type,
                    severity=config.severity,
                    message=f"SLA violated for {model_id}: {metric_type.value} = {value:.4f} (threshold: {config.threshold})",
                    value=value,
                    threshold=config.threshold,
                )
                self._alerts.append(alert)

                # Trigger callbacks
                for callback in self._alert_callbacks:
                    try:
                        callback(alert)
                    except Exception as e:
                        logger.error(f"Alert callback failed: {e}")

    def set_sla(self, model_id: str, configs: list[SLAConfig]) -> None:
        """Set SLA configurations for a model."""
        self._sla_configs[model_id] = configs

    def add_alert_callback(self, callback: Callable[[Alert], Any]) -> None:
        self._alert_callbacks.append(callback)

    def get_metrics(
        self,
        model_id: str,
        metric_type: Optional[MetricType] = None,
        since: Optional[datetime] = None,
        limit: int = 1000,
    ) -> list[PerformanceMetric]:
        """Get recorded metrics."""
        if metric_type:
            key = f"{model_id}:{metric_type.value}"
            metrics = list(self._metrics.get(key, []))
        else:
            metrics = []
            for key, deque_metrics in self._metrics.items():
                if key.startswith(f"{model_id}:"):
                    metrics.extend(deque_metrics)

        if since:
            metrics = [m for m in metrics if m.timestamp >= since]

        return metrics[-limit:]

    def get_aggregates(
        self,
        model_id: str,
        metric_type: MetricType,
        window_minutes: int = 60,
    ) -> dict[str, float]:
        """Get aggregated statistics for a metric."""
        metrics = self.get_metrics(model_id, metric_type)

        if not metrics:
            return {}

        # Filter by window
        cutoff = utc_now() - timedelta(minutes=window_minutes)
        recent = [m for m in metrics if m.timestamp >= cutoff]

        if not recent:
            return {}

        values = [m.value for m in recent]

        return {
            "count": len(values),
            "mean": float(np.mean(values)),
            "std": float(np.std(values)),
            "min": float(np.min(values)),
            "max": float(np.max(values)),
            "median": float(np.median(values)),
            "p50": float(np.percentile(values, 50)),
            "p90": float(np.percentile(values, 90)),
            "p95": float(np.percentile(values, 95)),
            "p99": float(np.percentile(values, 99)),
        }

    def get_snapshots(
        self,
        model_id: str,
        interval_minutes: int = 5,
        hours: int = 24,
    ) -> list[ModelPerformanceSnapshot]:
        """Get performance snapshots at regular intervals."""
        snapshots = []

        # Get all metric types for model
        metric_types = set()
        for key in self._metrics:
            if key.startswith(f"{model_id}:"):
                # keys are f"{model_id}:{metric_type.value}" -> split always
                # yields at least the metric part after the first colon
                metric_types.add(MetricType(key.split(":")[1]))

        # Create time buckets
        current = utc_now().replace(second=0, microsecond=0)
        start = current - timedelta(hours=hours)

        while current >= start:
            bucket_metrics: dict[MetricType, float] = {}
            sample_count = 0

            for metric_type in metric_types:
                key = f"{model_id}:{metric_type.value}"
                window_key = (
                    f"{model_id}:{metric_type.value}:"
                    f"{current.strftime('%Y%m%d%H%M')}"
                )
                window_values = list(self._sliding_windows.get(window_key, deque()))

                if window_values:
                    bucket_metrics[metric_type] = float(np.mean(window_values))
                    sample_count = max(sample_count, len(window_values))

            if bucket_metrics:
                snapshots.append(ModelPerformanceSnapshot(
                    model_id=model_id,
                    timestamp=current,
                    metrics=bucket_metrics,
                    sample_count=sample_count,
                ))

            current -= timedelta(minutes=interval_minutes)

        return snapshots

    def get_alerts(
        self,
        model_id: Optional[str] = None,
        severity: Optional[AlertSeverity] = None,
        unacknowledged_only: bool = False,
        limit: int = 100,
    ) -> list[Alert]:
        alerts = self._alerts

        if model_id:
            alerts = [a for a in alerts if a.model_id == model_id]
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        if unacknowledged_only:
            alerts = [a for a in alerts if not a.acknowledged]

        return alerts[-limit:]

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> bool:
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert.acknowledged = True
                alert.acknowledged_at = utc_now()
                alert.acknowledged_by = acknowledged_by
                return True
        return False

    async def start(self) -> None:
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        self._sla_task = asyncio.create_task(self._sla_check_loop())
        logger.info("Metrics collector started")

    async def stop(self) -> None:
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
        if self._sla_task:
            self._sla_task.cancel()
        logger.info("Metrics collector stopped")

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.flush_interval)
            await self._flush()

    async def _flush(self) -> None:
        # Persist metrics to storage (placeholder)
        self._last_flush = utc_now()

    async def _sla_check_loop(self) -> None:
        while self._running:
            await asyncio.sleep(60)  # Check every minute
            # SLA checking is done on metric ingestion

    def get_stats(self) -> dict[str, Any]:
        total_metrics = sum(len(d) for d in self._metrics.values())
        total_alerts = len(self._alerts)
        unack_alerts = len([a for a in self._alerts if not a.acknowledged])

        return {
            "total_metrics": total_metrics,
            "models_tracked": len(set(k.split(":")[0] for k in self._metrics)),
            "total_alerts": total_alerts,
            "unacknowledged_alerts": unack_alerts,
            "sla_configs": sum(len(c) for c in self._sla_configs.values()),
        }


class PerformanceDashboard:
    """
    Provides dashboard-ready data for model performance visualization.
    """

    def __init__(self, collector: MetricsCollector):
        self.collector = collector

    def get_model_overview(self, model_id: str) -> dict[str, Any]:
        """Get overview dashboard data for a model."""
        snapshots = self.collector.get_snapshots(model_id, interval_minutes=5, hours=24)

        if not snapshots:
            return {"status": "no_data", "model_id": model_id}

        latest = snapshots[0]

        # Build time series
        timestamps = [s.timestamp.isoformat() for s in reversed(snapshots)]

        # Metric time series
        metric_series = defaultdict(list)
        for s in reversed(snapshots):
            for mt, val in s.metrics.items():
                metric_series[mt.value].append(val)

        # Latency percentiles over time
        latency_series = defaultdict(list)
        for s in reversed(snapshots):
            if MetricType.LATENCY_P50 in s.metrics:
                latency_series["p50"].append(s.metrics[MetricType.LATENCY_P50])
            if MetricType.LATENCY_P95 in s.metrics:
                latency_series["p95"].append(s.metrics[MetricType.LATENCY_P95])
            if MetricType.LATENCY_P99 in s.metrics:
                latency_series["p99"].append(s.metrics[MetricType.LATENCY_P99])

        return {
            "model_id": model_id,
            "status": "healthy" if latest.metrics.get(MetricType.ACCURACY, 0) > 0.8 else "degraded",
            "current_metrics": {k.value: v for k, v in latest.metrics.items()},
            "sample_count": latest.sample_count,
            "time_series": {
                "timestamps": timestamps,
                "metrics": {k: v for k, v in metric_series.items()},
                "latency": latency_series,
            },
            "alerts": [
                a.to_dict() for a in self.collector.get_alerts(model_id=model_id, limit=10)
            ],
        }

    def get_comparison(
        self,
        model_ids: list[str],
        metric_type: MetricType,
        hours: int = 24,
    ) -> dict[str, Any]:
        """Compare multiple models on a metric."""
        comparison = {}

        for model_id in model_ids:
            snapshots = self.collector.get_snapshots(model_id, interval_minutes=5, hours=hours)
            values = [s.metrics.get(metric_type, 0) for s in snapshots if metric_type in s.metrics]

            if values:
                comparison[model_id] = {
                    "current": values[0] if values else 0,
                    "mean": float(np.mean(values)),
                    "min": float(np.min(values)),
                    "max": float(np.max(values)),
                    "trend": "up" if values[0] > values[-1] else "down",
                    "data_points": len(values),
                }

        return {
            "metric": metric_type.value,
            "hours": hours,
            "models": comparison,
        }

    def get_sla_report(self, model_id: str) -> dict[str, Any]:
        """Get SLA compliance report."""
        configs = self.collector._sla_configs.get(model_id, [])
        compliance = {}
        for config in configs:
            aggregates = self.collector.get_aggregates(model_id, config.metric_type, config.window_minutes)

            if aggregates:
                current_value = aggregates.get("mean", 0)
                violated = config.check(current_value)

                compliance[config.metric_type.value] = {
                    "threshold": config.threshold,
                    "comparison": config.comparison,
                    "current_value": current_value,
                    "violated": violated,
                    "severity": config.severity.value,
                    "window_minutes": config.window_minutes,
                }

        recent_alerts = [a for a in self.collector.get_alerts(model_id=model_id, limit=100)
                        if a.timestamp > utc_now() - timedelta(hours=24)]

        return {
            "model_id": model_id,
            "compliance": compliance,
            "recent_alerts_24h": len(recent_alerts),
            "unacknowledged_alerts": len([a for a in self.collector.get_alerts(model_id=model_id) if not a.acknowledged]),
        }


class PerformanceMonitor:
    """
    High-level performance monitoring with automatic metric collection.
    """

    def __init__(
        self,
        collector: Optional[MetricsCollector] = None,
    ):
        self.collector = collector or MetricsCollector()
        self.dashboard = PerformanceDashboard(self.collector)
        self._model_configs: dict[str, dict[str, Any]] = {}

    def configure_model(
        self,
        model_id: str,
        sla_configs: Optional[list[SLAConfig]] = None,
        expected_latency_ms: float = 100,
        expected_accuracy: float = 0.9,
    ) -> None:
        """Configure monitoring for a model."""
        self._model_configs[model_id] = {
            "expected_latency_ms": expected_latency_ms,
            "expected_accuracy": expected_accuracy,
        }

        if sla_configs:
            self.collector.set_sla(model_id, sla_configs)
        else:
            # Default SLAs
            default_slas = [
                SLAConfig(
                    metric_type=MetricType.LATENCY_P95,
                    threshold=expected_latency_ms * 2,
                    comparison="gt",
                    severity=AlertSeverity.WARNING,
                    description=f"P95 latency exceeds {expected_latency_ms * 2}ms",
                ),
                SLAConfig(
                    metric_type=MetricType.ERROR_RATE,
                    threshold=0.05,
                    comparison="gt",
                    severity=AlertSeverity.CRITICAL,
                    description="Error rate exceeds 5%",
                ),
                SLAConfig(
                    metric_type=MetricType.ACCURACY,
                    threshold=expected_accuracy * 0.9,
                    comparison="lt",
                    severity=AlertSeverity.WARNING,
                    description=f"Accuracy drops below {expected_accuracy * 0.9:.0%}",
                ),
            ]
            self.collector.set_sla(model_id, default_slas)

    def record_prediction(
        self,
        model_id: str,
        y_true: Any,
        y_pred: Any,
        y_prob: Optional[np.ndarray] = None,
        latency_ms: Optional[float] = None,
        tags: Optional[dict[str, str]] = None,
    ) -> dict[MetricType, float]:
        """Record a prediction and compute metrics."""
        if model_id not in self._model_configs:
            self.configure_model(model_id)

        return self.collector.record_prediction(model_id, y_true, y_pred, y_prob, latency_ms, tags)

    def record_latency(self, model_id: str, latency_ms: float, tags: Optional[dict[str, str]] = None) -> None:
        self.collector.record_metric(model_id, MetricType.LATENCY_P50, latency_ms, tags)

    def record_throughput(self, model_id: str, requests_per_second: float, tags: Optional[dict[str, str]] = None) -> None:
        self.collector.record_metric(model_id, MetricType.THROUGHPUT, requests_per_second, tags)

    def record_custom(
        self,
        model_id: str,
        name: str,
        value: float,
        tags: Optional[dict[str, str]] = None,
    ) -> None:
        # Use custom metric type
        self.collector.record_metric(
            model_id,
            MetricType.CUSTOM,
            value,
            {**(tags or {}), "custom_metric": name}
        )

    def get_dashboard(self, model_id: str) -> dict[str, Any]:
        return self.dashboard.get_model_overview(model_id)

    def compare_models(
        self,
        model_ids: list[str],
        metric_type: MetricType = MetricType.ACCURACY,
        hours: int = 24,
    ) -> dict[str, Any]:
        return self.dashboard.get_comparison(model_ids, metric_type, hours)

    def get_sla_report(self, model_id: str) -> dict[str, Any]:
        return self.dashboard.get_sla_report(model_id)

    def get_alerts(
        self,
        model_id: Optional[str] = None,
        severity: Optional[AlertSeverity] = None,
    ) -> list[Alert]:
        return self.collector.get_alerts(model_id, severity)

    def acknowledge_alert(self, alert_id: str, acknowledged_by: str) -> bool:
        return self.collector.acknowledge_alert(alert_id, acknowledged_by)

    async def start(self) -> None:
        await self.collector.start()

    async def stop(self) -> None:
        await self.collector.stop()


# Global instances
_performance_monitor: Optional[PerformanceMonitor] = None
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def get_performance_monitor() -> PerformanceMonitor:
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor


# Alias for backward compatibility
get_performance_monitor = get_performance_monitor
