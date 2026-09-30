"""
Dependency Injector for PyFault framework.
"""

import inspect
from typing import Any, Callable, get_type_hints


class DependencyResolutionError(Exception):
    """Raised when a dependency cannot be resolved."""


class Injector:
    """
    Dependency Injector for automatic dependency resolution.
    """

    def __init__(self, container: Any) -> None:
        self.container = container
        # Route the container's instantiation back through this injector so that
        # dependency resolution (and circular-dependency detection) is shared.
        self.container.set_injector(self)
        # Tracks the in-progress resolution chain to detect circular DI.
        self._resolving: set = set()

    def inject(self, cls: type) -> Any:
        """Inject dependencies into a class."""
        if cls in self._resolving:
            raise DependencyResolutionError(
                f"Circular dependency detected while resolving {cls.__name__}"
            )
        self._resolving.add(cls)
        try:
            return self._inject(cls)
        finally:
            self._resolving.discard(cls)

    def _inject(self, cls: type) -> Any:
        init_method = getattr(cls, '__init__', None)
        if init_method is None:
            return cls()

        # Resolve type hints (supports forward refs declared as strings)
        try:
            hints = get_type_hints(init_method)
        except Exception:
            hints = getattr(init_method, '__annotations__', {}) or {}

        # Forward-reference strings (e.g. 'ServiceA') cannot always be resolved
        # by get_type_hints — notably when the referenced class is local to a
        # function scope. Fall back to matching the annotation string against the
        # container's known provider type names.
        providers_by_name = {
            getattr(t, '__name__', None): t
            for t in self.container._providers
            if getattr(t, '__name__', None) is not None
        }
        for pname, ptype in list(hints.items()):
            if isinstance(ptype, str):
                resolved = providers_by_name.get(ptype)
                if resolved is not None:
                    hints[pname] = resolved

        # Resolve dependencies that the container knows about
        kwargs = {}
        for param_name, param_type in hints.items():
            if param_name == 'return':
                continue
            # Skip Any / unresolved forward refs — they are not DI-managed types
            if param_type is Any or param_type is inspect.Parameter.empty:
                continue
            if param_type in self.container._providers:
                kwargs[param_name] = self.container.resolve(param_type)

        # Validate that all required (no-default) parameters are satisfied.
        # A required parameter is one with no default and no DI-resolvable type;
        # this includes both annotated-but-unregistered and unannotated params,
        # so the injector fails clearly instead of letting Python raise an opaque
        # TypeError about missing positional arguments.
        sig = inspect.signature(init_method)
        missing = [
            name
            for name, p in sig.parameters.items()
            if name != 'self'
            and name not in kwargs
            and p.default is inspect.Parameter.empty
            and p.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
            and p.annotation is not Any
        ]
        if missing:
            raise DependencyResolutionError(
                f"Cannot resolve constructor for {cls.__name__}: "
                f"required parameter(s) {missing} are not provided and have no registered provider"
            )

        return cls(**kwargs)

    def inject_method(self, method: Callable[..., Any], **kwargs: Any) -> Any:
        """Inject dependencies into a method."""
        hints = {}
        if hasattr(method, '__annotations__'):
            hints = method.__annotations__

        for param_name, param_type in hints.items():
            if param_name == 'return':
                continue
            if param_name not in kwargs and param_type in self.container._providers:
                kwargs[param_name] = self.container.resolve(param_type)

        return method(**kwargs)
