"""
Admin Dashboard for PyFault framework.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from pyfault import __version__
from pyfault.common.plugins import get_plugin_manager
from pyfault.common.tenant import get_current_tenant


@dataclass
class AdminUser:
    """Admin user."""
    id: str
    username: str
    email: str
    roles: list[str] = field(default_factory=list)
    last_login: str = ""
    is_active: bool = True


@dataclass
class AdminConfig:
    """Admin dashboard configuration."""
    title: str = "PyFault Admin"
    theme: str = "dark"
    refresh_interval: int = 30
    enable_marketplace: bool = True
    enable_tenant_management: bool = True
    enable_plugin_management: bool = True
    custom_css: str = ""
    custom_js: str = ""


class AdminDashboard:
    """Main admin dashboard."""

    def __init__(self, config: Optional[AdminConfig] = None) -> None:
        self.config = config or AdminConfig()
        self._widgets: dict[str, Any] = {}
        self._routes: list[dict[str, Any]] = []

    def register_widget(self, name: str, widget: Any) -> None:
        """Register a dashboard widget."""
        self._widgets[name] = widget

    def get_widget(self, name: str) -> Optional[Any]:
        """Get a widget by name."""
        return self._widgets.get(name)

    def get_all_widgets(self) -> dict[str, Any]:
        """Get all widgets."""
        return self._widgets.copy()

    def get_system_overview(self) -> dict[str, Any]:
        """Get system overview data."""
        plugin_manager = get_plugin_manager()

        plugins_info = {}
        for name, plugin in plugin_manager.get_all_plugins().items():
            plugins_info[name] = {
                "name": name,
                "state": plugin.state.value,
                "version": plugin.metadata.version if plugin.metadata else "unknown",
            }

        tenant = get_current_tenant()

        return {
            "timestamp": time.time(),
            "version": __version__,
            "plugins": plugins_info,
            "plugin_count": len(plugins_info),
            "running_plugins": sum(1 for p in plugins_info.values() if p["state"] == "running"),
            "tenant": tenant.id if tenant else "default",
            "uptime": time.time() - self._start_time if hasattr(self, '_start_time') else 0,
        }

    def get_plugin_details(self, plugin_name: str) -> Optional[dict[str, Any]]:
        """Get detailed plugin information."""
        plugin_manager = get_plugin_manager()
        plugin = plugin_manager.get_plugin(plugin_name)
        if not plugin:
            return None

        return plugin_manager.get_plugin_info(plugin_name)

    def get_tenant_list(self) -> list[dict[str, Any]]:
        """Get list of tenants."""
        # This would integrate with tenant manager
        return []

    def start(self) -> None:
        """Start dashboard."""
        self._start_time = time.time()

    def stop(self) -> None:
        """Stop dashboard."""
        pass


class AdminAPIRouter:
    """Admin API routes."""

    def __init__(self, dashboard: AdminDashboard):
        self.dashboard = dashboard
        self._routes = self._build_routes()

    def _build_routes(self) -> list[dict[str, Any]]:
        """Build API routes."""
        return [
            {"path": "/api/admin/overview", "method": "GET", "handler": self.get_overview},
            {"path": "/api/admin/plugins", "method": "GET", "handler": self.get_plugins},
            {"path": "/api/admin/plugins/{name}", "method": "GET", "handler": self.get_plugin},
            {"path": "/api/admin/plugins/{name}/start", "method": "POST", "handler": self.start_plugin},
            {"path": "/api/admin/plugins/{name}/stop", "method": "POST", "handler": self.stop_plugin},
            {"path": "/api/admin/plugins/{name}/restart", "method": "POST", "handler": self.restart_plugin},
            {"path": "/api/admin/tenants", "method": "GET", "handler": self.get_tenants},
            {"path": "/api/admin/tenants/{id}", "method": "GET", "handler": self.get_tenant},
            {"path": "/api/admin/metrics", "method": "GET", "handler": self.get_metrics},
            {"path": "/api/admin/health", "method": "GET", "handler": self.get_health},
            {"path": "/api/admin/config", "method": "GET", "handler": self.get_config},
            {"path": "/api/admin/config", "method": "PUT", "handler": self.update_config},
        ]

    async def get_overview(self, request: Any) -> dict[str, Any]:
        """Get system overview."""
        return self.dashboard.get_system_overview()

    async def get_plugins(self, request: Any) -> dict[str, Any]:
        """Get all plugins."""
        plugin_manager = get_plugin_manager()
        plugins = {}
        for name, _plugin in plugin_manager.get_all_plugins().items():
            plugins[name] = plugin_manager.get_plugin_info(name)
        return {"plugins": plugins}

    async def get_plugin(self, request: Any) -> dict[str, Any] | tuple[dict[str, Any], int]:
        """Get plugin details."""
        plugin_name = request.path_params.get("name")
        details = self.dashboard.get_plugin_details(plugin_name)
        if not details:
            return {"error": "Plugin not found"}, 404
        return details

    async def start_plugin(
        self, request: Any
    ) -> dict[str, Any] | tuple[dict[str, Any], int]:
        """Start a plugin."""
        plugin_name = request.path_params.get("name")
        plugin_manager = get_plugin_manager()
        results = await plugin_manager.start_plugins([plugin_name])
        if not results.get(plugin_name):
            return {"error": "Failed to start plugin", "plugin": plugin_name}, 400
        return {"success": True, "plugin": plugin_name}

    async def stop_plugin(
        self, request: Any
    ) -> dict[str, Any] | tuple[dict[str, Any], int]:
        """Stop a plugin."""
        plugin_name = request.path_params.get("name")
        plugin_manager = get_plugin_manager()
        results = await plugin_manager.stop_plugins([plugin_name])
        if not results.get(plugin_name):
            return {"error": "Failed to stop plugin", "plugin": plugin_name}, 400
        return {"success": True, "plugin": plugin_name}

    async def restart_plugin(
        self, request: Any
    ) -> dict[str, Any] | tuple[dict[str, Any], int]:
        """Restart a plugin."""
        plugin_name = request.path_params.get("name")
        plugin_manager = get_plugin_manager()
        if not await plugin_manager.reload_plugin(plugin_name):
            return {"error": "Failed to restart plugin", "plugin": plugin_name}, 400
        return {"success": True, "plugin": plugin_name}

    async def get_tenants(self, request: Any) -> dict[str, Any]:
        """Get all tenants."""
        return {"tenants": self.dashboard.get_tenant_list()}

    async def get_tenant(self, request: Any) -> dict[str, Any]:
        """Get tenant details."""
        tenant_id = request.path_params.get("id")
        # Implementation would fetch from tenant manager
        return {"tenant": tenant_id}

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

    async def get_health(self, request: Any) -> dict[str, Any]:
        """Get health status."""
        plugin_manager = get_plugin_manager()
        health_plugin = plugin_manager.get_plugin("healthcheck")

        if health_plugin:
            checker = getattr(health_plugin, "run_checks", None)
            if checker is not None:
                health: dict[str, Any] = await checker()
                return health
        return {"status": "unknown"}

    async def get_config(self, request: Any) -> dict[str, Any]:
        """Get admin config."""
        return {
            "title": self.dashboard.config.title,
            "theme": self.dashboard.config.theme,
            "refresh_interval": self.dashboard.config.refresh_interval,
        }

    async def update_config(self, request: Any) -> dict[str, Any]:
        """Update admin config."""
        # Implementation would update config
        return {"success": True}

    def get_routes(self) -> list[dict[str, Any]]:
        """Get all routes."""
        return self._routes


async def create_admin_app(
    config: Optional[AdminConfig] = None,
    app_factory: Optional[Callable] = None,
) -> Any:
    """Create admin dashboard application."""
    config = config or AdminConfig()
    dashboard = AdminDashboard(config)

    if app_factory:
        _app = await app_factory()
        # Integrate dashboard routes
        # This would integrate with the main app
        pass

    dashboard.start()
    return dashboard
