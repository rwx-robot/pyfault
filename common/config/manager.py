"""
Configuration Module for PyFault framework.
"""

import json
import os
from typing import Any, Optional


class ConfigManager:
    """Configuration manager for PyFault."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._config: dict[str, Any] = {}
        self._config_path = config_path

        if config_path:
            self.load(config_path)

    def load(self, path: str) -> None:
        """Load configuration from file."""
        self._config_path = path

        if path.endswith('.json'):
            with open(path) as f:
                self._config = json.load(f)
        elif path.endswith('.py'):
            # Load Python config file
            import importlib.util
            spec = importlib.util.spec_from_file_location("config", path)
            if spec is None or spec.loader is None:
                raise ValueError(f"Cannot load Python config file: {path}")
            config_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config_module)

            for attr in dir(config_module):
                if not attr.startswith('_'):
                    self._config[attr] = getattr(config_module, attr)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value."""
        keys = key.split('.')
        value = self._config

        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default

        return value

    def set(self, key: str, value: Any) -> None:
        """Set configuration value."""
        keys = key.split('.')
        config = self._config

        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]

        config[keys[-1]] = value

    def get_all(self) -> dict[str, Any]:
        """Get all configuration."""
        return self._config.copy()

    def has(self, key: str) -> bool:
        """Check if configuration key exists."""
        return self.get(key) is not None

    def environment(self, key: str, default: Any = None) -> Any:
        """Get environment variable."""
        return os.environ.get(key, default)


class ConfigModule:
    """Config module for dependency injection."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self.manager = ConfigManager(config_path)

    def get_manager(self) -> ConfigManager:
        """Get config manager."""
        return self.manager
