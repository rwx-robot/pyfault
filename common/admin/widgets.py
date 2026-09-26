"""
Dashboard Widgets for PyFault Admin UI.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class WidgetConfig:
    """Widget configuration."""
    id: str
    title: str
    type: str
    width: int = 6  # 1-12 grid columns
    height: int = 4  # height units
    position: dict[str, int] = field(default_factory=dict)  # x, y
    refresh_interval: int = 30  # seconds
    config: dict[str, Any] = field(default_factory=dict)


class BaseWidget(ABC):
    """Base class for dashboard widgets."""

    def __init__(self, config: WidgetConfig):
        self.config = config
        self._data: Any = None
        self._last_update: float = 0

    @property
    def id(self) -> str:
        return self.config.id

    @property
    def title(self) -> str:
        return self.config.title

    @property
    def type(self) -> str:
        return self.config.type

    @abstractmethod
    async def fetch_data(self) -> Any:
        """Fetch widget data."""
        pass

    async def update(self) -> None:
        """Update widget data."""
        try:
            self._data = await self.fetch_data()
            self._last_update = time.time()
        except Exception as e:
            self._data = {"error": str(e)}

    def get_data(self) -> Any:
        """Get current data."""
        return self._data

    def get_last_update(self) -> float:
        return self._last_update

    def to_dict(self) -> dict[str, Any]:
        """Convert widget to dict for serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "type": self.type,
            "width": self.config.width,
            "height": self.config.height,
            "position": self.config.position,
            "refresh_interval": self.config.refresh_interval,
            "data": self._data,
            "last_update": self._last_update,
            "config": self.config.config,
        }


class MetricWidget(BaseWidget):
    """Widget for displaying a single metric value."""

    def __init__(self, config: WidgetConfig):
        super().__init__(config)
        self._metric_name = config.config.get("metric_name", "")
        self._format = config.config.get("format", "number")  # number, percent, bytes, duration
        self._thresholds = config.config.get("thresholds", {})

    async def fetch_data(self) -> dict[str, Any]:
        from pyfault.common.plugins import get_plugin_manager
        plugin_manager = get_plugin_manager()
        metrics_plugin = plugin_manager.get_plugin("metrics")

        if not metrics_plugin:
            return {"value": None, "error": "Metrics plugin not available"}

        metrics = metrics_plugin.get_metrics()  # type: ignore[attr-defined]
        value = metrics.get(self._metric_name)

        if value is None:
            return {"value": None, "error": "Metric not found"}

        # Format value
        formatted = self._format_value(value)

        # Check thresholds
        status = "normal"
        if self._thresholds:
            if value >= self._thresholds.get("critical", float('inf')):
                status = "critical"
            elif value >= self._thresholds.get("warning", float('inf')):
                status = "warning"

        return {
            "value": value,
            "formatted": formatted,
            "status": status,
            "unit": self._get_unit(),
            "timestamp": time.time(),
        }

    def _format_value(self, value: float) -> str:
        """Format value based on format type."""
        if self._format == "percent":
            return f"{value:.1f}%"
        elif self._format == "bytes":
            return self._format_bytes(value)
        elif self._format == "duration":
            return self._format_duration(value)
        else:
            return f"{value:.2f}"

    def _format_bytes(self, bytes_val: float) -> str:
        """Format bytes to human readable."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"

    def _format_duration(self, seconds: float) -> str:
        """Format duration to human readable."""
        if seconds < 1:
            return f"{seconds*1000:.1f}ms"
        elif seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            return f"{seconds/60:.1f}m"
        else:
            return f"{seconds/3600:.1f}h"

    def _get_unit(self) -> str:
        if self._format == "percent":
            return "%"
        elif self._format == "bytes":
            return "B"
        elif self._format == "duration":
            return "s"
        return ""


class ChartWidget(BaseWidget):
    """Widget for displaying time-series charts."""

    def __init__(self, config: WidgetConfig):
        super().__init__(config)
        self._metric_names = config.config.get("metrics", [])
        self._chart_type = config.config.get("chart_type", "line")  # line, bar, area
        self._time_range = config.config.get("time_range", 3600)  # seconds
        self._max_points = config.config.get("max_points", 100)

    async def fetch_data(self) -> dict[str, Any]:
        from pyfault.common.plugins import get_plugin_manager
        plugin_manager = get_plugin_manager()
        metrics_plugin = plugin_manager.get_plugin("metrics")

        if not metrics_plugin:
            return {"series": [], "error": "Metrics plugin not available"}

        metrics = metrics_plugin.get_metrics()  # type: ignore[attr-defined]
        series = []

        for metric_name in self._metric_names:
            if metric_name in metrics:
                # In a real implementation, this would fetch historical data
                # For now, generate mock time series
                points = self._generate_mock_series(metrics[metric_name])
                series.append({
                    "name": metric_name,
                    "data": points,
                })

        return {
            "series": series,
            "chart_type": self._chart_type,
            "time_range": self._time_range,
        }

    def _generate_mock_series(self, current_value: float) -> list[dict[str, Any]]:
        """Generate mock time series data."""
        import random
        points = []
        base_time = time.time() - self._time_range

        for i in range(self._max_points):
            t = base_time + (i * self._time_range / self._max_points)
            # Add some variation
            variation = random.uniform(-0.1, 0.1) * current_value
            points.append({
                "timestamp": t,
                "value": max(0, current_value + variation),
            })

        return points


class TableWidget(BaseWidget):
    """Widget for displaying tabular data."""

    def __init__(self, config: WidgetConfig):
        super().__init__(config)
        self._columns = config.config.get("columns", [])
        self._data_source = config.config.get("data_source", "plugins")
        self._sortable = config.config.get("sortable", True)
        self._page_size = config.config.get("page_size", 10)

    async def fetch_data(self) -> dict[str, Any]:
        if self._data_source == "plugins":
            return await self._fetch_plugins()
        elif self._data_source == "tenants":
            return await self._fetch_tenants()
        elif self._data_source == "metrics":
            return await self._fetch_metrics()
        return {"columns": [], "rows": []}

    async def _fetch_plugins(self) -> dict[str, Any]:
        from pyfault.common.plugins import get_plugin_manager
        plugin_manager = get_plugin_manager()

        rows = []
        for name, plugin in plugin_manager.get_all_plugins().items():
            rows.append({
                "name": name,
                "state": plugin.state.value,
                "version": plugin.metadata.version if plugin.metadata else "unknown",
                "description": plugin.metadata.description if plugin.metadata else "",
            })

        return {
            "columns": [
                {"key": "name", "title": "Name", "sortable": True},
                {"key": "state", "title": "State", "sortable": True},
                {"key": "version", "title": "Version", "sortable": True},
                {"key": "description", "title": "Description", "sortable": False},
            ],
            "rows": rows,
            "total": len(rows),
        }

    async def _fetch_tenants(self) -> dict[str, Any]:
        # Would integrate with tenant manager
        return {"columns": [], "rows": [], "total": 0}

    async def _fetch_metrics(self) -> dict[str, Any]:
        from pyfault.common.plugins import get_plugin_manager
        plugin_manager = get_plugin_manager()
        metrics_plugin = plugin_manager.get_plugin("metrics")

        if not metrics_plugin:
            return {"columns": [], "rows": []}

        metrics = metrics_plugin.get_metrics()  # type: ignore[attr-defined]
        rows = []

        for name, data in metrics.items():
            if isinstance(data, dict) and "count" in data:
                rows.append({
                    "metric": name,
                    "count": data["count"],
                    "avg_time": f"{data['total_time']/data['count']:.3f}s" if data['count'] > 0 else "N/A",
                    "errors": data.get("errors", 0),
                })

        return {
            "columns": [
                {"key": "metric", "title": "Metric", "sortable": True},
                {"key": "count", "title": "Count", "sortable": True},
                {"key": "avg_time", "title": "Avg Time", "sortable": True},
                {"key": "errors", "title": "Errors", "sortable": True},
            ],
            "rows": rows,
            "total": len(rows),
        }


class LogWidget(BaseWidget):
    """Widget for displaying logs."""

    def __init__(self, config: WidgetConfig):
        super().__init__(config)
        self._max_lines = config.config.get("max_lines", 100)
        self._level_filter = config.config.get("level_filter", [])
        self._source_filter = config.config.get("source_filter", [])

    async def fetch_data(self) -> dict[str, Any]:
        from pyfault.common.plugins import get_plugin_manager
        plugin_manager = get_plugin_manager()
        audit_plugin = plugin_manager.get_plugin("audit")

        if not audit_plugin:
            return {"logs": [], "error": "Audit plugin not available"}

        logs = audit_plugin.get_logs()  # type: ignore[attr-defined]

        # Apply filters
        if self._level_filter:
            logs = [entry for entry in logs if entry.get("level") in self._level_filter]

        if self._source_filter:
            logs = [entry for entry in logs if entry.get("source") in self._source_filter]

        # Limit lines
        logs = logs[-self._max_lines:]

        return {
            "logs": logs,
            "total": len(logs),
        }


class PluginCardWidget(BaseWidget):
    """Widget for displaying plugin cards."""

    def __init__(self, config: WidgetConfig):
        super().__init__(config)
        self._show_state = config.config.get("show_state", True)
        self._show_actions = config.config.get("show_actions", True)
        self._filter_state = config.config.get("filter_state", [])

    async def fetch_data(self) -> dict[str, Any]:
        from pyfault.common.plugins import get_plugin_manager
        plugin_manager = get_plugin_manager()

        cards = []
        for name, plugin in plugin_manager.get_all_plugins().items():
            if self._filter_state and plugin.state.value not in self._filter_state:
                continue

            cards.append({
                "name": name,
                "display_name": plugin.metadata.name if plugin.metadata else name,
                "version": plugin.metadata.version if plugin.metadata else "unknown",
                "description": plugin.metadata.description if plugin.metadata else "",
                "state": plugin.state.value,
                "author": plugin.metadata.author if plugin.metadata else "",
                "keywords": plugin.metadata.keywords if plugin.metadata else [],
            })

        return {
            "cards": cards,
            "total": len(cards),
        }


def create_widget(config: WidgetConfig) -> BaseWidget:
    """Factory function to create widget by type."""
    widget_types = {
        "metric": MetricWidget,
        "chart": ChartWidget,
        "table": TableWidget,
        "log": LogWidget,
        "plugin_card": PluginCardWidget,
    }

    widget_class = widget_types.get(config.type)
    if not widget_class:
        raise ValueError(f"Unknown widget type: {config.type}")

    return widget_class(config)  # type: ignore[abstract]
