"""
Multi-Tenant Management for PyFault framework.

Multi-tenancy support:
- Tenant isolation (data, resources, configuration)
- Tenant onboarding and lifecycle
- Resource quotas and limits
- Cross-tenant access control
- Tenant-aware services
"""

import asyncio
import logging
import secrets
import uuid
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union

from pyfault.common.time import utc_now

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class TenantStatus(str, Enum):
    """Tenant lifecycle status."""
    PROVISIONING = "provisioning"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEPROVISIONING = "deprovisioning"
    DELETED = "deleted"
    ERROR = "error"


class TenantPlan(str, Enum):
    """Tenant subscription plans."""
    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"
    CUSTOM = "custom"


class ResourceQuotaType(str, Enum):
    """Types of resource quotas."""
    COMPUTE_UNITS = "compute_units"
    STORAGE_GB = "storage_gb"
    API_CALLS_PER_DAY = "api_calls_per_day"
    CONCURRENT_CONNECTIONS = "concurrent_connections"
    FUNCTION_INVOCATIONS = "function_invocations"
    DATABASE_CONNECTIONS = "database_connections"
    CACHE_MEMORY_MB = "cache_memory_mb"
    BANDWIDTH_GB = "bandwidth_gb"
    CUSTOM = "custom"


class IsolationLevel(str, Enum):
    """Data isolation levels."""
    SHARED = "shared"           # Shared database/schema
    SCHEMA = "schema"           # Separate schemas
    DATABASE = "database"       # Separate databases
    CLUSTER = "cluster"         # Separate clusters
    DEDICATED = "dedicated"     # Fully dedicated infrastructure


@dataclass
class ResourceQuota:
    """Resource quota definition."""
    quota_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    quota_type: ResourceQuotaType = ResourceQuotaType.CUSTOM
    limit: float = 0.0
    used: float = 0.0
    unit: str = ""

    # Period
    period_start: datetime = field(default_factory=utc_now)
    period_end: Optional[datetime] = None
    reset_frequency: str = "monthly"  # daily, weekly, monthly, never

    # Alerts
    warning_threshold: float = 0.8  # 80%
    critical_threshold: float = 0.95  # 95%
    alert_enabled: bool = True

    # Actions on limit
    hard_limit: bool = True  # Hard block vs soft warning
    auto_scale: bool = False  # Auto-request increase

    # Metadata
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    @property
    def utilization(self) -> float:
        return self.used / self.limit if self.limit > 0 else 0.0

    @property
    def available(self) -> float:
        return max(0, self.limit - self.used)

    @property
    def is_warning(self) -> bool:
        return self.utilization >= self.warning_threshold

    @property
    def is_critical(self) -> bool:
        return self.utilization >= self.critical_threshold

    @property
    def is_exceeded(self) -> bool:
        return self.used >= self.limit

    def to_dict(self) -> dict[str, Any]:
        return {
            "quota_id": self.quota_id,
            "tenant_id": self.tenant_id,
            "quota_type": self.quota_type.value,
            "limit": self.limit,
            "used": self.used,
            "unit": self.unit,
            "utilization": self.utilization,
            "available": self.available,
            "warning_threshold": self.warning_threshold,
            "critical_threshold": self.critical_threshold,
            "is_warning": self.is_warning,
            "is_critical": self.is_critical,
            "is_exceeded": self.is_exceeded,
        }


@dataclass
class Tenant:
    """Tenant/Organization entity."""
    tenant_id: str
    name: str
    display_name: str = ""
    description: str = ""

    # Identification
    domain: str = ""  # Custom domain
    subdomain: str = ""  # Platform subdomain

    # Status
    status: TenantStatus = TenantStatus.PROVISIONING
    plan: TenantPlan = TenantPlan.FREE

    # Isolation
    isolation_level: IsolationLevel = IsolationLevel.SCHEMA
    database_name: str = ""
    schema_name: str = ""

    # Configuration
    settings: dict[str, Any] = field(default_factory=dict)
    features: set[str] = field(default_factory=set)

    # Limits
    quotas: dict[str, ResourceQuota] = field(default_factory=dict)

    # Ownership
    owner_id: str = ""  # User ID
    admin_ids: list[str] = field(default_factory=list)

    # Billing
    billing_email: str = ""
    payment_method_id: str = ""

    # Timestamps
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    activated_at: Optional[datetime] = None
    suspended_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)
    tags: dict[str, str] = field(default_factory=dict)

    def is_active(self) -> bool:
        return self.status == TenantStatus.ACTIVE

    def is_trial(self) -> bool:
        return bool(self.trial_ends_at and utc_now() < self.trial_ends_at)

    def get_quota(self, quota_type: ResourceQuotaType) -> Optional[ResourceQuota]:
        return self.quotas.get(quota_type.value)

    def set_quota(self, quota: ResourceQuota) -> None:
        quota.tenant_id = self.tenant_id
        self.quotas[quota.quota_type.value] = quota

    def check_quota(self, quota_type: ResourceQuotaType, amount: float = 1.0) -> tuple[bool, str]:
        """Check if quota allows additional usage."""
        quota = self.get_quota(quota_type)
        if not quota:
            return True, "No quota defined"

        if quota.is_exceeded:
            return False, f"Quota {quota.quota_type.value} exceeded ({quota.used}/{quota.limit})"

        if quota.used + amount > quota.limit:
            return False, f"Would exceed quota {quota.quota_type.value}"

        return True, "OK"

    def consume_quota(self, quota_type: ResourceQuotaType, amount: float = 1.0) -> bool:
        quota = self.get_quota(quota_type)
        if not quota:
            return True

        if quota.used + amount > quota.limit and quota.hard_limit:
            return False

        quota.used += amount
        quota.updated_at = utc_now()
        return True

    def release_quota(self, quota_type: ResourceQuotaType, amount: float = 1.0) -> bool:
        quota = self.get_quota(quota_type)
        if not quota:
            return True

        quota.used = max(0, quota.used - amount)
        quota.updated_at = utc_now()
        return True

    def to_dict(self, include_quotas: bool = True) -> dict[str, Any]:
        data = {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "domain": self.domain,
            "subdomain": self.subdomain,
            "status": self.status.value,
            "plan": self.plan.value,
            "isolation_level": self.isolation_level.value,
            "database_name": self.database_name,
            "schema_name": self.schema_name,
            "settings": self.settings,
            "features": list(self.features),
            "owner_id": self.owner_id,
            "admin_ids": self.admin_ids,
            "billing_email": self.billing_email,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "activated_at": self.activated_at.isoformat() if self.activated_at else None,
            "suspended_at": self.suspended_at.isoformat() if self.suspended_at else None,
            "trial_ends_at": self.trial_ends_at.isoformat() if self.trial_ends_at else None,
            "metadata": self.metadata,
            "tags": self.tags,
        }

        if include_quotas:
            data["quotas"] = {k: v.to_dict() for k, v in self.quotas.items()}

        return data


@dataclass
class TenantInvitation:
    """Invitation to join a tenant."""
    invitation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    email: str = ""
    role: str = "member"  # admin, member, viewer
    invited_by: str = ""
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    expires_at: datetime = field(default_factory=lambda: utc_now() + timedelta(days=7))
    accepted_at: Optional[datetime] = None
    accepted_by: str = ""
    status: str = "pending"  # pending, accepted, expired, revoked
    created_at: datetime = field(default_factory=utc_now)

    def is_valid(self) -> bool:
        return self.status == "pending" and utc_now() < self.expires_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "invitation_id": self.invitation_id,
            "tenant_id": self.tenant_id,
            "email": self.email,
            "role": self.role,
            "invited_by": self.invited_by,
            "token": self.token,
            "expires_at": self.expires_at.isoformat(),
            "status": self.status,
            "created_at": self.created_at.isoformat(),
        }


class TenantManager:
    """Manages tenant lifecycle and operations."""

    def __init__(self) -> None:
        self._tenants: dict[str, Tenant] = {}
        self._tenant_by_domain: dict[str, str] = {}
        self._tenant_by_subdomain: dict[str, str] = {}
        self._invitations: dict[str, TenantInvitation] = {}
        self._tenant_users: dict[str, set[str]] = defaultdict(set)  # tenant_id -> user_ids
        self._provisioning_tasks: dict[str, asyncio.Task] = {}

        # Default quotas by plan
        self._plan_quotas = {
            TenantPlan.FREE: {
                ResourceQuotaType.COMPUTE_UNITS: 100,
                ResourceQuotaType.STORAGE_GB: 1,
                ResourceQuotaType.API_CALLS_PER_DAY: 10000,
                ResourceQuotaType.CONCURRENT_CONNECTIONS: 10,
            },
            TenantPlan.STARTER: {
                ResourceQuotaType.COMPUTE_UNITS: 1000,
                ResourceQuotaType.STORAGE_GB: 10,
                ResourceQuotaType.API_CALLS_PER_DAY: 100000,
                ResourceQuotaType.CONCURRENT_CONNECTIONS: 100,
            },
            TenantPlan.PROFESSIONAL: {
                ResourceQuotaType.COMPUTE_UNITS: 10000,
                ResourceQuotaType.STORAGE_GB: 100,
                ResourceQuotaType.API_CALLS_PER_DAY: 1000000,
                ResourceQuotaType.CONCURRENT_CONNECTIONS: 1000,
            },
            TenantPlan.ENTERPRISE: {
                ResourceQuotaType.COMPUTE_UNITS: 100000,
                ResourceQuotaType.STORAGE_GB: 1000,
                ResourceQuotaType.API_CALLS_PER_DAY: 10000000,
                ResourceQuotaType.CONCURRENT_CONNECTIONS: 10000,
            },
        }

    def create_tenant(
        self,
        name: str,
        owner_id: str,
        display_name: str = "",
        description: str = "",
        plan: TenantPlan = TenantPlan.FREE,
        domain: str = "",
        subdomain: str = "",
        isolation_level: IsolationLevel = IsolationLevel.SCHEMA,
        trial_days: int = 0,
    ) -> Tenant:
        """Create a new tenant."""
        tenant = Tenant(
            tenant_id=str(uuid.uuid4()),
            name=name,
            display_name=display_name or name,
            description=description,
            owner_id=owner_id,
            plan=plan,
            domain=domain,
            subdomain=subdomain or name.lower().replace(" ", "-"),
            isolation_level=isolation_level,
        )

        # Set database/schema names based on isolation
        if isolation_level == IsolationLevel.DATABASE:
            tenant.database_name = f"tenant_{tenant.tenant_id}"
        elif isolation_level == IsolationLevel.SCHEMA:
            tenant.schema_name = f"tenant_{tenant.tenant_id}"

        # Apply plan quotas
        self._apply_plan_quotas(tenant)

        # Set trial
        if trial_days > 0:
            tenant.trial_ends_at = utc_now() + timedelta(days=trial_days)

        # Register
        self._tenants[tenant.tenant_id] = tenant
        self._tenant_users[tenant.tenant_id].add(owner_id)

        if domain:
            self._tenant_by_domain[domain] = tenant.tenant_id
        if tenant.subdomain:
            self._tenant_by_subdomain[tenant.subdomain] = tenant.tenant_id

        # Add admin
        tenant.admin_ids.append(owner_id)

        # Start provisioning
        self._start_provisioning(tenant)

        logger.info(f"Created tenant: {tenant.name} ({tenant.tenant_id})")
        return tenant

    def _apply_plan_quotas(self, tenant: Tenant) -> None:
        quotas = self._plan_quotas.get(tenant.plan, {})
        for quota_type, limit in quotas.items():
            quota = ResourceQuota(
                tenant_id=tenant.tenant_id,
                quota_type=quota_type,
                limit=limit,
                unit=self._get_unit(quota_type),
            )
            tenant.set_quota(quota)

    def _get_unit(self, quota_type: ResourceQuotaType) -> str:
        units = {
            ResourceQuotaType.COMPUTE_UNITS: "units",
            ResourceQuotaType.STORAGE_GB: "GB",
            ResourceQuotaType.API_CALLS_PER_DAY: "calls/day",
            ResourceQuotaType.CONCURRENT_CONNECTIONS: "connections",
            ResourceQuotaType.FUNCTION_INVOCATIONS: "invocations",
            ResourceQuotaType.DATABASE_CONNECTIONS: "connections",
            ResourceQuotaType.CACHE_MEMORY_MB: "MB",
            ResourceQuotaType.BANDWIDTH_GB: "GB",
        }
        return units.get(quota_type, "units")

    def _start_provisioning(self, tenant: Tenant) -> None:
        """Start tenant provisioning (synchronous)."""
        tenant.status = TenantStatus.PROVISIONING
        try:
            # Simulate provisioning steps (sync for simplicity)
            self._provision_database_sync(tenant)
            self._provision_storage_sync(tenant)
            self._provision_networking_sync(tenant)
            self._configure_dns_sync(tenant)

            tenant.status = TenantStatus.ACTIVE
            tenant.activated_at = utc_now()
            logger.info(f"Tenant {tenant.name} provisioned successfully")
        except Exception as e:
            tenant.status = TenantStatus.ERROR
            logger.error(f"Provisioning failed for {tenant.name}: {e}")

    def _provision_database_sync(self, tenant: Tenant) -> None:
        """Provision database for tenant (sync)."""
        logger.info(f"Provisioning database for {tenant.name}")
        # In production: create database/schema, run migrations

    def _provision_storage_sync(self, tenant: Tenant) -> None:
        logger.info(f"Provisioning storage for {tenant.name}")

    def _provision_networking_sync(self, tenant: Tenant) -> None:
        logger.info(f"Provisioning networking for {tenant.name}")

    def _configure_dns_sync(self, tenant: Tenant) -> None:
        if tenant.domain or tenant.subdomain:
            logger.info(f"Configuring DNS for {tenant.name}")

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        return self._tenants.get(tenant_id)

    def get_tenant_by_domain(self, domain: str) -> Optional[Tenant]:
        tenant_id = self._tenant_by_domain.get(domain)
        return self._tenants.get(tenant_id) if tenant_id else None

    def get_tenant_by_subdomain(self, subdomain: str) -> Optional[Tenant]:
        tenant_id = self._tenant_by_subdomain.get(subdomain)
        return self._tenants.get(tenant_id) if tenant_id else None

    def list_tenants(
        self,
        status: Optional[TenantStatus] = None,
        plan: Optional[TenantPlan] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Tenant]:
        tenants = list(self._tenants.values())

        if status:
            tenants = [t for t in tenants if t.status == status]
        if plan:
            tenants = [t for t in tenants if t.plan == plan]

        tenants.sort(key=lambda t: t.created_at, reverse=True)
        return tenants[offset:offset + limit]

    def update_tenant(self, tenant_id: str, updates: dict[str, Any]) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        old_domain = tenant.domain
        old_subdomain = tenant.subdomain

        for key, value in updates.items():
            if hasattr(tenant, key) and key not in ["tenant_id", "owner_id", "created_at"]:
                setattr(tenant, key, value)

        tenant.updated_at = utc_now()

        # Handle domain/subdomain changes (reindex using pre-update values)
        if "domain" in updates:
            if old_domain and self._tenant_by_domain.get(old_domain) == tenant_id:
                del self._tenant_by_domain[old_domain]
            if tenant.domain:
                self._tenant_by_domain[tenant.domain] = tenant_id

        if "subdomain" in updates:
            if old_subdomain and self._tenant_by_subdomain.get(old_subdomain) == tenant_id:
                del self._tenant_by_subdomain[old_subdomain]
            if tenant.subdomain:
                self._tenant_by_subdomain[tenant.subdomain] = tenant_id

        return True

    def suspend_tenant(self, tenant_id: str, reason: str = "") -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        tenant.status = TenantStatus.SUSPENDED
        tenant.suspended_at = utc_now()
        tenant.metadata["suspension_reason"] = reason
        tenant.updated_at = utc_now()
        return True

    def activate_tenant(self, tenant_id: str) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        if tenant.status == TenantStatus.SUSPENDED:
            tenant.status = TenantStatus.ACTIVE
            tenant.suspended_at = None
            tenant.updated_at = utc_now()
            return True
        return False

    def delete_tenant(self, tenant_id: str, force: bool = False) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        if tenant.status == TenantStatus.ACTIVE and not force:
            return False

        tenant.status = TenantStatus.DELETED
        tenant.deleted_at = utc_now()
        tenant.updated_at = utc_now()

        # Clean up indexes
        if tenant.domain in self._tenant_by_domain:
            del self._tenant_by_domain[tenant.domain]
        if tenant.subdomain in self._tenant_by_subdomain:
            del self._tenant_by_subdomain[tenant.subdomain]

        return True

    def add_user(self, tenant_id: str, user_id: str) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        self._tenant_users[tenant_id].add(user_id)
        return True

    def remove_user(self, tenant_id: str, user_id: str) -> bool:
        if tenant_id in self._tenant_users:
            self._tenant_users[tenant_id].discard(user_id)
            return True
        return False

    def get_tenant_users(self, tenant_id: str) -> set[str]:
        return self._tenant_users.get(tenant_id, set())

    def invite_user(
        self,
        tenant_id: str,
        email: str,
        role: str = "member",
        invited_by: str = "",
    ) -> TenantInvitation:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            raise ValueError("Tenant not found")

        invitation = TenantInvitation(
            tenant_id=tenant_id,
            email=email,
            role=role,
            invited_by=invited_by,
        )

        self._invitations[invitation.invitation_id] = invitation
        return invitation

    def accept_invitation(self, token: str, user_id: str) -> bool:
        invitation = next((i for i in self._invitations.values() if i.token == token), None)
        if not invitation or not invitation.is_valid():
            return False

        invitation.status = "accepted"
        invitation.accepted_at = utc_now()
        invitation.accepted_by = user_id

        # Add user to tenant
        self.add_user(invitation.tenant_id, user_id)

        return True

    def upgrade_plan(self, tenant_id: str, new_plan: TenantPlan) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        tenant.plan = new_plan
        tenant.updated_at = utc_now()

        # Apply new quotas
        self._apply_plan_quotas(tenant)

        return True

    def get_tenant_stats(self, tenant_id: str) -> dict[str, Any]:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return {}

        return {
            "tenant": tenant.to_dict(),
            "user_count": len(self._tenant_users.get(tenant_id, set())),
            "quota_utilization": {
                k: v.utilization for k, v in tenant.quotas.items()
            },
            "is_trial": tenant.is_trial(),
            "trial_days_remaining": (
                (tenant.trial_ends_at - utc_now()).days
                if tenant.trial_ends_at else None
            ),
        }


class TenantContext:
    """Thread-local tenant context for request-scoped operations."""

    def __init__(self) -> None:
        self._current_tenant: Optional[Tenant] = None
        self._user_id: str = ""
        self._roles: list[str] = []

    def set_tenant(self, tenant: Tenant, user_id: str = "", roles: Optional[list[str]] = None) -> None:
        self._current_tenant = tenant
        self._user_id = user_id
        self._roles = roles or []

    def clear(self) -> None:
        self._current_tenant = None
        self._user_id = ""
        self._roles = []

    @property
    def tenant(self) -> Optional[Tenant]:
        return self._current_tenant

    @property
    def tenant_id(self) -> str:
        return self._current_tenant.tenant_id if self._current_tenant else ""

    @property
    def user_id(self) -> str:
        return self._user_id

    @property
    def roles(self) -> list[str]:
        return self._roles

    def check_permission(self, permission: str) -> bool:
        # Would integrate with auth system
        return True

    def check_quota(self, quota_type: ResourceQuotaType, amount: float = 1.0) -> tuple[bool, str]:
        if not self._current_tenant:
            return False, "No tenant context"
        return self._current_tenant.check_quota(quota_type, amount)

    def consume_quota(self, quota_type: ResourceQuotaType, amount: float = 1.0) -> bool:
        if not self._current_tenant:
            return False
        return self._current_tenant.consume_quota(quota_type, amount)


class TenantAwareService:
    """Base class for tenant-aware services."""

    def __init__(self, tenant_context: TenantContext):
        self.tenant_context = tenant_context

    @property
    def tenant(self) -> Optional[Tenant]:
        return self.tenant_context.tenant

    @property
    def tenant_id(self) -> str:
        return self.tenant_context.tenant_id

    def get_tenant_config(self, key: str, default: Any = None) -> Any:
        if not self.tenant_context.tenant:
            return default
        return self.tenant_context.tenant.settings.get(key, default)

    def set_tenant_config(self, key: str, value: Any) -> bool:
        if not self.tenant_context.tenant:
            return False
        self.tenant_context.tenant.settings[key] = value
        self.tenant_context.tenant.updated_at = utc_now()
        return True

    def is_feature_enabled(self, feature: str) -> bool:
        if not self.tenant_context.tenant:
            return False
        return feature in self.tenant_context.tenant.features

    def enable_feature(self, feature: str) -> bool:
        if not self.tenant_context.tenant:
            return False
        self.tenant_context.tenant.features.add(feature)
        return True

    def disable_feature(self, feature: str) -> bool:
        if not self.tenant_context.tenant:
            return False
        self.tenant_context.tenant.features.discard(feature)
        return True


class TenantMiddleware:
    """Middleware for extracting tenant from requests."""

    def __init__(self, tenant_manager: TenantManager):
        self.tenant_manager = tenant_manager
        self._context = TenantContext()

    async def resolve_tenant(self, request: Any) -> Optional[Tenant]:
        """Resolve tenant from request."""
        # Try domain
        host = request.headers.get("host", "")
        if host:
            domain = host.split(":")[0]
            tenant = self.tenant_manager.get_tenant_by_domain(domain)
            if tenant:
                return tenant

        # Try subdomain
        if "." in host:
            subdomain = host.split(".")[0]
            tenant = self.tenant_manager.get_tenant_by_subdomain(subdomain)
            if tenant:
                return tenant

        # Try header
        tenant_id = request.headers.get("x-tenant-id")
        if tenant_id:
            return self.tenant_manager.get_tenant(tenant_id)

        # Try query param
        tenant_id = request.query_params.get("tenant_id")
        if tenant_id:
            return self.tenant_manager.get_tenant(tenant_id)

        return None

    async def __call__(self, request: Any, call_next: Any) -> Any:
        tenant = await self.resolve_tenant(request)

        if tenant:
            user_id = getattr(request.state, "user_id", "") if hasattr(request, "state") else ""
            roles = getattr(request.state, "roles", []) if hasattr(request, "state") else []
            self._context.set_tenant(tenant, user_id, roles)

        try:
            response = await call_next(request)
        finally:
            self._context.clear()

        return response


# Global instances
_tenant_manager: Optional[TenantManager] = None
_tenant_context: Optional[TenantContext] = None


def get_tenant_manager() -> TenantManager:
    global _tenant_manager
    if _tenant_manager is None:
        _tenant_manager = TenantManager()
    return _tenant_manager


def get_tenant_context() -> TenantContext:
    global _tenant_context
    if _tenant_context is None:
        _tenant_context = TenantContext()
    return _tenant_context


# Aliases for backward compatibility
get_tenant_manager = get_tenant_manager
get_tenant_context = get_tenant_context


__all__ = [
    "TenantStatus",
    "TenantPlan",
    "ResourceQuotaType",
    "IsolationLevel",
    "ResourceQuota",
    "Tenant",
    "TenantInvitation",
    "TenantManager",
    "TenantContext",
    "TenantAwareService",
    "TenantMiddleware",
    "get_tenant_manager",
    "get_tenant_context",
]
