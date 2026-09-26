"""
Dependency Injector for PyFault framework.
"""

from typing import Any, Callable


class Injector:
    """
    Dependency Injector for automatic dependency resolution.
    """

    def __init__(self, container: Any) -> None:
        self.container = container

    def inject(self, cls: type) -> Any:
        """Inject dependencies into a class."""
        # Get constructor parameters
        init_method = getattr(cls, '__init__', None)
        if init_method is None:
            return cls()

        # Get type hints
        hints = {}
        if hasattr(init_method, '__annotations__'):
            hints = init_method.__annotations__

        # Resolve dependencies
        kwargs = {}
        for param_name, param_type in hints.items():
            if param_name == 'return':
                continue
            if param_type in self.container._providers:
                kwargs[param_name] = self.container.resolve(param_type)

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
