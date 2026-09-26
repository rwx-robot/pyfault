"""
Plugin Registry for PyFault framework.
"""

import importlib
import inspect
import pkgutil
from pathlib import Path
from typing import Optional

from pyfault.common.plugins.base import BasePlugin, PluginMetadata


class PluginRegistry:
    """Central registry for managing plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, BasePlugin] = {}
        self._metadata: dict[str, PluginMetadata] = {}
        self._plugin_classes: dict[str, type[BasePlugin]] = {}
        self._load_order: list[str] = []
        self._dependency_graph: dict[str, set[str]] = {}

    def register(self, plugin_class: type[BasePlugin], name: Optional[str] = None) -> str:
        """Register a plugin class."""
        # Create temporary instance to get metadata
        temp_instance = plugin_class()
        plugin_name = name or temp_instance.name

        if plugin_name in self._plugin_classes:
            raise ValueError(f"Plugin '{plugin_name}' already registered")

        self._plugin_classes[plugin_name] = plugin_class
        self._metadata[plugin_name] = temp_instance.metadata
        self._dependency_graph[plugin_name] = set(temp_instance.metadata.dependencies)

        return plugin_name

    def unregister(self, name: str) -> bool:
        """Unregister a plugin class."""
        if name not in self._plugin_classes:
            return False

        del self._plugin_classes[name]
        del self._metadata[name]
        del self._dependency_graph[name]

        if name in self._load_order:
            self._load_order.remove(name)

        return True

    def get_plugin_class(self, name: str) -> Optional[type[BasePlugin]]:
        """Get plugin class by name."""
        return self._plugin_classes.get(name)

    def get_metadata(self, name: str) -> Optional[PluginMetadata]:
        """Get plugin metadata by name."""
        return self._metadata.get(name)

    def get_instance(self, name: str) -> Optional[BasePlugin]:
        """Get plugin instance by name."""
        return self._plugins.get(name)

    def get_all_plugins(self) -> dict[str, BasePlugin]:
        """Get all plugin instances."""
        return self._plugins.copy()

    def get_all_metadata(self) -> dict[str, PluginMetadata]:
        """Get all plugin metadata."""
        return self._metadata.copy()

    def get_load_order(self) -> list[str]:
        """Get plugin load order (respecting dependencies)."""
        if not self._load_order:
            self._load_order = self._calculate_load_order()
        return self._load_order

    def _calculate_load_order(self) -> list[str]:
        """Calculate load order using topological sort."""
        # Kahn's algorithm for topological sorting
        in_degree = {name: 0 for name in self._dependency_graph}

        for _name, deps in self._dependency_graph.items():
            for dep in deps:
                if dep in in_degree:
                    in_degree[dep] += 1

        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            name = queue.pop(0)
            result.append(name)

            for dep in self._dependency_graph.get(name, set()):
                if dep in in_degree:
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        queue.append(dep)

        if len(result) != len(self._dependency_graph):
            # Circular dependency detected, fallback to alphabetical
            return sorted(self._dependency_graph.keys())

        return result

    def check_dependencies(self, name: str) -> list[str]:
        """Check if all dependencies are satisfied."""
        missing = []
        for dep in self._dependency_graph.get(name, set()):
            if dep not in self._plugins:
                missing.append(dep)
        return missing

    def get_dependents(self, name: str) -> list[str]:
        """Get plugins that depend on this plugin."""
        dependents = []
        for plugin_name, deps in self._dependency_graph.items():
            if name in deps:
                dependents.append(plugin_name)
        return dependents

    def discover_plugins(self, package_path: str, recursive: bool = True) -> list[str]:
        """Discover and register plugins from a package."""
        discovered: list[str] = []

        try:
            package = importlib.import_module(package_path)
        except ImportError:
            return discovered

        # First, check the package's main module (__init__.py)
        for _name, obj in inspect.getmembers(package, inspect.isclass):
            if (issubclass(obj, BasePlugin) and
                obj is not BasePlugin and
                obj.__module__ == package.__name__):
                try:
                    plugin_name = self.register(obj)
                    discovered.append(plugin_name)
                except ValueError:
                    pass  # Already registered

        # Then check submodules
        for _importer, modname, ispkg in pkgutil.iter_modules(
            package.__path__, package.__name__ + "."
        ):
            try:
                module = importlib.import_module(modname)

                # Find plugin classes in module
                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BasePlugin) and
                        obj is not BasePlugin and
                        obj.__module__ == module.__name__):
                        try:
                            plugin_name = self.register(obj)
                            discovered.append(plugin_name)
                        except ValueError:
                            pass  # Already registered

                if recursive and ispkg:
                    discovered.extend(self.discover_plugins(modname, recursive))

            except Exception:
                continue

        return discovered

    def discover_from_path(self, path: str, module_prefix: str = "") -> list[str]:
        """Discover plugins from filesystem path."""
        discovered: list[str] = []
        path_obj = Path(path)

        if not path_obj.exists():
            return discovered

        for py_file in path_obj.rglob("*.py"):
            if py_file.name.startswith("_"):
                continue

            # Convert file path to module name
            relative_path = py_file.relative_to(path_obj.parent)
            module_parts = list(relative_path.with_suffix("").parts)
            module_name = ".".join(module_parts)

            if module_prefix:
                module_name = f"{module_prefix}.{module_name}"

            try:
                module = importlib.import_module(module_name)

                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, BasePlugin) and
                        obj is not BasePlugin and
                        obj.__module__ == module.__name__):
                        try:
                            plugin_name = self.register(obj)
                            discovered.append(plugin_name)
                        except ValueError:
                            pass

            except Exception:
                continue

        return discovered


# Global plugin registry
_plugin_registry: Optional[PluginRegistry] = None


def get_plugin_registry() -> PluginRegistry:
    """Get global plugin registry."""
    global _plugin_registry
    if _plugin_registry is None:
        _plugin_registry = PluginRegistry()
    return _plugin_registry


def set_plugin_registry(registry: PluginRegistry) -> None:
    """Set global plugin registry."""
    global _plugin_registry
    _plugin_registry = registry
