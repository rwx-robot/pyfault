"""
Tenant Manager for PyFault framework.
"""

from typing import Any, Optional

from pyfault.common import injectable, module
from pyfault.common.tenant.context import TenantContext, TenantContextManager
from pyfault.common.tenant.resolver import (
    CompositeTenantResolver,
    DomainTenantResolver,
    HeaderTenantResolver,
    SubdomainTenantResolver,
    TenantResolver,
)


@injectable()
class TenantManager:
    """Tenant manager for multi-tenant applications."""

    def __init__(
        self,
        resolvers: Optional[list[TenantResolver]] = None,
        default_tenant_id: str = "default",
    ):
        self.context_manager = TenantContextManager()
        self.resolvers: list[TenantResolver] = resolvers or []
        self.default_tenant_id = default_tenant_id
        self._composite_resolver: Optional[CompositeTenantResolver] = None

    def add_resolver(self, resolver: TenantResolver) -> "TenantManager":
        """Add a tenant resolver."""
        self.resolvers.append(resolver)
        return self

    def set_default_resolvers(self, header_name: str = "X-Tenant-ID", base_domain: str = "") -> "TenantManager":
        """Set up default resolvers."""
        self.resolvers = [
            HeaderTenantResolver(self.context_manager, header_name),
            SubdomainTenantResolver(self.context_manager, base_domain),
            DomainTenantResolver(self.context_manager),
        ]
        # The resolver list was replaced, so any cached composite resolver
        # still points at the old list.
        self._composite_resolver = None
        return self

    def get_composite_resolver(self) -> CompositeTenantResolver:
        """Get composite resolver."""
        if self._composite_resolver is None:
            self._composite_resolver = CompositeTenantResolver(
                self.context_manager, self.resolvers
            )
        return self._composite_resolver

    def resolve_tenant(self, request: Any) -> Optional[str]:
        """Resolve tenant ID from request."""
        resolver = self.get_composite_resolver()
        tenant_id = resolver.resolve(request)

        if not tenant_id:
            tenant_id = self.default_tenant_id

        # Validate tenant exists
        if tenant_id not in self.context_manager._tenants:
            return self.default_tenant_id

        return tenant_id

    def get_context(self, request: Any) -> Optional[TenantContext]:
        """Get tenant context for request."""
        tenant_id = self.resolve_tenant(request) or self.default_tenant_id
        return self.context_manager.create_context(tenant_id)

    def register_tenant(self, tenant: Any) -> "TenantManager":
        """Register a tenant."""
        self.context_manager.register_tenant(tenant)
        return self

    def get_tenant(self, tenant_id: str) -> Any:
        """Get tenant by ID."""
        return self.context_manager.get_tenant(tenant_id)

    def get_context_manager(self) -> TenantContextManager:
        """Get the context manager."""
        return self.context_manager


@module({
    "providers": [TenantManager],
})
class TenantModule:
    """Tenant module for dependency injection."""
    pass
