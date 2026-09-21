"""
Tenant Context for PyFault framework.
"""

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Tenant:
    """Tenant information."""
    id: str
    name: str
    domain: str = ""
    subdomain: str = ""
    config: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "domain": self.domain,
            "subdomain": self.subdomain,
            "config": self.config,
            "metadata": self.metadata,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# Context variable for current tenant
_current_tenant: ContextVar[Optional[Tenant]] = ContextVar("current_tenant", default=None)


def get_current_tenant() -> Optional[Tenant]:
    """Get the current tenant from context."""
    return _current_tenant.get()


def set_current_tenant(tenant: Optional[Tenant]) -> None:
    """Set the current tenant in context."""
    _current_tenant.set(tenant)


def clear_current_tenant() -> None:
    """Clear the current tenant from context."""
    _current_tenant.set(None)


class TenantContext:
    """Context manager for tenant isolation."""

    def __init__(self, tenant: Tenant):
        self.tenant = tenant
        self._token = None

    def __enter__(self) -> "TenantContext":
        self._token = _current_tenant.set(self.tenant)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._token:
            _current_tenant.reset(self._token)

    @property
    def tenant(self) -> Tenant:
        return self._tenant

    @tenant.setter
    def tenant(self, value: Tenant):
        self._tenant = value


class TenantContextManager:
    """Manages tenant contexts for request processing."""

    def __init__(self):
        self._tenants: Dict[str, Tenant] = {}

    def register_tenant(self, tenant: Tenant) -> None:
        """Register a tenant."""
        self._tenants[tenant.id] = tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        """Get tenant by ID."""
        return self._tenants.get(tenant_id)

    def get_tenant_by_domain(self, domain: str) -> Optional[Tenant]:
        """Get tenant by domain."""
        for tenant in self._tenants.values():
            if tenant.domain == domain:
                return tenant
        return None

    def get_tenant_by_subdomain(self, subdomain: str) -> Optional[Tenant]:
        """Get tenant by subdomain."""
        for tenant in self._tenants.values():
            if tenant.subdomain == subdomain:
                return tenant
        return None

    def list_tenants(self, active_only: bool = True) -> list[Tenant]:
        """List all tenants."""
        tenants = list(self._tenants.values())
        if active_only:
            tenants = [t for t in tenants if t.is_active]
        return tenants

    def create_context(self, tenant_id: str) -> Optional[TenantContext]:
        """Create a tenant context."""
        tenant = self.get_tenant(tenant_id)
        if tenant:
            return TenantContext(tenant)
        return None

    def create_context_from_request(self, request) -> Optional[TenantContext]:
        """Create tenant context from HTTP request."""
        # Try to resolve tenant from request
        tenant = None
        
        # Try header
        tenant_id = request.headers.get("X-Tenant-ID")
        if tenant_id:
            tenant = self.get_tenant(tenant_id)
        
        # Try subdomain
        if not tenant:
            host = request.headers.get("Host", "")
            subdomain = host.split(".")[0] if "." in host else ""
            if subdomain and subdomain != "www":
                tenant = self.get_tenant_by_subdomain(subdomain)
        
        # Try domain
        if not tenant:
            host = request.headers.get("Host", "")
            tenant = self.get_tenant_by_domain(host)
        
        if tenant:
            return TenantContext(tenant)
        return None