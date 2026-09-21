"""
Federation Schema utilities for PyFault framework.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from graphql import (
    GraphQLSchema,
    GraphQLObjectType,
    GraphQLField,
    GraphQLArgument,
    GraphQLString,
    GraphQLList,
    GraphQLNonNull,
    GraphQLInt,
    GraphQLBoolean,
    GraphQLFloat,
    GraphQLEnumType,
    GraphQLInputObjectType,
    GraphQLUnionType,
    GraphQLInterfaceType,
    GraphQLDirective,
    GraphQLScalarType,
    specified_scalar_types,
    DirectiveLocation,
)


@dataclass
class FederationConfig:
    """Configuration for federation schema."""
    services: List[Dict[str, Any]] = field(default_factory=list)
    schema_sdl: str = ""
    enable_federation_directives: bool = True
    enable_entities: bool = True


class FederationSchema:
    """
    Federation schema builder and manager.
    
    Handles composition of multiple service schemas into a federated schema.
    """
    
    def __init__(self, config: FederationConfig = None):
        self.config = config or FederationConfig()
        self._schema: Optional[GraphQLSchema] = None
        self._service_schemas: Dict[str, Any] = {}
        self._entity_types: Set[str] = set()
        self._federation_directives: Dict[str, Any] = {}

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
        
        # Collect all types from services
        all_types = {}
        entity_types = set()
        
        for service in self.config.services:
            schema = service.get("schema")
            if schema:
                self._service_schemas[service["name"]] = schema
                for type_name, type_def in schema.type_map.items():
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
    
    def _has_federation_key(self, type_def) -> bool:
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
            KeyDirective,
            ExtendsDirective,
            ExternalDirective,
            RequiresDirective,
            ProvidesDirective,
            TagDirective,
            InaccessibleDirective,
            ShareableDirective,
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
        all_types: Dict[str, Any],
        entity_types: Set[str]
    ) -> GraphQLSchema:
        """Build the final federated schema."""
        
        # Add federation root fields to query
        query_fields = {}
        
        # _entities query
        if entity_types:
            query_fields["_entities"] = GraphQLField(
                GraphQLList(GraphQLNonNull(GraphQLString)),
                args={
                    "representations": GraphQLArgument(
                        GraphQLNonNull(GraphQLList(GraphQLNonNull(GraphQLString)))
                    ),
                },
                description="Fetches entities by their representations",
            )
        
        # _service query
        query_fields["_service"] = GraphQLField(
            GraphQLString,
            description="Returns the SDL for this service",
        )
        
        # Create query type
        query_type = GraphQLObjectType(
            name="Query",
            fields=query_fields,
        )
        
        # Create _Entity union if we have entities
        types = list(all_types.values())
        if self._entity_types:
            entity_union = GraphQLUnionType(
                name="_Entity",
                types=[t for t in all_types.values() if t.name in entity_types],
                resolve_type=lambda obj, info, t: obj.get("__typename"),
            )
            types.append(entity_union)
        
        # Add _Service type
        service_type = GraphQLObjectType(
            name="_Service",
            fields={
                "sdl": GraphQLField(GraphQLString, description="The SDL for this service"),
            },
        )
        types.append(service_type)
        
        # Add federation directives
        directives = list(specified_scalar_types)  # Start with built-in
        # Add custom directives would go here
        
        return GraphQLSchema(
            query=query_type,
            types=types,
            directives=directives,
        )
    
    def get_entity_types(self) -> Set[str]:
        """Get all entity type names."""
        return self._entity_types
    
    def get_service_sdl(self, service_name: str) -> Optional[str]:
        """Get SDL for a specific service."""
        # Generate SDL for a service
        return ""
    
    def get_combined_sdl(self) -> str:
        """Get combined SDL for all services."""
        return self.config.schema_sdl


def build_federation_schema(
    services: List[Dict[str, Any]],
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