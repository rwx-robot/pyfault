"""
Cold Start Optimizer for PyFault Edge Runtime.

Strategies for reducing cold start latency:
- Function pre-warming and pool management
- Code snapshotting and fast restore
- Dependency layer caching
- Predictive scaling based on traffic patterns
- Init-time optimization (lazy loading, connection pooling)
"""

import asyncio
import logging
import time
import uuid
import pickle
import hashlib
import json
import os
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)


class PrewarmStrategy(str, Enum):
    """Pre-warming strategies."""
    ALWAYS_ON = "always_on"           # Keep N instances always warm
    SCHEDULED = "scheduled"           # Warm at specific times
    PREDICTIVE = "predictive"         # ML-based prediction
    ON_DEMAND = "on_demand"           # Warm when first request arrives
    TRAFFIC_BASED = "traffic_based"   # Scale with traffic patterns
    HYBRID = "hybrid"                 # Combination of strategies


class SnapshotFormat(str, Enum):
    """Snapshot formats."""
    PICKLE = "pickle"
    JSON = "json"
    MESSAGEPACK = "msgpack"
    CUSTOM = "custom"


@dataclass
class ColdStartMetrics:
    """Cold start performance metrics."""
    function_id: str
    total_invocations: int = 0
    cold_starts: int = 0
    warm_starts: int = 0
    avg_cold_start_ms: float = 0.0
    avg_warm_start_ms: float = 0.0
    p50_cold_start_ms: float = 0.0
    p95_cold_start_ms: float = 0.0
    p99_cold_start_ms: float = 0.0
    init_phase_ms: float = 0.0
    import_phase_ms: float = 0.0
    handler_phase_ms: float = 0.0
    last_updated: datetime = field(default_factory=datetime.utcnow)
    
    @property
    def cold_start_rate(self) -> float:
        return self.cold_starts / max(1, self.total_invocations)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "function_id": self.function_id,
            "total_invocations": self.total_invocations,
            "cold_starts": self.cold_starts,
            "warm_starts": self.warm_starts,
            "cold_start_rate": self.cold_start_rate,
            "avg_cold_start_ms": self.avg_cold_start_ms,
            "avg_warm_start_ms": self.avg_warm_start_ms,
            "p50_cold_start_ms": self.p50_cold_start_ms,
            "p95_cold_start_ms": self.p95_cold_start_ms,
            "p99_cold_start_ms": self.p99_cold_start_ms,
            "init_phase_ms": self.init_phase_ms,
            "import_phase_ms": self.import_phase_ms,
            "handler_phase_ms": self.handler_phase_ms,
        }


@dataclass
class PrewarmConfig:
    """Pre-warming configuration."""
    strategy: PrewarmStrategy = PrewarmStrategy.HYBRID
    min_warm_instances: int = 1
    max_warm_instances: int = 10
    warm_idle_timeout: int = 300  # seconds
    schedule: Dict[str, List[str]] = field(default_factory=dict)  # cron -> function_ids
    traffic_threshold: float = 0.1  # requests/sec to trigger warming
    prediction_window: int = 300  # seconds
    snapshot_enabled: bool = True
    snapshot_format: SnapshotFormat = SnapshotFormat.PICKLE
    snapshot_path: str = "./data/snapshots"
    lazy_loading: bool = True
    connection_pooling: bool = True


@dataclass
class FunctionSnapshot:
    """Function snapshot for fast restore."""
    snapshot_id: str
    function_id: str
    code_hash: str
    runtime_state: bytes
    memory_state: bytes
    created_at: datetime = field(default_factory=datetime.utcnow)
    size_bytes: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "function_id": self.function_id,
            "code_hash": self.code_hash,
            "created_at": self.created_at.isoformat(),
            "size_bytes": self.size_bytes,
            "metadata": self.metadata,
        }


class SnapshotManager:
    """Manages function snapshots for fast cold start."""
    
    def __init__(self, config: PrewarmConfig):
        self.config = config
        self._snapshots: Dict[str, FunctionSnapshot] = {}  # function_id -> snapshot
        self._snapshot_dir = Path(config.snapshot_path)
        self._snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    async def create_snapshot(
        self,
        function_id: str,
        code_hash: str,
        runtime_state: Any,
        memory_state: Any = None,
    ) -> Optional[FunctionSnapshot]:
        """Create a snapshot of function state."""
        if not self.config.snapshot_enabled:
            return None
        
        try:
            # Serialize state
            if self.config.snapshot_format == SnapshotFormat.PICKLE:
                runtime_bytes = pickle.dumps(runtime_state)
                memory_bytes = pickle.dumps(memory_state) if memory_state else b""
            else:
                runtime_bytes = json.dumps(runtime_state, default=str).encode()
                memory_bytes = json.dumps(memory_state, default=str).encode() if memory_state else b""
            
            snapshot = FunctionSnapshot(
                snapshot_id=str(uuid.uuid4()),
                function_id=function_id,
                code_hash=code_hash,
                runtime_state=runtime_bytes,
                memory_state=memory_bytes,
                size_bytes=len(runtime_bytes) + len(memory_bytes),
            )
            
            # Save to disk
            snapshot_file = self._snapshot_dir / f"{function_id}_{code_hash}.snap"
            async with asyncio.Lock():
                with open(snapshot_file, 'wb') as f:
                    f.write(pickle.dumps(snapshot))
            
            self._snapshots[function_id] = snapshot
            logger.info(f"Created snapshot for {function_id}: {snapshot.size_bytes} bytes")
            return snapshot
            
        except Exception as e:
            logger.error(f"Failed to create snapshot: {e}")
            return None
    
    async def restore_snapshot(self, function_id: str, code_hash: str) -> Optional[FunctionSnapshot]:
        """Restore function from snapshot."""
        snapshot = self._snapshots.get(function_id)
        if snapshot and snapshot.code_hash == code_hash:
            return snapshot
        
        # Try loading from disk
        snapshot_file = self._snapshot_dir / f"{function_id}_{code_hash}.snap"
        if snapshot_file.exists():
            try:
                with open(snapshot_file, 'rb') as f:
                    snapshot = pickle.loads(f.read())
                self._snapshots[function_id] = snapshot
                return snapshot
            except Exception as e:
                logger.error(f"Failed to load snapshot: {e}")
        
        return None
    
    def get_snapshot_info(self, function_id: str) -> Optional[Dict[str, Any]]:
        snapshot = self._snapshots.get(function_id)
        return snapshot.to_dict() if snapshot else None


class TrafficPredictor:
    """Predicts traffic patterns for proactive warming."""
    
    def __init__(self, window_seconds: int = 3600):
        self.window_seconds = window_seconds
        self._history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=1000))
        self._patterns: Dict[str, Dict[int, float]] = {}  # function_id -> hour -> expected_rps
    
    def record_invocation(self, function_id: str, timestamp: datetime = None) -> None:
        ts = timestamp or datetime.utcnow()
        self._history[function_id].append(ts)
    
    def predict_load(
        self,
        function_id: str,
        horizon_seconds: int = 300,
    ) -> float:
        """Predict requests per second for the next horizon."""
        history = self._history.get(function_id, deque())
        if not history:
            return 0.0
        
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self.window_seconds)
        
        # Filter recent history
        recent = [ts for ts in history if ts >= window_start]
        if not recent:
            return 0.0
        
        # Simple rate calculation
        duration = (now - recent[0]).total_seconds() if recent else 1
        rate = len(recent) / max(1, duration)
        
        # Apply time-of-day pattern if available
        hour = now.hour
        if function_id in self._patterns and hour in self._patterns[function_id]:
            pattern_factor = self._patterns[function_id][hour]
            rate *= pattern_factor
        
        return rate
    
    def update_patterns(self) -> None:
        """Update time-of-day patterns from history."""
        for function_id, history in self._history.items():
            hourly_counts = defaultdict(int)
            for ts in history:
                hourly_counts[ts.hour] += 1
            
            if hourly_counts:
                total = sum(hourly_counts.values())
                self._patterns[function_id] = {
                    hour: count / (total / 24) for hour, count in hourly_counts.items()
                }


class PrewarmScheduler:
    """Schedules pre-warming based on configuration."""
    
    def __init__(self, config: PrewarmConfig):
        self.config = config
        self._scheduled_tasks: Dict[str, asyncio.Task] = {}
        self._running = False
    
    async def schedule_warm(
        self,
        function_id: str,
        warm_func: Callable,
        schedule: str,  # cron expression or interval
    ) -> None:
        """Schedule periodic warming."""
        # Parse simple interval (e.g., "300s", "5m", "1h")
        interval = self._parse_interval(schedule)
        if not interval:
            return
        
        async def warm_loop():
            while self._running:
                try:
                    await warm_func(function_id)
                except Exception as e:
                    logger.error(f"Scheduled warm failed for {function_id}: {e}")
                await asyncio.sleep(interval)
        
        task = asyncio.create_task(warm_loop())
        self._scheduled_tasks[function_id] = task
    
    def _parse_interval(self, schedule: str) -> Optional[int]:
        """Parse interval string to seconds."""
        schedule = schedule.lower().strip()
        if schedule.endswith('s'):
            return int(schedule[:-1])
        elif schedule.endswith('m'):
            return int(schedule[:-1]) * 60
        elif schedule.endswith('h'):
            return int(schedule[:-1]) * 3600
        elif schedule.endswith('d'):
            return int(schedule[:-1]) * 86400
        return None
    
    async def cancel_warm(self, function_id: str) -> None:
        task = self._scheduled_tasks.pop(function_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
    
    async def start(self) -> None:
        self._running = True
    
    async def stop(self) -> None:
        self._running = False
        for task in self._scheduled_tasks.values():
            task.cancel()
        self._scheduled_tasks.clear()


class ColdStartOptimizer:
    """
    Main cold start optimizer coordinating all strategies.
    """
    
    def __init__(
        self,
        runtime,
        config: PrewarmConfig = None,
    ):
        self.runtime = runtime
        self.config = config or PrewarmConfig()
        self.snapshot_manager = SnapshotManager(self.config)
        self.predictor = TrafficPredictor()
        self.scheduler = PrewarmScheduler(self.config)
        self._metrics: Dict[str, ColdStartMetrics] = defaultdict(ColdStartMetrics)
        self._warm_pool: Dict[str, Set[str]] = defaultdict(set)  # function_id -> instance_ids
        self._running = False
        self._optimization_task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        self._running = True
        await self.scheduler.start()
        self._optimization_task = asyncio.create_task(self._optimization_loop())
        logger.info("Cold start optimizer started")
    
    async def stop(self) -> None:
        self._running = False
        await self.scheduler.stop()
        if self._optimization_task:
            self._optimization_task.cancel()
            try:
                await self._optimization_task
            except asyncio.CancelledError:
                pass
        logger.info("Cold start optimizer stopped")
    
    def record_invocation(
        self,
        function_id: str,
        cold_start: bool,
        duration_ms: float,
        phases: Dict[str, float] = None,
    ) -> None:
        """Record invocation for metrics and prediction."""
        metrics = self._metrics[function_id]
        metrics.total_invocations += 1
        metrics.last_updated = datetime.utcnow()
        
        if cold_start:
            metrics.cold_starts += 1
            # Update cold start avg
            metrics.avg_cold_start_ms = (
                (metrics.avg_cold_start_ms * (metrics.cold_starts - 1) + duration_ms) 
                / metrics.cold_starts
            )
        else:
            metrics.warm_starts += 1
            metrics.avg_warm_start_ms = (
                (metrics.avg_warm_start_ms * (metrics.warm_starts - 1) + duration_ms) 
                / metrics.warm_starts
            )
        
        if phases:
            metrics.init_phase_ms = phases.get("init", 0)
            metrics.import_phase_ms = phases.get("import", 0)
            metrics.handler_phase_ms = phases.get("handler", 0)
        
        # Update predictor
        self.predictor.record_invocation(function_id)
    
    async def warm_function(
        self,
        function_id: str,
        payload: Dict[str, Any] = None,
    ) -> bool:
        """Warm a specific function."""
        try:
            response = await self.runtime.invoke(
                function_id,
                payload=payload or {"_warm": True},
                context={"_prewarm": True},
            )
            
            if response.status_code == 200:
                self._warm_pool[function_id].add(response.span_id)
                logger.debug(f"Warmed function: {function_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Warm failed for {function_id}: {e}")
            return False
    
    async def ensure_warm(
        self,
        function_id: str,
        min_instances: int = None,
    ) -> int:
        """Ensure minimum warm instances."""
        min_instances = min_instances or self.config.min_warm_instances
        current = len(self._warm_pool.get(function_id, set()))
        
        if current >= min_instances:
            return current
        
        needed = min_instances - current
        warmed = 0
        
        for _ in range(needed):
            if await self.warm_function(function_id):
                warmed += 1
        
        return current + warmed
    
    async def scale_warm_pool(
        self,
        function_id: str,
        target_instances: int,
    ) -> int:
        """Scale warm pool to target size."""
        current = len(self._warm_pool.get(function_id, set()))
        
        if target_instances > current:
            # Warm more
            for _ in range(target_instances - current):
                await self.warm_function(function_id)
        elif target_instances < current:
            # Would need to evict instances (not implemented)
            pass
        
        return len(self._warm_pool.get(function_id, set()))
    
    async def _optimization_loop(self) -> None:
        """Main optimization loop."""
        while self._running:
            try:
                await self._run_optimization()
            except Exception as e:
                logger.error(f"Optimization loop error: {e}")
            
            await asyncio.sleep(60)  # Run every minute
    
    async def _run_optimization(self) -> None:
        """Run optimization based on strategy."""
        if self.config.strategy == PrewarmStrategy.ALWAYS_ON:
            await self._always_on_strategy()
        elif self.config.strategy == PrewarmStrategy.PREDICTIVE:
            await self._predictive_strategy()
        elif self.config.strategy == PrewarmStrategy.TRAFFIC_BASED:
            await self._traffic_based_strategy()
        elif self.config.strategy == PrewarmStrategy.HYBRID:
            await self._hybrid_strategy()
        
        # Update patterns
        self.predictor.update_patterns()
        
        # Cleanup idle warm instances
        await self._cleanup_idle_instances()
    
    async def _always_on_strategy(self) -> None:
        """Keep minimum instances always warm."""
        for function_id in self.runtime.list_functions():
            await self.ensure_warm(function_id)
    
    async def _predictive_strategy(self) -> None:
        """Use ML prediction to pre-warm."""
        for function_id in self.runtime.list_functions():
            predicted_rps = self.predictor.predict_load(
                function_id,
                self.config.prediction_window,
            )
            
            # Scale based on predicted load
            target = max(
                self.config.min_warm_instances,
                min(
                    self.config.max_warm_instances,
                    int(predicted_rps * 2),  # 2x headroom
                ),
            )
            await self.scale_warm_pool(function_id, target)
    
    async def _traffic_based_strategy(self) -> None:
        """Scale based on recent traffic."""
        for function_id in self.runtime.list_functions():
            predicted_rps = self.predictor.predict_load(function_id, 60)
            
            if predicted_rps > self.config.traffic_threshold:
                target = max(
                    self.config.min_warm_instances,
                    min(self.config.max_warm_instances, int(predicted_rps * 1.5)),
                )
            else:
                target = self.config.min_warm_instances
            
            await self.scale_warm_pool(function_id, target)
    
    async def _hybrid_strategy(self) -> None:
        """Combine multiple strategies."""
        for function_id in self.runtime.list_functions():
            # Always maintain minimum
            await self.ensure_warm(function_id)
            
            # Predictive scaling
            predicted_rps = self.predictor.predict_load(function_id, 300)
            
            if predicted_rps > self.config.traffic_threshold:
                target = max(
                    self.config.min_warm_instances,
                    min(self.config.max_warm_instances, int(predicted_rps * 1.5)),
                )
                await self.scale_warm_pool(function_id, target)
    
    async def _cleanup_idle_instances(self) -> None:
        """Remove idle warm instances beyond minimum."""
        for function_id, instances in self._warm_pool.items():
            if len(instances) > self.config.min_warm_instances:
                # In practice, would track last use time and evict oldest
                pass
    
    def get_metrics(self, function_id: str = None) -> Dict[str, Any]:
        if function_id:
            metrics = self._metrics.get(function_id)
            return metrics.to_dict() if metrics else {}
        return {fid: m.to_dict() for fid, m in self._metrics.items()}
    
    def get_warm_pool_status(self) -> Dict[str, int]:
        return {fid: len(instances) for fid, instances in self._warm_pool.items()}


class InitOptimizer:
    """
    Optimizes function initialization phase.
    """
    
    @staticmethod
    def analyze_imports(code: str) -> Dict[str, Any]:
        """Analyze import statements for optimization."""
        import ast
        
        tree = ast.parse(code)
        imports = []
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append({
                        "module": alias.name,
                        "alias": alias.asname,
                        "type": "import",
                    })
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append({
                        "module": f"{module}.{alias.name}" if module else alias.name,
                        "alias": alias.asname,
                        "type": "from_import",
                        "level": node.level,
                    })
        
        return {
            "total_imports": len(imports),
            "imports": imports,
            "heavy_imports": [
                i for i in imports 
                if any(heavy in i["module"] for heavy in [
                    "numpy", "pandas", "tensorflow", "torch", "sklearn",
                    "matplotlib", "scipy", "cv2", "PIL"
                ])
            ],
        }
    
    @staticmethod
    def suggest_lazy_imports(analysis: Dict[str, Any]) -> List[str]:
        """Suggest imports that could be lazy-loaded."""
        return [
            imp["module"] for imp in analysis.get("heavy_imports", [])
        ]
    
    @staticmethod
    def generate_optimized_init(
        code: str,
        lazy_modules: List[str],
    ) -> str:
        """Generate optimized initialization code with lazy imports."""
        # This would transform the code to use lazy imports
        # For now, return original
        return code


# Global optimizer
_coldstart_optimizer: Optional[ColdStartOptimizer] = None


def get_coldstart_optimizer(runtime=None, config: PrewarmConfig = None) -> ColdStartOptimizer:
    global _coldstart_optimizer
    if _coldstart_optimizer is None:
        _coldstart_optimizer = ColdStartOptimizer(runtime or get_runtime(), config)
    return _coldstart_optimizer


# Alias for backward compatibility
get_coldstart_optimizer = get_coldstart_optimizer