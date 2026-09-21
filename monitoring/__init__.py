"""
Model Monitoring and Governance for PyFault framework.

Provides comprehensive ML model monitoring and governance:
- Data drift detection (KS, PSI, Wasserstein, Chi-square, MMD, PCA)
- Model performance monitoring (accuracy, latency, throughput, custom metrics)
- Feature store (offline/online serving, feature pipelines, lineage)
- Model lineage tracking (Git, environment, artifacts, reproducibility)
"""

from .drift import (
    DriftType,
    DriftSeverity,
    DriftMetric,
    DriftReport,
    KSDriftDetector,
    PSIDriftDetector,
    WassersteinDriftDetector,
    ChiSquareDriftDetector,
    MMDDriftDetector,
    PCADriftDetector,
    DriftDetectorOrchestrator,
    DriftMonitor,
    create_drift_monitor,
)

from .performance import (
    MetricType,
    AlertSeverity,
    PerformanceMetric,
    SLAConfig,
    Alert,
    ModelPerformanceSnapshot,
    MetricsCollector,
    PerformanceDashboard,
    PerformanceMonitor,
    get_metrics_collector,
    get_performance_monitor,
)

from .features import (
    FeatureType,
    FeatureSource,
    ServingMode,
    FeatureDefinition,
    FeatureVector,
    FeatureView,
    FeatureService,
    FeatureRegistry,
    FeatureStore,
    OnlineStore,
    OfflineStore,
    InMemoryOnlineStore,
    ParquetOfflineStore,
    FeaturePipeline,
    FeatureServiceClient,
    FeatureLineageTracker,
    get_feature_registry,
    get_feature_store,
)

from .lineage import (
    ArtifactType,
    LineageEventType,
    Artifact,
    LineageEvent,
    ModelLineage,
    GitTracker,
    EnvironmentTracker,
    ArtifactStore,
    LineageTracker,
    ReproducibilityManager,
    LineageAPI,
    get_lineage_tracker,
    get_reproducibility_manager,
    get_lineage_api,
)

__all__ = [
    # Drift Detection
    "DriftType",
    "DriftSeverity",
    "DriftMetric",
    "DriftReport",
    "KSDriftDetector",
    "PSIDriftDetector",
    "WassersteinDriftDetector",
    "ChiSquareDriftDetector",
    "MMDDriftDetector",
    "PCADriftDetector",
    "DriftDetectorOrchestrator",
    "DriftMonitor",
    "create_drift_monitor",
    # Performance Monitoring
    "MetricType",
    "AlertSeverity",
    "PerformanceMetric",
    "SLAConfig",
    "Alert",
    "ModelPerformanceSnapshot",
    "MetricsCollector",
    "PerformanceDashboard",
    "PerformanceMonitor",
    "get_metrics_collector",
    "get_performance_monitor",
    # Feature Store
    "FeatureType",
    "FeatureSource",
    "ServingMode",
    "FeatureDefinition",
    "FeatureVector",
    "FeatureView",
    "FeatureService",
    "FeatureRegistry",
    "FeatureStore",
    "OnlineStore",
    "OfflineStore",
    "InMemoryOnlineStore",
    "ParquetOfflineStore",
    "FeaturePipeline",
    "FeatureServiceClient",
    "FeatureLineageTracker",
    "get_feature_registry",
    "get_feature_store",
    # Lineage Tracking
    "ArtifactType",
    "LineageEventType",
    "Artifact",
    "LineageEvent",
    "ModelLineage",
    "GitTracker",
    "EnvironmentTracker",
    "ArtifactStore",
    "LineageTracker",
    "ReproducibilityManager",
    "LineageAPI",
    "get_lineage_tracker",
    "get_reproducibility_manager",
    "get_lineage_api",
]