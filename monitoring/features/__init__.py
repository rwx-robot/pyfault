"""
Feature Store for PyFault framework.

Centralized feature management for ML:
- Feature definitions and metadata
- Offline/online feature serving
- Feature versioning and lineage
- Time-travel queries
- Feature transformation pipelines
"""

import asyncio
import logging
import hashlib
import json
import uuid
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union
from collections import defaultdict, deque
from pathlib import Path
import pandas as pd
import numpy as np

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class FeatureType(str, Enum):
    """Feature data types."""
    NUMERICAL = "numerical"
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    TEXT = "text"
    EMBEDDING = "embedding"
    TIMESTAMP = "timestamp"
    ARRAY = "array"


class FeatureSource(str, Enum):
    """Feature computation source."""
    RAW = "raw"              # Raw column from source
    DERIVED = "derived"      # Computed from other features
    AGGREGATE = "aggregate"  # Aggregated over time window
    EMBEDDING = "embedding"  # Learned embedding
    EXTERNAL = "external"    # External API/lookup


class ServingMode(str, Enum):
    """Feature serving mode."""
    ONLINE = "online"        # Low-latency serving
    OFFLINE = "offline"      # Batch/historical
    STREAMING = "streaming"  # Real-time stream


@dataclass
class FeatureDefinition:
    """Feature definition with metadata."""
    feature_id: str
    name: str
    feature_type: FeatureType
    description: str = ""
    source: FeatureSource = FeatureSource.RAW
    
    # Transformation
    transformation: str = ""  # Python expression or function name
    dependencies: List[str] = field(default_factory=list)  # Other feature names
    
    # Metadata
    tags: Dict[str, str] = field(default_factory=dict)
    owner: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    
    # Validation
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_categories: List[str] = field(default_factory=list)
    missing_value_policy: str = "drop"  # drop, fill_zero, fill_mean, fill_median
    
    # Serving
    serving_modes: List[ServingMode] = field(default_factory=lambda: [ServingMode.ONLINE, ServingMode.OFFLINE])
    cache_ttl_seconds: int = 3600
    default_value: Any = None
    
    # Versioning
    version: int = 1
    deprecated: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "feature_id": self.feature_id,
            "name": self.name,
            "feature_type": self.feature_type.value,
            "description": self.description,
            "source": self.source.value,
            "transformation": self.transformation,
            "dependencies": self.dependencies,
            "tags": self.tags,
            "owner": self.owner,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "min_value": self.min_value,
            "max_value": self.max_value,
            "allowed_categories": self.allowed_categories,
            "missing_value_policy": self.missing_value_policy,
            "serving_modes": [m.value for m in self.serving_modes],
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "default_value": self.default_value,
            "version": self.version,
            "deprecated": self.deprecated,
        }


@dataclass
class FeatureVector:
    """A feature vector for an entity."""
    entity_id: str
    features: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.utcnow)
    event_timestamp: Optional[datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "features": self.features,
            "timestamp": self.timestamp.isoformat(),
            "event_timestamp": self.event_timestamp.isoformat() if self.event_timestamp else None,
            "metadata": self.metadata,
        }


@dataclass
class FeatureView:
    """A curated set of features for a model/use case."""
    view_id: str
    name: str
    description: str = ""
    feature_names: List[str] = field(default_factory=list)
    entity_column: str = "entity_id"
    timestamp_column: str = "event_timestamp"
    
    # Filtering
    filter_condition: str = ""
    
    # TTL
    ttl_days: int = 30
    
    # Tags
    tags: Dict[str, str] = field(default_factory=dict)
    owner: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "view_id": self.view_id,
            "name": self.name,
            "description": self.description,
            "feature_names": self.feature_names,
            "entity_column": self.entity_column,
            "timestamp_column": self.timestamp_column,
            "filter_condition": self.filter_condition,
            "ttl_days": self.ttl_days,
            "tags": self.tags,
            "owner": self.owner,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class FeatureService:
    """Feature service configuration for online serving."""
    service_id: str
    name: str
    feature_view_ids: List[str] = field(default_factory=list)
    
    # Serving config
    cache_config: Dict[str, Any] = field(default_factory=dict)
    timeout_ms: int = 100
    
    # Monitoring
    enable_metrics: bool = True
    log_requests: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class FeatureRegistry:
    """
    Central registry for feature definitions and metadata.
    """
    
    def __init__(self):
        self._features: Dict[str, FeatureDefinition] = {}
        self._feature_views: Dict[str, FeatureView] = {}
        self._feature_services: Dict[str, FeatureService] = {}
        self._name_to_id: Dict[str, str] = {}  # name -> feature_id
        self._version_history: Dict[str, List[FeatureDefinition]] = defaultdict(list)
    
    def register_feature(self, feature: FeatureDefinition) -> FeatureDefinition:
        """Register a new feature or update existing."""
        # Check if name exists
        if feature.name in self._name_to_id:
            existing_id = self._name_to_id[feature.name]
            existing = self._features[existing_id]
            
            # Version bump
            feature.feature_id = existing_id
            feature.version = existing.version + 1
            feature.created_at = existing.created_at
            feature.updated_at = datetime.utcnow()
            
            # Archive old version
            self._version_history[existing_id].append(existing)
        else:
            # New feature
            feature.feature_id = feature.feature_id or str(uuid.uuid4())
            self._name_to_id[feature.name] = feature.feature_id
        
        self._features[feature.feature_id] = feature
        logger.info(f"Registered feature: {feature.name} v{feature.version}")
        return feature
    
    def get_feature(self, feature_id: str) -> Optional[FeatureDefinition]:
        return self._features.get(feature_id)
    
    def get_feature_by_name(self, name: str) -> Optional[FeatureDefinition]:
        feature_id = self._name_to_id.get(name)
        if feature_id:
            return self._features.get(feature_id)
        return None
    
    def list_features(
        self,
        feature_type: FeatureType = None,
        source: FeatureSource = None,
        tags: Dict[str, str] = None,
        include_deprecated: bool = False,
    ) -> List[FeatureDefinition]:
        features = list(self._features.values())
        
        if not include_deprecated:
            features = [f for f in features if not f.deprecated]
        
        if feature_type:
            features = [f for f in features if f.feature_type == feature_type]
        if source:
            features = [f for f in features if f.source == source]
        if tags:
            features = [f for f in features if all(f.tags.get(k) == v for k, v in tags.items())]
        
        return features
    
    def get_feature_versions(self, feature_id: str) -> List[FeatureDefinition]:
        return self._version_history.get(feature_id, [])
    
    def deprecate_feature(self, feature_id: str) -> bool:
        if feature_id in self._features:
            self._features[feature_id].deprecated = True
            self._features[feature_id].updated_at = datetime.utcnow()
            return True
        return False
    
    def register_feature_view(self, view: FeatureView) -> FeatureView:
        view.view_id = view.view_id or str(uuid.uuid4())
        self._feature_views[view.view_id] = view
        logger.info(f"Registered feature view: {view.name}")
        return view
    
    def get_feature_view(self, view_id: str) -> Optional[FeatureView]:
        return self._feature_views.get(view_id)
    
    def list_feature_views(self) -> List[FeatureView]:
        return list(self._feature_views.values())
    
    def register_feature_service(self, service: FeatureService) -> FeatureService:
        service.service_id = service.service_id or str(uuid.uuid4())
        self._feature_services[service.service_id] = service
        logger.info(f"Registered feature service: {service.name}")
        return service
    
    def get_feature_service(self, service_id: str) -> Optional[FeatureService]:
        return self._feature_services.get(service_id)


class FeatureStore:
    """
    Feature store with offline/online storage backends.
    """
    
    def __init__(
        self,
        registry: FeatureRegistry = None,
        online_store: "OnlineStore" = None,
        offline_store: "OfflineStore" = None,
    ):
        self.registry = registry or FeatureRegistry()
        self.online_store = online_store or InMemoryOnlineStore()
        self.offline_store = offline_store or ParquetOfflineStore()
        self._transformers: Dict[str, Callable] = {}
    
    def register_transformer(self, name: str, func: Callable) -> None:
        """Register a feature transformation function."""
        self._transformers[name] = func
    
    async def apply_transformation(
        self,
        feature: FeatureDefinition,
        data: pd.DataFrame,
    ) -> pd.Series:
        """Apply feature transformation."""
        if not feature.transformation:
            # Direct column mapping
            if feature.name in data.columns:
                return data[feature.name]
            return pd.Series([feature.default_value] * len(data), index=data.index)
        
        if feature.transformation in self._transformers:
            func = self._transformers[feature.transformation]
            try:
                return await func(data) if asyncio.iscoroutinefunction(func) else func(data)
            except Exception as e:
                logger.error(f"Transformation {feature.transformation} failed: {e}")
                return pd.Series([feature.default_value] * len(data), index=data.index)
        
        # Try eval for simple expressions (with safety)
        try:
            # Only allow safe operations
            safe_globals = {
                "pd": pd,
                "np": np,
                "datetime": datetime,
                "timedelta": timedelta,
            }
            result = eval(feature.transformation, safe_globals, {"data": data})
            if isinstance(result, pd.Series):
                return result
            return pd.Series([result] * len(data), index=data.index)
        except Exception as e:
            logger.error(f"Failed to evaluate transformation: {e}")
            return pd.Series([feature.default_value] * len(data), index=data.index)
    
    def compute_features(
        self,
        feature_names: List[str],
        data: pd.DataFrame,
        entity_column: str = "entity_id",
        timestamp_column: str = "event_timestamp",
    ) -> pd.DataFrame:
        """Compute features for a batch of entities."""
        results = {entity_column: data[entity_column]}
        
        if timestamp_column in data.columns:
            results[timestamp_column] = data[timestamp_column]
        
        for fname in feature_names:
            feature = self.registry.get_feature_by_name(fname)
            if not feature:
                logger.warning(f"Feature {fname} not found")
                results[fname] = feature.default_value if feature else None
                continue
            
            # Check dependencies
            for dep in feature.dependencies:
                if dep not in results and dep not in data.columns:
                    logger.warning(f"Dependency {dep} not computed for {fname}")
            
            # Compute feature
            try:
                if asyncio.iscoroutinefunction(self.apply_transformation):
                    # This would need async context
                    pass
                series = self.apply_transformation(feature, data)
                results[fname] = series
            except Exception as e:
                logger.error(f"Failed to compute {fname}: {e}")
                results[fname] = feature.default_value
        
        return pd.DataFrame(results)
    
    async def write_features(
        self,
        feature_vectors: List[FeatureVector],
        mode: ServingMode = ServingMode.OFFLINE,
    ) -> bool:
        """Write feature vectors to store."""
        if not feature_vectors:
            return True
        
        try:
            if mode == ServingMode.ONLINE:
                await self.online_store.write(feature_vectors)
            elif mode == ServingMode.OFFLINE:
                await self.offline_store.write(feature_vectors)
            elif mode == ServingMode.STREAMING:
                await self.online_store.write(feature_vectors)  # Also update online
                await self.offline_store.write(feature_vectors)  # And offline
            return True
        except Exception as e:
            logger.error(f"Failed to write features: {e}")
            return False
    
    async def read_features(
        self,
        entity_ids: List[str],
        feature_names: List[str],
        mode: ServingMode = ServingMode.ONLINE,
        timestamp: datetime = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Read features for entities."""
        try:
            if mode == ServingMode.ONLINE:
                return await self.online_store.read(entity_ids, feature_names)
            elif mode == ServingMode.OFFLINE:
                return await self.offline_store.read(entity_ids, feature_names, timestamp)
            return {}
        except Exception as e:
            logger.error(f"Failed to read features: {e}")
            return {}


class OnlineStore(ABC):
    """Abstract online feature store."""
    
    @abstractmethod
    async def write(self, feature_vectors: List[FeatureVector]) -> bool:
        pass
    
    @abstractmethod
    async def read(
        self,
        entity_ids: List[str],
        feature_names: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        pass


class OfflineStore(ABC):
    """Abstract offline feature store."""
    
    @abstractmethod
    async def write(self, feature_vectors: List[FeatureVector]) -> bool:
        pass
    
    @abstractmethod
    async def read(
        self,
        entity_ids: List[str],
        feature_names: List[str],
        timestamp: datetime = None,
    ) -> Dict[str, Dict[str, Any]]:
        pass


class InMemoryOnlineStore(OnlineStore):
    """In-memory online feature store."""
    
    def __init__(self):
        self._data: Dict[str, Dict[str, Any]] = {}  # entity_id -> {feature: value}
        self._timestamps: Dict[str, datetime] = {}
        self._lock = asyncio.Lock()
    
    async def write(self, feature_vectors: List[FeatureVector]) -> bool:
        async with self._lock:
            for fv in feature_vectors:
                if fv.entity_id not in self._data:
                    self._data[fv.entity_id] = {}
                
                self._data[fv.entity_id].update(fv.features)
                self._timestamps[fv.entity_id] = fv.timestamp
            return True
    
    async def read(
        self,
        entity_ids: List[str],
        feature_names: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        async with self._lock:
            result = {}
            for eid in entity_ids:
                if eid in self._data:
                    result[eid] = {fn: self._data[eid].get(fn) for fn in feature_names}
                else:
                    result[eid] = {fn: None for fn in feature_names}
            return result


class ParquetOfflineStore(OfflineStore):
    """Parquet-based offline feature store."""
    
    def __init__(self, base_path: str = "./data/feature_store"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._tables: Dict[str, pd.DataFrame] = {}
    
    def _get_table_path(self, feature_view: str) -> Path:
        return self.base_path / f"{feature_view}.parquet"
    
    async def write(self, feature_vectors: List[FeatureVector]) -> bool:
        if not feature_vectors:
            return True
        
        try:
            # Group by feature view (using first feature as proxy)
            df_data = []
            for fv in feature_vectors:
                row = {
                    "entity_id": fv.entity_id,
                    "event_timestamp": fv.event_timestamp or fv.timestamp,
                    "ingestion_timestamp": fv.timestamp,
                    **fv.features,
                }
                df_data.append(row)
            
            df = pd.DataFrame(df_data)
            
            # Write to parquet (partitioned by date)
            for date, group in df.groupby(df["event_timestamp"].dt.date):
                table_path = self.base_path / f"features_{date}.parquet"
                
                if table_path.exists():
                    existing = pd.read_parquet(table_path)
                    combined = pd.concat([existing, group], ignore_index=True)
                    # Deduplicate by entity_id + event_timestamp
                    combined = combined.drop_duplicates(subset=["entity_id", "event_timestamp"], keep="last")
                    combined.to_parquet(table_path, index=False)
                else:
                    group.to_parquet(table_path, index=False)
            
            return True
        except Exception as e:
            logger.error(f"Offline write failed: {e}")
            return False
    
    async def read(
        self,
        entity_ids: List[str],
        feature_names: List[str],
        timestamp: datetime = None,
    ) -> Dict[str, Dict[str, Any]]:
        try:
            # Read relevant parquet files
            if timestamp:
                # Read partitions up to timestamp
                date_filter = timestamp.date()
            else:
                date_filter = None
            
            all_files = list(self.base_path.glob("features_*.parquet"))
            if not all_files:
                return {eid: {fn: None for fn in feature_names} for eid in entity_ids}
            
            # Read and filter
            dfs = []
            for f in all_files:
                try:
                    df = pd.read_parquet(f)
                    if date_filter and "event_timestamp" in df.columns:
                        df = df[df["event_timestamp"].dt.date <= date_filter]
                    dfs.append(df)
                except:
                    continue
            
            if not dfs:
                return {eid: {fn: None for fn in feature_names} for eid in entity_ids}
            
            combined = pd.concat(dfs, ignore_index=True)
            
            # Filter entities
            combined = combined[combined["entity_id"].isin(entity_ids)]
            
            # Get latest per entity
            combined = combined.sort_values("event_timestamp").drop_duplicates(
                subset=["entity_id"], keep="last"
            )
            
            result = {}
            for eid in entity_ids:
                row = combined[combined["entity_id"] == eid]
                if len(row) > 0:
                    result[eid] = {fn: row.iloc[0].get(fn) for fn in feature_names}
                else:
                    result[eid] = {fn: None for fn in feature_names}
            
            return result
        except Exception as e:
            logger.error(f"Offline read failed: {e}")
            return {eid: {fn: None for fn in feature_names} for eid in entity_ids}


class FeaturePipeline:
    """
    Feature transformation pipeline with DAG execution.
    """
    
    def __init__(self, registry: FeatureRegistry):
        self.registry = registry
        self._steps: List[Tuple[str, Callable]] = []  # (feature_name, func)
        self._dag: Dict[str, Set[str]] = defaultdict(set)
    
    def add_step(
        self,
        feature_name: str,
        func: Callable[[pd.DataFrame], pd.Series],
        dependencies: List[str] = None,
    ) -> None:
        """Add a transformation step."""
        self._steps.append((feature_name, func))
        if dependencies:
            self._dag[feature_name].update(dependencies)
    
    def get_execution_order(self, feature_names: List[str]) -> List[str]:
        """Get topological execution order."""
        # Kahn's algorithm for topological sort
        in_degree = defaultdict(int)
        subgraph = defaultdict(set)
        
        # Build subgraph for requested features
        visited = set()
        to_visit = set(feature_names)
        
        while to_visit:
            node = to_visit.pop()
            if node in visited:
                continue
            visited.add(node)
            
            for dep in self._dag.get(node, []):
                if dep in feature_names or dep in visited:
                    subgraph[dep].add(node)
                    in_degree[node] += 1
                if dep not in visited:
                    to_visit.add(dep)
        
        # Topological sort
        queue = [n for n in visited if in_degree[n] == 0]
        result = []
        
        while queue:
            node = queue.pop(0)
            result.append(node)
            
            for neighbor in subgraph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        
        if len(result) != len(visited):
            # Cycle detected, return original order
            return feature_names
        
        return result
    
    async def execute(
        self,
        data: pd.DataFrame,
        feature_names: List[str],
    ) -> pd.DataFrame:
        """Execute pipeline on data."""
        order = self.get_execution_order(feature_names)
        results = data.copy()
        
        for feature_name in order:
            # Find the step
            step_func = None
            for fname, func in self._steps:
                if fname == feature_name:
                    step_func = func
                    break
            
            if step_func:
                try:
                    if asyncio.iscoroutinefunction(step_func):
                        results[feature_name] = await step_func(results)
                    else:
                        results[feature_name] = step_func(results)
                except Exception as e:
                    logger.error(f"Pipeline step {feature_name} failed: {e}")
                    if feature_name not in results.columns:
                        results[feature_name] = None
        
        return results[feature_names] if feature_names else results


class FeatureServiceClient:
    """
    Client for online feature serving.
    """
    
    def __init__(
        self,
        feature_store: FeatureStore,
        cache_ttl: int = 300,
    ):
        self.feature_store = feature_store
        self.cache_ttl = cache_ttl
        self._cache: Dict[str, Tuple[Dict[str, Any], datetime]] = {}
    
    def _cache_key(self, entity_id: str, feature_names: List[str]) -> str:
        names = ",".join(sorted(feature_names))
        return f"{entity_id}:{hashlib.md5(names.encode()).hexdigest()[:8]}"
    
    async def get_features(
        self,
        entity_id: str,
        feature_names: List[str],
        use_cache: bool = True,
    ) -> Dict[str, Any]:
        """Get features for a single entity."""
        cache_key = self._cache_key(entity_id, feature_names)
        
        # Check cache
        if use_cache and cache_key in self._cache:
            cached, cached_time = self._cache[cache_key]
            if (datetime.utcnow() - cached_time).total_seconds() < self.cache_ttl:
                return cached
        
        # Fetch from store
        features = await self.feature_store.read_features(
            [entity_id],
            feature_names,
            mode=ServingMode.ONLINE,
        )
        
        result = features.get(entity_id, {})
        
        # Update cache
        if use_cache:
            self._cache[cache_key] = (result, datetime.utcnow())
        
        return result
    
    async def get_batch_features(
        self,
        entity_ids: List[str],
        feature_names: List[str],
        use_cache: bool = True,
    ) -> Dict[str, Dict[str, Any]]:
        """Get features for multiple entities."""
        # Check cache for each entity
        results = {}
        to_fetch = []
        
        for eid in entity_ids:
            cache_key = self._cache_key(eid, feature_names)
            if use_cache and cache_key in self._cache:
                cached, cached_time = self._cache[cache_key]
                if (datetime.utcnow() - cached_time).total_seconds() < self.cache_ttl:
                    results[eid] = cached
                else:
                    to_fetch.append(eid)
            else:
                to_fetch.append(eid)
        
        # Fetch missing
        if to_fetch:
            fetched = await self.feature_store.read_features(
                to_fetch,
                feature_names,
                mode=ServingMode.ONLINE,
            )
            results.update(fetched)
            
            # Update cache
            if use_cache:
                for eid, feats in fetched.items():
                    cache_key = self._cache_key(eid, feature_names)
                    self._cache[cache_key] = (feats, datetime.utcnow())
        
        return results
    
    async def refresh_entity(self, entity_id: str, feature_names: List[str]) -> Dict[str, Any]:
        """Force refresh an entity's features."""
        cache_key = self._cache_key(entity_id, feature_names)
        if cache_key in self._cache:
            del self._cache[cache_key]
        return await self.get_features(entity_id, feature_names, use_cache=False)


class FeatureLineageTracker:
    """
    Tracks feature lineage and provenance.
    """
    
    def __init__(self, registry: FeatureRegistry):
        self.registry = registry
        self._lineage: Dict[str, Dict[str, Any]] = {}
        self._usage: Dict[str, List[str]] = defaultdict(list)  # feature -> [models/views]
    
    def track_feature_creation(
        self,
        feature: FeatureDefinition,
        source: str,
        code: str = "",
    ) -> None:
        """Track when a feature is created."""
        self._lineage[feature.feature_id] = {
            "feature_id": feature.feature_id,
            "name": feature.name,
            "created_at": datetime.utcnow().isoformat(),
            "source": source,
            "code": code,
            "version": feature.version,
            "dependencies": feature.dependencies.copy(),
            "transformations": feature.transformation,
        }
    
    def track_feature_usage(
        self,
        feature_name: str,
        consumer: str,  # model_id or view_id
        consumer_type: str,  # "model" or "view"
    ) -> None:
        """Track feature usage by model or view."""
        feature = self.registry.get_feature_by_name(feature_name)
        if feature:
            key = f"{consumer_type}:{consumer}"
            if key not in self._usage[feature.feature_id]:
                self._usage[feature.feature_id].append(key)
    
    def get_lineage(self, feature_name: str) -> Optional[Dict[str, Any]]:
        """Get full lineage for a feature."""
        feature = self.registry.get_feature_by_name(feature_name)
        if not feature:
            return None
        
        lineage = self._lineage.get(feature.feature_id, {})
        
        # Add upstream dependencies recursively
        upstream = []
        for dep_name in feature.dependencies:
            dep_lineage = self.get_lineage(dep_name)
            if dep_lineage:
                upstream.append(dep_lineage)
        
        lineage["upstream"] = upstream
        lineage["downstream"] = self._usage.get(feature.feature_id, [])
        
        return lineage
    
    def get_impact_analysis(self, feature_name: str) -> Dict[str, Any]:
        """Analyze impact of changing a feature."""
        feature = self.registry.get_feature_by_name(feature_name)
        if not feature:
            return {"error": "Feature not found"}
        
        downstream = self._usage.get(feature.feature_id, [])
        
        return {
            "feature": feature_name,
            "direct_consumers": downstream,
            "consumer_count": len(downstream),
            "risk_level": "high" if len(downstream) > 5 else "medium" if len(downstream) > 0 else "low",
            "recommendation": "Coordinate with downstream consumers before changes" if downstream else "Safe to modify",
        }


# Global instances
_feature_registry: Optional[FeatureRegistry] = None
_feature_store: Optional[FeatureStore] = None


def get_feature_registry() -> FeatureRegistry:
    global _feature_registry
    if _feature_registry is None:
        _feature_registry = FeatureRegistry()
    return _feature_registry


def get_feature_store() -> FeatureStore:
    global _feature_store
    if _feature_store is None:
        _feature_store = FeatureStore()
    return _feature_store


def get_feature_registry() -> FeatureRegistry:
    return get_feature_registry()


def get_feature_store() -> FeatureStore:
    return get_feature_store()


__all__ = [
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
]