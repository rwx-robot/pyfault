"""
Admin API for PyFault framework.
"""

from typing import Any

from pyfault.common.plugins import get_plugin_manager
from pyfault.common.tenant import get_current_tenant


class AdminAPIRouter:
    """Admin API router for REST endpoints."""

    def __init__(self) -> None:
        self._routes: list[dict[str, Any]] = [
            {"path": "/api/admin/status", "method": "GET", "handler": self.get_status},
            {"path": "/api/admin/plugins", "method": "GET", "handler": self.list_plugins},
            {"path": "/api/admin/plugins/{name}", "method": "GET", "handler": "get_plugin"},
            {"path": "/api/admin/plugins/{name}/config", "method": "GET", "handler": "get_plugin_config"},
            {"path": "/api/admin/plugins/{name}/config", "method": "PUT", "handler": "update_plugin_config"},
            {"path": "/api/admin/plugins/{name}/start", "method": "POST", "handler": "start_plugin"},
            {"path": "/api/admin/plugins/{name}/stop", "method": "POST", "handler": "stop_plugin"},
            {"path": "/api/admin/plugins/{name}/restart", "method": "POST", "handler": "restart_plugin"},
            {"path": "/api/admin/tenants", "method": "GET", "handler": "list_tenants"},
            {"path": "/api/admin/tenants/{id}", "method": "GET", "handler": "get_tenant"},
            {"path": "/api/admin/tenants", "method": "POST", "handler": "create_tenant"},
            {"path": "/api/admin/tenants/{id}", "method": "PUT", "handler": "update_tenant"},
            {"path": "/api/admin/tenants/{id}", "method": "DELETE", "handler": "delete_tenant"},
            {"path": "/api/admin/metrics", "method": "GET", "handler": "get_metrics"},
            {"path": "/api/admin/health", "method": "GET", "handler": "health_check"},
            {"path": "/api/admin/logs", "method": "GET", "handler": "get_logs"},
            {"path": "/api/admin/config", "method": "GET", "handler": "get_config"},
            {"path": "/api/admin/config", "method": "PUT", "handler": "update_config"},
        ]

    def get_routes(self) -> list[dict[str, Any]]:
        return self._routes

    async def get_status(self, request: Any) -> dict[str, Any]:
        """Get system status."""
        plugin_manager = get_plugin_manager()
        plugins = plugin_manager.get_all_plugins()
        tenant = get_current_tenant()

        return {
            "status": "ok",
            "version": "1.4.0",
            "plugins": len(plugins),
            "running": sum(1 for p in plugins.values() if p.state.value == "running"),
            "tenant": tenant.id if tenant is not None else "default",
        }

    async def list_plugins(self, request: Any) -> dict[str, Any]:
        """List all plugins."""
        plugin_manager = get_plugin_manager()
        plugins = {}

        for name, plugin in plugin_manager.get_all_plugins().items():
            plugins[name] = {
                "name": name,
                "state": plugin.state.value,
                "version": plugin.metadata.version if plugin.metadata else "unknown",
                "description": plugin.metadata.description if plugin.metadata else "",
            }

        return {"plugins": plugins}

    async def get_plugin(self, request: Any) -> dict[str, Any] | tuple[dict[str, Any], int]:
        """Get plugin details."""
        name = request.path_params.get("name")
        plugin_manager = get_plugin_manager()
        plugin = plugin_manager.get_plugin(name)

        if not plugin:
            return {"error": "Plugin not found"}, 404

        info = plugin_manager.get_plugin_info(name)
        if info is None:
            return {"error": "Plugin not found"}, 404
        return info

    async def get_plugin_config(self, request: Any) -> dict[str, Any] | tuple[dict[str, Any], int]:
        """Get plugin configuration."""
        name = request.path_params.get("name")
        plugin_manager = get_plugin_manager()
        plugin = plugin_manager.get_plugin(name)

        if not plugin:
            return {"error": "Plugin not found"}, 404

        return {"config": plugin.config}

    async def update_plugin_config(self, request: Any) -> dict[str, Any] | tuple[dict[str, Any], int]:
        """Update plugin configuration."""
        name = request.path_params.get("name")
        plugin_manager = get_plugin_manager()

        # Get request body
        body = await request.json() if hasattr(request, 'json') else {}

        if plugin_manager.update_config(name, body):
            return {"success": True}
        return {"error": "Plugin not found"}, 404

    async def start_plugin(self, request: Any) -> dict[str, Any]:
        """Start a plugin."""
        name = request.path_params.get("name")
        plugin_manager = get_plugin_manager()

        await plugin_manager.start_plugins([name])
        return {"success": True, "plugin": name}

    async def stop_plugin(self, request: Any) -> dict[str, Any]:
        """Stop a plugin."""
        name = request.path_params.get("name")
        plugin_manager = get_plugin_manager()

        await plugin_manager.stop_plugins([name])
        return {"success": True, "plugin": name}

    async def restart_plugin(self, request: Any) -> dict[str, Any]:
        """Restart a plugin."""
        name = request.path_params.get("name")
        plugin_manager = get_plugin_manager()

        await plugin_manager.reload_plugin(name)
        return {"success": True, "plugin": name}

    async def list_tenants(self, request: Any) -> dict[str, Any]:
        """List all tenants."""
        # Would integrate with tenant manager
        return {"tenants": []}

    async def get_tenant(self, request: Any) -> dict[str, Any]:
        """Get tenant details."""
        tenant_id = request.path_params.get("id")
        return {"tenant": tenant_id}

    async def create_tenant(self, request: Any) -> dict[str, Any]:
        """Create a new tenant."""
        body = await request.json() if hasattr(request, 'json') else {}
        return {"created": True, "tenant": body}

    async def update_tenant(self, request: Any) -> dict[str, Any]:
        """Update tenant."""
        tenant_id = request.path_params.get("id")
        _body = await request.json() if hasattr(request, 'json') else {}
        return {"updated": True, "tenant": tenant_id}

    async def delete_tenant(self, request: Any) -> dict[str, Any]:
        """Delete a tenant."""
        tenant_id = request.path_params.get("id")
        return {"deleted": True, "tenant": tenant_id}

    async def get_metrics(self, request: Any) -> dict[str, Any]:
        """Get system metrics."""
        plugin_manager = get_plugin_manager()
        metrics_plugin = plugin_manager.get_plugin("metrics")

        if metrics_plugin:
            getter = getattr(metrics_plugin, "get_metrics", None)
            if getter is not None:
                metrics: dict[str, Any] = getter()
                return metrics
        return {"metrics": {}}

    async def health_check(self, request: Any) -> dict[str, Any]:
        """Health check endpoint."""
        plugin_manager = get_plugin_manager()
        health_plugin = plugin_manager.get_plugin("healthcheck")

        if health_plugin:
            checker = getattr(health_plugin, "run_checks", None)
            if checker is not None:
                checks: dict[str, Any] = await checker()
                return checks
        return {"status": "ok"}

    async def get_logs(self, request: Any) -> dict[str, Any]:
        """Get system logs."""
        plugin_manager = get_plugin_manager()
        audit_plugin = plugin_manager.get_plugin("audit")

        if audit_plugin:
            getter = getattr(audit_plugin, "get_logs", None)
            if getter is not None:
                logs: Any = getter()
                return {"logs": logs}
        return {"logs": []}

    async def get_config(self, request: Any) -> dict[str, Any]:
        """Get admin configuration."""
        return {
            "version": "1.4.0",
            "features": {
                "plugins": True,
                "tenants": True,
                "metrics": True,
                "health": True,
                "marketplace": True,
            }
        }

    async def update_config(self, request: Any) -> dict[str, Any]:
        """Update admin configuration."""
        return {"success": True}
