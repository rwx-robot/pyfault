"""
IoC Container for PyFault framework.
"""

import contextvars
from enum import Enum
from typing import Any, Optional


class Scope(Enum):
    """Service scope."""
    SINGLETON = 'singleton'
    TRANSIENT = 'transient'
    REQUEST = 'request'


class Container:
    """
    IoC Container for managing service instances.
    """

    def __init__(self, injector: Optional[Any] = None) -> None:
        self._providers: dict[type, Any] = {}
        self._singletons: dict[type, Any] = {}
        self._scoped: dict[type, Any] = {}
        self._injector = injector
        # Per-request instance cache. Uses a ContextVar so instances are
        # isolated between concurrent requests/tasks (REQUEST scope semantics).
        self._request_instances: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
            'pyfault_request_instances', default=None
        )

    def register(self, token: type, provider: Any, scope: Scope = Scope.SINGLETON) -> None:
        """Register a provider."""
        self._providers[token] = {
            'provider': provider,
            'scope': scope,
        }

    def set_injector(self, injector: Any) -> None:
        """Set injector for dependency injection during resolution."""
        self._injector = injector

    def resolve(self, token: type) -> Any:
        """Resolve a dependency."""
        if token not in self._providers:
            raise ValueError(f"No provider registered for {token.__name__}")

        provider_info = self._providers[token]
        scope = provider_info['scope']
        provider = provider_info['provider']

        if scope == Scope.SINGLETON:
            if token not in self._singletons:
                self._singletons[token] = self._create_instance(provider)
            return self._singletons[token]

        elif scope == Scope.TRANSIENT:
            return self._create_instance(provider)

        elif scope == Scope.REQUEST:
            request_instances = self._request_instances.get()
            if request_instances is None:
                # No active request scope yet — lazily seed one so we never
                # mutate a shared default dict across contexts.
                request_instances = {}
                self._request_instances.set(request_instances)
            if token not in request_instances:
                request_instances[token] = self._create_instance(provider)
            return request_instances[token]

    def _create_instance(self, provider: Any) -> Any:
        """Create an instance of the provider with dependency injection."""
        if self._injector is not None and isinstance(provider, type):
            # Use injector for classes to enable dependency injection
            return self._injector.inject(provider)
        if callable(provider):
            return provider()
        return provider

    def enter_request(self) -> None:
        """
        Begin a new request scope. Subsequent REQUEST-scoped resolves share
        instances until ``exit_request`` is called.
        """
        self._request_instances.set({})

    def exit_request(self) -> None:
        """End the current request scope, discarding its instances."""
        self._request_instances.set({})

    def clear(self) -> None:
        """Clear all providers and instances."""
        self._providers.clear()
        self._singletons.clear()
        self._scoped.clear()
        self._request_instances.set({})

    def has(self, token: type) -> bool:
        """Check if a provider is registered."""
        return token in self._providers
