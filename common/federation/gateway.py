"""
GraphQL Gateway for PyFault framework - Apollo Federation compatible.
"""

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin

import httpx
from graphql import (
    GraphQLSchema,
    GraphQLObjectType,
    GraphQLInputObjectType,
    GraphQLInputField,
    GraphQLField,
    GraphQLString,
    GraphQLList,
    GraphQLNonNull,
    GraphQLInt,
    GraphQLBoolean,
    graphql,
    parse,
    validate,
    specified_rules,
    GraphQLError,
)
from graphql.execution import execute

from pyfault.common.federation.directives import (
    KeyDirective,
    ExtendsDirective,
    ExternalDirective,
    RequiresDirective,
    ProvidesDirective,
)


@dataclass
class ServiceConfig:
    """Configuration for a federated service."""
    name: str
    url: str
    schema: Optional[GraphQLSchema] = None
    headers: Dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass
class QueryPlan:
    """Execution plan for a federated query."""
    operations: List[Dict[str, Any]]
    services: List[str]


class GraphQLGateway:
    """
    GraphQL Gateway for Apollo Federation.
    
    Composes multiple GraphQL services into a single unified schema.
    """

    def __init__(
        self,
        services: List[ServiceConfig] = None,
        schema: GraphQLSchema = None,
        experimental_entities: bool = True,
    ):
        self.services = services or []
        self._schema = schema
        self._service_clients: Dict[str, httpx.AsyncClient] = {}
        self._experimental_entities = experimental_entities
        self._federation_schema: Optional[GraphQLSchema] = None
        self._entity_resolver: Dict[str, Callable] = {}

    async def initialize(self) -> None:
        """Initialize the gateway by fetching and composing schemas."""
        for service in self.services:
            await self._fetch_service_schema(service)

        # Build federation schema
        self._federation_schema = self._compose_schemas()

    async def _fetch_service_schema(self, service: ServiceConfig) -> None:
        """Fetch schema from a federated service."""
        client = httpx.AsyncClient(
            base_url=service.url,
            headers=service.headers,
            timeout=service.timeout,
        )
        self._service_clients[service.name] = client

        try:
            # Introspection query
            introspection_query = """
            query IntrospectionQuery {
                __schema {
                    types {
                        kind
                        name
                        description
                        fields(includeDeprecated: true) {
                            name
                            description
                            args {
                                name
                                description
                                type {
                                    kind
                                    name
                                    ofType {
                                        kind
                                        name
                                        ofType {
                                            kind
                                            name
                                        }
                                    }
                                }
                            }
                        }
                        inputFields {
                            name
                            description
                            type {
                                kind
                                name
                                ofType {
                                    kind
                                    name
                                }
                            }
                        }
                        interfaces {
                            kind
                            name
                        }
                        enumValues(includeDeprecated: true) {
                            name
                            description
                            isDeprecated
                        }
                        possibleTypes {
                            kind
                            name
                        }
                    }
                    directives {
                        name
                        description
                        locations
                        args {
                            name
                            description
                            type {
                                kind
                                name
                                ofType {
                                    kind
                                    name
                                }
                            }
                        }
                    }
                }
            }
            """

            response = await client.post(
                "/graphql",
                json={"query": introspection_query},
            )
            response.raise_for_status()

            result = response.json()
            # Parse and store schema
            service.schema = self._parse_introspection(result.get("data", {}).get("__schema", {}))

        except Exception as e:
            print(f"Failed to fetch schema for {service.name}: {e}")

    def _parse_introspection(self, schema_data: Dict) -> GraphQLSchema:
        """Parse introspection result into GraphQLSchema."""
        # Simplified - in production use graphql-core's build_client_schema
        return GraphQLSchema()

    def _compose_schemas(self) -> GraphQLSchema:
        """Compose all service schemas into a federated schema."""
        # Build federated schema with _entities, _service queries
        # This is a simplified version

        # Create _Entity union type
        entity_union = GraphQLObjectType(
            name="_Entity",
            fields={
                "__typename": GraphQLField(GraphQLNonNull(GraphQLString)),
            },
        )

        # _Service type
        service_type = GraphQLObjectType(
            name="_Service",
            fields={
                "sdl": GraphQLField(GraphQLString),
            },
        )

        # Root query fields
        query_fields = {}

        # Add _entities field
        query_fields["_entities"] = GraphQLField(
            GraphQLList(GraphQLNonNull(entity_union)),
            args={
                "representations": GraphQLArgument(
                    GraphQLNonNull(
                        GraphQLList(
                            GraphQLNonNull(
                                GraphQLInputObjectType(
                                    name="_Any",
                                    fields={
                                        "__typename": GraphQLInputField(
                                            GraphQLNonNull(GraphQLString)
                                        ),
                                    },
                                )
                            )
                        )
                    )
                ),
            },
            resolve=self._resolve_entities,
        )

        # Add _service field
        query_fields["_service"] = GraphQLField(
            service_type,
            resolve=self._resolve_service,
        )

        # Add service-specific query fields
        for service in self.services:
            if service.schema and service.schema.query_type:
                for field_name, field in service.schema.query_type.fields.items():
                    if field_name not in query_fields:
                        query_fields[field_name] = field

        # Create federated schema
        return GraphQLSchema(
            query=GraphQLObjectType(name="Query", fields=query_fields),
            types=[entity_union, service_type] + [s.schema.query_type for s in self.services if s.schema],
        )

    def _has_key_directive(self, type_def: GraphQLObjectType) -> bool:
        """Check if type has @key directive."""
        # Check type directives
        for directive in getattr(type_def, "directives", []):
            if directive.name == "key":
                return True
        return False

    async def _resolve_entities(self, obj, info, representations: List[Dict]) -> List[Any]:
        """Resolve entity representations across services."""
        results = []

        for rep in representations:
            typename = rep.get("__typename")
            if not typename:
                results.append(None)
                continue

            # Find service that owns this entity
            for service in self.services:
                if service.schema and typename in service.schema.type_map:
                    # Forward to service
                    result = await self._resolve_entity_in_service(service, rep)
                    results.append(result)
                    break
            else:
                results.append(None)

        return results

    async def _resolve_entity_in_service(self, service: ServiceConfig, representation: Dict) -> Any:
        """Resolve a single entity in a specific service."""
        # Build query for entity
        typename = representation.get("__typename")
        fields = list(representation.keys())
        fields.remove("__typename")

        query = f"""
        query GetEntity(\$representations: [_Any!]!) {{
            _entities(representations: \$representations) {{
                ... on {typename} {{
                    {" ".join(fields)}
                }}
            }}
        """

        variables = {"representations": [representation]}

        client = self._service_clients.get(service.name)
        if not client:
            return None

        try:
            response = await client.post(
                "/graphql",
                json={"query": query, "variables": variables},
            )
            response.raise_for_status()
            return response.json().get("data", {}).get("_entities", [None])[0]
        except Exception:
            return None

    async def _resolve_service(self, obj, info) -> Dict[str, str]:
        """Resolve _service query."""
        # Return combined SDL
        sdl_parts = []
        for service in self.services:
            if service.schema:
                # Generate SDL from schema
                sdl_parts.append(f"# Service: {service.name}")

        return {"sdl": "\n".join(sdl_parts)}

    async def execute(self, query: str, variables: Dict = None, context: Any = None) -> Dict[str, Any]:
        """Execute a federated query."""
        if not self._federation_schema:
            await self.initialize()

        # Execute query against federated schema
        result = await graphql(
            self._federation_schema,
            query,
            variable_values=variables,
            context_value=context,
        )

        return {
            "data": result.data,
            "errors": [str(e) for e in result.errors] if result.errors else None,
        }

    async def execute_subscription(self, query: str, variables: Dict = None) -> Any:
        """Execute a federated subscription."""
        # Subscriptions would need special handling for federation
        pass

    async def close(self) -> None:
        """Close all service connections."""
        for client in self._service_clients.values():
            await client.aclose()
        self._service_clients.clear()


def create_federation_gateway(
    services: List[Dict[str, Any]] = None,
    **kwargs
) -> GraphQLGateway:
    """Create a GraphQL Gateway from service configurations."""
    services = []
    for svc in services or []:
        services.append(ServiceConfig(
            name=svc["name"],
            url=svc["url"],
            headers=svc.get("headers", {}),
            timeout=svc.get("timeout", 30.0),
        ))

    gateway = GraphQLGateway(services=services, **kwargs)
    return gateway