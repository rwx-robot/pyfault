"""
Plugin Manager for PyFault framework.
"""

import asyncio
from typing import Any, Optional

from pyfault.common.plugins.base import BasePlugin, PluginState
from pyfault.common.plugins.registry import PluginRegistry, get_plugin_registry


class PluginModule:
    """Plugin module configuration."""

    def __init__(
        self,
        plugins: Optional[list[str]] = None,
        config: Optional[dict[str, dict[str, Any]]] = None,
        auto_load: bool = True,
        auto_start: bool = True,
    ):
        self.plugins = plugins or []
        self.config = config or {}
        self.auto_load = auto_load
        self.auto_start = auto_start


class PluginManager:
    """
    Manages plugin lifecycle: load, initialize, start, stop, unload.
    """

    def __init__(self, app: Any = None, registry: Optional[PluginRegistry] = None) -> None:
        self._app = app
        self._registry = registry or get_plugin_registry()
        self._plugins: dict[str, BasePlugin] = {}
        self._config: dict[str, dict[str, Any]] = {}
        self._module: Optional[PluginModule] = None
        self._initialized = False

    def set_app(self, app: Any) -> None:
        """Set the application instance."""
        self._app = app
        for plugin in self._plugins.values():
            plugin.set_app(app)

    def set_container(self, container: Any) -> None:
        """Set the dependency injection container."""
        for plugin in self._plugins.values():
            plugin.set_container(container)

    async def load_module(self, module: PluginModule) -> "PluginManager":
        """Load plugins from a module configuration."""
        self._module = module
        self._config = module.config

        # Register plugin classes first
        for plugin_name in module.plugins:
            if plugin_name not in self._registry._plugin_classes:
                # Try to discover from common locations
                self._registry.discover_plugins("pyfault.plugins")
                self._registry.discover_plugins("plugins")

        if module.auto_load:
            await self.load_plugins(module.plugins)
            await self.initialize_plugins(module.plugins)

        if module.auto_start:
            await self.start_plugins(module.plugins)

        return self

    async def load_plugins(self, plugin_names: Optional[list[str]] = None) -> dict[str, bool]:
        """Load plugins by name."""
        results = {}
        load_order = self._registry.get_load_order()

        # Filter and order plugins
        plugins_to_load = plugin_names or list(self._registry._plugin_classes.keys())
        plugins_to_load = [p for p in load_order if p in plugins_to_load]

        for name in plugins_to_load:
            if name in self._plugins:
                results[name] = True
                continue

            results[name] = await self._load_plugin(name)

        return results

    async def _load_plugin(self, name: str) -> bool:
        """Load a single plugin."""
        # Check dependencies
        missing = self._registry.check_dependencies(name)
        if missing:
            raise RuntimeError(f"Plugin '{name}' missing dependencies: {missing}")

        plugin_class = self._registry.get_plugin_class(name)
        if not plugin_class:
            raise ValueError(f"Plugin '{name}' not registered")

        # Create instance with config
        config = self._config.get(name, {})
        plugin = plugin_class(config)

        # Set app and container
        if self._app:
            plugin.set_app(self._app)

        # Store instance
        self._plugins[name] = plugin
        self._registry._plugins[name] = plugin

        # Call load hook
        try:
            await plugin.load()
        except Exception:
            plugin._state = PluginState.ERROR
            raise

        return True

    async def initialize_plugins(self, plugin_names: Optional[list[str]] = None) -> dict[str, bool]:
        """Initialize loaded plugins."""
        results = {}
        load_order = self._registry.get_load_order()

        plugins_to_init = plugin_names or list(self._plugins.keys())
        plugins_to_init = [p for p in load_order if p in plugins_to_init]

        for name in plugins_to_init:
            plugin = self._plugins.get(name)
            if not plugin or plugin.state != PluginState.LOADED:
                results[name] = False
                continue

            try:
                await plugin.initialize()
                results[name] = True
            except Exception:
                plugin._state = PluginState.ERROR
                results[name] = False

        self._initialized = all(results.values())
        return results

    async def start_plugins(self, plugin_names: Optional[list[str]] = None) -> dict[str, bool]:
        """Start initialized plugins."""
        results = {}
        load_order = self._registry.get_load_order()

        plugins_to_start = plugin_names or list(self._plugins.keys())
        plugins_to_start = [p for p in load_order if p in plugins_to_start]

        for name in plugins_to_start:
            plugin = self._plugins.get(name)
            if not plugin or plugin.state != PluginState.INITIALIZED:
                results[name] = False
                continue

            try:
                await plugin.start()
                results[name] = True
            except Exception:
                plugin._state = PluginState.ERROR
                results[name] = False

        return results

    async def stop_plugins(self, plugin_names: Optional[list[str]] = None) -> dict[str, bool]:
        """Stop running plugins."""
        results = {}
        # Reverse load order for stopping
        load_order = self._registry.get_load_order()
        load_order.reverse()

        plugins_to_stop = plugin_names or list(self._plugins.keys())
        plugins_to_stop = [p for p in load_order if p in plugins_to_stop]

        for name in plugins_to_stop:
            plugin = self._plugins.get(name)
            if not plugin or plugin.state != PluginState.RUNNING:
                results[name] = False
                continue

            try:
                await plugin.stop()
                results[name] = True
            except Exception:
                plugin._state = PluginState.ERROR
                results[name] = False

        return results

    async def unload_plugins(self, plugin_names: Optional[list[str]] = None) -> dict[str, bool]:
        """Unload plugins."""
        results = {}
        # Reverse load order for unloading
        load_order = self._registry.get_load_order()
        load_order.reverse()

        plugins_to_unload = plugin_names or list(self._plugins.keys())
        plugins_to_unload = [p for p in load_order if p in plugins_to_unload]

        for name in plugins_to_unload:
            plugin = self._plugins.get(name)
            if not plugin or plugin.state not in (PluginState.STOPPED, PluginState.ERROR):
                results[name] = False
                continue

            try:
                await plugin.unload()
                results[name] = True

                # Remove from registry
                del self._plugins[name]
                if name in self._registry._plugins:
                    del self._registry._plugins[name]
            except Exception:
                plugin._state = PluginState.ERROR
                results[name] = False

        return results

    def get_plugin(self, name: str) -> Optional[BasePlugin]:
        """Get plugin instance by name."""
        return self._plugins.get(name)

    def get_all_plugins(self) -> dict[str, BasePlugin]:
        """Get all loaded plugins."""
        return self._plugins.copy()

    def get_plugin_state(self, name: str) -> Optional[PluginState]:
        """Get plugin state."""
        plugin = self._plugins.get(name)
        return plugin.state if plugin else None

    def is_plugin_running(self, name: str) -> bool:
        """Check if plugin is running."""
        plugin = self._plugins.get(name)
        return plugin.is_running if plugin else False

    def get_plugin_info(self, name: str) -> Optional[dict[str, Any]]:
        """Get plugin information."""
        plugin = self._plugins.get(name)
        metadata = self._registry.get_metadata(name)

        if not plugin and not metadata:
            return None

        info: dict[str, Any] = {}
        if metadata:
            info["metadata"] = {
                "name": metadata.name,
                "version": metadata.version,
                "description": metadata.description,
                "author": metadata.author,
                "dependencies": metadata.dependencies,
                "provides": metadata.provides,
            }
        if plugin:
            info["state"] = plugin.state.value
            info["config"] = plugin.config

        return info

    async def reload_plugin(self, name: str) -> bool:
        """Reload a plugin (stop, unload, load, initialize, start)."""
        if name not in self._plugins:
            return False

        plugin = self._plugins[name]

        # Stop and unload
        if plugin.state == PluginState.RUNNING:
            await plugin.stop()
        if plugin.state in (PluginState.STOPPED, PluginState.ERROR):
            await plugin.unload()

        # Remove from registry
        del self._plugins[name]
        if name in self._registry._plugins:
            del self._registry._plugins[name]

        # Reload
        config = self._config.get(name, {})
        plugin_class = self._registry.get_plugin_class(name)
        if plugin_class is None:
            return False
        new_plugin = plugin_class(config)

        if self._app:
            new_plugin.set_app(self._app)

        self._plugins[name] = new_plugin
        self._registry._plugins[name] = new_plugin

        await new_plugin.load()
        await new_plugin.initialize()
        await new_plugin.start()

        return True

    def update_config(self, name: str, config: dict[str, Any]) -> bool:
        """Update plugin configuration."""
        plugin = self._plugins.get(name)
        if not plugin:
            return False

        old_config = plugin.config.copy()
        plugin.config.update(config)

        # Notify plugin of config changes
        for key, new_value in config.items():
            old_value = old_config.get(key)
            if old_value != new_value:
                # on_config_change is async, schedule it
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(plugin.on_config_change(key, old_value, new_value))
                    else:
                        asyncio.run(plugin.on_config_change(key, old_value, new_value))
                except RuntimeError:
                    asyncio.run(plugin.on_config_change(key, old_value, new_value))

        # Update stored config
        if name in self._config:
            self._config[name].update(config)
        else:
            self._config[name] = config

        return True

    def get_all_plugins_info(self) -> list[dict[str, Any]]:
        """Get info for all plugins."""
        infos = [self.get_plugin_info(name) for name in self._plugins]
        return [info for info in infos if info is not None]

    async def shutdown(self) -> None:
        """Shutdown all plugins gracefully."""
        await self.stop_plugins()
        await self.unload_plugins()
        self._plugins.clear()
        self._initialized = False


# Global plugin manager
_plugin_manager: Optional[PluginManager] = None


def get_plugin_manager(app: Any = None) -> PluginManager:
    """Get global plugin manager."""
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager(app)
    elif app and _plugin_manager._app is None:
        _plugin_manager.set_app(app)
    return _plugin_manager


def set_plugin_manager(manager: PluginManager) -> None:
    """Set global plugin manager."""
    global _plugin_manager
    _plugin_manager = manager
