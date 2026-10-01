"""
Data Residency and Compliance for PyFault framework.

Provides compliance management for:
- Data residency requirements (GDPR, CCPA, etc.)
- Cross-border data transfer controls
- Audit logging and compliance reporting
- Regional data isolation
- Encryption and key management per region
"""

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pyfault.common.time import parse_iso, utc_now

logger = logging.getLogger(__name__)


class ComplianceFramework(str, Enum):
    """Supported compliance frameworks."""
    GDPR = "gdpr"           # EU General Data Protection Regulation
    CCPA = "ccpa"           # California Consumer Privacy Act
    PDPA = "pdpa"           # Singapore Personal Data Protection Act
    LGPD = "lgpd"           # Brazil Lei Geral de Proteção de Dados
    PIPEDA = "pipeda"       # Canada Personal Information Protection
    HIPAA = "hipaa"         # US Healthcare
    SOX = "sox"             # US Financial
    PCI_DSS = "pci_dss"     # Payment Card Industry
    CUSTOM = "custom"


class DataCategory(str, Enum):
    """Data categories for classification."""
    PERSONAL = "personal"           # Personal identifiers
    SENSITIVE = "sensitive"         # Health, financial, biometric
    PSEUDONYMOUS = "pseudonymous"   # Pseudonymized data
    ANONYMOUS = "anonymous"         # Fully anonymized
    PUBLIC = "public"               # Publicly available
    SYSTEM = "system"               # System/log data


class DataProcessingPurpose(str, Enum):
    """Lawful basis for processing."""
    CONSENT = "consent"
    CONTRACT = "contract"
    LEGAL_OBLIGATION = "legal_obligation"
    VITAL_INTERESTS = "vital_interests"
    PUBLIC_TASK = "public_task"
    LEGITIMATE_INTERESTS = "legitimate_interests"


class TransferMechanism(str, Enum):
    """Cross-border transfer mechanisms."""
    ADEQUACY_DECISION = "adequacy_decision"
    STANDARD_CONTRACTUAL_CLAUSES = "scc"
    BINDING_CORPORATE_RULES = "bcr"
    CERTIFICATION = "certification"
    DEROGATION = "derogation"
    NONE = "none"


@dataclass
class DataResidencyRule:
    """Data residency rule for a region/framework."""
    rule_id: str
    framework: ComplianceFramework
    region_codes: list[str]  # Regions where data MUST reside
    excluded_regions: list[str] = field(default_factory=list)  # Regions where data MUST NOT reside
    data_categories: list[DataCategory] = field(default_factory=list)
    requires_encryption_at_rest: bool = True
    requires_encryption_in_transit: bool = True
    max_retention_days: Optional[int] = None
    allowed_transfer_mechanisms: list[TransferMechanism] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)


@dataclass
class DataAsset:
    """Data asset with compliance metadata."""
    asset_id: str
    name: str
    category: DataCategory
    region_id: str
    service_name: str
    description: str = ""
    processing_purposes: list[DataProcessingPurpose] = field(default_factory=list)
    retention_days: Optional[int] = None
    encryption_at_rest: bool = False
    encryption_in_transit: bool = False
    tags: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "name": self.name,
            "category": self.category.value,
            "region_id": self.region_id,
            "service_name": self.service_name,
            "description": self.description,
            "processing_purposes": [p.value for p in self.processing_purposes],
            "retention_days": self.retention_days,
            "encryption_at_rest": self.encryption_at_rest,
            "encryption_in_transit": self.encryption_in_transit,
            "tags": self.tags,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class ComplianceViolation:
    """Compliance violation record."""
    violation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rule_id: str = ""
    asset_id: str = ""
    service_name: str = ""
    region_id: str = ""
    framework: ComplianceFramework = ComplianceFramework.CUSTOM
    severity: str = "medium"  # low, medium, high, critical
    description: str = ""
    detected_at: datetime = field(default_factory=utc_now)
    resolved_at: Optional[datetime] = None
    resolution: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "violation_id": self.violation_id,
            "rule_id": self.rule_id,
            "asset_id": self.asset_id,
            "service_name": self.service_name,
            "region_id": self.region_id,
            "framework": self.framework.value,
            "severity": self.severity,
            "description": self.description,
            "detected_at": self.detected_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution": self.resolution,
            "metadata": self.metadata,
        }


@dataclass
class CrossBorderTransfer:
    """Cross-border data transfer record."""
    transfer_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_region: str = ""
    target_region: str = ""
    asset_id: str = ""
    service_name: str = ""
    mechanism: TransferMechanism = TransferMechanism.NONE
    purpose: str = ""
    data_volume_bytes: int = 0
    initiated_at: datetime = field(default_factory=utc_now)
    completed_at: Optional[datetime] = None
    status: str = "pending"  # pending, completed, failed, blocked
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "transfer_id": self.transfer_id,
            "source_region": self.source_region,
            "target_region": self.target_region,
            "asset_id": self.asset_id,
            "service_name": self.service_name,
            "mechanism": self.mechanism.value,
            "purpose": self.purpose,
            "data_volume_bytes": self.data_volume_bytes,
            "initiated_at": self.initiated_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "status": self.status,
            "metadata": self.metadata,
        }


class ComplianceRuleEngine:
    """
    Evaluates compliance rules against data assets and operations.
    """

    def __init__(self) -> None:
        self._rules: dict[str, DataResidencyRule] = {}
        self._assets: dict[str, DataAsset] = {}
        self._violations: list[ComplianceViolation] = []
        self._transfers: list[CrossBorderTransfer] = []

    def add_rule(self, rule: DataResidencyRule) -> None:
        self._rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False

    def get_rule(self, rule_id: str) -> Optional[DataResidencyRule]:
        return self._rules.get(rule_id)

    def list_rules(self, framework: Optional[ComplianceFramework] = None) -> list[DataResidencyRule]:
        rules = list(self._rules.values())
        if framework:
            rules = [r for r in rules if r.framework == framework]
        return rules

    def register_asset(self, asset: DataAsset) -> None:
        self._assets[asset.asset_id] = asset

    def unregister_asset(self, asset_id: str) -> bool:
        if asset_id in self._assets:
            del self._assets[asset_id]
            return True
        return False

    def get_asset(self, asset_id: str) -> Optional[DataAsset]:
        return self._assets.get(asset_id)

    def get_assets_in_region(self, region_id: str) -> list[DataAsset]:
        return [a for a in self._assets.values() if a.region_id == region_id]

    def get_assets_by_category(self, category: DataCategory) -> list[DataAsset]:
        return [a for a in self._assets.values() if a.category == category]

    def validate_residency(
        self,
        asset: DataAsset,
        target_region: Optional[str] = None,
    ) -> list[ComplianceViolation]:
        """Validate data residency for an asset."""
        violations = []
        region = target_region or asset.region_id

        for rule in self._rules.values():
            if not self._rule_applies(rule, asset):
                continue

            # Check if region is allowed
            if rule.region_codes and region not in rule.region_codes:
                violations.append(ComplianceViolation(
                    rule_id=rule.rule_id,
                    asset_id=asset.asset_id,
                    service_name=asset.service_name,
                    region_id=region,
                    framework=rule.framework,
                    severity="high",
                    description=f"Data residency violation: {asset.name} in {region} not in allowed regions {rule.region_codes}",
                ))

            # Check excluded regions
            if region in rule.excluded_regions:
                violations.append(ComplianceViolation(
                    rule_id=rule.rule_id,
                    asset_id=asset.asset_id,
                    service_name=asset.service_name,
                    region_id=region,
                    framework=rule.framework,
                    severity="critical",
                    description=f"Data in excluded region: {asset.name} in {region}",
                ))

            # Check encryption requirements
            if rule.requires_encryption_at_rest and not asset.encryption_at_rest:
                violations.append(ComplianceViolation(
                    rule_id=rule.rule_id,
                    asset_id=asset.asset_id,
                    service_name=asset.service_name,
                    region_id=region,
                    framework=rule.framework,
                    severity="medium",
                    description=f"Encryption at rest required but not enabled for {asset.name}",
                ))

            if rule.requires_encryption_in_transit and not asset.encryption_in_transit:
                violations.append(ComplianceViolation(
                    rule_id=rule.rule_id,
                    asset_id=asset.asset_id,
                    service_name=asset.service_name,
                    region_id=region,
                    framework=rule.framework,
                    severity="medium",
                    description=f"Encryption in transit required but not enabled for {asset.name}",
                ))

            # Check retention
            if rule.max_retention_days and asset.retention_days and asset.retention_days > rule.max_retention_days:
                violations.append(ComplianceViolation(
                        rule_id=rule.rule_id,
                        asset_id=asset.asset_id,
                        service_name=asset.service_name,
                        region_id=region,
                        framework=rule.framework,
                        severity="medium",
                        description=f"Retention period {asset.retention_days} days exceeds maximum {rule.max_retention_days} days",
                    ))

        return violations

    def _rule_applies(self, rule: DataResidencyRule, asset: DataAsset) -> bool:
        """Check if a rule applies to an asset."""
        # Check category match
        return not (rule.data_categories and asset.category not in rule.data_categories)

    def validate_transfer(
        self,
        transfer: CrossBorderTransfer,
    ) -> list[ComplianceViolation]:
        """Validate cross-border data transfer."""
        violations = []
        asset = self._assets.get(transfer.asset_id)

        if not asset:
            violations.append(ComplianceViolation(
                rule_id="",
                asset_id=transfer.asset_id,
                service_name=transfer.service_name,
                region_id=transfer.target_region,
                framework=ComplianceFramework.CUSTOM,
                severity="high",
                description=f"Asset not registered: {transfer.asset_id}",
            ))
            return violations

        # Check applicable rules for the asset
        for rule in self._rules.values():
            if not self._rule_applies(rule, asset):
                continue

            # Check if transfer mechanism is allowed
            if rule.allowed_transfer_mechanisms and transfer.mechanism not in rule.allowed_transfer_mechanisms:
                violations.append(ComplianceViolation(
                        rule_id=rule.rule_id,
                        asset_id=asset.asset_id,
                        service_name=transfer.service_name,
                        region_id=transfer.target_region,
                        framework=rule.framework,
                        severity="high",
                        description=f"Transfer mechanism {transfer.mechanism.value} not allowed for {rule.framework.value}",
                    ))

            # Check if target region is allowed
            if rule.region_codes and transfer.target_region not in rule.region_codes:
                violations.append(ComplianceViolation(
                    rule_id=rule.rule_id,
                    asset_id=asset.asset_id,
                    service_name=transfer.service_name,
                    region_id=transfer.target_region,
                    framework=rule.framework,
                    severity="high",
                    description=f"Transfer to {transfer.target_region} not allowed for {asset.name}",
                ))

        return violations

    def record_transfer(self, transfer: CrossBorderTransfer) -> None:
        violations = self.validate_transfer(transfer)
        if violations:
            transfer.status = "blocked"
            for v in violations:
                self._violations.append(v)
        else:
            transfer.status = "completed"
            transfer.completed_at = utc_now()

        self._transfers.append(transfer)

    def get_violations(
        self,
        service_name: Optional[str] = None,
        region_id: Optional[str] = None,
        framework: Optional[ComplianceFramework] = None,
        unresolved_only: bool = False,
    ) -> list[ComplianceViolation]:
        violations = self._violations

        if service_name:
            violations = [v for v in violations if v.service_name == service_name]
        if region_id:
            violations = [v for v in violations if v.region_id == region_id]
        if framework:
            violations = [v for v in violations if v.framework == framework]
        if unresolved_only:
            violations = [v for v in violations if v.resolved_at is None]

        return violations

    def resolve_violation(
        self,
        violation_id: str,
        resolution: str,
    ) -> bool:
        for v in self._violations:
            if v.violation_id == violation_id:
                v.resolved_at = utc_now()
                v.resolution = resolution
                return True
        return False

    def get_compliance_report(
        self,
        service_name: Optional[str] = None,
        region_id: Optional[str] = None,
    ) -> dict[str, Any]:
        violations = self.get_violations(service_name, region_id)

        by_severity: defaultdict[Any, int] = defaultdict(int)
        by_framework: defaultdict[Any, int] = defaultdict(int)
        for v in violations:
            by_severity[v.severity] += 1
            by_framework[v.framework.value] += 1

        return {
            "total_violations": len(violations),
            "by_severity": dict(by_severity),
            "by_framework": dict(by_framework),
            "unresolved": len([v for v in violations if v.resolved_at is None]),
            "assets_count": len(self._assets),
            "rules_count": len(self._rules),
            "transfers_count": len(self._transfers),
            "blocked_transfers": len([t for t in self._transfers if t.status == "blocked"]),
        }


# Pre-defined compliance rules
GDPR_RULES = [
    DataResidencyRule(
        rule_id="gdpr-eu-residency",
        framework=ComplianceFramework.GDPR,
        region_codes=["eu-west-1", "eu-central-1", "eu-north-1"],
        data_categories=[DataCategory.PERSONAL, DataCategory.SENSITIVE],
        requires_encryption_at_rest=True,
        requires_encryption_in_transit=True,
        allowed_transfer_mechanisms=[
            TransferMechanism.ADEQUACY_DECISION,
            TransferMechanism.STANDARD_CONTRACTUAL_CLAUSES,
            TransferMechanism.BINDING_CORPORATE_RULES,
        ],
    ),
    DataResidencyRule(
        rule_id="gdpr-sensitive-encryption",
        framework=ComplianceFramework.GDPR,
        region_codes=["eu-west-1", "eu-central-1", "eu-north-1"],
        data_categories=[DataCategory.SENSITIVE],
        requires_encryption_at_rest=True,
        requires_encryption_in_transit=True,
        max_retention_days=2555,  # 7 years
    ),
]

CCPA_RULES = [
    DataResidencyRule(
        rule_id="ccpa-california-residency",
        framework=ComplianceFramework.CCPA,
        region_codes=["us-west-1", "us-west-2"],
        data_categories=[DataCategory.PERSONAL, DataCategory.SENSITIVE],
        requires_encryption_at_rest=True,
        requires_encryption_in_transit=True,
    ),
]

HIPAA_RULES = [
    DataResidencyRule(
        rule_id="hipaa-us-residency",
        framework=ComplianceFramework.HIPAA,
        region_codes=["us-east-1", "us-west-2"],
        data_categories=[DataCategory.SENSITIVE],
        requires_encryption_at_rest=True,
        requires_encryption_in_transit=True,
        max_retention_days=2190,  # 6 years
        allowed_transfer_mechanisms=[
            TransferMechanism.STANDARD_CONTRACTUAL_CLAUSES,
            TransferMechanism.BINDING_CORPORATE_RULES,
        ],
    ),
]

PCI_DSS_RULES = [
    DataResidencyRule(
        rule_id="pci-dss-card-data",
        framework=ComplianceFramework.PCI_DSS,
        region_codes=["us-east-1", "us-west-2", "eu-west-1"],
        data_categories=[DataCategory.SENSITIVE],
        requires_encryption_at_rest=True,
        requires_encryption_in_transit=True,
        max_retention_days=365,  # 1 year for card data
    ),
]

ALL_DEFAULT_RULES = GDPR_RULES + CCPA_RULES + HIPAA_RULES + PCI_DSS_RULES


class ComplianceManager:
    """
    High-level compliance manager.
    """

    def __init__(self) -> None:
        self.engine = ComplianceRuleEngine()
        self._initialized = False

    def initialize(self, frameworks: Optional[list[ComplianceFramework]] = None) -> None:
        """Initialize with default rules for frameworks."""
        if self._initialized:
            return

        if frameworks is None:
            frameworks = [
                ComplianceFramework.GDPR,
                ComplianceFramework.CCPA,
                ComplianceFramework.HIPAA,
                ComplianceFramework.PCI_DSS,
            ]

        for framework in frameworks:
            rules = self._get_framework_rules(framework)
            for rule in rules:
                self.engine.add_rule(rule)

        self._initialized = True

    def _get_framework_rules(self, framework: ComplianceFramework) -> list[DataResidencyRule]:
        if framework == ComplianceFramework.GDPR:
            return GDPR_RULES
        elif framework == ComplianceFramework.CCPA:
            return CCPA_RULES
        elif framework == ComplianceFramework.HIPAA:
            return HIPAA_RULES
        elif framework == ComplianceFramework.PCI_DSS:
            return PCI_DSS_RULES
        return []

    def register_data_asset(
        self,
        name: str,
        category: DataCategory,
        region_id: str,
        service_name: str,
        **kwargs: Any
    ) -> DataAsset:
        """Register a data asset."""
        asset = DataAsset(
            asset_id=str(uuid.uuid4()),
            name=name,
            category=category,
            region_id=region_id,
            service_name=service_name,
            **kwargs
        )
        self.engine.register_asset(asset)

        # Validate immediately
        violations = self.engine.validate_residency(asset)
        for v in violations:
            self.engine._violations.append(v)

        return asset

    def validate_region_for_data(
        self,
        category: DataCategory,
        region_id: str,
        frameworks: Optional[list[ComplianceFramework]] = None,
    ) -> tuple[bool, list[str]]:
        """Check if a region is compliant for a data category."""
        violations = []

        for rule in self.engine._rules.values():
            if frameworks and rule.framework not in frameworks:
                continue

            if rule.data_categories and category not in rule.data_categories:
                continue

            if rule.region_codes and region_id not in rule.region_codes:
                violations.append(f"{rule.framework.value}: region {region_id} not in allowed regions {rule.region_codes}")

            if region_id in rule.excluded_regions:
                violations.append(f"{rule.framework.value}: region {region_id} is excluded")

        return len(violations) == 0, violations

    def request_transfer(
        self,
        asset_id: str,
        source_region: str,
        target_region: str,
        service_name: str,
        mechanism: TransferMechanism,
        purpose: str,
        data_volume_bytes: int = 0,
    ) -> CrossBorderTransfer:
        """Request a cross-border data transfer."""
        transfer = CrossBorderTransfer(
            source_region=source_region,
            target_region=target_region,
            asset_id=asset_id,
            service_name=service_name,
            mechanism=mechanism,
            purpose=purpose,
            data_volume_bytes=data_volume_bytes,
        )

        self.engine.record_transfer(transfer)
        return transfer

    def get_compliance_status(
        self,
        service_name: Optional[str] = None,
        region_id: Optional[str] = None,
    ) -> dict[str, Any]:
        return self.engine.get_compliance_report(service_name, region_id)

    def get_violations(
        self,
        service_name: Optional[str] = None,
        region_id: Optional[str] = None,
        framework: Optional[ComplianceFramework] = None,
    ) -> list[ComplianceViolation]:
        return self.engine.get_violations(service_name, region_id, framework)

    def audit_data_flows(self) -> dict[str, Any]:
        """Audit all data flows for compliance."""
        flows: defaultdict[str, dict[str, Any]] = defaultdict(lambda: {
            "assets": 0,
            "transfers": 0,
            "violations": 0,
            "by_region": defaultdict(int),
            "by_category": defaultdict(int),
        })

        for asset in self.engine._assets.values():
            key = f"{asset.service_name}:{asset.region_id}"
            flows[key]["assets"] += 1
            flows[key]["by_category"][asset.category.value] += 1
            flows[key]["by_region"][asset.region_id] += 1

        for transfer in self.engine._transfers:
            key = f"{transfer.service_name}:{transfer.source_region}->{transfer.target_region}"
            flows[key]["transfers"] += 1
            if transfer.status == "blocked":
                flows[key]["violations"] += 1

        return {k: {**v, "by_region": dict(v["by_region"]), "by_category": dict(v["by_category"])}
                for k, v in flows.items()}


class DataIsolationManager:
    """
    Manages data isolation between regions.
    """

    def __init__(self, compliance_manager: ComplianceManager):
        self.compliance = compliance_manager
        self._isolation_policies: dict[str, dict[str, Any]] = {}

    def set_isolation_policy(
        self,
        service_name: str,
        source_region: str,
        target_region: str,
        policy: dict[str, Any],
    ) -> None:
        """Set isolation policy between regions."""
        key = f"{service_name}:{source_region}->{target_region}"
        self._isolation_policies[key] = policy

    def check_isolation(
        self,
        service_name: str,
        source_region: str,
        target_region: str,
        operation: str,
    ) -> tuple[bool, list[str]]:
        """Check if operation is allowed under isolation policy."""
        key = f"{service_name}:{source_region}->{target_region}"
        policy = self._isolation_policies.get(key, {})

        allowed = True
        reasons = []

        # Check allowed operations
        allowed_ops = policy.get("allowed_operations", [])
        if allowed_ops and operation not in allowed_ops:
            allowed = False
            reasons.append(f"Operation {operation} not in allowed operations: {allowed_ops}")

        # Check blocked operations
        blocked_ops = policy.get("blocked_operations", [])
        if operation in blocked_ops:
            allowed = False
            reasons.append(f"Operation {operation} is blocked")

        # Check data categories
        # This would need the asset category in practice

        return allowed, reasons


class AuditLogger:
    """Audit logger for compliance events."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._max_events = 10000

    def log_event(
        self,
        event_type: str,
        service_name: str,
        region_id: str,
        user_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        event = {
            "event_id": str(uuid.uuid4()),
            "event_type": event_type,
            "service_name": service_name,
            "region_id": region_id,
            "user_id": user_id,
            "timestamp": utc_now().isoformat(),
            "details": details or {},
        }

        self._events.append(event)

        # Trim
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]

    def get_events(
        self,
        event_type: Optional[str] = None,
        service_name: Optional[str] = None,
        region_id: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        events = self._events

        if event_type:
            events = [e for e in events if e["event_type"] == event_type]
        if service_name:
            events = [e for e in events if e["service_name"] == service_name]
        if region_id:
            events = [e for e in events if e["region_id"] == region_id]
        if since:
            events = [e for e in events if parse_iso(e["timestamp"]) >= since]

        return events[-limit:]

    def export_audit_log(
        self,
        format: str = "json",
    ) -> str:
        if format == "json":
            return json.dumps(self._events, indent=2, default=str)
        elif format == "csv":
            import csv
            import io
            output = io.StringIO()
            if self._events:
                writer = csv.DictWriter(output, fieldnames=self._events[0].keys())
                writer.writeheader()
                writer.writerows(self._events)
            return output.getvalue()
        return ""


# Global instances
_compliance_manager: Optional[ComplianceManager] = None
_audit_logger: Optional[AuditLogger] = None


def get_compliance_manager() -> ComplianceManager:
    global _compliance_manager
    if _compliance_manager is None:
        _compliance_manager = ComplianceManager()
    return _compliance_manager


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


