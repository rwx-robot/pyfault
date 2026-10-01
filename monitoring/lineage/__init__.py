"""
Model Lineage Tracking for PyFault framework.

Complete provenance tracking for ML models:
- Code version (Git) tracking
- Data versioning and lineage
- Model artifact tracking
- Experiment tracking
- Reproducibility guarantees
"""

import asyncio
import hashlib
import json
import logging
import os
import subprocess
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

from pyfault.common.time import utc_now

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class ArtifactType(str, Enum):
    """Types of artifacts in lineage."""
    MODEL = "model"
    DATASET = "dataset"
    CODE = "code"
    CONFIG = "config"
    ENVIRONMENT = "environment"
    METRIC = "metric"
    FEATURE = "feature"
    PIPELINE = "pipeline"


class LineageEventType(str, Enum):
    """Types of lineage events."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    USED = "used"
    PRODUCED = "produced"
    TRANSFORMED = "transformed"
    DEPLOYED = "deployed"
    RETIRED = "retired"


@dataclass
class Artifact:
    """An artifact in the lineage graph."""
    artifact_id: str
    artifact_type: ArtifactType
    name: str
    version: str
    description: str = ""

    # Content
    path: str = ""  # Local path or URI
    hash: str = ""  # Content hash
    size_bytes: int = 0

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)

    # Provenance
    created_by: str = ""
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    # Lineage
    parent_artifacts: list[str] = field(default_factory=list)  # artifact_ids
    child_artifacts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type.value,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "path": self.path,
            "hash": self.hash,
            "size_bytes": self.size_bytes,
            "metadata": self.metadata,
            "tags": self.tags,
            "created_by": self.created_by,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "parent_artifacts": self.parent_artifacts,
            "child_artifacts": self.child_artifacts,
        }


@dataclass
class LineageEvent:
    """A lineage event."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: LineageEventType = LineageEventType.CREATED
    artifact_id: str = ""
    actor: str = ""  # user, system, pipeline
    timestamp: datetime = field(default_factory=utc_now)
    details: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)  # pipeline_id, experiment_id, etc.

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "artifact_id": self.artifact_id,
            "actor": self.actor,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
            "context": self.context,
        }


@dataclass
class ModelLineage:
    """Complete lineage for a model."""
    model_id: str
    model_name: str
    model_version: str

    # Code lineage
    git_commit: str = ""
    git_branch: str = ""
    git_repo: str = ""
    code_hash: str = ""

    # Data lineage
    training_data: list[str] = field(default_factory=list)  # dataset artifact_ids
    validation_data: list[str] = field(default_factory=list)
    test_data: list[str] = field(default_factory=list)

    # Feature lineage
    features: list[str] = field(default_factory=list)  # feature names
    feature_transformations: dict[str, str] = field(default_factory=dict)

    # Hyperparameters
    hyperparameters: dict[str, Any] = field(default_factory=dict)

    # Environment
    environment: dict[str, str] = field(default_factory=dict)  # pip freeze, conda env
    docker_image: str = ""

    # Training
    training_duration_seconds: float = 0
    training_hardware: str = ""
    framework: str = ""
    framework_version: str = ""

    # Metrics
    metrics: dict[str, float] = field(default_factory=dict)

    # Artifacts
    model_artifact_id: str = ""
    checkpoint_artifacts: list[str] = field(default_factory=list)

    # Deployment
    deployed: bool = False
    deployment_environments: list[str] = field(default_factory=list)

    # Timestamps
    created_at: datetime = field(default_factory=utc_now)
    trained_at: Optional[datetime] = None
    deployed_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "git_commit": self.git_commit,
            "git_branch": self.git_branch,
            "git_repo": self.git_repo,
            "code_hash": self.code_hash,
            "training_data": self.training_data,
            "validation_data": self.validation_data,
            "test_data": self.test_data,
            "features": self.features,
            "feature_transformations": self.feature_transformations,
            "hyperparameters": self.hyperparameters,
            "environment": self.environment,
            "docker_image": self.docker_image,
            "training_duration_seconds": self.training_duration_seconds,
            "training_hardware": self.training_hardware,
            "framework": self.framework,
            "framework_version": self.framework_version,
            "metrics": self.metrics,
            "model_artifact_id": self.model_artifact_id,
            "checkpoint_artifacts": self.checkpoint_artifacts,
            "deployed": self.deployed,
            "deployment_environments": self.deployment_environments,
            "created_at": self.created_at.isoformat(),
            "trained_at": self.trained_at.isoformat() if self.trained_at else None,
            "deployed_at": self.deployed_at.isoformat() if self.deployed_at else None,
        }


class GitTracker:
    """Tracks Git repository state for reproducibility."""

    def __init__(self, repo_path: str = "."):
        self.repo_path = Path(repo_path).resolve()

    def get_commit_hash(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def get_branch(self) -> str:
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def get_repo_url(self) -> str:
        try:
            result = subprocess.run(
                ["git", "config", "--get", "remote.origin.url"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.stdout.strip()
        except Exception:
            return ""

    def get_dirty_files(self) -> list[str]:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            lines = result.stdout.split("\n")
            return [line[3:] for line in lines if line]
        except Exception:
            return []

    def get_diff(self) -> str:
        try:
            result = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout
        except Exception:
            return ""

    def is_dirty(self) -> bool:
        return len(self.get_dirty_files()) > 0

    def get_full_state(self) -> dict[str, Any]:
        return {
            "commit": self.get_commit_hash(),
            "branch": self.get_branch(),
            "repo_url": self.get_repo_url(),
            "dirty": self.is_dirty(),
            "dirty_files": self.get_dirty_files(),
            "diff": self.get_diff() if self.is_dirty() else "",
        }


class EnvironmentTracker:
    """Tracks Python environment for reproducibility."""

    @staticmethod
    def get_pip_freeze() -> str:
        try:
            result = subprocess.run(
                ["pip", "freeze"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout
        except Exception:
            return ""

    @staticmethod
    def get_conda_env() -> str:
        try:
            result = subprocess.run(
                ["conda", "env", "export"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout
        except Exception:
            return ""

    @staticmethod
    def get_python_version() -> str:
        import sys
        return sys.version

    @staticmethod
    def get_system_info() -> dict[str, str]:
        import platform
        return {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "architecture": platform.architecture()[0],
        }

    @staticmethod
    def get_full_environment() -> dict[str, Any]:
        return {
            "pip_freeze": EnvironmentTracker.get_pip_freeze(),
            "conda_env": EnvironmentTracker.get_conda_env(),
            "python_version": EnvironmentTracker.get_python_version(),
            "system_info": EnvironmentTracker.get_system_info(),
            "env_vars": {k: v for k, v in os.environ.items() if k.startswith(("PYTHON", "CONDA", "VIRTUAL"))},
        }


class ArtifactStore:
    """Storage for lineage artifacts."""

    def __init__(self, base_path: str = "./data/lineage"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._artifacts: dict[str, Artifact] = {}
        self._events: list[LineageEvent] = []
        self._index: dict[str, set[str]] = defaultdict(set)  # type -> artifact_ids

    def _compute_hash(self, path: str) -> str:
        """Compute SHA256 hash of file."""
        if not path or not Path(path).exists():
            return ""

        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    async def save_artifact(
        self,
        artifact: Artifact,
        content: Optional[bytes] = None,
    ) -> Artifact:
        """Save artifact to store."""
        # Compute hash if content provided
        if content:
            artifact.hash = hashlib.sha256(content).hexdigest()
            artifact.size_bytes = len(content)

            # Save content
            artifact_path = self.base_path / "artifacts" / artifact.artifact_id[:2] / artifact.artifact_id
            artifact_path.parent.mkdir(parents=True, exist_ok=True)
            artifact_path.write_bytes(content)
            artifact.path = str(artifact_path)

        # If path exists but no content, hash the file
        elif artifact.path and Path(artifact.path).exists():
            artifact.hash = self._compute_hash(artifact.path)
            artifact.size_bytes = Path(artifact.path).stat().st_size

        artifact.updated_at = utc_now()

        # Store in index
        self._artifacts[artifact.artifact_id] = artifact
        self._index[artifact.artifact_type.value].add(artifact.artifact_id)

        # Record event
        event = LineageEvent(
            event_type=LineageEventType.CREATED,
            artifact_id=artifact.artifact_id,
            actor="system",
            details={"name": artifact.name, "version": artifact.version},
        )
        self._events.append(event)

        # Persist metadata
        await self._persist_metadata(artifact)

        return artifact

    async def _persist_metadata(self, artifact: Artifact) -> None:
        meta_path = self.base_path / "metadata" / artifact.artifact_id[:2] / f"{artifact.artifact_id}.json"
        meta_path.parent.mkdir(parents=True, exist_ok=True)

        class NumpyEncoder(json.JSONEncoder):
            def default(self, obj: Any) -> Any:
                if isinstance(obj, np.integer):
                    return int(obj)
                if isinstance(obj, np.floating):
                    return float(obj)
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                if isinstance(obj, datetime):
                    return obj.isoformat()
                return super().default(obj)

        meta_path.write_text(json.dumps(artifact.to_dict(), indent=2, cls=NumpyEncoder))

    def get_artifact(self, artifact_id: str) -> Optional[Artifact]:
        return self._artifacts.get(artifact_id)

    def get_artifacts_by_type(self, artifact_type: ArtifactType) -> list[Artifact]:
        ids = self._index.get(artifact_type.value, set())
        return [self._artifacts[aid] for aid in ids if aid in self._artifacts]

    def search_artifacts(
        self,
        name: Optional[str] = None,
        artifact_type: Optional[ArtifactType] = None,
        tags: Optional[dict[str, str]] = None,
        since: Optional[datetime] = None,
    ) -> list[Artifact]:
        results = []

        for artifact in self._artifacts.values():
            if name and name.lower() not in artifact.name.lower():
                continue
            if artifact_type and artifact.artifact_type != artifact_type:
                continue
            if tags and not all(artifact.tags.get(k) == v for k, v in tags.items()):
                continue
            if since and artifact.created_at < since:
                continue
            results.append(artifact)

        return results

    def add_lineage_relationship(
        self,
        parent_id: str,
        child_id: str,
    ) -> bool:
        """Add parent-child relationship."""
        if parent_id in self._artifacts and child_id in self._artifacts:
            parent = self._artifacts[parent_id]
            child = self._artifacts[child_id]

            if child_id not in parent.child_artifacts:
                parent.child_artifacts.append(child_id)
            if parent_id not in child.parent_artifacts:
                child.parent_artifacts.append(parent_id)

            parent.updated_at = utc_now()
            child.updated_at = utc_now()

            # Record event
            event = LineageEvent(
                event_type=LineageEventType.PRODUCED,
                artifact_id=child_id,
                actor="system",
                details={"parent": parent_id},
            )
            self._events.append(event)

            return True
        return False

    def get_lineage(self, artifact_id: str, depth: int = 5) -> dict[str, Any]:
        """Get full lineage graph for an artifact."""
        artifact = self.get_artifact(artifact_id)
        if not artifact:
            return {}

        def build_tree(aid: str, current_depth: int, direction: str) -> dict[str, Any]:
            if current_depth <= 0:
                return {"artifact_id": aid}

            artifact = self.get_artifact(aid)
            if not artifact:
                return {"artifact_id": aid, "error": "Not found"}

            result = artifact.to_dict()

            if direction in ("upstream", "both"):
                result["parents"] = [
                    build_tree(pid, current_depth - 1, "upstream")
                    for pid in artifact.parent_artifacts
                ]

            if direction in ("downstream", "both"):
                result["children"] = [
                    build_tree(cid, current_depth - 1, "downstream")
                    for cid in artifact.child_artifacts
                ]

            return result

        return build_tree(artifact_id, depth, "both")

    def get_events(
        self,
        artifact_id: Optional[str] = None,
        event_type: Optional[LineageEventType] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[LineageEvent]:
        events = self._events

        if artifact_id:
            events = [e for e in events if e.artifact_id == artifact_id]
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if since:
            events = [e for e in events if e.timestamp >= since]

        return events[-limit:]


class LineageTracker:
    """
    High-level lineage tracking for ML workflows.
    """

    def __init__(self, artifact_store: Optional[ArtifactStore] = None):
        self.artifact_store = artifact_store or ArtifactStore()
        self.git_tracker = GitTracker()
        self.env_tracker = EnvironmentTracker()
        self._current_context: dict[str, Any] = {}
        self._pipeline_runs: dict[str, dict[str, Any]] = {}

    def start_pipeline(
        self,
        pipeline_name: str,
        pipeline_version: str = "",
        context: Optional[dict[str, Any]] = None,
    ) -> str:
        """Start a new pipeline run."""
        pipeline_id = str(uuid.uuid4())

        self._current_context = {
            "pipeline_id": pipeline_id,
            "pipeline_name": pipeline_name,
            "pipeline_version": pipeline_version,
            "started_at": utc_now(),
            "context": context or {},
            "artifacts_created": [],
            "artifacts_used": [],
        }

        self._pipeline_runs[pipeline_id] = self._current_context.copy()

        return pipeline_id

    def end_pipeline(self, pipeline_id: Optional[str] = None, status: str = "success") -> dict[str, Any]:
        """End pipeline run and return summary."""
        if pipeline_id is None:
            pipeline_id = self._current_context.get("pipeline_id")

        if pipeline_id not in self._pipeline_runs:
            return {"error": "Pipeline not found"}

        run = self._pipeline_runs[pipeline_id]
        run["ended_at"] = utc_now()
        run["duration_seconds"] = (run["ended_at"] - run["started_at"]).total_seconds()
        run["status"] = status
        run["artifacts_created_count"] = len(run["artifacts_created"])
        run["artifacts_used_count"] = len(run["artifacts_used"])

        return run

    def track_code(self, path: str = ".") -> dict[str, Any]:
        """Track current code state."""
        git_state = self.git_tracker.get_full_state()
        self._current_context["git"] = git_state
        return git_state

    def track_environment(self) -> dict[str, Any]:
        """Track environment state."""
        env = self.env_tracker.get_full_environment()
        self._current_context["environment"] = env
        return env

    async def log_artifact(
        self,
        name: str,
        artifact_type: ArtifactType,
        path: str = "",
        content: Optional[bytes] = None,
        version: str = "1.0.0",
        description: str = "",
        tags: Optional[dict[str, str]] = None,
        parent_artifacts: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Artifact:
        """Log an artifact."""
        artifact_id = str(uuid.uuid4())

        artifact = Artifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            name=name,
            version=version,
            description=description,
            path=path,
            tags=tags or {},
            created_by=self._current_context.get("pipeline_name", "system"),
            parent_artifacts=parent_artifacts or [],
            metadata=metadata or {},
        )

        # Add git context
        if "git" in self._current_context:
            artifact.metadata["git"] = self._current_context["git"]

        # Add environment context
        if "environment" in self._current_context:
            artifact.metadata["environment"] = self._current_context["environment"]

        # Save to store
        artifact = await self.artifact_store.save_artifact(artifact, content)

        # Track in pipeline
        if "artifacts_created" in self._current_context:
            self._current_context["artifacts_created"].append(artifact_id)

        # Link parent artifacts
        if parent_artifacts:
            for parent_id in parent_artifacts:
                self.artifact_store.add_lineage_relationship(parent_id, artifact_id)

        return artifact

    async def log_dataset(
        self,
        name: str,
        df: pd.DataFrame,
        path: str = "",
        version: str = "1.0.0",
        **kwargs: Any
    ) -> Artifact:
        """Log a dataset artifact."""
        # Save to parquet
        if not path:
            path = f"./data/lineage/datasets/{name}_{uuid.uuid4().hex[:8]}.parquet"
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            df.to_parquet(path, index=False)

        # Compute statistics
        stats = {
            "rows": len(df),
            "columns": len(df.columns),
            "dtypes": {col: str(dtype) for col, dtype in df.dtypes.items()},
            "missing_values": df.isnull().sum().to_dict(),
            "memory_usage_bytes": df.memory_usage(deep=True).sum(),
        }

        extra_metadata = dict(kwargs.pop("metadata", {}))

        return await self.log_artifact(
            name=name,
            artifact_type=ArtifactType.DATASET,
            path=path,
            version=version,
            metadata={"statistics": stats, **extra_metadata},
            **kwargs
        )

    async def log_model(
        self,
        name: str,
        model_path: str,
        framework: str = "",
        version: str = "1.0.0",
        hyperparameters: Optional[dict[str, Any]] = None,
        metrics: Optional[dict[str, float]] = None,
        training_data_artifacts: Optional[list[str]] = None,
        feature_names: Optional[list[str]] = None,
        **kwargs: Any
    ) -> Artifact:
        """Log a model artifact."""
        extra_tags = dict(kwargs.pop("tags", {}))
        extra_metadata = dict(kwargs.pop("metadata", {}))
        artifact = await self.log_artifact(
            name=name,
            artifact_type=ArtifactType.MODEL,
            path=model_path,
            version=version,
            tags={"framework": framework, **extra_tags},
            metadata={
                "framework": framework,
                "hyperparameters": hyperparameters or {},
                "metrics": metrics or {},
                "training_data_artifacts": training_data_artifacts or [],
                "feature_names": feature_names or [],
                **extra_metadata,
            },
            **kwargs
        )
        return artifact

    async def log_code_snapshot(self) -> Artifact:
        """Create a code snapshot artifact."""
        git = self.track_code()
        diff = self.git_tracker.get_diff()

        # Create code bundle
        code_path = f"./data/lineage/code/code_{uuid.uuid4().hex[:8]}.json"
        Path(code_path).parent.mkdir(parents=True, exist_ok=True)

        code_bundle = {
            "git": git,
            "diff": diff,
            "timestamp": utc_now().isoformat(),
        }

        content = json.dumps(code_bundle, indent=2).encode()

        return await self.log_artifact(
            name="code_snapshot",
            artifact_type=ArtifactType.CODE,
            content=content,
            version=git.get("commit", "unknown")[:8],
            metadata=code_bundle,
        )

    def use_artifact(self, artifact_id: str) -> None:
        """Mark an artifact as used in current pipeline."""
        if (
            "artifacts_used" in self._current_context
            and artifact_id not in self._current_context["artifacts_used"]
        ):
            self._current_context["artifacts_used"].append(artifact_id)

    def get_model_lineage(self, model_name: str, model_version: str) -> Optional[ModelLineage]:
        """Get complete lineage for a model."""
        # Search for model artifact
        artifacts = self.artifact_store.search_artifacts(
            name=model_name,
            artifact_type=ArtifactType.MODEL,
        )

        model_artifact = None
        for art in artifacts:
            if art.version == model_version:
                model_artifact = art
                break

        if not model_artifact:
            return None

        # Build lineage
        model_lineage = ModelLineage(
            model_id=model_artifact.artifact_id,
            model_name=model_name,
            model_version=model_version,
        )

        # Extract metadata
        model_lineage.git_commit = model_artifact.metadata.get("git", {}).get("commit", "")
        model_lineage.git_branch = model_artifact.metadata.get("git", {}).get("branch", "")
        model_lineage.git_repo = model_artifact.metadata.get("git", {}).get("repo_url", "")

        model_lineage.hyperparameters = model_artifact.metadata.get("hyperparameters", {})
        model_lineage.metrics = model_artifact.metadata.get("metrics", {})
        model_lineage.features = model_artifact.metadata.get("feature_names", [])
        model_lineage.model_artifact_id = model_artifact.artifact_id
        model_lineage.environment = model_artifact.metadata.get("environment", {})
        model_lineage.framework = model_artifact.tags.get("framework", "")

        # Get training data artifacts from lineage
        for parent_id in model_artifact.parent_artifacts:
            parent = self.artifact_store.get_artifact(parent_id)
            if parent and parent.artifact_type == ArtifactType.DATASET:
                if "train" in parent.tags.get("split", "").lower():
                    model_lineage.training_data.append(parent_id)
                elif "val" in parent.tags.get("split", "").lower() or "valid" in parent.tags.get("split", "").lower():
                    model_lineage.validation_data.append(parent_id)
                elif "test" in parent.tags.get("split", "").lower():
                    model_lineage.test_data.append(parent_id)

        return model_lineage

    def get_pipeline_summary(self, pipeline_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        if pipeline_id is None:
            pipeline_id = self._current_context.get("pipeline_id")
        if pipeline_id is None:
            return None

        return self._pipeline_runs.get(pipeline_id)


class ReproducibilityManager:
    """
    Ensures reproducibility of ML experiments.
    """

    def __init__(self, lineage_tracker: LineageTracker):
        self.lineage = lineage_tracker
        self._snapshots: dict[str, dict[str, Any]] = {}

    def create_snapshot(self, name: str) -> str:
        """Create a reproducibility snapshot."""
        snapshot_id = str(uuid.uuid4())

        snapshot = {
            "snapshot_id": snapshot_id,
            "name": name,
            "timestamp": utc_now().isoformat(),
            "git": self.lineage.track_code(),
            "environment": self.lineage.track_environment(),
            "context": self.lineage._current_context.copy(),
        }

        self._snapshots[snapshot_id] = snapshot

        # Save to file
        snapshot_path = f"./data/lineage/snapshots/{snapshot_id}.json"
        Path(snapshot_path).parent.mkdir(parents=True, exist_ok=True)
        Path(snapshot_path).write_text(json.dumps(snapshot, indent=2, default=str))

        return snapshot_id

    def restore_snapshot(self, snapshot_id: str) -> dict[str, Any]:
        """Restore environment from snapshot."""
        if snapshot_id in self._snapshots:
            snapshot = self._snapshots[snapshot_id]
        else:
            # Load from file
            snapshot_path = f"./data/lineage/snapshots/{snapshot_id}.json"
            if not Path(snapshot_path).exists():
                raise ValueError(f"Snapshot not found: {snapshot_id}")
            snapshot = json.loads(Path(snapshot_path).read_text())

        return {
            "git_commit": snapshot["git"]["commit"],
            "python_packages": snapshot["environment"]["pip_freeze"],
            "environment_vars": snapshot["environment"]["env_vars"],
        }

    def verify_reproducibility(
        self,
        snapshot_id: str,
        tolerance: float = 0.0,
    ) -> dict[str, Any]:
        """Verify current environment matches snapshot."""
        snapshot = self._snapshots.get(snapshot_id)
        if not snapshot:
            snapshot_path = f"./data/lineage/snapshots/{snapshot_id}.json"
            if not Path(snapshot_path).exists():
                return {"error": "Snapshot not found"}
            snapshot = json.loads(Path(snapshot_path).read_text())

        current_git = self.lineage.track_code()
        current_env = self.lineage.track_environment()

        git_match = current_git["commit"] == snapshot["git"]["commit"]
        env_match = current_env["pip_freeze"] == snapshot["environment"]["pip_freeze"]

        return {
            "reproducible": git_match and env_match,
            "git_match": git_match,
            "environment_match": env_match,
            "snapshot_commit": snapshot["git"]["commit"],
            "current_commit": current_git["commit"],
            "differences": {
                "git_dirty": current_git["dirty"],
                "snapshot_dirty": snapshot["git"]["dirty"],
            },
        }


class LineageAPI:
    """
    REST-like API interface for lineage queries.
    """

    def __init__(self, tracker: LineageTracker):
        self.tracker = tracker
        self.store = tracker.artifact_store

    def get_artifact(self, artifact_id: str) -> Optional[dict[str, Any]]:
        artifact = self.store.get_artifact(artifact_id)
        return artifact.to_dict() if artifact else None

    def list_artifacts(
        self,
        artifact_type: Optional[ArtifactType] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if artifact_type:
            artifacts = self.store.get_artifacts_by_type(artifact_type)
        else:
            artifacts = list(self.store._artifacts.values())

        # Sort by created_at descending
        artifacts.sort(key=lambda a: a.created_at, reverse=True)

        return [a.to_dict() for a in artifacts[offset:offset+limit]]

    def search_artifacts(
        self,
        query: str = "",
        artifact_type: Optional[ArtifactType] = None,
        tags: Optional[dict[str, str]] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        artifacts = self.store.search_artifacts(
            name=query,
            artifact_type=artifact_type,
            tags=tags,
        )
        return [a.to_dict() for a in artifacts[:limit]]

    def get_lineage_graph(self, artifact_id: str, depth: int = 3) -> dict[str, Any]:
        return self.store.get_lineage(artifact_id, depth)

    def get_model_lineage(self, model_name: str, model_version: str) -> Optional[dict[str, Any]]:
        lineage = self.tracker.get_model_lineage(model_name, model_version)
        return lineage.to_dict() if lineage else None

    def get_events(
        self,
        artifact_id: Optional[str] = None,
        event_type: Optional[LineageEventType] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        events = self.store.get_events(artifact_id, event_type, limit=limit)
        return [e.to_dict() for e in events]

    def get_pipeline_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        runs = list(self.tracker._pipeline_runs.values())
        runs.sort(key=lambda r: r["started_at"], reverse=True)
        return runs[:limit]


# Global instances
_lineage_tracker: Optional[LineageTracker] = None
_reproducibility_manager: Optional[ReproducibilityManager] = None
_lineage_api: Optional[LineageAPI] = None


def get_lineage_tracker() -> LineageTracker:
    global _lineage_tracker
    if _lineage_tracker is None:
        _lineage_tracker = LineageTracker()
    return _lineage_tracker


def get_reproducibility_manager() -> ReproducibilityManager:
    global _reproducibility_manager
    if _reproducibility_manager is None:
        _reproducibility_manager = ReproducibilityManager(get_lineage_tracker())
    return _reproducibility_manager


def get_lineage_api() -> LineageAPI:
    global _lineage_api
    if _lineage_api is None:
        _lineage_api = LineageAPI(get_lineage_tracker())
    return _lineage_api


# Alias for backward compatibility
get_lineage_tracker = get_lineage_tracker


__all__ = [
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
