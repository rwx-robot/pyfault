"""
Application Factory for PyFault framework.
"""

from typing import Any, Optional

from pyfault.core.container import Container, Scope
from pyfault.core.injector import Injector
from pyfault.core.scanner import MetadataKeys, MetadataScanner


class CircularDependencyError(Exception):
    """Raised when module/dependency graph contains a cycle."""


class PyFaultFactory:
    """
    Application Factory for creating PyFault applications.
    """

    def __init__(self) -> None:
        self.container = Container()
        self.injector = Injector(self.container)
        self.container.set_injector(self.injector)
        self.scanner = MetadataScanner()

    async def create(self, root_module: type, config: Optional[dict] = None) -> "PyFaultFactory":
        """Create an application from a root module."""
        config = config or {}

        # Process module
        self._process_module(root_module)

        return self

    def _process_module(
        self,
        module_class: type,
        stack: Optional[set] = None,
        processed: Optional[set] = None,
    ) -> None:
        """Process a module and its dependencies (cycle-safe).

        ``stack`` tracks the current recursion path (to detect true cycles);
        ``processed`` prevents re-processing shared modules (e.g. diamond imports).
        """
        stack = stack or set()
        processed = processed or set()

        # Check if it's a module
        if not self.scanner.is_module(module_class):
            raise ValueError(f"{module_class.__name__} is not a module")

        # A module already on the current recursion path is a true cycle.
        if module_class in stack:
            raise CircularDependencyError(
                f"Circular module dependency detected at {module_class.__name__}"
            )
        # A module already fully processed (shared import) is fine — skip.
        if module_class in processed:
            return

        stack.add(module_class)
        processed.add(module_class)

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
            self._process_module(imported_module, stack, processed)

        stack.discard(module_class)

    def _register_provider(self, provider: type) -> None:
        """Register a provider in the container."""
        if self.scanner.is_injectable(provider):
            scope = self.scanner.get_scope(provider)
            scope_enum = Scope(scope)
            self.container.register(provider, provider, scope_enum)

    def _register_controller(self, controller: type) -> None:
        """Register a controller as a singleton provider (NestJS-style).

        Controllers are instantiated by the DI container so their constructor
        dependencies are injected just like any other provider.
        """
        self.container.register(controller, controller, Scope.SINGLETON)

    def get_provider(self, token: type) -> Any:
        """Get a provider from the container with dependency injection."""
        return self.container.resolve(token)
