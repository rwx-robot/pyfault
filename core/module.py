"""
Module system for PyFault framework.
"""

from typing import Optional


class Module:
    """
    Module class for organizing application components.
    """

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}
        self.controllers: list[type] = self.config.get('controllers', [])
        self.providers: list[type] = self.config.get('providers', [])
        self.imports: list[type] = self.config.get('imports', [])
        self.exports: list[type] = self.config.get('exports', [])

    def add_controller(self, controller: type) -> None:
        """Add a controller to the module."""
        self.controllers.append(controller)

    def add_provider(self, provider: type) -> None:
        """Add a provider to the module."""
        self.providers.append(provider)

    def add_import(self, module: type) -> None:
        """Import another module."""
        self.imports.append(module)

    def add_export(self, provider: type) -> None:
        """Export a provider."""
        self.exports.append(provider)
