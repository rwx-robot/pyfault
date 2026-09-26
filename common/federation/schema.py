"""
Federation Schema utilities for PyFault framework.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLScalarType,
    GraphQLSchema,
    GraphQLString,
    GraphQLUnionType,
    print_schema,
)
from graphql.utilities import value_from_ast_untyped


def _any_scalar_identity(value: Any) -> Any:
    return value


def _any_scalar_parse_literal(node: Any, variables: Optional[dict] = None) -> Any:
    return value_from_ast_untyped(node, variables)


#: Federation ``_Any`` scalar: accepts arbitrary JSON (entity representations).
#: Apollo Federation defines ``_Any`` as a scalar — NOT an input object (an
#: input object cannot carry arbitrary key fields like ``id``).
ANY_SCALAR = GraphQLScalarType(
    name="_Any",
    description="Federation representation object (arbitrary JSON)",
    serialize=_any_scalar_identity,
    parse_value=_any_scalar_identity,
    parse_literal=_any_scalar_parse_literal,
)

#: Root/introspection type names that must not be merged verbatim from
#: service schemas (the federated schema defines its own ``Query`` —
#: including a second ``Query`` instance makes the schema invalid).
_RESERVED_TYPE_NAMES = frozenset(
    {"Query", "Mutation", "Subscription", "_Entity", "_Service", "_Any"}
)


@dataclass
class FederationConfig:
    """Configuration for federation schema."""
    services: list[dict[str, Any]] = field(default_factory=list)
    schema_sdl: str = ""
    enable_federation_directives: bool = True
    enable_entities: bool = True


class FederationSchema:
    """
    Federation schema builder and manager.

    Handles composition of multiple service schemas into a federated schema.
    """

    def __init__(self, config: Optional[FederationConfig] = None):
        self.config = config or FederationConfig()
        self._schema: Optional[GraphQLSchema] = None
        self._service_schemas: dict[str, Any] = {}
        self._entity_types: set[str] = set()
        self._federation_directives: dict[str, Any] = {}

    def add_service(self, name: str, schema: Any, url: str = "") -> "FederationSchema":
        """Add a service schema to the federation."""
        self.config.services.append({
            "name": name,
            "schema": schema,
            "url": url,
        })
        return self

    def set_schema_sdl(self, sdl: str) -> "FederationSchema":
        """Set the combined schema SDL."""
        self.config.schema_sdl = sdl
        return self

    def build(self) -> GraphQLSchema:
        """Build the federated schema."""
        if self._schema:
            return self._schema

        # Collect all types from services (skip root/introspection types:
        # merging a second "Query" instance would make the schema invalid)
        all_types = {}
        entity_types = set()

        for service in self.config.services:
            schema = service.get("schema")
            if schema:
                self._service_schemas[service["name"]] = schema
                for type_name, type_def in schema.type_map.items():
                    if (
                        type_name.startswith("__")
                        or type_name in _RESERVED_TYPE_NAMES
                    ):
                        continue
                    if type_name not in all_types:
                        all_types[type_name] = type_def

                    # Check for @key directive
                    if self._has_federation_key(type_def):
                        entity_types.add(type_name)

        self._entity_types = entity_types

        # Build federation directives
        self._build_federation_directives()

        # Build the schema
        self._schema = self._build_federated_schema(all_types, entity_types)

        return self._schema

    def _has_federation_key(self, type_def: Any) -> bool:
        """Check if type has @key directive."""
        if not hasattr(type_def, "directives"):
            return False
        for directive in type_def.directives:
            if directive.name in ("key", "extends", "external", "requires", "provides"):
                return True
        return False

    def _build_federation_directives(self) -> None:
        """Build federation-specific directives."""
        from pyfault.common.federation.directives import (
            ExtendsDirective,
            ExternalDirective,
            InaccessibleDirective,
            KeyDirective,
            ProvidesDirective,
            RequiresDirective,
            ShareableDirective,
            TagDirective,
        )

        self._federation_directives = {
            "key": KeyDirective,
            "extends": ExtendsDirective,
            "external": ExternalDirective,
            "requires": RequiresDirective,
            "provides": ProvidesDirective,
            "tag": TagDirective,
            "inaccessible": InaccessibleDirective,
            "shareable": ShareableDirective,
        }

    def _build_federated_schema(
        self,
        all_types: dict[str, Any],
        entity_types: set[str]
    ) -> GraphQLSchema:
        """Build the final federated schema."""

        types = list(all_types.values())

        # _Service type (Apollo federation: _service { sdl })
        service_type = GraphQLObjectType(
            name="_Service",
            fields={
                "sdl": GraphQLField(GraphQLString, description="The SDL for this service"),
            },
        )
        types.append(service_type)

        # _Entity union if we have entities (must exist before _entities
        # references it; per federation spec _entities returns [_Entity])
        entity_union: Optional[GraphQLUnionType] = None
        if entity_types:
            entity_union = GraphQLUnionType(
                name="_Entity",
                types=[t for t in all_types.values() if t.name in entity_types],
                resolve_type=lambda obj, info, t: (
                    obj.get("__typename")
                    if isinstance(obj, dict)
                    else getattr(obj, "__typename", None)
                ),
            )
            types.append(entity_union)

        # Federation root fields
        query_fields: dict[str, Any] = {}

        if entity_union is not None:
            query_fields["_entities"] = GraphQLField(
                GraphQLNonNull(GraphQLList(entity_union)),
                args={
                    "representations": GraphQLArgument(
                        GraphQLNonNull(
                            GraphQLList(GraphQLNonNull(ANY_SCALAR))
                        )
                    ),
                },
                description="Fetches entities by their representations",
                # FederationSchema only builds schema structure — entity
                # fetching belongs to the gateway/resolver layer. Return an
                # empty list instead of null (the field is non-null).
                resolve=lambda *_args, **_kwargs: [],
            )

        query_fields["_service"] = GraphQLField(
            service_type,
            description="Returns the SDL for this service",
            resolve=self._resolve_service_field,
        )

        # Migrate service query fields (first service wins on collisions)
        for service in self.config.services:
            schema = service.get("schema")
            if schema is None or schema.query_type is None:
                continue
            for field_name, field_def in schema.query_type.fields.items():
                if field_name not in query_fields:
                    query_fields[field_name] = field_def

        # Create query type
        query_type = GraphQLObjectType(
            name="Query",
            fields=query_fields,
        )

        # Add federation directives: GraphQLSchema defaults to the built-in
        # specified directives; custom federation directives can be added here.
        return GraphQLSchema(
            query=query_type,
            types=types,
        )

    def _resolve_service_field(self, obj: Any, info: Any) -> dict[str, str]:
        """Resolver for the _service root field."""
        if self.config.schema_sdl:
            return {"sdl": self.config.schema_sdl}
        parts = []
        for service in self.config.services:
            name = service.get("name", "")
            sdl = self.get_service_sdl(name)
            if sdl:
                parts.append(f"# Service: {name}\n{sdl}")
        return {"sdl": "\n".join(parts)}

    def get_entity_types(self) -> set[str]:
        """Get all entity type names."""
        return self._entity_types

    def get_service_sdl(self, service_name: str) -> Optional[str]:
        """Get SDL for a specific service (None if unknown / not a schema)."""
        schema = self._service_schemas.get(service_name)
        if schema is None:
            for svc in self.config.services:
                if svc.get("name") == service_name:
                    schema = svc.get("schema")
                    break
        if not isinstance(schema, GraphQLSchema):
            return None
        return print_schema(schema)

    def get_combined_sdl(self) -> str:
        """Get combined SDL for all services."""
        return self.config.schema_sdl


def build_federation_schema(
    services: list[dict[str, Any]],
    schema_sdl: str = "",
) -> GraphQLSchema:
    """
    Build a federation schema from service configurations.

    Args:
        services: List of service configs with name, schema, url
        schema_sdl: Optional pre-combined SDL

    Returns:
        Combined federated GraphQLSchema
    """
    config = FederationConfig(services=services, schema_sdl=schema_sdl)
    federation = FederationSchema(config)
    return federation.build()
