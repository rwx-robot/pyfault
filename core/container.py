"""
IoC Container for PyFault framework.
"""

from enum import Enum
from typing import Any


class Scope(Enum):
    """Service scope."""
    SINGLETON = 'singleton'
    TRANSIENT = 'transient'
    REQUEST = 'request'


class Container:
    """
    IoC Container for managing service instances.
    """

    def __init__(self) -> None:
        self._providers: dict[type, Any] = {}
        self._singletons: dict[type, Any] = {}
        self._scoped: dict[type, Any] = {}

    def register(self, token: type, provider: Any, scope: Scope = Scope.SINGLETON) -> None:
        """Register a provider."""
        self._providers[token] = {
            'provider': provider,
            'scope': scope,
        }

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
            if token not in self._scoped:
                self._scoped[token] = self._create_instance(provider)
            return self._scoped[token]

    def _create_instance(self, provider: Any) -> Any:
        """Create an instance of the provider."""
        if callable(provider):
            return provider()
        return provider

    def clear(self) -> None:
        """Clear all providers and instances."""
        self._providers.clear()
        self._singletons.clear()
        self._scoped.clear()

    def has(self, token: type) -> bool:
        """Check if a provider is registered."""
        return token in self._providers
