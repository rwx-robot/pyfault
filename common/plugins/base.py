"""
Base Plugin classes for PyFault framework.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional


class PluginState(Enum):
    """Plugin lifecycle states."""
    UNLOADED = "unloaded"
    LOADING = "loading"
    LOADED = "loaded"
    INITIALIZING = "initializing"
    INITIALIZED = "initialized"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    UNLOADING = "unloading"


@dataclass
class PluginMetadata:
    """Plugin metadata information."""
    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = "MIT"
    homepage: str = ""
    repository: str = ""
    keywords: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    config_schema: dict[str, Any] = field(default_factory=dict)
    min_pyfault_version: str = "1.0.0"
    max_pyfault_version: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


class BasePlugin(ABC):
    """
    Base class for all plugins.

    Plugins extend this class to provide custom functionality.
    """

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config = config or {}
        self.metadata = self._create_metadata()
        self._state = PluginState.UNLOADED
        self._app = None
        self._container = None

    @abstractmethod
    def _create_metadata(self) -> PluginMetadata:
        """Create plugin metadata."""
        pass

    @property
    def name(self) -> str:
        """Plugin name."""
        return self.metadata.name

    @property
    def version(self) -> str:
        """Plugin version."""
        return self.metadata.version

    @property
    def state(self) -> PluginState:
        """Current plugin state."""
        return self._state

    @property
    def is_initialized(self) -> bool:
        """Check if plugin is initialized."""
        return self._state in (PluginState.INITIALIZED, PluginState.STARTING, PluginState.RUNNING)

    @property
    def is_running(self) -> bool:
        """Check if plugin is running."""
        return self._state == PluginState.RUNNING

    def set_app(self, app: Any) -> None:
        """Set the application instance."""
        self._app = app

    def set_container(self, container: Any) -> None:
        """Set the dependency injection container."""
        self._container = container

    def get_config(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        return self.config.get(key, default)

    async def load(self) -> bool:
        """Load the plugin."""
        if self._state != PluginState.UNLOADED:
            return False

        self._state = PluginState.LOADING
        try:
            await self.on_load()
            self._state = PluginState.LOADED
            return True
        except Exception:
            self._state = PluginState.ERROR
            raise

    async def initialize(self) -> bool:
        """Initialize the plugin."""
        if self._state != PluginState.LOADED:
            return False

        self._state = PluginState.INITIALIZING
        try:
            await self.on_initialize()
            self._state = PluginState.INITIALIZED
            return True
        except Exception:
            self._state = PluginState.ERROR
            raise

    async def start(self) -> bool:
        """Start the plugin."""
        if self._state != PluginState.INITIALIZED:
            return False

        self._state = PluginState.STARTING
        try:
            await self.on_start()
            self._state = PluginState.RUNNING
            return True
        except Exception:
            self._state = PluginState.ERROR
            raise

    async def stop(self) -> bool:
        """Stop the plugin."""
        if self._state != PluginState.RUNNING:
            return False

        self._state = PluginState.STOPPING
        try:
            await self.on_stop()
            self._state = PluginState.STOPPED
            return True
        except Exception:
            self._state = PluginState.ERROR
            raise

    async def unload(self) -> bool:
        """Unload the plugin."""
        if self._state not in (PluginState.STOPPED, PluginState.ERROR):
            return False

        self._state = PluginState.UNLOADING
        try:
            await self.on_unload()
            self._state = PluginState.UNLOADED
            return True
        except Exception:
            self._state = PluginState.ERROR
            raise

    # Lifecycle hooks - override in subclasses
    async def on_load(self) -> None:
        """Called when plugin is loaded."""
        pass

    async def on_initialize(self) -> None:
        """Called when plugin is initialized."""
        pass

    async def on_start(self) -> None:
        """Called when plugin starts."""
        pass

    async def on_stop(self) -> None:
        """Called when plugin stops."""
        pass

    async def on_unload(self) -> None:
        """Called when plugin is unloaded."""
        pass

    async def on_config_change(self, key: str, old_value: Any, new_value: Any) -> None:
        """Called when configuration changes."""
        pass

    def __repr__(self) -> str:
        return f"<Plugin {self.name} v{self.version} ({self.state.value})>"
