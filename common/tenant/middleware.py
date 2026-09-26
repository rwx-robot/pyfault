"""
Tenant Middleware for PyFault framework.
"""

from collections.abc import Awaitable
from typing import Any, Callable, Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from pyfault.common.tenant.manager import TenantManager


class TenantMiddleware(BaseHTTPMiddleware):
    """Middleware for tenant resolution and context management."""

    def __init__(
        self,
        app: Any,
        tenant_manager: TenantManager,
        excluded_paths: Optional[list[str]] = None,
    ) -> None:
        super().__init__(app)
        self.tenant_manager = tenant_manager
        self.excluded_paths = excluded_paths or ["/health", "/health/live", "/health/ready", "/metrics"]

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        # Skip tenant resolution for excluded paths
        if request.url.path in self.excluded_paths:
            return await call_next(request)

        # Resolve tenant and create context
        _tenant_id = self.tenant_manager.resolve_tenant(request)
        context = self.tenant_manager.get_context(request)

        # Set tenant context for request
        request.state.tenant = context.tenant if context else None
        request.state.tenant_id = context.tenant.id if context else None

        # Set context in contextvars
        token = context.__enter__() if context else None

        try:
            response = await call_next(request)

            # Add tenant headers to response
            if context:
                response.headers["X-Tenant-ID"] = context.tenant.id
                response.headers["X-Tenant-Name"] = context.tenant.name

            return response
        finally:
            if context is not None and token is not None:
                context.__exit__(None, None, None)


def create_tenant_middleware(
    tenant_manager: TenantManager,
    excluded_paths: Optional[list[str]] = None,
) -> type:
    """Create a tenant middleware class with the given tenant manager."""

    class _TenantMiddleware(BaseHTTPMiddleware):
        def __init__(self, app: Any) -> None:
            super().__init__(app)
            self.tenant_manager = tenant_manager
            self.excluded_paths = excluded_paths or ["/health", "/health/live", "/health/ready", "/metrics"]

        async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
            if request.url.path in self.excluded_paths:
                return await call_next(request)

            context = self.tenant_manager.get_context(request)

            request.state.tenant = context.tenant if context else None
            request.state.tenant_id = context.tenant.id if context else None

            token = context.__enter__() if context else None

            try:
                response = await call_next(request)

                if context:
                    response.headers["X-Tenant-ID"] = context.tenant.id
                    response.headers["X-Tenant-Name"] = context.tenant.name

                return response
            finally:
                if context is not None and token is not None:
                    context.__exit__(None, None, None)

    return _TenantMiddleware
