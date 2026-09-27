"""
Compliance Framework for PyFault framework.

Compliance management:
- Regulatory frameworks (SOC2, GDPR, HIPAA, PCI-DSS, ISO27001)
- Policy management and enforcement
- Control implementation and testing
- Evidence collection and management
- Compliance reporting and dashboards
- Risk assessment and management
"""

import asyncio
import hashlib
import logging
import uuid
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class ComplianceFramework(str, Enum):
    """Supported compliance frameworks."""
    SOC2 = "soc2"
    GDPR = "gdpr"
    HIPAA = "hipaa"
    PCI_DSS = "pci_dss"
    ISO27001 = "iso27001"
    NIST = "nist"
    CIS = "cis"
    CUSTOM = "custom"


class ControlStatus(str, Enum):
    """Control implementation status."""
    NOT_IMPLEMENTED = "not_implemented"
    PARTIALLY_IMPLEMENTED = "partially_implemented"
    IMPLEMENTED = "implemented"
    TESTED = "tested"
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    NOT_APPLICABLE = "not_applicable"


class EvidenceType(str, Enum):
    """Types of compliance evidence."""
    DOCUMENT = "document"
    SCREENSHOT = "screenshot"
    LOG = "log"
    CONFIG = "config"
    SCAN_RESULT = "scan_result"
    TEST_RESULT = "test_result"
    CERTIFICATE = "certificate"
    POLICY = "policy"
    PROCEDURE = "procedure"
    MEETING_NOTES = "meeting_notes"
    OTHER = "other"


class RiskLevel(str, Enum):
    """Risk levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class PolicyStatus(str, Enum):
    """Policy lifecycle status."""
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"


@dataclass
class FrameworkControl:
    """A control within a compliance framework."""
    control_id: str
    framework: ComplianceFramework
    control_ref: str  # Official reference (e.g., "CC6.1")
    title: str
    description: str = ""
    category: str = ""

    # Implementation
    implementation_guidance: str = ""
    testing_procedure: str = ""

    # Mapping
    related_controls: list[str] = field(default_factory=list)  # Other control IDs
    mapped_requirements: list[str] = field(default_factory=list)  # Regulatory requirements

    # Metadata
    criticality: RiskLevel = RiskLevel.MEDIUM
    automation_possible: bool = False
    testing_frequency: str = "annual"  # continuous, monthly, quarterly, annual
    evidence_required: list[EvidenceType] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "framework": self.framework.value,
            "control_ref": self.control_ref,
            "title": self.title,
            "description": self.description,
            "category": self.category,
            "implementation_guidance": self.implementation_guidance,
            "testing_procedure": self.testing_procedure,
            "related_controls": self.related_controls,
            "mapped_requirements": self.mapped_requirements,
            "criticality": self.criticality.value,
            "automation_possible": self.automation_possible,
            "testing_frequency": self.testing_frequency,
            "evidence_required": [e.value for e in self.evidence_required],
        }


@dataclass
class ControlImplementation:
    """Implementation of a control in the organization."""
    implementation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    control_id: str = ""
    framework: ComplianceFramework = ComplianceFramework.CUSTOM

    # Status
    status: ControlStatus = ControlStatus.NOT_IMPLEMENTED
    implementation_details: str = ""

    # Responsibility
    owner: str = ""  # User/team responsible
    reviewer: str = ""  # User/team for review

    # Evidence
    evidence: list["Evidence"] = field(default_factory=list)

    # Testing
    last_tested: Optional[datetime] = None
    next_test_due: Optional[datetime] = None
    test_results: list["TestResult"] = field(default_factory=list)

    # Exceptions
    exception: bool = False
    exception_reason: str = ""
    exception_expires: Optional[datetime] = None
    exception_approved_by: str = ""

    # Timestamps
    implemented_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_compliant(self) -> bool:
        return self.status in [ControlStatus.COMPLIANT, ControlStatus.TESTED]

    def is_overdue(self) -> bool:
        return bool(self.next_test_due and datetime.utcnow() > self.next_test_due)

    def to_dict(self) -> dict[str, Any]:
        return {
            "implementation_id": self.implementation_id,
            "control_id": self.control_id,
            "framework": self.framework.value,
            "status": self.status.value,
            "implementation_details": self.implementation_details,
            "owner": self.owner,
            "reviewer": self.reviewer,
            "evidence_count": len(self.evidence),
            "last_tested": self.last_tested.isoformat() if self.last_tested else None,
            "next_test_due": self.next_test_due.isoformat() if self.next_test_due else None,
            "test_results_count": len(self.test_results),
            "exception": self.exception,
            "exception_reason": self.exception_reason,
            "implemented_at": self.implemented_at.isoformat() if self.implemented_at else None,
        }


@dataclass
class Evidence:
    """Compliance evidence artifact."""
    evidence_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    implementation_id: str = ""
    evidence_type: EvidenceType = EvidenceType.DOCUMENT

    # Content
    title: str = ""
    description: str = ""
    file_path: str = ""
    file_hash: str = ""
    file_size: int = 0

    # Metadata
    collected_by: str = ""
    collected_at: datetime = field(default_factory=datetime.utcnow)
    valid_from: datetime = field(default_factory=datetime.utcnow)
    valid_until: Optional[datetime] = None

    # Verification
    verified: bool = False
    verified_by: str = ""
    verified_at: Optional[datetime] = None

    # Tags
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "implementation_id": self.implementation_id,
            "evidence_type": self.evidence_type.value,
            "title": self.title,
            "description": self.description,
            "file_path": self.file_path,
            "file_hash": self.file_hash,
            "file_size": self.file_size,
            "collected_by": self.collected_by,
            "collected_at": self.collected_at.isoformat(),
            "valid_from": self.valid_from.isoformat(),
            "valid_until": self.valid_until.isoformat() if self.valid_until else None,
            "verified": self.verified,
            "verified_by": self.verified_by,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
            "tags": self.tags,
        }


@dataclass
class TestResult:
    """Result of a control test."""
    test_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    implementation_id: str = ""
    test_type: str = "manual"  # manual, automated, scan
    tester: str = ""

    # Result
    passed: bool = False
    score: float = 0.0  # 0-100
    findings: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    # Evidence
    evidence: list[str] = field(default_factory=list)  # Evidence IDs

    # Timing
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    duration_minutes: int = 0

    # Metadata
    notes: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id,
            "implementation_id": self.implementation_id,
            "test_type": self.test_type,
            "tester": self.tester,
            "passed": self.passed,
            "score": self.score,
            "findings": self.findings,
            "recommendations": self.recommendations,
            "evidence": self.evidence,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "duration_minutes": self.duration_minutes,
        }


@dataclass
class Policy:
    """Compliance policy."""
    policy_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    version: str = "1.0"

    # Scope
    frameworks: list[ComplianceFramework] = field(default_factory=list)
    applies_to: list[str] = field(default_factory=list)  # Tenants, systems, teams

    # Content
    content: str = ""  # Markdown or HTML
    rules: list[dict[str, Any]] = field(default_factory=list)  # Structured rules

    # Lifecycle
    status: PolicyStatus = PolicyStatus.DRAFT
    effective_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    review_frequency: str = "annual"
    next_review_date: Optional[datetime] = None

    # Approval
    author: str = ""
    approved_by: str = ""
    approved_at: Optional[datetime] = None

    # Metadata
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def is_active(self) -> bool:
        if self.status != PolicyStatus.ACTIVE:
            return False
        if self.effective_date and datetime.utcnow() < self.effective_date:
            return False
        return not (self.expiry_date and datetime.utcnow() > self.expiry_date)

    def to_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "frameworks": [f.value for f in self.frameworks],
            "applies_to": self.applies_to,
            "status": self.status.value,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "review_frequency": self.review_frequency,
            "next_review_date": self.next_review_date.isoformat() if self.next_review_date else None,
            "author": self.author,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at.isoformat() if self.approved_at else None,
        }


@dataclass
class Risk:
    """Risk assessment."""
    risk_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str = ""
    description: str = ""

    # Assessment
    likelihood: int = 3  # 1-5
    impact: int = 3  # 1-5
    risk_level: RiskLevel = RiskLevel.MEDIUM

    # Context
    category: str = ""  # operational, financial, reputational, compliance, security
    assets_affected: list[str] = field(default_factory=list)
    threats: list[str] = field(default_factory=list)
    vulnerabilities: list[str] = field(default_factory=list)

    # Mitigation
    existing_controls: list[str] = field(default_factory=list)  # Control IDs
    mitigation_plan: str = ""
    residual_likelihood: int = 3
    residual_impact: int = 3
    residual_risk: RiskLevel = RiskLevel.MEDIUM

    # Ownership
    owner: str = ""
    reviewer: str = ""

    # Status
    status: str = "open"  # open, mitigating, accepted, closed
    treatment: str = "mitigate"  # mitigate, accept, transfer, avoid

    # Timestamps
    identified_at: datetime = field(default_factory=datetime.utcnow)
    reviewed_at: Optional[datetime] = None
    next_review: Optional[datetime] = None

    @property
    def risk_score(self) -> int:
        return self.likelihood * self.impact

    @property
    def residual_score(self) -> int:
        return self.residual_likelihood * self.residual_impact

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_id": self.risk_id,
            "title": self.title,
            "description": self.description,
            "likelihood": self.likelihood,
            "impact": self.impact,
            "risk_level": self.risk_level.value,
            "risk_score": self.risk_score,
            "category": self.category,
            "assets_affected": self.assets_affected,
            "threats": self.threats,
            "vulnerabilities": self.vulnerabilities,
            "existing_controls": self.existing_controls,
            "mitigation_plan": self.mitigation_plan,
            "residual_likelihood": self.residual_likelihood,
            "residual_impact": self.residual_impact,
            "residual_risk": self.residual_risk.value,
            "residual_score": self.residual_score,
            "owner": self.owner,
            "reviewer": self.reviewer,
            "status": self.status,
            "treatment": self.treatment,
        }


@dataclass
class ComplianceAssessment:
    """Compliance assessment for a framework."""
    assessment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    framework: ComplianceFramework = ComplianceFramework.SOC2
    tenant_id: str = ""

    # Scope
    scope: str = "full"  # full, partial, specific_controls
    controls_assessed: list[str] = field(default_factory=list)

    # Results
    total_controls: int = 0
    compliant: int = 0
    non_compliant: int = 0
    partially_compliant: int = 0
    not_applicable: int = 0

    # Scores
    compliance_score: float = 0.0  # 0-100
    criticality_weighted_score: float = 0.0

    # Findings
    findings: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)

    # Timestamps
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    assessor: str = ""

    # Next steps
    next_assessment_due: Optional[datetime] = None

    def calculate_scores(self) -> None:
        if self.total_controls > 0:
            self.compliance_score = (self.compliant / self.total_controls) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "assessment_id": self.assessment_id,
            "framework": self.framework.value,
            "tenant_id": self.tenant_id,
            "scope": self.scope,
            "total_controls": self.total_controls,
            "compliant": self.compliant,
            "non_compliant": self.non_compliant,
            "partially_compliant": self.partially_compliant,
            "not_applicable": self.not_applicable,
            "compliance_score": self.compliance_score,
            "criticality_weighted_score": self.criticality_weighted_score,
            "findings_count": len(self.findings),
            "recommendations_count": len(self.recommendations),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class FrameworkRegistry:
    """Registry of compliance frameworks and controls."""

    def __init__(self) -> None:
        self._frameworks: dict[ComplianceFramework, list[FrameworkControl]] = defaultdict(list)
        self._load_standard_frameworks()

    def _load_standard_frameworks(self) -> None:
        # SOC 2 Controls
        self._load_soc2_controls()
        # GDPR Controls
        self._load_gdpr_controls()
        # HIPAA Controls
        self._load_hipaa_controls()
        # PCI DSS Controls
        self._load_pci_controls()
        # ISO 27001 Controls
        self._load_iso_controls()

    def _load_soc2_controls(self) -> None:
        controls = [
            FrameworkControl(
                control_id="soc2_cc6_1",
                framework=ComplianceFramework.SOC2,
                control_ref="CC6.1",
                title="Logical Access Controls",
                description="The entity implements logical access security software, infrastructure, and architectures over protected information assets to protect them from security events.",
                category="Common Criteria - Logical and Physical Access",
                criticality=RiskLevel.HIGH,
                automation_possible=True,
                testing_frequency="continuous",
                evidence_required=[EvidenceType.LOG, EvidenceType.CONFIG, EvidenceType.SCAN_RESULT],
            ),
            FrameworkControl(
                control_id="soc2_cc6_7",
                framework=ComplianceFramework.SOC2,
                control_ref="CC6.7",
                title="Data Transmission Protection",
                description="The entity restricts the transmission, movement, and removal of information to authorized internal and external users and processes, and protects it during transmission, movement, or removal.",
                category="Common Criteria - Logical and Physical Access",
                criticality=RiskLevel.HIGH,
                automation_possible=True,
                testing_frequency="continuous",
                evidence_required=[EvidenceType.CONFIG, EvidenceType.SCAN_RESULT],
            ),
            FrameworkControl(
                control_id="soc2_cc7_2",
                framework=ComplianceFramework.SOC2,
                control_ref="CC7.2",
                title="System Monitoring",
                description="The entity monitors system components and the operation of those components for anomalies that are indicative of malicious acts, natural disasters, and errors affecting the entity's ability to meet its objectives.",
                category="Common Criteria - System Operations",
                criticality=RiskLevel.HIGH,
                automation_possible=True,
                testing_frequency="continuous",
                evidence_required=[EvidenceType.LOG, EvidenceType.SCAN_RESULT],
            ),
            FrameworkControl(
                control_id="soc2_cc8_1",
                framework=ComplianceFramework.SOC2,
                control_ref="CC8.1",
                title="Change Management",
                description="The entity authorizes, designs, develops or acquires, configures, documents, tests, approves, and implements changes to infrastructure, data, software, and procedures to meet its objectives.",
                category="Common Criteria - Change Management",
                criticality=RiskLevel.MEDIUM,
                automation_possible=False,
                testing_frequency="quarterly",
                evidence_required=[EvidenceType.DOCUMENT, EvidenceType.PROCEDURE],
            ),
        ]
        for c in controls:
            self._frameworks[ComplianceFramework.SOC2].append(c)

    def _load_gdpr_controls(self) -> None:
        controls = [
            FrameworkControl(
                control_id="gdpr_art5_1",
                framework=ComplianceFramework.GDPR,
                control_ref="Article 5(1)",
                title="Lawfulness, Fairness and Transparency",
                description="Personal data shall be processed lawfully, fairly and in a transparent manner in relation to the data subject.",
                category="Principles",
                criticality=RiskLevel.CRITICAL,
                evidence_required=[EvidenceType.POLICY, EvidenceType.DOCUMENT],
            ),
            FrameworkControl(
                control_id="gdpr_art5_2",
                framework=ComplianceFramework.GDPR,
                control_ref="Article 5(2)",
                title="Accountability",
                description="The controller shall be responsible for, and be able to demonstrate compliance with, paragraph 1.",
                category="Principles",
                criticality=RiskLevel.CRITICAL,
                evidence_required=[EvidenceType.DOCUMENT, EvidenceType.PROCEDURE],
            ),
            FrameworkControl(
                control_id="gdpr_art32",
                framework=ComplianceFramework.GDPR,
                control_ref="Article 32",
                title="Security of Processing",
                description="Implement appropriate technical and organisational measures to ensure a level of security appropriate to the risk.",
                category="Security",
                criticality=RiskLevel.CRITICAL,
                automation_possible=True,
                evidence_required=[EvidenceType.CONFIG, EvidenceType.SCAN_RESULT, EvidenceType.POLICY],
            ),
            FrameworkControl(
                control_id="gdpr_art25",
                framework=ComplianceFramework.GDPR,
                control_ref="Article 25",
                title="Data Protection by Design and by Default",
                description="Implement appropriate technical and organisational measures for data protection by design and by default.",
                category="Data Protection",
                criticality=RiskLevel.HIGH,
                evidence_required=[EvidenceType.DOCUMENT, EvidenceType.CONFIG],
            ),
        ]
        for c in controls:
            self._frameworks[ComplianceFramework.GDPR].append(c)

    def _load_hipaa_controls(self) -> None:
        controls = [
            FrameworkControl(
                control_id="hipaa_164_308_a1",
                framework=ComplianceFramework.HIPAA,
                control_ref="§164.308(a)(1)",
                title="Security Officer Assignment",
                description="Identify the security official who is responsible for the development and implementation of the policies and procedures required by this subpart.",
                category="Administrative Safeguards",
                criticality=RiskLevel.HIGH,
                evidence_required=[EvidenceType.DOCUMENT],
            ),
            FrameworkControl(
                control_id="hipaa_164_312_a1",
                framework=ComplianceFramework.HIPAA,
                control_ref="§164.312(a)(1)",
                title="Access Control",
                description="Implement technical policies and procedures for electronic information systems that maintain electronic protected health information to allow access only to those persons or software programs that have been granted access rights.",
                category="Technical Safeguards",
                criticality=RiskLevel.CRITICAL,
                automation_possible=True,
                evidence_required=[EvidenceType.CONFIG, EvidenceType.LOG],
            ),
            FrameworkControl(
                control_id="hipaa_164_312_b",
                framework=ComplianceFramework.HIPAA,
                control_ref="§164.312(b)",
                title="Audit Controls",
                description="Implement hardware, software, and/or procedural mechanisms that record and examine activity in information systems that contain or use electronic protected health information.",
                category="Technical Safeguards",
                criticality=RiskLevel.HIGH,
                automation_possible=True,
                evidence_required=[EvidenceType.LOG, EvidenceType.CONFIG],
            ),
            FrameworkControl(
                control_id="hipaa_164_312_e1",
                framework=ComplianceFramework.HIPAA,
                control_ref="§164.312(e)(1)",
                title="Transmission Security",
                description="Implement technical security measures to guard against unauthorized access to electronic protected health information that is being transmitted over an electronic communications network.",
                category="Technical Safeguards",
                criticality=RiskLevel.CRITICAL,
                automation_possible=True,
                evidence_required=[EvidenceType.CONFIG, EvidenceType.SCAN_RESULT],
            ),
        ]
        for c in controls:
            self._frameworks[ComplianceFramework.HIPAA].append(c)

    def _load_pci_controls(self) -> None:
        controls = [
            FrameworkControl(
                control_id="pci_req1",
                framework=ComplianceFramework.PCI_DSS,
                control_ref="Requirement 1",
                title="Install and maintain a firewall configuration to protect cardholder data",
                category="Network Security",
                criticality=RiskLevel.CRITICAL,
                automation_possible=True,
                evidence_required=[EvidenceType.CONFIG, EvidenceType.SCAN_RESULT],
            ),
            FrameworkControl(
                control_id="pci_req3",
                framework=ComplianceFramework.PCI_DSS,
                control_ref="Requirement 3",
                title="Protect stored cardholder data",
                category="Data Protection",
                criticality=RiskLevel.CRITICAL,
                automation_possible=True,
                evidence_required=[EvidenceType.CONFIG, EvidenceType.SCAN_RESULT],
            ),
            FrameworkControl(
                control_id="pci_req10",
                framework=ComplianceFramework.PCI_DSS,
                control_ref="Requirement 10",
                title="Track and monitor all access to network resources and cardholder data",
                category="Monitoring",
                criticality=RiskLevel.HIGH,
                automation_possible=True,
                evidence_required=[EvidenceType.LOG, EvidenceType.CONFIG],
            ),
        ]
        for c in controls:
            self._frameworks[ComplianceFramework.PCI_DSS].append(c)

    def _load_iso_controls(self) -> None:
        controls = [
            FrameworkControl(
                control_id="iso_a5_1",
                framework=ComplianceFramework.ISO27001,
                control_ref="A.5.1",
                title="Policies for Information Security",
                description="A set of policies for information security shall be defined, approved by management, published and communicated to employees and relevant external parties.",
                category="Information Security Policies",
                criticality=RiskLevel.HIGH,
                evidence_required=[EvidenceType.POLICY, EvidenceType.DOCUMENT],
            ),
            FrameworkControl(
                control_id="iso_a6_1",
                framework=ComplianceFramework.ISO27001,
                control_ref="A.6.1",
                title="Internal Organization",
                description="Information security roles and responsibilities shall be defined and allocated.",
                category="Organization of Information Security",
                criticality=RiskLevel.MEDIUM,
                evidence_required=[EvidenceType.DOCUMENT],
            ),
            FrameworkControl(
                control_id="iso_a8_1",
                framework=ComplianceFramework.ISO27001,
                control_ref="A.8.1",
                title="Responsibility for Assets",
                description="All assets shall be clearly identified and an inventory of all important assets associated with information and information processing facilities shall be drawn up and maintained.",
                category="Asset Management",
                criticality=RiskLevel.HIGH,
                automation_possible=True,
                evidence_required=[EvidenceType.CONFIG, EvidenceType.DOCUMENT],
            ),
            FrameworkControl(
                control_id="iso_a12_6",
                framework=ComplianceFramework.ISO27001,
                control_ref="A.12.6",
                title="Technical Vulnerability Management",
                description="Information about technical vulnerabilities of information systems being used shall be obtained in a timely fashion, the organization's exposure to such vulnerabilities evaluated and appropriate measures taken to address the associated risk.",
                category="Operations Security",
                criticality=RiskLevel.HIGH,
                automation_possible=True,
                evidence_required=[EvidenceType.SCAN_RESULT, EvidenceType.DOCUMENT],
            ),
        ]
        for c in controls:
            self._frameworks[ComplianceFramework.ISO27001].append(c)

    def get_controls(self, framework: ComplianceFramework) -> list[FrameworkControl]:
        return self._frameworks.get(framework, [])

    def get_control(self, control_id: str) -> Optional[FrameworkControl]:
        for controls in self._frameworks.values():
            for control in controls:
                if control.control_id == control_id:
                    return control
        return None

    def get_all_controls(self) -> list[FrameworkControl]:
        all_controls = []
        for controls in self._frameworks.values():
            all_controls.extend(controls)
        return all_controls

    def add_custom_control(self, control: FrameworkControl) -> None:
        self._frameworks[control.framework].append(control)


class ComplianceManager:
    """Manages compliance programs."""

    def __init__(self, framework_registry: Optional[FrameworkRegistry] = None):
        self.framework_registry = framework_registry or FrameworkRegistry()
        self._implementations: dict[str, ControlImplementation] = {}
        self._evidence: dict[str, Evidence] = {}
        self._test_results: dict[str, TestResult] = {}
        self._policies: dict[str, Policy] = {}
        self._risks: dict[str, Risk] = {}
        self._assessments: dict[str, ComplianceAssessment] = {}

    def register_implementation(
        self,
        control_id: str,
        owner: str,
        reviewer: str = "",
        details: str = "",
    ) -> ControlImplementation:
        control = self.framework_registry.get_control(control_id)
        impl = ControlImplementation(
            control_id=control_id,
            framework=control.framework if control else ComplianceFramework.CUSTOM,
            owner=owner,
            reviewer=reviewer,
            implementation_details=details,
            status=ControlStatus.NOT_IMPLEMENTED,
        )
        self._implementations[impl.implementation_id] = impl
        return impl

    def get_implementation(self, implementation_id: str) -> Optional[ControlImplementation]:
        return self._implementations.get(implementation_id)

    def get_implementations_by_control(self, control_id: str) -> list[ControlImplementation]:
        return [i for i in self._implementations.values() if i.control_id == control_id]

    def get_implementations_by_framework(self, framework: ComplianceFramework) -> list[ControlImplementation]:
        controls = self.framework_registry.get_controls(framework)
        control_ids = {c.control_id for c in controls}
        return [i for i in self._implementations.values() if i.control_id in control_ids]

    def update_implementation_status(
        self,
        implementation_id: str,
        status: ControlStatus,
        details: str = "",
        owner: str = "",
    ) -> bool:
        impl = self._implementations.get(implementation_id)
        if not impl:
            return False

        impl.status = status
        impl.implementation_details = details or impl.implementation_details
        if owner:
            impl.owner = owner
        impl.updated_at = datetime.utcnow()

        if status in [ControlStatus.IMPLEMENTED, ControlStatus.COMPLIANT]:
            impl.implemented_at = datetime.utcnow()

        return True

    def add_evidence(self, evidence: Evidence) -> None:
        self._evidence[evidence.evidence_id] = evidence
        # Link to implementation
        impl = self._implementations.get(evidence.implementation_id)
        if impl:
            impl.evidence.append(evidence)

    def get_evidence(self, evidence_id: str) -> Optional[Evidence]:
        return self._evidence.get(evidence_id)

    def get_evidence_for_implementation(self, implementation_id: str) -> list[Evidence]:
        return [e for e in self._evidence.values() if e.implementation_id == implementation_id]

    def verify_evidence(self, evidence_id: str, verified_by: str) -> bool:
        evidence = self._evidence.get(evidence_id)
        if not evidence:
            return False
        evidence.verified = True
        evidence.verified_by = verified_by
        evidence.verified_at = datetime.utcnow()
        return True

    def record_test_result(self, test_result: TestResult) -> None:
        self._test_results[test_result.test_id] = test_result

        # Update implementation
        impl = self._implementations.get(test_result.implementation_id)
        if impl:
            impl.test_results.append(test_result)
            impl.last_tested = test_result.completed_at or datetime.utcnow()
            # Set next test due based on control frequency
            # Would need control reference for frequency
            impl.next_test_due = datetime.utcnow() + timedelta(days=365)

    def get_test_results(self, implementation_id: str) -> list[TestResult]:
        return [t for t in self._test_results.values() if t.implementation_id == implementation_id]

    def create_policy(self, policy: Policy) -> Policy:
        self._policies[policy.policy_id] = policy
        return policy

    def get_policy(self, policy_id: str) -> Optional[Policy]:
        return self._policies.get(policy_id)

    def list_policies(self, framework: Optional[ComplianceFramework] = None, status: Optional[PolicyStatus] = None) -> list[Policy]:
        policies = list(self._policies.values())
        if framework:
            policies = [p for p in policies if framework in p.frameworks]
        if status:
            policies = [p for p in policies if p.status == status]
        return policies

    def create_risk(self, risk: Risk) -> Risk:
        self._risks[risk.risk_id] = risk
        return risk

    def get_risk(self, risk_id: str) -> Optional[Risk]:
        return self._risks.get(risk_id)

    def list_risks(self, status: Optional[str] = None, category: Optional[str] = None, owner: Optional[str] = None) -> list[Risk]:
        risks = list(self._risks.values())
        if status:
            risks = [r for r in risks if r.status == status]
        if category:
            risks = [r for r in risks if r.category == category]
        if owner:
            risks = [r for r in risks if r.owner == owner]
        return risks

    def create_assessment(
        self,
        framework: ComplianceFramework,
        tenant_id: str = "",
        scope: str = "full",
        assessor: str = "",
    ) -> ComplianceAssessment:
        controls = self.framework_registry.get_controls(framework)

        assessment = ComplianceAssessment(
            framework=framework,
            tenant_id=tenant_id,
            scope=scope,  # was hardcoded to "full" — caller's scope dropped
            controls_assessed=[c.control_id for c in controls],
            total_controls=len(controls),
            assessor=assessor,
        )

        self._assessments[assessment.assessment_id] = assessment
        return assessment

    def run_assessment(
        self,
        assessment_id: str,
        tenant_implementations: Optional[dict[str, ControlImplementation]] = None,
    ) -> ComplianceAssessment:
        assessment = self._assessments.get(assessment_id)
        if not assessment:
            raise ValueError("Assessment not found")

        # Reset prior run — without this, re-running the same assessment
        # accumulated counters (proof: second run doubled compliant and
        # findings, inflating the score past reality).
        assessment.compliant = 0
        assessment.non_compliant = 0
        assessment.partially_compliant = 0
        assessment.not_applicable = 0
        assessment.findings = []

        # Use tenant implementations or global. An explicit EMPTY dict
        # means "this tenant has no implementations" — it must not fall
        # back to the global registry (proof: run with {} still reported
        # global compliant controls).
        if tenant_implementations is not None:
            impls = tenant_implementations
        else:
            impls = {
                impl.control_id: impl
                for impl in self._implementations.values()
                if impl.control_id in assessment.controls_assessed
            }

        for control_id in assessment.controls_assessed:
            impl = impls.get(control_id)
            if not impl:
                assessment.non_compliant += 1
                assessment.findings.append({
                    "control_id": control_id,
                    "finding": "Not implemented",
                    "severity": "high",
                })
            else:
                if impl.status == ControlStatus.COMPLIANT:
                    assessment.compliant += 1
                elif impl.status == ControlStatus.PARTIALLY_IMPLEMENTED:
                    assessment.partially_compliant += 1
                elif impl.status == ControlStatus.NOT_APPLICABLE:
                    assessment.not_applicable += 1
                else:
                    assessment.non_compliant += 1
                    assessment.findings.append({
                        "control_id": control_id,
                        "finding": f"Status: {impl.status.value}",
                        "severity": "medium",
                    })

        assessment.total_controls = len(assessment.controls_assessed)
        assessment.calculate_scores()
        assessment.completed_at = datetime.utcnow()
        assessment.next_assessment_due = datetime.utcnow() + timedelta(days=365)

        return assessment

    def get_assessment(self, assessment_id: str) -> Optional[ComplianceAssessment]:
        return self._assessments.get(assessment_id)

    def list_assessments(self, framework: Optional[ComplianceFramework] = None, tenant_id: Optional[str] = None) -> list[ComplianceAssessment]:
        assessments = list(self._assessments.values())
        if framework:
            assessments = [a for a in assessments if a.framework == framework]
        if tenant_id:
            assessments = [a for a in assessments if a.tenant_id == tenant_id]
        return assessments


class ComplianceDashboard:
    """Dashboard for compliance monitoring."""

    def __init__(self, manager: ComplianceManager):
        self.manager = manager

    def get_overview(self, tenant_id: Optional[str] = None) -> dict[str, Any]:
        """Get compliance overview."""
        all_impls = list(self.manager._implementations.values())
        if tenant_id:
            # Filter by tenant (would need tenant context on implementations)
            pass

        total = len(all_impls)
        by_status: dict[str, int] = defaultdict(int)
        by_framework: dict[str, int] = defaultdict(int)

        for impl in all_impls:
            by_status[impl.status.value] += 1
            by_framework[impl.framework.value] += 1

        overdue = sum(1 for i in all_impls if i.is_overdue())

        return {
            "total_controls": total,
            "by_status": dict(by_status),
            "by_framework": dict(by_framework),
            "overdue_tests": overdue,
            "compliance_rate": by_status.get("compliant", 0) / max(1, total) * 100,
        }

    def get_framework_status(self, framework: ComplianceFramework) -> dict[str, Any]:
        controls = self.manager.framework_registry.get_controls(framework)
        impls = self.manager.get_implementations_by_framework(framework)

        control_status = {}
        for control in controls:
            impl = next((i for i in impls if i.control_id == control.control_id), None)
            if impl:
                control_status[control.control_ref] = {
                    "title": control.title,
                    "status": impl.status.value,
                    "criticality": control.criticality.value,
                    "overdue": impl.is_overdue(),
                }
            else:
                control_status[control.control_ref] = {
                    "title": control.title,
                    "status": "not_implemented",
                    "criticality": control.criticality.value,
                    "overdue": False,
                }

        total = len(controls)
        compliant = sum(1 for i in impls if i.is_compliant())

        return {
            "framework": framework.value,
            "total_controls": total,
            "implemented": len(impls),
            "compliant": sum(1 for i in impls if i.is_compliant()),
            "compliance_rate": compliant / len(impls) * 100 if impls else 0,
            "controls": control_status,
        }

    def get_risk_summary(self) -> dict[str, Any]:
        risks = list(self.manager._risks.values())

        by_level: dict[str, int] = defaultdict(int)
        by_category: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)

        for risk in risks:
            by_level[risk.risk_level.value] += 1
            by_category[risk.category] += 1
            by_status[risk.status] += 1

        return {
            "total_risks": len(risks),
            "by_level": dict(by_level),
            "by_category": dict(by_category),
            "by_status": dict(by_status),
            "open_high_critical": sum(1 for r in risks if r.risk_level in [RiskLevel.HIGH, RiskLevel.CRITICAL] and r.status == "open"),
        }

    def get_upcoming_tests(self, days: int = 30) -> dict[str, list[dict[str, Any]]]:
        due_date = datetime.utcnow() + timedelta(days=days)
        overdue = []
        upcoming = []

        for impl in self.manager._implementations.values():
            if impl.next_test_due:
                if impl.next_test_due < datetime.utcnow():
                    overdue.append({
                        "implementation_id": impl.implementation_id,
                        "control_id": impl.control_id,
                        "owner": impl.owner,
                        "due_date": impl.next_test_due.isoformat(),
                    })
                elif impl.next_test_due <= due_date:
                    upcoming.append({
                        "implementation_id": impl.implementation_id,
                        "control_id": impl.control_id,
                        "owner": impl.owner,
                        "due_date": impl.next_test_due.isoformat(),
                    })

        return {
            "overdue": overdue,
            "upcoming": upcoming,
        }


class AutomatedComplianceChecker:
    """Automated compliance checking."""

    def __init__(self, manager: ComplianceManager):
        self.manager = manager
        self._checks: dict[str, Callable] = {}

    def register_check(
        self,
        control_id: str,
        check_func: Callable[[ControlImplementation], tuple[bool, str]],
    ) -> None:
        self._checks[control_id] = check_func

    async def run_checks(self, implementation_ids: Optional[list[str]] = None) -> dict[str, TestResult]:
        """Run automated checks for implementations."""
        impls = []
        if implementation_ids is not None:
            # An explicit empty list means "check nothing" — not "check all"
            # (proof: run_checks([]) used to run every implementation).
            impls = [self.manager._implementations[i] for i in implementation_ids if i in self.manager._implementations]
        else:
            impls = list(self.manager._implementations.values())

        results = {}

        for impl in impls:
            if impl.control_id in self._checks:
                check_func = self._checks[impl.control_id]
                try:
                    passed, message = check_func(impl)

                    result = TestResult(
                        implementation_id=impl.implementation_id,
                        test_type="automated",
                        tester="system",
                        passed=passed,
                        score=100 if passed else 0,
                        findings=[message] if not passed else [],
                        completed_at=datetime.utcnow(),
                    )

                    self.manager.record_test_result(result)
                    results[impl.implementation_id] = result

                except Exception as e:
                    logger.error(f"Automated check failed for {impl.implementation_id}: {e}")

        return results


# Global instances
_compliance_manager: Optional[ComplianceManager] = None


def get_compliance_manager() -> ComplianceManager:
    global _compliance_manager
    if _compliance_manager is None:
        _compliance_manager = ComplianceManager()
    return _compliance_manager


# Alias for backward compatibility
get_compliance_manager = get_compliance_manager


__all__ = [
    "ComplianceFramework",
    "ControlStatus",
    "EvidenceType",
    "RiskLevel",
    "PolicyStatus",
    "FrameworkControl",
    "ControlImplementation",
    "Evidence",
    "TestResult",
    "Policy",
    "Risk",
    "ComplianceAssessment",
    "FrameworkRegistry",
    "ComplianceManager",
    "ComplianceDashboard",
    "AutomatedComplianceChecker",
    "get_compliance_manager",
]
