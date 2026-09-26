"""
GraphQL Gateway for PyFault framework - Apollo Federation compatible.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, cast

import httpx
from graphql import (
    GraphQLArgument,
    GraphQLField,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    GraphQLUnionType,
    get_introspection_query,
    graphql,
    print_schema,
)
from graphql.utilities import build_client_schema

from pyfault.common.federation.schema import ANY_SCALAR


@dataclass
class ServiceConfig:
    """Configuration for a federated service."""
    name: str
    url: str
    schema: Optional[GraphQLSchema] = None
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass
class QueryPlan:
    """Execution plan for a federated query."""
    operations: list[dict[str, Any]]
    services: list[str]


class GraphQLGateway:
    """
    GraphQL Gateway for Apollo Federation.

    Composes multiple GraphQL services into a single unified schema.
    """

    def __init__(
        self,
        services: Optional[list[ServiceConfig]] = None,
        schema: Optional[GraphQLSchema] = None,
        experimental_entities: bool = True,
    ):
        self.services = services or []
        self._schema = schema
        self._service_clients: dict[str, httpx.AsyncClient] = {}
        self._experimental_entities = experimental_entities
        self._federation_schema: Optional[GraphQLSchema] = None
        self._entity_resolver: dict[str, Callable] = {}

    async def initialize(self) -> None:
        """Initialize the gateway by fetching and composing schemas."""
        for service in self.services:
            if service.schema is None:
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
            # Canonical introspection query (complete enough for
            # build_client_schema — a hand-rolled subset is not)
            introspection_query = get_introspection_query()

            response = await client.post(
                "/graphql",
                json={"query": introspection_query},
            )
            response.raise_for_status()

            result = response.json()
            # Parse and store schema
            service.schema = self._parse_introspection(
                result.get("data") or {}
            )

        except Exception as e:
            print(f"Failed to fetch schema for {service.name}: {e}")

    def _parse_introspection(self, introspection: dict) -> GraphQLSchema:
        """Parse introspection result into GraphQLSchema."""
        return build_client_schema(cast(Any, introspection))

    def _compose_schemas(self) -> GraphQLSchema:
        """Compose all service schemas into a federated schema."""
        # Collect entity-candidate object types from service schemas.
        # Apollo's _Entity is a UNION of entity types — defining it as an
        # object type (or giving it an explicit __typename field) makes the
        # whole schema fail validation, breaking every query.
        entity_members: dict[str, GraphQLObjectType] = {}
        for service in self.services:
            if not service.schema:
                continue
            for type_name, type_def in service.schema.type_map.items():
                if (
                    type_name.startswith("__")
                    or type_name
                    in ("Query", "Mutation", "Subscription", "_Entity", "_Service", "_Any")
                ):
                    continue
                if isinstance(type_def, GraphQLObjectType) and type_name not in entity_members:
                    entity_members[type_name] = type_def

        # _Service type
        service_type = GraphQLObjectType(
            name="_Service",
            fields={
                "sdl": GraphQLField(GraphQLString),
            },
        )

        # Root query fields
        query_fields = {}
        types: list[Any] = [service_type]

        entity_union: Optional[GraphQLUnionType] = None
        if entity_members and self._experimental_entities:
            entity_union = GraphQLUnionType(
                name="_Entity",
                types=list(entity_members.values()),
                resolve_type=lambda obj, info, t: (
                    obj.get("__typename")
                    if isinstance(obj, dict)
                    else getattr(obj, "__typename", None)
                ),
            )
            types.append(entity_union)

            # Add _entities field (_Any is a scalar per the federation spec:
            # representations carry arbitrary key fields such as ``id``.
            # Items are nullable: an unresolvable entity yields null, not an
            # error for the whole list — matching Apollo's [_Entity]!
            query_fields["_entities"] = GraphQLField(
                GraphQLNonNull(GraphQLList(entity_union)),
                args={
                    "representations": GraphQLArgument(
                        GraphQLNonNull(
                            GraphQLList(GraphQLNonNull(ANY_SCALAR))
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

        # Create federated schema. Service ``Query`` types are deliberately
        # NOT added to ``types``: their fields are migrated above, and a
        # second type named "Query" would invalidate the schema.
        return GraphQLSchema(
            query=GraphQLObjectType(name="Query", fields=query_fields),
            types=types,
        )

    def _has_key_directive(self, type_def: GraphQLObjectType) -> bool:
        """Check if type has @key directive."""
        # Check type directives
        for directive in getattr(type_def, "directives", []):
            if directive.name == "key":
                return True
        return False

    async def _resolve_entities(self, obj: Any, info: Any, representations: list[dict]) -> list[Any]:
        """Resolve entity representations across services."""
        results: list[Any] = []

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

    async def _resolve_entity_in_service(self, service: ServiceConfig, representation: dict) -> Any:
        """Resolve a single entity in a specific service."""
        # Build query for entity. Both typename and field keys come from
        # client input — they are interpolated into the query string, so
        # they must be valid GraphQL identifiers (injection guard).
        typename = representation.get("__typename")
        if not isinstance(typename, str) or not typename.isidentifier():
            return None

        fields = [k for k in representation if k != "__typename"]
        if not fields or not all(f.isidentifier() for f in fields):
            return None

        query = f"""
        query GetEntity($representations: [_Any!]!) {{
            _entities(representations: $representations) {{
                ... on {typename} {{
                    {" ".join(fields)}
                }}
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

    async def _resolve_service(self, obj: Any, info: Any) -> dict[str, str]:
        """Resolve _service query."""
        # Return combined SDL of all service schemas
        sdl_parts = []
        for service in self.services:
            if service.schema:
                try:
                    sdl_parts.append(
                        f"# Service: {service.name}\n{print_schema(service.schema)}"
                    )
                except Exception:
                    sdl_parts.append(f"# Service: {service.name}")

        return {"sdl": "\n".join(sdl_parts)}

    async def execute(self, query: str, variables: Optional[dict] = None, context: Any = None) -> dict[str, Any]:
        """Execute a federated query."""
        if not self._federation_schema:
            await self.initialize()
        schema = self._federation_schema
        if schema is None:
            raise RuntimeError("Federation schema not initialized")

        # Execute query against federated schema
        result = await graphql(
            schema,
            query,
            variable_values=variables,
            context_value=context,
        )

        errors = None
        if result.errors:
            errors = []
            for exc in result.errors:
                item: dict[str, Any] = {"message": str(exc)}
                if exc.locations:
                    item["locations"] = [
                        {"line": loc.line, "column": loc.column}
                        for loc in exc.locations
                    ]
                if exc.path is not None:
                    item["path"] = list(exc.path)
                errors.append(item)

        return {
            "data": result.data,
            "errors": errors,
        }

    async def execute_subscription(self, query: str, variables: Optional[dict] = None) -> Any:
        """Execute a federated subscription.

        Subscriptions are not supported by this gateway — raising instead of
        silently returning ``None`` makes the limitation explicit.
        """
        raise NotImplementedError(
            "GraphQL subscriptions are not supported by GraphQLGateway"
        )

    async def close(self) -> None:
        """Close all service connections."""
        for client in self._service_clients.values():
            await client.aclose()
        self._service_clients.clear()


def create_federation_gateway(
    services: Optional[list[dict[str, Any]]] = None,
    **kwargs: Any
) -> GraphQLGateway:
    """Create a GraphQL Gateway from service configurations."""
    service_configs = [
        ServiceConfig(
            name=svc["name"],
            url=svc["url"],
            schema=svc.get("schema"),
            headers=svc.get("headers", {}),
            timeout=svc.get("timeout", 30.0),
        )
        for svc in services or []
    ]

    gateway = GraphQLGateway(services=service_configs, **kwargs)
    return gateway
