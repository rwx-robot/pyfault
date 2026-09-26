"""
Tenant Resolvers for PyFault framework.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional

from pyfault.common.tenant.context import TenantContextManager


class TenantResolver(ABC):
    """Abstract base class for tenant resolvers."""

    def __init__(self, tenant_manager: TenantContextManager):
        self.tenant_manager = tenant_manager

    @abstractmethod
    def resolve(self, request: Any) -> Optional[str]:
        """Resolve tenant ID from request."""
        pass


class HeaderTenantResolver(TenantResolver):
    """Resolve tenant from HTTP header."""

    def __init__(self, tenant_manager: TenantContextManager, header_name: str = "X-Tenant-ID"):
        super().__init__(tenant_manager)
        self.header_name = header_name

    def resolve(self, request: Any) -> Optional[str]:
        value: Optional[str] = request.headers.get(self.header_name)
        return value


class DomainTenantResolver(TenantResolver):
    """Resolve tenant from domain."""

    def __init__(self, tenant_manager: TenantContextManager):
        super().__init__(tenant_manager)

    def resolve(self, request: Any) -> Optional[str]:
        host = request.headers.get("Host", "")
        # Remove port if present
        domain = host.split(":")[0]
        tenant = self.tenant_manager.get_tenant_by_domain(domain)
        return tenant.id if tenant else None


class SubdomainTenantResolver(TenantResolver):
    """Resolve tenant from subdomain."""

    def __init__(self, tenant_manager: TenantContextManager, base_domain: str = ""):
        super().__init__(tenant_manager)
        self.base_domain = base_domain

    def resolve(self, request: Any) -> Optional[str]:
        host = request.headers.get("Host", "")
        domain = host.split(":")[0]

        if self.base_domain and not domain.endswith(self.base_domain):
            return None

        # Extract subdomain
        parts = domain.split(".")
        if len(parts) < 2:
            return None

        subdomain = parts[0]
        if subdomain == "www":
            return None

        tenant = self.tenant_manager.get_tenant_by_subdomain(subdomain)
        return tenant.id if tenant else None


class PathTenantResolver(TenantResolver):
    """Resolve tenant from URL path prefix."""

    def __init__(self, tenant_manager: TenantContextManager, path_prefix: str = "/tenant/"):
        super().__init__(tenant_manager)
        self.path_prefix = path_prefix

    def resolve(self, request: Any) -> Optional[str]:
        path = request.url.path if hasattr(request, "url") else request.path

        if not path.startswith(self.path_prefix):
            return None

        # Extract tenant ID from path
        remaining = path[len(self.path_prefix):]
        tenant_id = remaining.split("/")[0]
        return tenant_id if tenant_id else None


class CompositeTenantResolver(TenantResolver):
    """Composite resolver that tries multiple resolvers in order."""

    def __init__(self, tenant_manager: TenantContextManager, resolvers: list[TenantResolver]):
        super().__init__(tenant_manager)
        self.resolvers = resolvers

    def resolve(self, request: Any) -> Optional[str]:
        for resolver in self.resolvers:
            tenant_id = resolver.resolve(request)
            if tenant_id:
                return tenant_id
        return None
