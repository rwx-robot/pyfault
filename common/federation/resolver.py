"""
Federation Resolver for PyFault framework.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Union
import asyncio


@dataclass
class EntityReference:
    """Reference to a federated entity."""
    __typename: str
    __reference: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        self.__reference = {k: v for k, v in self.__dict__.items() if k != "__typename"}


@dataclass
class FederatedField:
    """Represents a federated field."""
    name: str
    type_name: str
    is_key: bool = False
    is_external: bool = False
    requires: List[str] = field(default_factory=list)
    provides: List[str] = field(default_factory=list)
    resolver: Optional[Callable] = None


class FederatedObjectType:
    """Represents a federated object type."""
    
    def __init__(
        self,
        name: str,
        keys: List[List[str]] = None,
        fields: Dict[str, Any] = None,
        extends: bool = False,
    ):
        self.name = name
        self.keys = keys or []
        self.fields = fields or {}
        self.extends = extends
        self._resolvers: Dict[str, Callable] = {}
    
    def add_field(self, name: str, field_type: str, resolver: Callable = None,
                  external: bool = False, requires: List[str] = None,
                  provides: List[str] = None) -> "FederatedObjectType":
        """Add a field to this type."""
        self.fields[name] = FederatedField(
            name=name,
            type_name=field_type,
            is_external=external,
            requires=requires or [],
            provides=provides or [],
            resolver=resolver,
        )
        if resolver:
            self._resolvers[name] = resolver
        return self
    
    def add_key(self, fields: List[str]) -> "FederatedObjectType":
        """Add a key for this entity."""
        self.keys.append(fields)
        return self
    
    def set_resolver(self, field_name: str, resolver: Callable) -> "FederatedObjectType":
        """Set a resolver for a field."""
        self._resolvers[field_name] = resolver
        if field_name in self.fields:
            self.fields[field_name].resolver = resolver
        return self
    
    def get_resolver(self, field_name: str) -> Optional[Callable]:
        """Get resolver for a field."""
        return self._resolvers.get(field_name)


class FederationResolver:
    """
    Resolver for federated GraphQL queries.
    
    Handles entity resolution across services.
    """
    
    def __init__(self):
        self._types: Dict[str, FederatedObjectType] = {}
        self._resolvers: Dict[str, Callable] = {}
        self._entity_resolvers: Dict[str, Callable] = {}
        self._reference_resolvers: Dict[str, Callable] = {}
    
    def register_type(self, type_obj: FederatedObjectType) -> "FederationResolver":
        """Register a federated object type."""
        self._types[type_obj.name] = type_obj
        return self
    
    def register_resolver(self, type_name: str, field_name: str, resolver: Callable) -> "FederationResolver":
        """Register a field resolver."""
        key = f"{type_name}.{field_name}"
        self._resolvers[key] = resolver
        return self
    
    def register_entity_resolver(self, type_name: str, resolver: Callable) -> "FederationResolver":
        """Register an entity resolver for a type."""
        self._entity_resolvers[type_name] = resolver
        return self
    
    def register_reference_resolver(self, type_name: str, resolver: Callable) -> "FederationResolver":
        """Register a reference resolver for a type."""
        self._reference_resolvers[type_name] = resolver
        return self
    
    def get_type(self, name: str) -> Optional[Any]:
        """Get a registered type."""
        return self._types.get(name)
    
    def get_resolver(self, type_name: str, field_name: str) -> Optional[Callable]:
        """Get a field resolver."""
        return self._resolvers.get(f"{type_name}.{field_name}")
    
    def get_entity_resolver(self, type_name: str) -> Optional[Callable]:
        """Get entity resolver for a type."""
        return self._entity_resolvers.get(type_name)
    
    def get_reference_resolver(self, type_name: str) -> Optional[Callable]:
        """Get reference resolver for a type."""
        return self._reference_resolvers.get(type_name)
    
    async def resolve_entity(self, type_name: str, reference: Dict[str, Any]) -> Optional[Dict]:
        """Resolve an entity by its reference."""
        resolver = self._reference_resolvers.get(type_name)
        if resolver:
            return await resolver(reference)
        return None
    
    async def resolve_field(self, type_name: str, field_name: str, source: Any, 
                          args: Dict[str, Any], context: Any) -> Any:
        """Resolve a field value."""
        resolver = self._resolvers.get(f"{type_name}.{field_name}")
        if resolver:
            return await resolver(source, context)
        return None
    
    def get_type(self, name: str) -> Optional[Any]:
        """Get a registered type."""
        return self._types.get(name)
    
    def get_resolver(self, type_name: str, field_name: str) -> Optional[Callable]:
        """Get a field resolver."""
        return self._resolvers.get(f"{type_name}.{field_name}")
    
    def get_entity_resolver(self, type_name: str) -> Optional[Callable]:
        """Get entity resolver for a type."""
        return self._entity_resolvers.get(type_name)
    
    def get_reference_resolver(self, type_name: str) -> Optional[Callable]:
        """Get reference resolver for a type."""
        return self._reference_resolvers.get(type_name)
    
    async def resolve_entity(self, type_name: str, reference: Dict[str, Any]) -> Optional[Dict]:
        """Resolve an entity by its reference."""
        resolver = self._reference_resolvers.get(type_name)
        if resolver:
            return await resolver(reference)
        return None
    
    async def resolve_field(self, type_name: str, field_name: str, source: Any, 
                          args: Dict[str, Any], context: Any) -> Any:
        """Resolve a field value."""
        resolver = self._resolvers.get(f"{type_name}.{field_name}")
        if resolver:
            return await resolver(source, context)
        return None
    
    def get_type(self, name: str) -> Optional[Any]:
        """Get a registered type."""
        return self._types.get(name)
    
    def get_resolver(self, type_name: str, field_name: str) -> Optional[Callable]:
        """Get a field resolver."""
        return self._resolvers.get(f"{type_name}.{field_name}")
    
    def get_entity_resolver(self, type_name: str) -> Optional[Callable]:
        """Get entity resolver for a type."""
        return self._entity_resolvers.get(type_name)
    
    def get_reference_resolver(self, type_name: str) -> Optional[Callable]:
        """Get reference resolver for a type."""
        return self._reference_resolvers.get(type_name)
    
    async def resolve_entity(self, type_name: str, reference: Dict[str, Any]) -> Optional[Dict]:
        """Resolve an entity by its reference."""
        resolver = self._reference_resolvers.get(type_name)
        if resolver:
            return await resolver(reference)
        return None
    
    async def resolve_field(self, type_name: str, field_name: str, source: Any, 
                          args: Dict[str, Any], context: Any) -> Any:
        """Resolve a field value."""
        resolver = self._resolvers.get(f"{type_name}.{field_name}")
        if resolver:
            return await resolver(source, context)
        return None
    
    def get_type_keys(self, type_name: str) -> List[List[str]]:
        """Get key fields for a type."""
        type_obj = self._types.get(type_name)
        if type_obj:
            return type_obj.keys
        return []


def create_federation_resolver() -> FederationResolver:
    """Create a new federation resolver."""
    return FederationResolver()


# Decorators for defining federated types
def federated_type(name: str, keys: List[List[str]] = None, extends: bool = False):
    """Decorator for creating federated types."""
    def decorator(cls):
        type_obj = FederatedObjectType(
            name=name,
            keys=keys or [],
            extends=extends,
        )
        # Register fields from class
        for attr_name in dir(cls):
            if not attr_name.startswith("_"):
                attr = getattr(cls, attr_name)
                if callable(attr) and hasattr(attr, "_federated_field"):
                    field_info = attr._federated_field
                    type_obj.add_field(
                        name=field_info["name"] or attr_name,
                        field_type=field_info["type"],
                        resolver=attr,
                        external=field_info.get("external", False),
                        requires=field_info.get("requires", []),
                        provides=field_info.get("provides", []),
                    )
                elif callable(attr) and hasattr(attr, "_federated_key"):
                    for key_fields in attr._federated_key:
                        type_obj.add_key(key_fields)
        
        return cls
    return decorator


def federated_field(name: str = None, type: str = None, external: bool = False,
                   requires: List[str] = None, provides: List[str] = None):
    """Decorator for federated fields."""
    def decorator(func):
        func._federated_field = {
            "name": name or func.__name__,
            "type": type or func.__annotations__.get("return", "String"),
            "external": external,
            "requires": requires or [],
            "provides": provides or [],
        }
        return func
    return decorator


def federated_key(*fields: str):
    """Decorator for defining entity keys."""
    def decorator(func):
        func._federated_key = list(fields)
        return func
    return decorator


def federated_requires(*fields: str):
    """Decorator for @requires directive."""
    def decorator(func):
        if not hasattr(func, "_federated_field"):
            func._federated_field = {}
        func._federated_field["requires"] = list(fields)
        return func
    return decorator


def federated_provides(*fields: str):
    """Decorator for @provides directive."""
    def decorator(func):
        if not hasattr(func, "_federated_field"):
            func._federated_field = {}
        func._federated_field["provides"] = list(fields)
        return func
    return decorator


def federated_external(func):
    """Decorator for @external directive."""
    if not hasattr(func, "_federated_field"):
        func._federated_field = {}
    func._federated_field["external"] = True
    return func