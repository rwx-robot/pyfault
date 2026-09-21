"""
Admin UI for PyFault framework - Web-based administration dashboard.
"""

from pyfault.common.admin.dashboard import AdminDashboard, AdminConfig, AdminUser, create_admin_app
from pyfault.common.admin.api import AdminAPIRouter
from pyfault.common.admin.websocket import AdminWebSocketHandler
from pyfault.common.admin.marketplace import PluginMarketplace
from pyfault.common.admin.widgets import (
    MetricWidget,
    ChartWidget,
    TableWidget,
    LogWidget,
    PluginCardWidget,
    WidgetConfig,
)

__all__ = [
    "AdminDashboard",
    "AdminConfig",
    "AdminUser",
    "create_admin_app",
    "AdminAPIRouter",
    "AdminWebSocketHandler",
    "PluginMarketplace",
    "MetricWidget",
    "ChartWidget",
    "TableWidget",
    "LogWidget",
    "PluginCardWidget",
    "WidgetConfig",
]