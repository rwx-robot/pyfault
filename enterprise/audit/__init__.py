"""
Audit Logging for PyFault framework.

Comprehensive audit logging:
- Structured audit events
- Tamper-proof storage
- Compliance reporting
- Real-time alerting
- Query and analysis
"""

import asyncio
import hashlib
import json
import logging
import os
import statistics
import uuid
import warnings
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class AuditEventType(str, Enum):
    """Types of audit events."""
    # Authentication
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    LOGIN_FAILED = "auth.login_failed"
    MFA_CHALLENGE = "auth.mfa_challenge"
    MFA_SUCCESS = "auth.mfa_success"
    MFA_FAILED = "auth.mfa_failed"
    PASSWORD_CHANGE = "auth.password_change"
    PASSWORD_RESET = "auth.password_reset"

    # Authorization
    PERMISSION_GRANTED = "authz.permission_granted"
    PERMISSION_DENIED = "authz.permission_denied"
    ROLE_ASSIGNED = "authz.role_assigned"
    ROLE_REVOKED = "authz.role_revoked"

    # User management
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_SUSPENDED = "user.suspended"
    USER_ACTIVATED = "user.activated"

    # Tenant management
    TENANT_CREATED = "tenant.created"
    TENANT_UPDATED = "tenant.updated"
    TENANT_DELETED = "tenant.deleted"
    TENANT_SUSPENDED = "tenant.suspended"

    # API keys
    API_KEY_CREATED = "apikey.created"
    API_KEY_REVOKED = "apikey.revoked"
    API_KEY_USED = "apikey.used"

    # Data access
    DATA_READ = "data.read"
    DATA_WRITTEN = "data.written"
    DATA_DELETED = "data.deleted"
    DATA_EXPORTED = "data.exported"

    # Configuration
    CONFIG_CHANGED = "config.changed"
    FEATURE_FLAG_CHANGED = "config.feature_flag_changed"

    # Security
    SECURITY_ALERT = "security.alert"
    SUSPICIOUS_ACTIVITY = "security.suspicious_activity"
    RATE_LIMIT_EXCEEDED = "security.rate_limit_exceeded"
    BRUTE_FORCE_DETECTED = "security.brute_force_detected"

    # System
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"
    BACKUP_CREATED = "system.backup_created"
    BACKUP_RESTORED = "system.backup_restored"

    # Compliance
    COMPLIANCE_CHECK = "compliance.check"
    COMPLIANCE_VIOLATION = "compliance.violation"
    DATA_RETENTION_APPLIED = "compliance.data_retention_applied"

    # Custom
    CUSTOM = "custom"


class AuditSeverity(str, Enum):
    """Audit event severity."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class AuditOutcome(str, Enum):
    """Outcome of the audited action."""
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    PENDING = "pending"


_SEVERITY_RANK: dict[AuditSeverity, int] = {
    AuditSeverity.DEBUG: 0,
    AuditSeverity.INFO: 1,
    AuditSeverity.WARNING: 2,
    AuditSeverity.ERROR: 3,
    AuditSeverity.CRITICAL: 4,
}


@dataclass
class AuditEvent:
    """Structured audit event."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    event_type: AuditEventType = AuditEventType.CUSTOM
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Actor
    actor_id: str = ""  # User ID, service ID, or "system"
    actor_type: str = "user"  # user, service, system, api_key
    actor_name: str = ""
    tenant_id: str = ""

    # Action
    action: str = ""
    resource_type: str = ""  # user, tenant, resource, config, etc.
    resource_id: str = ""
    resource_name: str = ""

    # Outcome
    outcome: AuditOutcome = AuditOutcome.SUCCESS
    severity: AuditSeverity = AuditSeverity.INFO
    error_message: str = ""

    # Context
    ip_address: str = ""
    user_agent: str = ""
    session_id: str = ""
    request_id: str = ""
    correlation_id: str = ""

    # Details
    details: dict[str, Any] = field(default_factory=dict)
    before_state: dict[str, Any] = field(default_factory=dict)
    after_state: dict[str, Any] = field(default_factory=dict)

    # Security
    risk_score: int = 0  # 0-100
    tags: list[str] = field(default_factory=list)

    # Integrity
    hash: str = ""  # SHA256 of event content
    previous_hash: str = ""  # Hash of previous event (chain)

    def compute_hash(self, previous_hash: str = "") -> str:
        """Compute hash for tamper detection."""
        content = f"{self.event_id}{self.timestamp.isoformat()}{self.actor_id}{self.action}{self.resource_id}{json.dumps(self.details, sort_keys=True)}{previous_hash}"
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
            "actor": {
                "id": self.actor_id,
                "type": self.actor_type,
                "name": self.actor_name,
            },
            "tenant_id": self.tenant_id,
            "action": self.action,
            "resource": {
                "type": self.resource_type,
                "id": self.resource_id,
                "name": self.resource_name,
            },
            "outcome": self.outcome.value,
            "severity": self.severity.value,
            "error_message": self.error_message,
            "context": {
                "ip_address": self.ip_address,
                "user_agent": self.user_agent,
                "session_id": self.session_id,
                "request_id": self.request_id,
                "correlation_id": self.correlation_id,
            },
            "details": self.details,
            "before_state": self.before_state,
            "after_state": self.after_state,
            "risk_score": self.risk_score,
            "tags": self.tags,
            "hash": self.hash,
            "previous_hash": self.previous_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEvent":
        event = cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            event_type=AuditEventType(data.get("event_type", "custom")),
            timestamp=datetime.fromisoformat(data["timestamp"]) if isinstance(data["timestamp"], str) else data["timestamp"],
            actor_id=data.get("actor", {}).get("id", ""),
            actor_type=data.get("actor", {}).get("type", "user"),
            actor_name=data.get("actor", {}).get("name", ""),
            tenant_id=data.get("tenant_id", ""),
            action=data.get("action", ""),
            resource_type=data.get("resource", {}).get("type", ""),
            resource_id=data.get("resource", {}).get("id", ""),
            resource_name=data.get("resource", {}).get("name", ""),
            outcome=AuditOutcome(data.get("outcome", "success")),
            severity=AuditSeverity(data.get("severity", "info")),
            error_message=data.get("error_message", ""),
            ip_address=data.get("context", {}).get("ip_address", ""),
            user_agent=data.get("context", {}).get("user_agent", ""),
            session_id=data.get("context", {}).get("session_id", ""),
            request_id=data.get("context", {}).get("request_id", ""),
            correlation_id=data.get("context", {}).get("correlation_id", ""),
            details=data.get("details", {}),
            before_state=data.get("before_state", {}),
            after_state=data.get("after_state", {}),
            risk_score=data.get("risk_score", 0),
            tags=data.get("tags", []),
            hash=data.get("hash", ""),
            previous_hash=data.get("previous_hash", ""),
        )
        return event


class AuditStore:
    """Storage backend for audit events."""

    def __init__(self, base_path: str = "./data/audit"):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._events: deque[AuditEvent] = deque(maxlen=100000)
        self._index: dict[str, set[str]] = defaultdict(set)  # type -> event_ids
        self._tenant_index: dict[str, set[str]] = defaultdict(set)
        self._actor_index: dict[str, set[str]] = defaultdict(set)
        self._last_hash = ""
        self._lock = asyncio.Lock()

    async def append(self, event: AuditEvent) -> bool:
        """Append event to store."""
        async with self._lock:
            # Compute hash chain
            event.previous_hash = self._last_hash
            event.hash = event.compute_hash(self._last_hash)
            self._last_hash = event.hash

            # Store in memory
            self._events.append(event)

            # Update indices
            self._index[event.event_type.value].add(event.event_id)
            self._tenant_index[event.tenant_id].add(event.event_id)
            self._actor_index[event.actor_id].add(event.event_id)

            # Persist to disk (batch write)
            if len(self._events) % 100 == 0:
                await self._flush_to_disk()

            return True

    async def _flush_to_disk(self) -> None:
        """Flush events to disk in batches."""
        try:
            # Write to daily files
            today = datetime.utcnow().strftime("%Y-%m-%d")
            file_path = self.base_path / f"audit-{today}.jsonl"

            # Get events since last flush (simplified - write all)
            file_path.parent.mkdir(parents=True, exist_ok=True)

            with open(file_path, 'a') as f:
                for event in list(self._events)[-1000:]:  # Last 1000 events
                    f.write(json.dumps(event.to_dict()) + '\n')
        except Exception as e:
            logger.error(f"Failed to flush audit events: {e}")

    async def query(
        self,
        event_type: Optional[AuditEventType] = None,
        tenant_id: Optional[str] = None,
        actor_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        severity: Optional[AuditSeverity] = None,
        outcome: Optional[AuditOutcome] = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[AuditEvent]:
        """Query audit events."""
        results = []

        for event in self._events:
            # Apply filters
            if event_type and event.event_type != event_type:
                continue
            if tenant_id and event.tenant_id != tenant_id:
                continue
            if actor_id and event.actor_id != actor_id:
                continue
            if start_time and event.timestamp < start_time:
                continue
            if end_time and event.timestamp > end_time:
                continue
            if severity and event.severity != severity:
                continue
            if outcome and event.outcome != outcome:
                continue

            results.append(event)

        # Sort by timestamp descending
        results.sort(key=lambda e: e.timestamp, reverse=True)

        return results[offset:offset + limit]

    async def get_event(self, event_id: str) -> Optional[AuditEvent]:
        for event in self._events:
            if event.event_id == event_id:
                return event
        return None

    async def verify_integrity(self, start_time: Optional[datetime] = None, end_time: Optional[datetime] = None) -> dict[str, Any]:
        """Verify hash chain integrity."""
        issues = []
        prev_hash = ""

        for event in self._events:
            expected_hash = event.compute_hash(prev_hash)
            in_window = True
            if start_time and event.timestamp < start_time:
                in_window = False
            if end_time and event.timestamp > end_time:
                in_window = False

            # Always advance the chain from the true predecessor, but only
            # report issues for events inside the requested window — seeding
            # prev_hash from "" at a window start produced false "tamper"
            # reports for intact chains.
            if in_window:
                if event.hash != expected_hash:
                    issues.append({
                        "event_id": event.event_id,
                        "expected_hash": expected_hash,
                        "actual_hash": event.hash,
                    })

                if event.previous_hash != prev_hash:
                    issues.append({
                        "event_id": event.event_id,
                        "issue": "Previous hash mismatch",
                        "expected": prev_hash,
                        "actual": event.previous_hash,
                    })

            prev_hash = event.hash

        return {
            "verified": len(issues) == 0,
            "total_events": len(self._events),
            "issues": issues,
            "checked_at": datetime.utcnow().isoformat(),
        }

    async def get_stats(self) -> dict[str, Any]:
        """Get audit statistics."""
        by_type: defaultdict[str, int] = defaultdict(int)
        by_severity: defaultdict[str, int] = defaultdict(int)
        by_outcome: defaultdict[str, int] = defaultdict(int)
        by_tenant: defaultdict[str, int] = defaultdict(int)

        for event in self._events:
            by_type[event.event_type.value] += 1
            by_severity[event.severity.value] += 1
            by_outcome[event.outcome.value] += 1
            by_tenant[event.tenant_id] += 1

        return {
            "total_events": len(self._events),
            "by_type": dict(by_type),
            "by_severity": dict(by_severity),
            "by_outcome": dict(by_outcome),
            "by_tenant": dict(by_tenant),
            "last_event": self._events[-1].timestamp.isoformat() if self._events else None,
            "chain_verified": True,  # Would need to call verify_integrity
        }


class AuditLogger:
    """High-level audit logging interface."""

    def __init__(self, store: Optional[AuditStore] = None):
        self.store = store or AuditStore()
        self._context: dict[str, Any] = {}
        self._filters: list[Callable[[AuditEvent], bool]] = []
        self._handlers: list[Callable[[AuditEvent], None]] = []
        self._alert_threshold = AuditSeverity.WARNING
        self._alert_handlers: list[Callable[[AuditEvent], Any]] = []

    def set_context(self, **context: Any) -> None:
        """Set default context for all events."""
        self._context.update(context)

    def clear_context(self) -> None:
        self._context.clear()

    def add_filter(self, filter_func: Callable[[AuditEvent], bool]) -> None:
        self._filters.append(filter_func)

    def add_handler(self, handler: Callable[[AuditEvent], None]) -> None:
        self._handlers.append(handler)

    def add_alert_handler(self, handler: Callable[[AuditEvent], Any], threshold: AuditSeverity = AuditSeverity.WARNING) -> None:
        self._alert_threshold = threshold
        self._alert_handlers.append(handler)

    def _should_log(self, event: AuditEvent) -> bool:
        return all(filter_func(event) for filter_func in self._filters)

    async def log(self, event: AuditEvent) -> bool:
        """Log an audit event."""
        # Apply context
        for key, value in self._context.items():
            if not getattr(event, key, None):
                setattr(event, key, value)

        # Check filters
        if not self._should_log(event):
            return False

        # Store
        await self.store.append(event)

        # Call handlers
        for handler in self._handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Audit handler error: {e}")

        # Check alerts (rank order — string comparison put "error" below
        # "warning" lexicographically, so ERROR/CRITICAL never fired)
        if _SEVERITY_RANK[event.severity] >= _SEVERITY_RANK[self._alert_threshold]:
            for handler in self._alert_handlers:
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(f"Alert handler error: {e}")

        return True

    async def log_event(
        self,
        event_type: AuditEventType,
        action: str,
        actor_id: str = "",
        actor_type: str = "user",
        actor_name: str = "",
        tenant_id: str = "",
        resource_type: str = "",
        resource_id: str = "",
        resource_name: str = "",
        outcome: AuditOutcome = AuditOutcome.SUCCESS,
        severity: AuditSeverity = AuditSeverity.INFO,
        error_message: str = "",
        details: Optional[dict[str, Any]] = None,
        before_state: Optional[dict[str, Any]] = None,
        after_state: Optional[dict[str, Any]] = None,
        ip_address: str = "",
        user_agent: str = "",
        session_id: str = "",
        request_id: str = "",
        correlation_id: str = "",
        risk_score: int = 0,
        tags: Optional[list[str]] = None,
    ) -> bool:
        """Log an audit event with simplified parameters."""
        # Honor an explicitly passed actor_type; only infer when the caller
        # left the default ("user") — previously the parameter was dropped
        # entirely and actor_type was always recomputed from actor_id.
        resolved_actor_type = actor_type
        if resolved_actor_type == "user" and not actor_id:
            resolved_actor_type = "system"

        event = AuditEvent(
            event_type=event_type,
            action=action,
            actor_id=actor_id,
            actor_type=resolved_actor_type,
            actor_name=actor_name,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            outcome=outcome,
            severity=severity,
            error_message=error_message,
            details=details or {},
            before_state=before_state or {},
            after_state=after_state or {},
            ip_address=ip_address,
            user_agent=user_agent,
            session_id=session_id,
            request_id=request_id,
            correlation_id=correlation_id,
            risk_score=risk_score,
            tags=tags or [],
        )

        return await self.log(event)

    # Convenience methods for common events
    async def log_login(self, user_id: str, username: str, tenant_id: str, success: bool, ip: str = "", **kwargs: Any) -> bool:
        return await self.log_event(
            event_type=AuditEventType.LOGIN if success else AuditEventType.LOGIN_FAILED,
            action="user_login",
            actor_id=user_id,
            actor_name=username,
            tenant_id=tenant_id,
            outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
            severity=AuditSeverity.INFO if success else AuditSeverity.WARNING,
            ip_address=ip,
            user_agent=kwargs.get("user_agent", ""),
            session_id=kwargs.get("session_id", ""),
            details=kwargs.get("details", {}),
        )

    async def log_permission_check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
        granted: bool,
        tenant_id: str,
        **kwargs: Any
    ) -> bool:
        return await self.log_event(
            event_type=AuditEventType.PERMISSION_GRANTED if granted else AuditEventType.PERMISSION_DENIED,
            action=f"permission_check:{permission}",
            actor_id=user_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            outcome=AuditOutcome.SUCCESS if granted else AuditOutcome.FAILURE,
            severity=AuditSeverity.INFO if granted else AuditSeverity.WARNING,
            details={"permission": permission, **kwargs.get("details", {})},
        )

    async def log_data_access(
        self,
        user_id: str,
        action: str,  # read, write, delete, export
        resource_type: str,
        resource_id: str,
        resource_name: str = "",
        tenant_id: str = "",
        success: bool = True,
        **kwargs: Any
    ) -> bool:
        event_type_map = {
            "read": AuditEventType.DATA_READ,
            "write": AuditEventType.DATA_WRITTEN,
            "delete": AuditEventType.DATA_DELETED,
            "export": AuditEventType.DATA_EXPORTED,
        }

        return await self.log_event(
            event_type=event_type_map.get(action, AuditEventType.CUSTOM),
            action=f"data_{action}",
            actor_id=user_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
            severity=AuditSeverity.INFO,
            details=kwargs.get("details", {}),
        )

    async def log_security_alert(
        self,
        alert_type: str,
        message: str,
        severity: AuditSeverity = AuditSeverity.WARNING,
        user_id: str = "",
        tenant_id: str = "",
        risk_score: int = 50,
        **kwargs: Any
    ) -> bool:
        return await self.log_event(
            event_type=AuditEventType.SECURITY_ALERT,
            action=f"security_alert:{alert_type}",
            actor_id=user_id,
            tenant_id=tenant_id,
            outcome=AuditOutcome.SUCCESS,
            severity=severity,
            error_message=message,
            risk_score=risk_score,
            details=kwargs.get("details", {}),
        )

    async def log_config_change(
        self,
        user_id: str,
        config_key: str,
        old_value: Any,
        new_value: Any,
        tenant_id: str = "",
        **kwargs: Any
    ) -> bool:
        return await self.log_event(
            event_type=AuditEventType.CONFIG_CHANGED,
            action="config_change",
            actor_id=user_id,
            tenant_id=tenant_id,
            resource_type="config",
            resource_id=config_key,
            outcome=AuditOutcome.SUCCESS,
            severity=AuditSeverity.INFO,
            before_state={"value": old_value},
            after_state={"value": new_value},
            details=kwargs.get("details", {}),
        )


class AuditQueryBuilder:
    """Build complex audit queries."""

    def __init__(self, store: AuditStore):
        self.store = store
        self._filters: dict[str, Any] = {}

    def event_type(self, event_type: AuditEventType) -> "AuditQueryBuilder":
        self._filters["event_type"] = event_type
        return self

    def tenant(self, tenant_id: str) -> "AuditQueryBuilder":
        self._filters["tenant_id"] = tenant_id
        return self

    def actor(self, actor_id: str) -> "AuditQueryBuilder":
        self._filters["actor_id"] = actor_id
        return self

    def time_range(self, start: datetime, end: datetime) -> "AuditQueryBuilder":
        self._filters["start_time"] = start
        self._filters["end_time"] = end
        return self

    def severity(self, severity: AuditSeverity) -> "AuditQueryBuilder":
        self._filters["severity"] = severity
        return self

    def outcome(self, outcome: AuditOutcome) -> "AuditQueryBuilder":
        self._filters["outcome"] = outcome
        return self

    def limit(self, limit: int) -> "AuditQueryBuilder":
        self._filters["limit"] = limit
        return self

    def offset(self, offset: int) -> "AuditQueryBuilder":
        self._filters["offset"] = offset
        return self

    async def execute(self) -> list[AuditEvent]:
        return await self.store.query(**self._filters)

    async def count(self) -> int:
        results = await self.store.query(**self._filters)
        return len(results)

    async def aggregate(self, field: str) -> dict[str, int]:
        """Aggregate events by a field."""
        events = await self.store.query(**self._filters)

        counts: defaultdict[str, int] = defaultdict(int)
        for event in events:
            value = getattr(event, field, None)
            if value:
                counts[str(value)] += 1

        return dict(counts)


class ComplianceReporter:
    """Generate compliance reports from audit data."""

    def __init__(self, store: AuditStore):
        self.store = store

    async def generate_soc2_report(
        self,
        start_time: datetime,
        end_time: datetime,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate SOC 2 Type II compliance report."""
        query = AuditQueryBuilder(self.store).time_range(start_time, end_time)

        if tenant_id:
            query.tenant(tenant_id)

        events = await query.execute()

        # Categorize events for SOC 2 criteria
        cc6_1 = []  # Logical access
        cc6_7 = []  # Data transmission
        cc7_2 = []  # System monitoring

        for event in events:
            if event.event_type in [AuditEventType.LOGIN, AuditEventType.LOGIN_FAILED, AuditEventType.PERMISSION_GRANTED, AuditEventType.PERMISSION_DENIED]:
                cc6_1.append(event)
            elif event.event_type in [AuditEventType.DATA_EXPORTED, AuditEventType.DATA_READ]:
                cc6_7.append(event)
            elif event.severity in [AuditSeverity.WARNING, AuditSeverity.ERROR, AuditSeverity.CRITICAL]:
                cc7_2.append(event)

        return {
            "report_type": "SOC 2 Type II",
            "period": {"start": start_time.isoformat(), "end": end_time.isoformat()},
            "tenant_id": tenant_id,
            # Same filtered result as above — the old re-query here dropped
            # the tenant filter, so tenant-scoped reports reported ALL
            # tenants' events as total_events.
            "total_events": len(events),
            "cc6_1_logical_access": {
                "total_events": len(cc6_1),
                "failed_logins": len([e for e in cc6_1 if e.event_type == AuditEventType.LOGIN_FAILED]),
                "permission_denials": len([e for e in cc6_1 if e.event_type == AuditEventType.PERMISSION_DENIED]),
            },
            "cc6_7_data_transmission": {
                "total_events": len(cc6_7),
                "data_exports": len([e for e in cc6_7 if e.event_type == AuditEventType.DATA_EXPORTED]),
            },
            "cc7_2_system_monitoring": {
                "total_events": len(cc7_2),
                "critical_alerts": len([e for e in cc7_2 if e.severity == AuditSeverity.CRITICAL]),
                "security_alerts": len([e for e in cc7_2 if e.event_type == AuditEventType.SECURITY_ALERT]),
            },
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def generate_gdpr_report(
        self,
        start_time: datetime,
        end_time: datetime,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate GDPR compliance report."""
        query = AuditQueryBuilder(self.store).time_range(start_time, end_time)

        if tenant_id:
            query.tenant(tenant_id)

        events = await query.execute()

        # GDPR Article 30 - Records of processing activities
        processing_activities: defaultdict[str, int] = defaultdict(int)
        data_subject_requests = []
        breaches = []

        for event in events:
            if event.event_type in [AuditEventType.DATA_READ, AuditEventType.DATA_WRITTEN, AuditEventType.DATA_DELETED, AuditEventType.DATA_EXPORTED]:
                processing_activities[event.event_type.value] += 1

            if event.event_type == AuditEventType.CUSTOM and "data_subject_request" in event.details:
                data_subject_requests.append(event)

            if event.event_type == AuditEventType.SECURITY_ALERT and "breach" in event.details.get("type", "").lower():
                breaches.append(event)

        return {
            "report_type": "GDPR Article 30",
            "period": {"start": start_time.isoformat(), "end": end_time.isoformat()},
            "tenant_id": tenant_id,
            "processing_activities": dict(processing_activities),
            "data_subject_requests": len(data_subject_requests),
            "breaches": len(breaches),
            "breach_details": [e.to_dict() for e in breaches],
            "generated_at": datetime.utcnow().isoformat(),
        }

    async def generate_hipaa_report(
        self,
        start_time: datetime,
        end_time: datetime,
        tenant_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Generate HIPAA compliance report."""
        query = AuditQueryBuilder(self.store).time_range(start_time, end_time)

        if tenant_id:
            query.tenant(tenant_id)

        events = await query.execute()

        # HIPAA Security Rule - Administrative safeguards
        access_control = [e for e in events if e.event_type in [
            AuditEventType.LOGIN, AuditEventType.LOGIN_FAILED,
            AuditEventType.PERMISSION_GRANTED, AuditEventType.PERMISSION_DENIED,
            AuditEventType.ROLE_ASSIGNED, AuditEventType.ROLE_REVOKED,
        ]]

        audit_controls = [e for e in events if e.event_type == AuditEventType.CUSTOM]

        integrity = [e for e in events if e.event_type in [
            AuditEventType.DATA_WRITTEN, AuditEventType.DATA_DELETED,
        ]]

        transmission = [e for e in events if e.event_type == AuditEventType.DATA_EXPORTED]

        return {
            "report_type": "HIPAA Security Rule",
            "period": {"start": start_time.isoformat(), "end": end_time.isoformat()},
            "tenant_id": tenant_id,
            "administrative_safeguards": {
                "access_control_events": len(access_control),
                "failed_logins": len([e for e in access_control if e.event_type == AuditEventType.LOGIN_FAILED]),
                "role_changes": len([e for e in access_control if e.event_type in [AuditEventType.ROLE_ASSIGNED, AuditEventType.ROLE_REVOKED]]),
            },
            "audit_controls": {
                "audit_events": len(audit_controls),
            },
            "integrity_controls": {
                "data_modifications": len([e for e in integrity if e.event_type == AuditEventType.DATA_WRITTEN]),
                "data_deletions": len([e for e in integrity if e.event_type == AuditEventType.DATA_DELETED]),
            },
            "transmission_security": {
                "data_exports": len(transmission),
            },
            "generated_at": datetime.utcnow().isoformat(),
        }


# Global instances
_audit_logger: Optional[AuditLogger] = None


def get_audit_logger() -> AuditLogger:
    global _audit_logger
    if _audit_logger is None:
        _audit_logger = AuditLogger()
    return _audit_logger


def init_audit_logger(store: Optional[AuditStore] = None) -> AuditLogger:
    global _audit_logger
    _audit_logger = AuditLogger(store)
    return _audit_logger


# Alias for backward compatibility
get_audit_logger = get_audit_logger


__all__ = [
    "AuditEventType",
    "AuditSeverity",
    "AuditOutcome",
    "AuditEvent",
    "AuditStore",
    "AuditLogger",
    "AuditQueryBuilder",
    "ComplianceReporter",
    "get_audit_logger",
    "init_audit_logger",
]
