"""
Federation Resolver for PyFault framework.
"""

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, cast


@dataclass
class EntityReference:
    """Reference to a federated entity.

    ``to_dict()`` renders the standard federation representation:
    ``{"__typename": <typename>, **reference}``.
    """

    typename: str
    reference: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"__typename": self.typename, **self.reference}


@dataclass
class FederatedField:
    """Represents a federated field."""
    name: str
    type_name: str
    is_key: bool = False
    is_external: bool = False
    requires: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    resolver: Optional[Callable] = None


class FederatedObjectType:
    """Represents a federated object type."""

    def __init__(
        self,
        name: str,
        keys: Optional[list[list[str]]] = None,
        fields: Optional[dict[str, Any]] = None,
        extends: bool = False,
    ):
        self.name = name
        self.keys = keys or []
        self.fields = fields or {}
        self.extends = extends
        self._resolvers: dict[str, Callable] = {}

    def add_field(self, name: str, field_type: str, resolver: Optional[Callable] = None,
                  external: bool = False, requires: Optional[list[str]] = None,
                  provides: Optional[list[str]] = None) -> "FederatedObjectType":
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

    def add_key(self, fields: list[str]) -> "FederatedObjectType":
        """Add a key for this entity (duplicate keys are ignored)."""
        if fields not in self.keys:
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

    def __init__(self) -> None:
        self._types: dict[str, FederatedObjectType] = {}
        self._resolvers: dict[str, Callable] = {}
        self._entity_resolvers: dict[str, Callable] = {}
        self._reference_resolvers: dict[str, Callable] = {}

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

    async def resolve_entity(self, type_name: str, reference: dict[str, Any]) -> Optional[dict]:
        """Resolve an entity by its reference (sync resolvers supported)."""
        resolver = self._reference_resolvers.get(type_name)
        if resolver:
            resolved: Any = resolver(reference)
            if inspect.isawaitable(resolved):
                resolved = await resolved
            return cast(Optional[dict[str, Any]], resolved)
        return None

    async def resolve_field(self, type_name: str, field_name: str, source: Any,
                          args: dict[str, Any], context: Any) -> Any:
        """Resolve a field value (sync resolvers supported)."""
        resolver = self._resolvers.get(f"{type_name}.{field_name}")
        if resolver:
            result = resolver(source, context)
            if inspect.isawaitable(result):
                result = await result
            return result
        return None

    def get_key_fields(self, type_name: str) -> list[list[str]]:
        """Get key fields for a type."""
        type_obj = self._types.get(type_name)
        if type_obj:
            return type_obj.keys
        return []


def create_federation_resolver() -> FederationResolver:
    """Create a new federation resolver."""
    return FederationResolver()


# Decorators for defining federated types
def federated_type(name: str, keys: Optional[list[list[str]]] = None, extends: bool = False) -> Callable[..., Any]:
    """Decorator for creating federated types.

    The collected ``FederatedObjectType`` is attached to the class as
    ``cls._federation_type`` so it can be inspected or registered.
    """
    def decorator(cls: Any) -> Any:
        type_obj = FederatedObjectType(
            name=name,
            keys=[list(k) for k in (keys or [])],
            extends=extends,
        )
        # Register fields from class
        for attr_name in dir(cls):
            if attr_name.startswith("_"):
                continue
            attr = getattr(cls, attr_name)
            if not callable(attr):
                continue
            if hasattr(attr, "_federated_field"):
                field_info = attr._federated_field
                type_obj.add_field(
                    name=field_info.get("name") or attr_name,
                    field_type=field_info.get("type", "String"),
                    resolver=attr,
                    external=field_info.get("external", False),
                    requires=list(field_info.get("requires") or []),
                    provides=list(field_info.get("provides") or []),
                )
            if hasattr(attr, "_federated_key"):
                raw_keys = attr._federated_key
                if raw_keys and isinstance(raw_keys[0], (list, tuple)):
                    # nested: each element is one composite key
                    for key_fields in raw_keys:
                        type_obj.add_key(list(key_fields))
                else:
                    # flat: one call declares one composite key
                    type_obj.add_key(list(raw_keys))

        cls._federation_type = type_obj
        return cls
    return decorator


# Python return annotations -> GraphQL type names for @federated_field
_PY_TO_GQL = {
    str: "String",
    int: "Int",
    float: "Float",
    bool: "Boolean",
}


def _annotation_to_gql_type(annotation: Any, fallback: str = "String") -> str:
    """Coerce a return annotation into a GraphQL type name."""
    if isinstance(annotation, str):
        return annotation
    if annotation in _PY_TO_GQL:
        return _PY_TO_GQL[annotation]
    name = getattr(annotation, "__name__", None)
    return name or fallback


def federated_field(name: Optional[str] = None, type: Optional[str] = None, external: bool = False,
                   requires: Optional[list[str]] = None, provides: Optional[list[str]] = None) -> Callable[..., Any]:
    """Decorator for federated fields.

    Merges with metadata set by sibling decorators (``@federated_requires``,
    ``@federated_provides``, ``@federated_external``) instead of overwriting
    it, so decorator stacking order does not lose information.
    """
    def decorator(func: Any) -> Any:
        info: dict[str, Any] = dict(getattr(func, "_federated_field", None) or {})
        info["name"] = name or func.__name__
        if type is not None:
            info["type"] = type
        elif "type" not in info:
            info["type"] = _annotation_to_gql_type(
                func.__annotations__.get("return")
            )
        info["external"] = bool(external or info.get("external", False))
        info["requires"] = list(requires if requires is not None else info.get("requires") or [])
        info["provides"] = list(provides if provides is not None else info.get("provides") or [])
        func._federated_field = info
        return func
    return decorator


def federated_key(*fields: str) -> Callable[..., Any]:
    """Decorator for defining entity keys."""
    def decorator(func: Any) -> Any:
        func._federated_key = list(fields)
        return func
    return decorator


def federated_requires(*fields: str) -> Callable[..., Any]:
    """Decorator for @requires directive."""
    def decorator(func: Any) -> Any:
        if not hasattr(func, "_federated_field"):
            func._federated_field = {}
        func._federated_field["requires"] = list(fields)
        return func
    return decorator


def federated_provides(*fields: str) -> Callable[..., Any]:
    """Decorator for @provides directive."""
    def decorator(func: Any) -> Any:
        if not hasattr(func, "_federated_field"):
            func._federated_field = {}
        func._federated_field["provides"] = list(fields)
        return func
    return decorator


def federated_external(func: Any) -> Any:
    """Decorator for @external directive."""
    if not hasattr(func, "_federated_field"):
        func._federated_field = {}
    func._federated_field["external"] = True
    return func
