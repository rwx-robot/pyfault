"""
Model Versioning and Canary Deployment for PyFault AI framework.

Provides version management for AI models and plugins:
- Semantic versioning
- Model registry with version history
- Canary deployment strategies
- Rollback capabilities
- A/B testing integration
- Promotion pipelines
"""

import asyncio
import hashlib
import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from pyfault.common.time import parse_iso, utc_now

logger = logging.getLogger(__name__)


class VersionStage(str, Enum):
    """Version lifecycle stages."""
    DEVELOPMENT = "development"
    TESTING = "testing"
    STAGING = "staging"
    CANARY = "canary"
    PRODUCTION = "production"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


class DeploymentStrategy(str, Enum):
    """Deployment strategies."""
    BLUE_GREEN = "blue_green"
    CANARY = "canary"
    ROLLING = "rolling"
    RECREATE = "recreate"
    A_B_TEST = "a_b_test"


class PromotionStatus(str, Enum):
    """Promotion request status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class SemanticVersion:
    """Semantic version (MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD])."""
    major: int
    minor: int
    patch: int
    prerelease: str = ""
    build: str = ""

    def __str__(self) -> str:
        version = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease:
            version += f"-{self.prerelease}"
        if self.build:
            version += f"+{self.build}"
        return version

    @classmethod
    def parse(cls, version: str) -> "SemanticVersion":
        """Parse semantic version string."""
        import re

        # Normalize: tolerate leading "v" (git-tag style: v1.2.3)
        version = version.strip()
        if version[:1] in ("v", "V"):
            version = version[1:]

        # Regex for semver
        pattern = r'^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$'
        match = re.match(pattern, version)

        if not match:
            # Try simple version (tolerate "v1.2.3", "1.2.x", "latest", ...)
            parts = version.split('.')

            def _part(idx: int) -> int:
                if idx < len(parts) and parts[idx].isdigit():
                    return int(parts[idx])
                return 0

            return cls(_part(0), _part(1), _part(2))

        major_s, minor_s, patch_s, prerelease, build = match.groups()
        return cls(
            int(major_s), int(minor_s), int(patch_s),
            prerelease or "", build or ""
        )

    def compare(self, other: "SemanticVersion") -> int:
        """Compare with another version. Returns -1, 0, or 1."""
        if self.major != other.major:
            return 1 if self.major > other.major else -1
        if self.minor != other.minor:
            return 1 if self.minor > other.minor else -1
        if self.patch != other.patch:
            return 1 if self.patch > other.patch else -1

        # Handle prerelease
        if self.prerelease and not other.prerelease:
            return -1
        if not self.prerelease and other.prerelease:
            return 1
        if self.prerelease and other.prerelease and self.prerelease != other.prerelease:
            return 1 if self.prerelease > other.prerelease else -1

        return 0

    def __lt__(self, other: "SemanticVersion") -> bool:
        return self.compare(other) < 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, SemanticVersion):
            return NotImplemented
        return self.compare(other) == 0


@dataclass
class ModelVersion:
    """Model/plugin version record."""
    version_id: str
    name: str
    version: SemanticVersion
    stage: VersionStage = VersionStage.DEVELOPMENT

    # Artifact info
    artifact_path: str = ""
    artifact_hash: str = ""
    artifact_size: int = 0

    # Metadata
    description: str = ""
    author: str = ""
    tags: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)

    # Dependencies
    dependencies: dict[str, str] = field(default_factory=dict)  # plugin_id -> version

    # Metrics
    metrics: dict[str, float] = field(default_factory=dict)
    validation_results: dict[str, Any] = field(default_factory=dict)

    # Deployment
    deployed_regions: list[str] = field(default_factory=list)
    traffic_percentage: float = 0.0

    # Timestamps
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    promoted_at: Optional[datetime] = None
    deprecated_at: Optional[datetime] = None

    # Source
    source_commit: str = ""
    source_branch: str = ""
    build_number: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "name": self.name,
            "version": str(self.version),
            "stage": self.stage.value,
            "artifact_path": self.artifact_path,
            "artifact_hash": self.artifact_hash,
            "artifact_size": self.artifact_size,
            "description": self.description,
            "author": self.author,
            "tags": self.tags,
            "labels": self.labels,
            "dependencies": self.dependencies,
            "metrics": self.metrics,
            "validation_results": self.validation_results,
            "deployed_regions": self.deployed_regions,
            "traffic_percentage": self.traffic_percentage,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "promoted_at": self.promoted_at.isoformat() if self.promoted_at else None,
            "deprecated_at": self.deprecated_at.isoformat() if self.deprecated_at else None,
            "source_commit": self.source_commit,
            "source_branch": self.source_branch,
            "build_number": self.build_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelVersion":
        version = SemanticVersion.parse(data["version"])
        return cls(
            version_id=data["version_id"],
            name=data["name"],
            version=version,
            stage=VersionStage(data.get("stage", "development")),
            artifact_path=data.get("artifact_path", ""),
            artifact_hash=data.get("artifact_hash", ""),
            artifact_size=data.get("artifact_size", 0),
            description=data.get("description", ""),
            author=data.get("author", ""),
            tags=data.get("tags", []),
            labels=data.get("labels", {}),
            dependencies=data.get("dependencies", {}),
            metrics=data.get("metrics", {}),
            validation_results=data.get("validation_results", {}),
            deployed_regions=data.get("deployed_regions", []),
            traffic_percentage=data.get("traffic_percentage", 0.0),
            created_at=parse_iso(data["created_at"]) if isinstance(data["created_at"], str) else data["created_at"],
            updated_at=parse_iso(data["updated_at"]) if isinstance(data["updated_at"], str) else data["updated_at"],
            promoted_at=parse_iso(data["promoted_at"]) if data.get("promoted_at") else None,
            deprecated_at=parse_iso(data["deprecated_at"]) if data.get("deprecated_at") else None,
            source_commit=data.get("source_commit", ""),
            source_branch=data.get("source_branch", ""),
            build_number=data.get("build_number", 0),
        )


@dataclass
class DeploymentConfig:
    """Deployment configuration."""
    deployment_id: str
    name: str
    version_id: str
    strategy: DeploymentStrategy = DeploymentStrategy.CANARY

    # Canary settings
    canary_percentage: float = 5.0
    canary_step_percentage: float = 10.0
    canary_interval_minutes: int = 30
    canary_max_steps: int = 10

    # Blue-green settings
    blue_version_id: str = ""
    green_version_id: str = ""

    # Rolling settings
    max_surge: int = 1
    max_unavailable: int = 0

    # Regions
    target_regions: list[str] = field(default_factory=list)
    exclude_regions: list[str] = field(default_factory=list)

    # Validation
    health_check_endpoint: str = "/health"
    success_threshold: float = 0.95
    error_rate_threshold: float = 0.05
    latency_threshold_ms: float = 1000.0

    # Rollback
    auto_rollback: bool = True
    rollback_threshold: float = 0.10  # 10% degradation

    # Schedule
    scheduled_at: Optional[datetime] = None
    timeout_minutes: int = 60

    # Metadata
    created_by: str = ""
    description: str = ""


@dataclass
class Deployment:
    """Active deployment record."""
    deployment_id: str
    config: DeploymentConfig
    status: str = "pending"  # pending, running, completed, failed, rolled_back
    current_step: int = 0
    current_traffic: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: str = ""
    metrics: dict[str, float] = field(default_factory=dict)
    rollback_version_id: str = ""


@dataclass
class PromotionRequest:
    """Request to promote a version to next stage."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version_id: str = ""
    from_stage: VersionStage = VersionStage.TESTING
    to_stage: VersionStage = VersionStage.STAGING
    requested_by: str = ""
    reason: str = ""
    status: PromotionStatus = PromotionStatus.PENDING
    approvers: list[str] = field(default_factory=list)
    required_approvals: int = 1
    created_at: datetime = field(default_factory=utc_now)
    approved_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CanaryMetrics:
    """Metrics for canary analysis."""
    version_id: str
    timestamp: datetime
    request_count: int = 0
    error_count: int = 0
    error_rate: float = 0.0
    latency_p50: float = 0.0
    latency_p95: float = 0.0
    latency_p99: float = 0.0
    cpu_usage: float = 0.0
    memory_usage: float = 0.0
    custom_metrics: dict[str, float] = field(default_factory=dict)


class VersionRegistry:
    """
    Registry for model/plugin versions.
    """

    def __init__(self, storage_path: str = "./data/versions"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._versions: dict[str, ModelVersion] = {}  # version_id -> version
        self._name_index: dict[str, list[str]] = defaultdict(list)  # name -> version_ids
        self._stage_index: dict[VersionStage, set[str]] = defaultdict(set)

    async def initialize(self) -> None:
        await self._load_index()

    async def _load_index(self) -> None:
        index_file = self.storage_path / "index.json"
        if index_file.exists():
            async with asyncio.Lock():
                try:
                    import aiofiles
                    async with aiofiles.open(index_file) as f:
                        data = json.loads(await f.read())
                        for v_data in data:
                            version = ModelVersion.from_dict(v_data)
                            self._versions[version.version_id] = version
                            self._name_index[version.name].append(version.version_id)
                            self._stage_index[version.stage].add(version.version_id)
                except Exception as e:
                    logger.error(f"Failed to load version index: {e}")

    async def _save_index(self) -> None:
        index_file = self.storage_path / "index.json"
        data = [v.to_dict() for v in self._versions.values()]
        try:
            import aiofiles
            async with aiofiles.open(index_file, 'w') as f:
                await f.write(json.dumps(data, indent=2, default=str))
        except Exception as e:
            logger.error(f"Failed to save version index: {e}")

    async def register_version(self, version: ModelVersion) -> bool:
        """Register a new version."""
        if version.version_id in self._versions:
            return False

        self._versions[version.version_id] = version
        self._name_index[version.name].append(version.version_id)
        self._stage_index[version.stage].add(version.version_id)

        await self._save_index()
        logger.info(f"Registered version: {version.name} {version.version} ({version.stage.value})")
        return True

    async def update_version(self, version: ModelVersion) -> bool:
        """Update existing version."""
        if version.version_id not in self._versions:
            return False

        self._versions[version.version_id] = version

        # Re-index unconditionally: callers typically mutate the stored
        # object in place, so the "old" stage/name read below would already
        # be the new value and the indexes would silently go stale.
        for bucket in self._stage_index.values():
            bucket.discard(version.version_id)
        self._stage_index[version.stage].add(version.version_id)

        for ids in self._name_index.values():
            if version.version_id in ids:
                ids.remove(version.version_id)
                break
        self._name_index[version.name].append(version.version_id)

        await self._save_index()
        return True

    def get_version(self, version_id: str) -> Optional[ModelVersion]:
        return self._versions.get(version_id)

    def get_latest_version(
        self,
        name: str,
        stage: Optional[VersionStage] = None,
    ) -> Optional[ModelVersion]:
        version_ids = self._name_index.get(name, [])
        if not version_ids:
            return None

        if stage:
            version_ids = [vid for vid in version_ids if self._versions[vid].stage == stage]

        if not version_ids:
            return None

        # Return highest version
        latest = max(version_ids, key=lambda vid: self._versions[vid].version)
        return self._versions[latest]

    def get_versions(
        self,
        name: Optional[str] = None,
        stage: Optional[VersionStage] = None,
        limit: int = 100,
    ) -> list[ModelVersion]:
        version_ids = []

        if name:
            version_ids = self._name_index.get(name, [])
            if stage:
                version_ids = [
                    vid for vid in version_ids
                    if vid in self._versions and self._versions[vid].stage == stage
                ]
        elif stage:
            version_ids = list(self._stage_index.get(stage, set()))
        else:
            version_ids = list(self._versions.keys())

        versions = [self._versions[vid] for vid in version_ids if vid in self._versions]
        versions.sort(key=lambda v: v.version, reverse=True)
        return versions[:limit]

    async def promote_version(
        self,
        version_id: str,
        new_stage: VersionStage,
    ) -> bool:
        """Promote version to new stage."""
        if version_id not in self._versions:
            return False

        version = self._versions[version_id]
        old_stage = version.stage

        # Validate promotion path
        valid_transitions = {
            VersionStage.DEVELOPMENT: [VersionStage.TESTING],
            VersionStage.TESTING: [VersionStage.STAGING, VersionStage.DEVELOPMENT],
            VersionStage.STAGING: [VersionStage.CANARY, VersionStage.PRODUCTION, VersionStage.TESTING],
            VersionStage.CANARY: [VersionStage.PRODUCTION, VersionStage.STAGING],
            VersionStage.PRODUCTION: [VersionStage.DEPRECATED, VersionStage.STAGING],
            VersionStage.DEPRECATED: [VersionStage.ARCHIVED],
        }

        if new_stage not in valid_transitions.get(old_stage, []):
            logger.warning(f"Invalid promotion: {old_stage.value} -> {new_stage.value}")
            return False

        version.stage = new_stage
        version.updated_at = utc_now()
        version.promoted_at = utc_now()

        self._stage_index[old_stage].discard(version_id)
        self._stage_index[new_stage].add(version_id)

        await self._save_index()
        logger.info(f"Promoted {version.name} {version.version}: {old_stage.value} -> {new_stage.value}")
        return True

    async def deprecate_version(self, version_id: str) -> bool:
        return await self.promote_version(version_id, VersionStage.DEPRECATED)

    def get_production_version(self, name: str) -> Optional[ModelVersion]:
        return self.get_latest_version(name, VersionStage.PRODUCTION)

    def get_canary_versions(self, name: str) -> list[ModelVersion]:
        return self.get_versions(name, VersionStage.CANARY)


class DeploymentManager:
    """
    Manages deployments with various strategies.
    """

    def __init__(self, registry: VersionRegistry):
        self.registry = registry
        self._deployments: dict[str, Deployment] = {}
        self._canary_metrics: dict[str, list[CanaryMetrics]] = defaultdict(list)
        self._running = False
        self._deployment_task: Optional[asyncio.Task] = None

    async def create_deployment(self, config: DeploymentConfig) -> Deployment:
        """Create a new deployment."""
        # Validate version exists BEFORE storing — otherwise a failed
        # creation leaves a ghost pending deployment in _deployments.
        version = self.registry.get_version(config.version_id)
        if not version:
            raise ValueError(f"Version not found: {config.version_id}")

        deployment = Deployment(
            deployment_id=config.deployment_id,
            config=config,
        )
        self._deployments[config.deployment_id] = deployment
        return deployment

    async def start_deployment(self, deployment_id: str) -> bool:
        """Start a deployment."""
        deployment = self._deployments.get(deployment_id)
        if not deployment:
            return False

        if deployment.status != "pending":
            return False

        deployment.status = "running"
        deployment.started_at = utc_now()

        # Start deployment based on strategy
        if deployment.config.strategy == DeploymentStrategy.CANARY:
            self._deployment_task = asyncio.create_task(self._run_canary(deployment))
        elif deployment.config.strategy == DeploymentStrategy.BLUE_GREEN:
            self._deployment_task = asyncio.create_task(self._run_blue_green(deployment))
        elif deployment.config.strategy == DeploymentStrategy.ROLLING:
            self._deployment_task = asyncio.create_task(self._run_rolling(deployment))
        else:
            # RECREATE / A_B_TEST have no executor here — fail explicitly
            # instead of claiming success and leaving status "running" forever.
            deployment.status = "failed"
            deployment.error = (
                f"Unsupported deployment strategy: {deployment.config.strategy.value}")
            return False

        return True

    async def _run_canary(self, deployment: Deployment) -> None:
        """Run canary deployment."""
        config = deployment.config
        version = self.registry.get_version(config.version_id)

        if not version:
            deployment.status = "failed"
            deployment.error = "Version not found"
            return

        try:
            # Initial canary
            deployment.current_traffic = config.canary_percentage
            version.traffic_percentage = config.canary_percentage
            await self.registry.update_version(version)

            # Monitor and increment
            for step in range(config.canary_max_steps):
                deployment.current_step = step + 1

                # Wait for interval
                await asyncio.sleep(config.canary_interval_minutes * 60)

                # Analyze metrics
                if not await self._analyze_canary(deployment):
                    # Rollback
                    await self._rollback(deployment, "Canary metrics degraded")
                    return

                # Increase traffic
                deployment.current_traffic += config.canary_step_percentage
                version.traffic_percentage = min(100, deployment.current_traffic)
                await self.registry.update_version(version)

                if deployment.current_traffic >= 100:
                    break

            # Promote to production — must actually succeed, otherwise the
            # deployment would claim "completed" while the version never
            # reached PRODUCTION (silent false success).
            promoted = await self.registry.promote_version(
                config.version_id, VersionStage.PRODUCTION)
            if not promoted:
                deployment.status = "failed"
                deployment.error = (
                    f"Promotion to production failed from {version.stage.value}")
                if config.auto_rollback:
                    await self._rollback(deployment, deployment.error)
                return

            deployment.status = "completed"
            deployment.completed_at = utc_now()

        except Exception as e:
            deployment.status = "failed"
            deployment.error = str(e)
            if config.auto_rollback:
                await self._rollback(deployment, str(e))

    async def _analyze_canary(self, deployment: Deployment) -> bool:
        """Analyze canary metrics against thresholds."""
        config = deployment.config
        version_id = config.version_id

        # Get recent metrics
        metrics_list = self._canary_metrics.get(version_id, [])
        if not metrics_list:
            return True  # No metrics yet, continue

        latest = metrics_list[-1]

        # Check thresholds
        if latest.error_rate > config.error_rate_threshold:
            logger.warning(f"Canary error rate {latest.error_rate} exceeds threshold {config.error_rate_threshold}")
            return False

        if latest.latency_p99 > config.latency_threshold_ms:
            logger.warning(f"Canary p99 latency {latest.latency_p99}ms exceeds threshold {config.latency_threshold_ms}ms")
            return False

        # Check success rate
        success_rate = 1 - latest.error_rate
        if success_rate < config.success_threshold:
            logger.warning(f"Canary success rate {success_rate} below threshold {config.success_threshold}")
            return False

        # Compare with baseline (would need baseline metrics)
        return True

    async def _run_blue_green(self, deployment: Deployment) -> None:
        """Run blue-green deployment."""
        # Switch traffic to green
        # This would integrate with load balancer/router
        deployment.current_traffic = 100
        deployment.status = "completed"
        deployment.completed_at = utc_now()

    async def _run_rolling(self, deployment: Deployment) -> None:
        """Run rolling deployment."""
        # Rolling update with max_surge/max_unavailable
        deployment.status = "completed"
        deployment.completed_at = utc_now()

    async def _rollback(self, deployment: Deployment, reason: str) -> None:
        """Rollback deployment."""
        logger.warning(f"Rolling back deployment {deployment.deployment_id}: {reason}")

        deployment.status = "rolled_back"
        deployment.error = reason
        deployment.completed_at = utc_now()

        # Restore previous version traffic
        config = deployment.config
        version = self.registry.get_version(config.version_id)
        if version:
            version.traffic_percentage = 0
            await self.registry.update_version(version)

    async def record_canary_metrics(self, metrics: CanaryMetrics) -> None:
        """Record canary metrics."""
        self._canary_metrics[metrics.version_id].append(metrics)

        # Keep last 1000 metrics
        if len(self._canary_metrics[metrics.version_id]) > 1000:
            self._canary_metrics[metrics.version_id] = self._canary_metrics[metrics.version_id][-1000:]

    def get_deployment(self, deployment_id: str) -> Optional[Deployment]:
        return self._deployments.get(deployment_id)

    def get_active_deployments(self) -> list[Deployment]:
        return [d for d in self._deployments.values() if d.status == "running"]

    def get_deployment_history(self, limit: int = 100) -> list[Deployment]:
        deployments = list(self._deployments.values())
        # datetime.min is naive; mixing it with aware started_at raises
        # TypeError, so fall back to an aware sentinel instead.
        earliest = datetime.min.replace(tzinfo=timezone.utc)
        deployments.sort(key=lambda d: d.started_at or earliest, reverse=True)
        return deployments[:limit]


class PromotionManager:
    """
    Manages version promotion workflows.
    """

    def __init__(self, registry: VersionRegistry):
        self.registry = registry
        self._requests: dict[str, PromotionRequest] = {}
        self._approval_policies: dict[VersionStage, dict[str, Any]] = {
            VersionStage.TESTING: {"required_approvals": 1, "auto_approve": True},
            VersionStage.STAGING: {"required_approvals": 2, "auto_approve": False},
            VersionStage.CANARY: {"required_approvals": 2, "auto_approve": False},
            VersionStage.PRODUCTION: {"required_approvals": 3, "auto_approve": False},
        }

    def create_promotion_request(
        self,
        version_id: str,
        to_stage: VersionStage,
        requested_by: str,
        reason: str,
    ) -> PromotionRequest:
        version = self.registry.get_version(version_id)
        if not version:
            raise ValueError(f"Version not found: {version_id}")

        from_stage = version.stage
        policy = self._approval_policies.get(to_stage, {"required_approvals": 1})

        request = PromotionRequest(
            version_id=version_id,
            from_stage=from_stage,
            to_stage=to_stage,
            requested_by=requested_by,
            reason=reason,
            required_approvals=policy["required_approvals"],
        )

        if policy.get("auto_approve", False):
            request.status = PromotionStatus.APPROVED
            request.approvers.append("auto")

        self._requests[request.request_id] = request
        return request

    def approve_request(self, request_id: str, approver: str) -> bool:
        request = self._requests.get(request_id)
        if not request:
            return False

        if request.status != PromotionStatus.PENDING:
            return False

        if approver not in request.approvers:
            request.approvers.append(approver)

        if len(request.approvers) >= request.required_approvals:
            request.status = PromotionStatus.APPROVED
            request.approved_at = utc_now()

        return True

    def reject_request(self, request_id: str, reason: str) -> bool:
        request = self._requests.get(request_id)
        if not request:
            return False

        request.status = PromotionStatus.REJECTED
        request.metadata["rejection_reason"] = reason
        return True

    async def process_approved_requests(self) -> list[str]:
        """Process all approved promotion requests."""
        processed = []

        for request in self._requests.values():
            if request.status == PromotionStatus.APPROVED and not request.completed_at:
                success = await self.registry.promote_version(
                    request.version_id,
                    request.to_stage,
                )

                if success:
                    request.status = PromotionStatus.COMPLETED
                    request.completed_at = utc_now()
                    processed.append(request.request_id)
                else:
                    request.status = PromotionStatus.FAILED

        return processed

    def get_request(self, request_id: str) -> Optional[PromotionRequest]:
        return self._requests.get(request_id)

    def get_pending_requests(self) -> list[PromotionRequest]:
        return [r for r in self._requests.values() if r.status == PromotionStatus.PENDING]


class RollbackManager:
    """
    Manages version rollbacks.
    """

    def __init__(self, registry: VersionRegistry, deployment_manager: DeploymentManager):
        self.registry = registry
        self.deployment_manager = deployment_manager
        self._rollback_history: list[dict[str, Any]] = []

    async def rollback_to_version(
        self,
        name: str,
        target_version_id: str,
        reason: str = "Manual rollback",
    ) -> bool:
        """Rollback to a specific version."""
        target = self.registry.get_version(target_version_id)
        if not target:
            return False

        # Get current production version
        current = self.registry.get_production_version(name)

        # Demote current — abort if the transition is not allowed
        if current:
            demoted = await self.registry.promote_version(
                current.version_id, VersionStage.STAGING)
            if not demoted:
                logger.error(
                    f"Rollback aborted: cannot demote {current.version_id} "
                    f"from production")
                return False

        # Promote target to production — on failure restore the previous
        # production version so state is never left half-changed.
        promoted = await self.registry.promote_version(
            target_version_id, VersionStage.PRODUCTION)
        if not promoted:
            if current:
                await self.registry.promote_version(
                    current.version_id, VersionStage.PRODUCTION)
            logger.error(
                f"Rollback failed: cannot promote {target_version_id} "
                f"to production")
            return False

        # Record rollback
        self._rollback_history.append({
            "timestamp": utc_now().isoformat(),
            "name": name,
            "from_version": current.version_id if current else None,
            "to_version": target_version_id,
            "reason": reason,
        })

        logger.info(f"Rolled back {name}: {current.version if current else 'none'} -> {target.version} ({reason})")
        return True

    async def rollback_deployment(self, deployment_id: str) -> bool:
        """Rollback an active deployment."""
        deployment = self.deployment_manager.get_deployment(deployment_id)
        if not deployment:
            return False

        await self.deployment_manager._rollback(deployment, "Manual rollback")
        return True

    def get_rollback_history(self, name: Optional[str] = None, limit: int = 50) -> list[dict[str, Any]]:
        history = self._rollback_history
        if name:
            history = [h for h in history if h["name"] == name]
        return history[-limit:]


class VersionManager:
    """
    High-level version management.
    """

    def __init__(self, storage_path: str = "./data/versions"):
        self.registry = VersionRegistry(storage_path)
        self.deployment_manager = DeploymentManager(self.registry)
        self.promotion_manager = PromotionManager(self.registry)
        self.rollback_manager = RollbackManager(self.registry, self.deployment_manager)

    async def initialize(self) -> None:
        await self.registry.initialize()

    async def create_version(
        self,
        name: str,
        version: str,
        artifact_path: str,
        **kwargs: Any
    ) -> ModelVersion:
        """Create a new version."""
        semver = SemanticVersion.parse(version)
        version_id = str(uuid.uuid4())

        # Compute artifact hash
        artifact_hash = ""
        artifact_size = 0
        if Path(artifact_path).exists():
            with open(artifact_path, 'rb') as f:
                content = f.read()
                artifact_hash = hashlib.sha256(content).hexdigest()
                artifact_size = len(content)

        model_version = ModelVersion(
            version_id=version_id,
            name=name,
            version=semver,
            artifact_path=artifact_path,
            artifact_hash=artifact_hash,
            artifact_size=artifact_size,
            **kwargs
        )

        await self.registry.register_version(model_version)
        return model_version

    async def deploy_version(
        self,
        version_id: str,
        strategy: DeploymentStrategy = DeploymentStrategy.CANARY,
        **config_kwargs: Any
    ) -> Deployment:
        """Deploy a version."""
        config = DeploymentConfig(
            deployment_id=str(uuid.uuid4()),
            name=f"Deploy {version_id}",
            version_id=version_id,
            strategy=strategy,
            **config_kwargs
        )

        deployment = await self.deployment_manager.create_deployment(config)
        await self.deployment_manager.start_deployment(deployment.deployment_id)
        return deployment

    async def promote(
        self,
        version_id: str,
        to_stage: VersionStage,
        requested_by: str,
        reason: str = "",
    ) -> PromotionRequest:
        """Request version promotion."""
        return self.promotion_manager.create_promotion_request(
            version_id, to_stage, requested_by, reason
        )

    async def approve_promotion(self, request_id: str, approver: str) -> bool:
        """Approve a promotion request."""
        return self.promotion_manager.approve_request(request_id, approver)

    async def rollback(
        self,
        name: str,
        target_version_id: str,
        reason: str = "Manual rollback",
    ) -> bool:
        """Rollback to a previous version."""
        return await self.rollback_manager.rollback_to_version(name, target_version_id, reason)

    def get_version(self, version_id: str) -> Optional[ModelVersion]:
        return self.registry.get_version(version_id)

    def get_versions(self, name: Optional[str] = None, stage: Optional[VersionStage] = None) -> list[ModelVersion]:
        return self.registry.get_versions(name, stage)

    def get_production_version(self, name: str) -> Optional[ModelVersion]:
        return self.registry.get_production_version(name)

    def get_latest_version(self, name: str, stage: Optional[VersionStage] = None) -> Optional[ModelVersion]:
        return self.registry.get_latest_version(name, stage)

    def get_deployment_status(self, deployment_id: str) -> Optional[Deployment]:
        return self.deployment_manager.get_deployment(deployment_id)

    def get_active_deployments(self) -> list[Deployment]:
        return self.deployment_manager.get_active_deployments()

    def get_promotion_requests(self, status: Optional[PromotionStatus] = None) -> list[PromotionRequest]:
        requests = list(self.promotion_manager._requests.values())
        if status:
            requests = [r for r in requests if r.status == status]
        return requests

    def get_rollback_history(self, name: Optional[str] = None) -> list[dict[str, Any]]:
        return self.rollback_manager.get_rollback_history(name)


# Global version manager
_version_manager: Optional[VersionManager] = None


def get_version_manager(storage_path: str = "./data/versions") -> VersionManager:
    global _version_manager
    if _version_manager is None:
        _version_manager = VersionManager(storage_path)
    return _version_manager


# Alias for backward compatibility
get_version_manager = get_version_manager
