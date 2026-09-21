"""
Application Factory for PyFault framework.
"""

from typing import Any, Optional

from pyfault.core.container import Container, Scope
from pyfault.core.injector import Injector
from pyfault.core.scanner import MetadataKeys, MetadataScanner


class PyFaultFactory:
    """
    Application Factory for creating PyFault applications.
    """

    def __init__(self):
        self.container = Container()
        self.injector = Injector(self.container)
        self.scanner = MetadataScanner()

    async def create(self, root_module: type, config: Optional[dict] = None):
        """Create an application from a root module."""
        config = config or {}

        # Process module
        self._process_module(root_module)

        return self

    def _process_module(self, module_class: type):
        """Process a module and its dependencies."""
        # Check if it's a module
        if not self.scanner.is_module(module_class):
            raise ValueError(f"{module_class.__name__} is not a module")

        # Get module config
        module_config = self.scanner.get_metadata(module_class, MetadataKeys.MODULE)
        if module_config is None:
            module_config = {}

        # Process providers
        providers = module_config.get('providers', [])
        for provider in providers:
            self._register_provider(provider)

        # Process controllers
        controllers = module_config.get('controllers', [])
        for controller in controllers:
            self._register_controller(controller)

        # Process imports
        imports = module_config.get('imports', [])
        for imported_module in imports:
            self._process_module(imported_module)

    def _register_provider(self, provider: type):
        """Register a provider in the container."""
        if self.scanner.is_injectable(provider):
            scope = self.scanner.get_scope(provider)
            scope_enum = Scope(scope)
            self.container.register(provider, provider, scope_enum)

    def _register_controller(self, controller: type):
        """Register a controller."""
        # Controllers are registered but not instantiated yet
        pass

    def get_provider(self, token: type) -> Any:
        """Get a provider from the container with dependency injection."""
        return self.injector.inject(token)
