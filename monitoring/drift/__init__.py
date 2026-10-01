"""
Data Drift Detection for PyFault framework.

Provides statistical drift detection for ML model inputs:
- Univariate drift: KS test, Chi-square, PSI, Wasserstein distance
- Multivariate drift: MMD, PCA reconstruction error
- Concept drift: Label distribution shift
- Automated alerting and retraining triggers
"""

import asyncio
import json
import logging
import random
import uuid
import warnings
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import wasserstein_distance
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

from pyfault.common.time import utc_now

warnings.filterwarnings("ignore", category=RuntimeWarning)

logger = logging.getLogger(__name__)


class DriftType(str, Enum):
    """Types of drift."""
    DATA_DRIFT = "data_drift"          # Covariate shift P(X) changes
    CONCEPT_DRIFT = "concept_drift"    # P(Y|X) changes
    LABEL_DRIFT = "label_drift"        # P(Y) changes
    PREDICTION_DRIFT = "prediction_drift"  # Model prediction distribution shift


class DriftSeverity(str, Enum):
    """Drift severity levels."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


_SEVERITY_RANK: dict[DriftSeverity, int] = {
    DriftSeverity.NONE: 0,
    DriftSeverity.LOW: 1,
    DriftSeverity.MEDIUM: 2,
    DriftSeverity.HIGH: 3,
    DriftSeverity.CRITICAL: 4,
}


@dataclass
class DriftMetric:
    """Single drift metric result."""
    metric_name: str
    feature_name: str
    value: float
    threshold: float
    severity: DriftSeverity
    p_value: Optional[float] = None
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "feature_name": self.feature_name,
            "value": self.value,
            "threshold": self.threshold,
            "severity": self.severity.value,
            "p_value": self.p_value,
            "details": self.details,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class DriftReport:
    """Complete drift detection report."""
    report_id: str
    model_id: str
    drift_type: DriftType
    overall_severity: DriftSeverity
    metrics: list[DriftMetric]
    reference_period: tuple[datetime, datetime]
    current_period: tuple[datetime, datetime]
    sample_sizes: dict[str, int]
    recommendations: list[str] = field(default_factory=list)
    timestamp: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "model_id": self.model_id,
            "drift_type": self.drift_type.value,
            "overall_severity": self.overall_severity.value,
            "metrics": [m.to_dict() for m in self.metrics],
            "reference_period": [p.isoformat() for p in self.reference_period],
            "current_period": [p.isoformat() for p in self.current_period],
            "sample_sizes": self.sample_sizes,
            "recommendations": self.recommendations,
            "timestamp": self.timestamp.isoformat(),
        }


class DriftDetector(ABC):
    """Abstract drift detector."""

    @abstractmethod
    def detect(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_names: Optional[list[str]] = None,
    ) -> list[DriftMetric]:
        pass

    @abstractmethod
    def get_detector_name(self) -> str:
        pass


class KSDriftDetector:
    """Kolmogorov-Smirnov test for continuous features."""

    def __init__(self, threshold: float = 0.05, min_samples: int = 30):
        self.threshold = threshold
        self.min_samples = min_samples

    def detect(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_names: Optional[list[str]] = None,
    ) -> list[DriftMetric]:
        metrics = []
        n_features = reference.shape[1] if reference.ndim > 1 else 1

        for i in range(n_features):
            ref_col = reference[:, i] if reference.ndim > 1 else reference
            cur_col = current[:, i] if current.ndim > 1 else current

            name = feature_names[i] if feature_names else f"feature_{i}"

            if len(ref_col) < self.min_samples or len(cur_col) < self.min_samples:
                metrics.append(DriftMetric(
                    metric_name="ks_test",
                    feature_name=name,
                    value=0.0,
                    threshold=self.threshold,
                    severity=DriftSeverity.NONE,
                    details={"error": "Insufficient samples"},
                ))
                continue

            # Remove NaN
            ref_clean = ref_col[~np.isnan(ref_col)]
            cur_clean = cur_col[~np.isnan(cur_col)]

            if len(ref_clean) < self.min_samples or len(cur_clean) < self.min_samples:
                continue

            # KS test
            statistic, p_value = stats.ks_2samp(ref_clean, cur_clean)

            severity = DriftSeverity.NONE
            if p_value < self.threshold:
                if statistic > 0.3:
                    severity = DriftSeverity.HIGH
                elif statistic > 0.15:
                    severity = DriftSeverity.MEDIUM
                else:
                    severity = DriftSeverity.LOW

            metrics.append(DriftMetric(
                metric_name="ks_test",
                feature_name=name,
                value=statistic,
                threshold=self.threshold,
                severity=severity,
                p_value=p_value,
                details={
                    "ref_mean": float(np.mean(ref_clean)),
                    "cur_mean": float(np.mean(cur_clean)),
                    "ref_std": float(np.std(ref_clean)),
                    "cur_std": float(np.std(cur_clean)),
                },
            ))

        return metrics


class PSIDriftDetector:
    """Population Stability Index for categorical/numerical features."""

    def __init__(self, threshold: float = 0.1, bins: int = 10):
        self.threshold = threshold
        self.bins = bins

    def _calculate_psi(self, ref: np.ndarray, cur: np.ndarray) -> float:
        """Calculate PSI between two distributions."""
        # Create bins based on reference quantiles
        try:
            quantiles = np.linspace(0, 1, self.bins + 1)
            bin_edges = np.quantile(ref, quantiles)
            bin_edges = np.unique(bin_edges)

            if len(bin_edges) < 2:
                return 0.0

            ref_hist, _ = np.histogram(ref, bins=bin_edges)
            cur_hist, _ = np.histogram(cur, bins=bin_edges)

            # Normalize
            ref_dist = ref_hist / len(ref)
            cur_dist = cur_hist / len(cur)

            # Avoid division by zero
            ref_dist = np.where(ref_dist == 0, 1e-6, ref_dist)
            cur_dist = np.where(cur_dist == 0, 1e-6, cur_dist)

            psi = np.sum((cur_dist - ref_dist) * np.log(cur_dist / ref_dist))
            return float(psi)
        except Exception:
            return 0.0

    def detect(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_names: Optional[list[str]] = None,
    ) -> list[DriftMetric]:
        metrics = []
        n_features = reference.shape[1] if reference.ndim > 1 else 1

        for i in range(n_features):
            ref_col = reference[:, i] if reference.ndim > 1 else reference
            cur_col = current[:, i] if current.ndim > 1 else current

            name = feature_names[i] if feature_names else f"feature_{i}"

            # Remove NaN
            ref_clean = ref_col[~np.isnan(ref_col)]
            cur_clean = cur_col[~np.isnan(cur_col)]

            if len(ref_clean) < 10 or len(cur_clean) < 10:
                continue

            psi = self._calculate_psi(ref_clean, cur_clean)

            severity = DriftSeverity.NONE
            if psi > self.threshold:
                if psi > 0.25:
                    severity = DriftSeverity.HIGH
                elif psi > 0.15:
                    severity = DriftSeverity.MEDIUM
                else:
                    severity = DriftSeverity.LOW

            metrics.append(DriftMetric(
                metric_name="psi",
                feature_name=name,
                value=psi,
                threshold=self.threshold,
                severity=severity,
                details={
                    "bins": self.bins,
                    "ref_samples": len(ref_clean),
                    "cur_samples": len(cur_clean),
                },
            ))

        return metrics


class WassersteinDriftDetector:
    """Wasserstein distance (Earth Mover's Distance) for continuous features."""

    def __init__(self, threshold: float = 0.1):
        self.threshold = threshold

    def detect(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_names: Optional[list[str]] = None,
    ) -> list[DriftMetric]:
        metrics = []
        n_features = reference.shape[1] if reference.ndim > 1 else 1

        for i in range(n_features):
            ref_col = reference[:, i] if reference.ndim > 1 else reference
            cur_col = current[:, i] if current.ndim > 1 else current

            name = feature_names[i] if feature_names else f"feature_{i}"

            ref_clean = ref_col[~np.isnan(ref_col)]
            cur_clean = cur_col[~np.isnan(cur_col)]

            if len(ref_clean) < 10 or len(cur_clean) < 10:
                continue

            distance = wasserstein_distance(ref_clean, cur_clean)

            # Normalize by reference range
            ref_range = np.max(ref_clean) - np.min(ref_clean)
            normalized = distance / ref_range if ref_range > 0 else distance

            severity = DriftSeverity.NONE
            if normalized > self.threshold:
                if normalized > 0.5:
                    severity = DriftSeverity.HIGH
                elif normalized > 0.2:
                    severity = DriftSeverity.MEDIUM
                else:
                    severity = DriftSeverity.LOW

            metrics.append(DriftMetric(
                metric_name="wasserstein",
                feature_name=name,
                value=normalized,
                threshold=self.threshold,
                severity=severity,
                details={
                    "raw_distance": float(distance),
                    "ref_range": float(ref_range),
                },
            ))

        return metrics


class ChiSquareDriftDetector:
    """Chi-square test for categorical features."""

    def __init__(self, threshold: float = 0.05, max_categories: int = 50):
        self.threshold = threshold
        self.max_categories = max_categories

    def detect(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_names: Optional[list[str]] = None,
    ) -> list[DriftMetric]:
        metrics = []
        n_features = reference.shape[1] if reference.ndim > 1 else 1

        for i in range(n_features):
            ref_col = reference[:, i] if reference.ndim > 1 else reference
            cur_col = current[:, i] if current.ndim > 1 else current

            name = feature_names[i] if feature_names else f"feature_{i}"

            # Convert to string for categorical
            ref_str = np.array([str(x) for x in ref_col if not (isinstance(x, float) and np.isnan(x))])
            cur_str = np.array([str(x) for x in cur_col if not (isinstance(x, float) and np.isnan(x))])

            if len(ref_str) < 10 or len(cur_str) < 10:
                continue

            # Get all categories
            all_categories = np.unique(np.concatenate([ref_str, cur_str]))
            if len(all_categories) > self.max_categories:
                # Too many categories, skip
                continue

            # Count frequencies
            ref_counts = np.array([np.sum(ref_str == cat) for cat in all_categories])
            cur_counts = np.array([np.sum(cur_str == cat) for cat in all_categories])

            # Chi-square test
            # Add small constant to avoid zero
            ref_counts = ref_counts + 0.5
            cur_counts = cur_counts + 0.5

            # Expected frequencies
            total_ref = np.sum(ref_counts)
            total_cur = np.sum(cur_counts)
            total = total_ref + total_cur

            expected_ref = (ref_counts + cur_counts) * total_ref / total
            expected_cur = (ref_counts + cur_counts) * total_cur / total

            # Chi-square statistic
            chi2 = np.sum((ref_counts - expected_ref) ** 2 / expected_ref) + \
                   np.sum((cur_counts - expected_cur) ** 2 / expected_cur)

            dof = len(all_categories) - 1
            p_value = 1 - stats.chi2.cdf(chi2, dof) if dof > 0 else 1.0

            severity = DriftSeverity.NONE
            if p_value < self.threshold:
                if chi2 / dof > 5:
                    severity = DriftSeverity.HIGH
                elif chi2 / dof > 2:
                    severity = DriftSeverity.MEDIUM
                else:
                    severity = DriftSeverity.LOW

            metrics.append(DriftMetric(
                metric_name="chi_square",
                feature_name=name,
                value=float(chi2),
                threshold=self.threshold,
                severity=severity,
                p_value=p_value,
                details={
                    "categories": len(all_categories),
                    "dof": dof,
                    "ref_distribution": {cat: int(cnt) for cat, cnt in zip(all_categories, ref_counts) if cnt > 0.5},
                    "cur_distribution": {cat: int(cnt) for cat, cnt in zip(all_categories, cur_counts) if cnt > 0.5},
                },
            ))

        return metrics


class MMDDriftDetector:
    """Maximum Mean Discrepancy for multivariate drift detection."""

    def __init__(self, threshold: float = 0.05, kernel: str = "rbf", gamma: float = 1.0):
        self.threshold = threshold
        self.kernel = kernel
        self.gamma = gamma

    def _rbf_kernel(self, X: np.ndarray, Y: np.ndarray) -> np.ndarray:
        """Compute RBF kernel matrix."""
        # X: (n, d), Y: (m, d)
        XX = np.sum(X**2, axis=1, keepdims=True)
        YY = np.sum(Y**2, axis=1, keepdims=True)
        XY = X @ Y.T
        dist_sq = XX + YY.T - 2 * XY
        kernel: np.ndarray = np.exp(-self.gamma * dist_sq)
        return kernel

    def _mmd_squared(self, X: np.ndarray, Y: np.ndarray) -> float:
        """Compute MMD^2."""
        K_XX = self._rbf_kernel(X, X)
        K_YY = self._rbf_kernel(Y, Y)
        K_XY = self._rbf_kernel(X, Y)

        m = X.shape[0]
        n = Y.shape[0]

        mmd2 = (np.sum(K_XX) - np.trace(K_XX)) / (m * (m - 1)) + \
               (np.sum(K_YY) - np.trace(K_YY)) / (n * (n - 1)) - \
               2 * np.mean(K_XY)

        return float(max(0, mmd2))

    def detect(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_names: Optional[list[str]] = None,
    ) -> list[DriftMetric]:
        # Remove rows with NaN
        ref_clean = reference[~np.isnan(reference).any(axis=1)]
        cur_clean = current[~np.isnan(current).any(axis=1)]

        if len(ref_clean) < 10 or len(cur_clean) < 10:
            return []

        # Subsample if too large
        max_samples = 1000
        if len(ref_clean) > max_samples:
            idx = np.random.choice(len(ref_clean), max_samples, replace=False)
            ref_clean = ref_clean[idx]
        if len(cur_clean) > max_samples:
            idx = np.random.choice(len(cur_clean), max_samples, replace=False)
            cur_clean = cur_clean[idx]

        # Standardize
        scaler = StandardScaler()
        ref_scaled = scaler.fit_transform(ref_clean)
        cur_scaled = scaler.transform(cur_clean)

        mmd2 = self._mmd_squared(ref_scaled, cur_scaled)
        mmd = np.sqrt(max(0, mmd2))

        severity = DriftSeverity.NONE
        if mmd > self.threshold:
            if mmd > 0.5:
                severity = DriftSeverity.HIGH
            elif mmd > 0.2:
                severity = DriftSeverity.MEDIUM
            else:
                severity = DriftSeverity.LOW

        return [DriftMetric(
            metric_name="mmd",
            feature_name="multivariate",
            value=mmd,
            threshold=self.threshold,
            severity=severity,
            details={
                "kernel": self.kernel,
                "gamma": self.gamma,
                "ref_samples": len(ref_clean),
                "cur_samples": len(cur_clean),
            },
        )]


class PCADriftDetector:
    """PCA-based reconstruction error for multivariate drift."""

    def __init__(self, threshold: float = 2.0, n_components: Optional[int] = None, variance_threshold: float = 0.95):
        self.threshold = threshold
        self.n_components = n_components
        self.variance_threshold = variance_threshold
        self._pca: Any = None
        self._scaler: Any = None

    def detect(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_names: Optional[list[str]] = None,
    ) -> list[DriftMetric]:
        # Clean data
        ref_clean = reference[~np.isnan(reference).any(axis=1)]
        cur_clean = current[~np.isnan(current).any(axis=1)]

        if len(ref_clean) < 20 or len(cur_clean) < 20:
            return []

        # Standardize
        self._scaler = StandardScaler()
        ref_scaled = self._scaler.fit_transform(ref_clean)
        cur_scaled = self._scaler.transform(cur_clean)

        # Fit PCA on reference
        if self.n_components:
            n_comp = min(self.n_components, ref_scaled.shape[1])
        else:
            n_comp = min(ref_scaled.shape[1], 10)

        self._pca = PCA(n_components=n_comp)
        ref_pca = self._pca.fit_transform(ref_scaled)

        # Transform current
        cur_pca = self._pca.transform(cur_scaled)

        # Reconstruction error
        ref_reconstructed = self._pca.inverse_transform(ref_pca)
        cur_reconstructed = self._pca.inverse_transform(cur_pca)

        ref_error = np.mean((ref_scaled - ref_reconstructed) ** 2, axis=1)
        cur_error = np.mean((cur_scaled - cur_reconstructed) ** 2, axis=1)

        # Compare mean reconstruction errors
        ref_mean_error = np.mean(ref_error)
        cur_mean_error = np.mean(cur_error)

        # Ratio
        error_ratio = cur_mean_error / ref_mean_error if ref_mean_error > 0 else 1.0

        severity = DriftSeverity.NONE
        if error_ratio > self.threshold:
            if error_ratio > 5:
                severity = DriftSeverity.HIGH
            elif error_ratio > 2:
                severity = DriftSeverity.MEDIUM
            else:
                severity = DriftSeverity.LOW

        return [DriftMetric(
            metric_name="pca_reconstruction",
            feature_name="multivariate",
            value=error_ratio,
            threshold=self.threshold,
            severity=severity,
            details={
                "n_components": n_comp,
                "explained_variance": float(np.sum(self._pca.explained_variance_ratio_)),
                "ref_mean_error": float(ref_mean_error),
                "cur_mean_error": float(cur_mean_error),
                "ref_samples": len(ref_clean),
                "cur_samples": len(cur_clean),
            },
        )]


class DriftDetectorOrchestrator:
    """
    Orchestrates multiple drift detectors.
    """

    def __init__(self) -> None:
        self.detectors: list[DriftDetector] = []
        self._univariate_detectors: list[Any] = [
            KSDriftDetector(),
            PSIDriftDetector(),
            WassersteinDriftDetector(),
            ChiSquareDriftDetector(),
        ]
        self._multivariate_detectors: list[Any] = [
            MMDDriftDetector(),
            PCADriftDetector(),
        ]

    def add_univariate_detector(self, detector: DriftDetector) -> None:
        self._univariate_detectors.append(detector)

    def add_multivariate_detector(self, detector: DriftDetector) -> None:
        self._multivariate_detectors.append(detector)

    async def detect_drift(
        self,
        reference: np.ndarray,
        current: np.ndarray,
        feature_names: Optional[list[str]] = None,
        model_id: str = "unknown",
        include_multivariate: bool = True,
    ) -> DriftReport:
        """Run all detectors and compile report."""
        all_metrics = []

        # Univariate detectors
        for detector in self._univariate_detectors:
            try:
                metrics = detector.detect(reference, current, feature_names)
                all_metrics.extend(metrics)
            except Exception as e:
                logger.error(f"Detector {type(detector).__name__} failed: {e}")

        # Multivariate detectors
        if include_multivariate:
            for detector in self._multivariate_detectors:
                try:
                    metrics = detector.detect(reference, current, feature_names)
                    all_metrics.extend(metrics)
                except Exception as e:
                    logger.error(f"Multivariate detector {type(detector).__name__} failed: {e}")

        # Determine overall severity
        severities = [m.severity for m in all_metrics]
        if DriftSeverity.CRITICAL in severities:
            overall = DriftSeverity.CRITICAL
        elif DriftSeverity.HIGH in severities:
            overall = DriftSeverity.HIGH
        elif DriftSeverity.MEDIUM in severities:
            overall = DriftSeverity.MEDIUM
        elif DriftSeverity.LOW in severities:
            overall = DriftSeverity.LOW
        else:
            overall = DriftSeverity.NONE

        # Generate recommendations
        recommendations = self._generate_recommendations(all_metrics, overall)

        report = DriftReport(
            report_id=str(uuid.uuid4()),
            model_id=model_id,
            drift_type=DriftType.DATA_DRIFT,
            overall_severity=overall,
            metrics=all_metrics,
            reference_period=(utc_now() - timedelta(days=7), utc_now()),
            current_period=(utc_now() - timedelta(hours=1), utc_now()),
            sample_sizes={
                "reference": len(reference),
                "current": len(current),
            },
            recommendations=recommendations,
        )

        return report

    def _generate_recommendations(
        self,
        metrics: list[DriftMetric],
        overall: DriftSeverity,
    ) -> list[str]:
        recommendations = []

        if overall == DriftSeverity.NONE:
            recommendations.append("No significant drift detected. Continue monitoring.")
            return recommendations

        # Feature-level recommendations
        drifted_features = [m for m in metrics if m.severity in (DriftSeverity.HIGH, DriftSeverity.CRITICAL)]

        if drifted_features:
            feature_names = list(set(m.feature_name for m in drifted_features))
            recommendations.append(
                f"Significant drift detected in features: {', '.join(feature_names)}. "
                "Consider retraining with recent data."
            )

        if overall in (DriftSeverity.HIGH, DriftSeverity.CRITICAL):
            recommendations.append(
                "Critical drift detected. Immediate model retraining recommended. "
                "Consider activating fallback model if available."
            )

        # Check for specific metric patterns
        psi_metrics = [m for m in metrics if m.metric_name == "psi" and m.severity != DriftSeverity.NONE]
        if psi_metrics:
            recommendations.append(
                "Population Stability Index drift detected. "
                "Review feature engineering and data collection pipelines."
            )

        ks_metrics = [m for m in metrics if m.metric_name == "ks_test" and m.severity != DriftSeverity.NONE]
        if ks_metrics:
            recommendations.append(
                "Kolmogorov-Smirnov test indicates distribution shift. "
                "Investigate data source changes."
            )

        return recommendations


class DriftMonitor:
    """
    Continuous drift monitoring with alerting.
    """

    def __init__(
        self,
        orchestrator: DriftDetectorOrchestrator,
        check_interval: int = 3600,  # 1 hour
        alert_threshold: DriftSeverity = DriftSeverity.MEDIUM,
    ):
        self.orchestrator = orchestrator
        self.check_interval = check_interval
        self.alert_threshold = alert_threshold
        self._reference_data: dict[str, np.ndarray] = {}
        self._feature_names: dict[str, list[str]] = {}
        self._reports: deque = deque(maxlen=1000)
        self._callbacks: list[Callable] = []
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def set_reference(
        self,
        model_id: str,
        reference_data: np.ndarray,
        feature_names: Optional[list[str]] = None,
    ) -> None:
        """Set reference distribution for a model."""
        self._reference_data[model_id] = reference_data
        n_features = reference_data.shape[1] if reference_data.ndim > 1 else 1
        self._feature_names[model_id] = feature_names or [f"feature_{i}" for i in range(n_features)]
        logger.info(f"Set reference data for model {model_id}: {reference_data.shape}")

    def add_callback(self, callback: Callable[[DriftReport], Any]) -> None:
        self._callbacks.append(callback)

    async def check_drift(
        self,
        model_id: str,
        current_data: np.ndarray,
    ) -> Optional[DriftReport]:
        """Check drift for a model."""
        if model_id not in self._reference_data:
            logger.warning(f"No reference data for model {model_id}")
            return None

        reference = self._reference_data[model_id]
        feature_names = self._feature_names.get(model_id)

        report = await self.orchestrator.detect_drift(
            reference=reference,
            current=current_data,
            feature_names=feature_names,
            model_id=model_id,
        )

        self._reports.append(report)

        # Trigger alerts
        if _SEVERITY_RANK[report.overall_severity] >= _SEVERITY_RANK[self.alert_threshold]:
            for callback in self._callbacks:
                try:
                    await callback(report)
                except Exception as e:
                    logger.error(f"Alert callback failed: {e}")

        return report

    async def start_monitoring(self) -> None:
        """Start continuous monitoring (placeholder for scheduler integration)."""
        self._running = True
        logger.info("Drift monitoring started")

    async def stop_monitoring(self) -> None:
        self._running = False
        logger.info("Drift monitoring stopped")

    def get_recent_reports(
        self,
        model_id: Optional[str] = None,
        limit: int = 100,
    ) -> list[DriftReport]:
        reports = list(self._reports)
        if model_id:
            reports = [r for r in reports if r.model_id == model_id]
        return reports[-limit:]

    def get_drift_summary(self, model_id: Optional[str] = None) -> dict[str, Any]:
        reports = self.get_recent_reports(model_id, 100)

        if not reports:
            return {"status": "no_data"}

        latest = reports[-1]
        severity_counts: defaultdict[str, int] = defaultdict(int)
        for r in reports:
            severity_counts[r.overall_severity.value] += 1

        return {
            "model_id": model_id,
            "latest_check": latest.timestamp.isoformat(),
            "latest_severity": latest.overall_severity.value,
            "total_checks": len(reports),
            "severity_distribution": dict(severity_counts),
            "drifted_features": list(set(
                m.feature_name
                for r in reports
                for m in r.metrics
                if m.severity != DriftSeverity.NONE
            )),
        }


# Convenience function
def create_drift_monitor(
    model_id: str,
    reference_data: np.ndarray,
    feature_names: Optional[list[str]] = None,
    **kwargs: Any
) -> DriftMonitor:
    """Create a drift monitor with default detectors."""
    orchestrator = DriftDetectorOrchestrator()
    monitor = DriftMonitor(orchestrator, **kwargs)
    monitor.set_reference(model_id, reference_data, feature_names)
    return monitor


# Export
__all__ = [
    "DriftType",
    "DriftSeverity",
    "DriftMetric",
    "DriftReport",
    "DriftDetector",
    "KSDriftDetector",
    "PSIDriftDetector",
    "WassersteinDriftDetector",
    "ChiSquareDriftDetector",
    "MMDDriftDetector",
    "PCADriftDetector",
    "DriftDetectorOrchestrator",
    "DriftMonitor",
    "create_drift_monitor",
]
