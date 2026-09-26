"""
Multi-Tenant Support for PyFault framework.
"""

from pyfault.common.tenant.context import (
    Tenant,
    TenantContext,
    TenantContextManager,
    get_current_tenant,
    set_current_tenant,
)
from pyfault.common.tenant.manager import TenantManager, TenantModule
from pyfault.common.tenant.middleware import TenantMiddleware
from pyfault.common.tenant.resolver import (
    CompositeTenantResolver,
    DomainTenantResolver,
    HeaderTenantResolver,
    PathTenantResolver,
    SubdomainTenantResolver,
    TenantResolver,
)

__all__ = [
    "TenantContext",
    "TenantContextManager",
    "Tenant",
    "get_current_tenant",
    "set_current_tenant",
    "TenantResolver",
    "HeaderTenantResolver",
    "DomainTenantResolver",
    "SubdomainTenantResolver",
    "PathTenantResolver",
    "CompositeTenantResolver",
    "TenantManager",
    "TenantModule",
    "TenantMiddleware",
]
