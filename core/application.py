"""
Application bootstrap for PyFault.

Wires the DI/module system (Container, Injector, PyFaultFactory, decorators)
to the platform HTTP adapter so that ``@controller`` + ``@get``/``@post``/...
declarations become live routes. This closes the core architectural gap where
controllers were declared but never registered with the adapter.
"""

from __future__ import annotations

from typing import Any

from pyfault import __version__
from pyfault.core.factory import PyFaultFactory
from pyfault.core.scanner import MetadataKeys, MetadataScanner
from pyfault.platform.http.adapter import HttpAdapter


class PyFault:
    """
    Assemble a runnable application from a root module.

    Usage::

        app = await PyFault().create(AppModule)
        starlette_app = app.build()   # serve with uvicorn
    """

    def __init__(self, adapter: HttpAdapter | None = None) -> None:
        self.factory = PyFaultFactory()
        self.adapter = adapter or HttpAdapter()
        self._scanner = MetadataScanner()

    async def create(self, root_module: type, config: dict | None = None) -> PyFault:
        """Register providers, instantiate the DI graph, and wire controllers."""
        await self.factory.create(root_module, config)
        self._wire_module(root_module)
        self._add_default_probes()
        return self

    def _wire_module(self, module_class: type, seen: set | None = None) -> None:
        if seen is None:
            seen = set()
        if module_class in seen:
            return
        seen.add(module_class)

        module_config = self._scanner.get_metadata(module_class, MetadataKeys.MODULE) or {}
        for controller in module_config.get('controllers', []):
            self._wire_controller(controller)
        for imported in module_config.get('imports', []):
            self._wire_module(imported, seen)

    def _wire_controller(self, controller_class: type) -> None:
        instance = self.factory.get_provider(controller_class)
        prefix = self._scanner.get_metadata(controller_class, MetadataKeys.PREFIX) or ''
        for attr_name in dir(instance):
            attr = getattr(instance, attr_name)
            routes = getattr(attr, '__routes__', None)
            if callable(attr) and isinstance(routes, list):
                for route in routes:
                    path = self._join_path(prefix, route.get('path', ''))
                    self.adapter.add_route(route['method'], path, attr)
        self.adapter.register_controller(controller_class, instance)

    @staticmethod
    def _join_path(prefix: str, path: str) -> str:
        prefix = (prefix or '').rstrip('/')
        path = path or '/'
        if not prefix:
            return path
        if path.startswith('/'):
            return prefix + path
        return f"{prefix}/{path}"

    def _add_default_probes(self) -> None:
        """Register default liveness probe and metrics endpoint."""
        self.adapter.add_route('GET', '/health', self._health)
        self.adapter.add_route('GET', '/metrics', self._metrics)

    async def _health(self, request: Any = None) -> dict:
        return {"status": "ok", "version": __version__}

    async def _metrics(self, request: Any = None) -> dict:
        # Best-effort metrics exposition; degrades to basic signal if the
        # collector API is unavailable.
        try:
            from pyfault.common.monitoring import MetricsCollector

            collector = MetricsCollector()
            get_metrics = getattr(collector, 'get_metrics', None)
            metrics = get_metrics() if callable(get_metrics) else {}
        except Exception:
            metrics = {}
        return {"up": 1, "version": __version__, "metrics": metrics or {}}

    def build(self) -> Any:
        """Build and return the underlying Starlette application."""
        return self.adapter.build()

    @property
    def app(self) -> Any:
        """Convenience accessor for the underlying ASGI app (e.g. uvicorn)."""
        return self.build()
