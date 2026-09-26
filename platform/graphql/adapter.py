"""
GraphQL Adapter for PyFault framework.
"""

import inspect
from types import SimpleNamespace
from typing import Any, Callable

from graphql import (
    GraphQLArgument,
    GraphQLBoolean,
    GraphQLField,
    GraphQLFloat,
    GraphQLInt,
    GraphQLList,
    GraphQLNonNull,
    GraphQLObjectType,
    GraphQLSchema,
    GraphQLString,
    graphql,
)
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


class GraphQLAdapter:
    """
    GraphQL Adapter for handling GraphQL queries.
    """

    def __init__(self) -> None:
        self._queries: dict[str, dict] = {}
        self._mutations: dict[str, dict] = {}
        self._types: dict[str, GraphQLObjectType] = {}
        self._type_definitions: dict[str, dict] = {}
        self._resolved_types: dict[str, GraphQLObjectType] = {}

    def register_query(self, name: str, resolver: Callable, return_type: Any = 'String') -> None:
        """Register a query resolver."""
        self._queries[name] = {
            'resolver': resolver,
            'return_type': return_type,
        }

    def register_mutation(self, name: str, resolver: Callable, return_type: Any = 'String') -> None:
        """Register a mutation resolver."""
        self._mutations[name] = {
            'resolver': resolver,
            'return_type': return_type,
        }

    def Query(self, name: str, return_type: Any = 'String') -> Callable[..., Any]:
        """Decorator for registering a query."""
        def decorator(func: Callable) -> Any:
            self.register_query(name, func, return_type)
            return func
        return decorator

    def Mutation(self, name: str, return_type: Any = 'String') -> Callable[..., Any]:
        """Decorator for registering a mutation."""
        def decorator(func: Callable) -> Any:
            self.register_mutation(name, func, return_type)
            return func
        return decorator

    def _get_mock_obj_and_info(self) -> tuple[SimpleNamespace, SimpleNamespace]:
        """Create mock obj and info for resolver introspection."""
        mock_obj = SimpleNamespace()
        mock_info = SimpleNamespace()
        mock_info.variable_values = {}
        return mock_obj, mock_info

    def _infer_type_from_value(self, value: Any, type_name: str) -> Any:
        """Infer GraphQL type from a Python value."""
        if value is None:
            return GraphQLString
        elif isinstance(value, bool):
            return GraphQLBoolean
        elif isinstance(value, int):
            return GraphQLInt
        elif isinstance(value, float):
            return GraphQLFloat
        elif isinstance(value, str):
            return GraphQLString
        elif isinstance(value, list):
            if len(value) > 0:
                item_type = self._infer_type_from_value(value[0], f"{type_name}Item")
                return GraphQLList(item_type)
            return GraphQLList(GraphQLString)
        elif isinstance(value, dict):
            # Create object type from dict
            return self._create_object_type_from_dict(type_name, value)
        else:
            return GraphQLString

    def _create_object_type_from_dict(self, type_name: str, value: dict) -> GraphQLObjectType:
        """Create GraphQLObjectType from a dictionary."""
        if type_name in self._resolved_types:
            return self._resolved_types[type_name]

        fields = {}
        for key, val in value.items():
            field_type = self._infer_type_from_value(val, f"{type_name}{key.capitalize()}")
            fields[key] = GraphQLField(field_type)

        obj_type = GraphQLObjectType(name=type_name, fields=fields)
        self._resolved_types[type_name] = obj_type
        return obj_type

    def _get_return_type(self, resolver: Callable, return_type_hint: Any, field_name: str) -> Any:
        """Get the GraphQL return type for a resolver."""
        # If return_type_hint is a string (type name), check if it's a registered type
        if isinstance(return_type_hint, str):
            if return_type_hint in self._resolved_types:
                return self._resolved_types[return_type_hint]
            if return_type_hint in self._type_definitions:
                # Build the type from definition
                return self._create_object_type_from_dict(return_type_hint, self._type_definitions[return_type_hint])
            # Try to infer from resolver execution (even for default 'String')
            try:
                mock_obj, mock_info = self._get_mock_obj_and_info()
                sig = inspect.signature(resolver)
                kwargs = {}
                for param_name, param in sig.parameters.items():
                    if param_name in ('obj', 'info', 'self'):
                        continue
                    if param.default != inspect.Parameter.empty:
                        kwargs[param_name] = param.default
                    else:
                        # Provide default test values for required params
                        if param.annotation is int:
                            kwargs[param_name] = 1
                        elif param.annotation is float:
                            kwargs[param_name] = 1.0
                        elif param.annotation is bool:
                            kwargs[param_name] = True
                        else:
                            kwargs[param_name] = "test"
                result = resolver(mock_obj, mock_info, **kwargs)
                return self._infer_type_from_value(result, f"{field_name}Return")
            except Exception:
                pass
            return GraphQLString
        elif isinstance(return_type_hint, dict):
            # Inline type definition
            return self._create_object_type_from_dict(f"{field_name}Return", return_type_hint)
        elif hasattr(return_type_hint, '_meta') or hasattr(return_type_hint, '__annotations__'):
            # Python class with annotations (dataclass, pydantic, etc.)
            return self._create_object_type_from_class(return_type_hint, field_name)
        else:
            return GraphQLString

    def _create_object_type_from_class(self, cls: type, type_name: str) -> GraphQLObjectType:
        """Create GraphQLObjectType from a Python class with annotations."""
        if type_name in self._resolved_types:
            return self._resolved_types[type_name]

        fields = {}
        annotations = getattr(cls, '__annotations__', {})
        for field_name, field_type in annotations.items():
            gql_type: Any = GraphQLString
            if field_type is int:
                gql_type = GraphQLInt
            elif field_type is float:
                gql_type = GraphQLFloat
            elif field_type is bool:
                gql_type = GraphQLBoolean
            elif field_type is list:
                gql_type = GraphQLList(GraphQLString)
            fields[field_name] = GraphQLField(gql_type)

        obj_type = GraphQLObjectType(name=type_name, fields=fields)
        self._resolved_types[type_name] = obj_type
        return obj_type

    def _build_schema(self) -> GraphQLSchema:
        """Build GraphQL schema."""
        # Build query type
        query_fields = {}
        for name, info in self._queries.items():
            resolver = info['resolver']
            return_type_hint = info['return_type']

            # Get resolver arguments (skip obj and info)
            sig = inspect.signature(resolver)
            args = {}
            for param_name, param in sig.parameters.items():
                if param_name in ('obj', 'info', 'self'):
                    continue
                # Map Python type to GraphQL type
                gql_type: Any = GraphQLString
                if param.annotation != inspect.Parameter.empty:
                    if param.annotation is int:
                        gql_type = GraphQLInt
                    elif param.annotation is float:
                        gql_type = GraphQLFloat
                    elif param.annotation is bool:
                        gql_type = GraphQLBoolean
                # Check if required (no default value)
                if param.default == inspect.Parameter.empty:
                    gql_type = GraphQLNonNull(gql_type)
                args[param_name] = GraphQLArgument(gql_type)

            # Determine return type
            return_type = self._get_return_type(resolver, return_type_hint, name)

            query_fields[name] = GraphQLField(
                return_type,
                args=args,
                resolve=lambda obj, info, resolver=resolver, **kwargs: resolver(obj, info, **kwargs)
            )

        # Ensure Query type has at least one field (GraphQL spec requirement)
        if not query_fields:
            query_fields['_'] = GraphQLField(GraphQLString, resolve=lambda obj, info: "")

        query_type = GraphQLObjectType(
            name='Query',
            fields=query_fields
        )

        # Build mutation type
        mutation_fields = {}
        for name, info in self._mutations.items():
            resolver = info['resolver']
            return_type_hint = info['return_type']

            # Get resolver arguments (skip obj and info)
            sig = inspect.signature(resolver)
            args = {}
            for param_name, param in sig.parameters.items():
                if param_name in ('obj', 'info', 'self'):
                    continue
                # Map Python type to GraphQL type
                gql_type = GraphQLString
                if param.annotation != inspect.Parameter.empty:
                    if param.annotation is int:
                        gql_type = GraphQLInt
                    elif param.annotation is float:
                        gql_type = GraphQLFloat
                    elif param.annotation is bool:
                        gql_type = GraphQLBoolean
                # Check if required (no default value)
                if param.default == inspect.Parameter.empty:
                    gql_type = GraphQLNonNull(gql_type)
                args[param_name] = GraphQLArgument(gql_type)

            # Determine return type
            return_type = self._get_return_type(resolver, return_type_hint, name)

            mutation_fields[name] = GraphQLField(
                return_type,
                args=args,
                resolve=lambda obj, info, resolver=resolver, **kwargs: resolver(obj, info, **kwargs)
            )

        mutation_type = GraphQLObjectType(
            name='Mutation',
            fields=mutation_fields
        ) if mutation_fields else None

        return GraphQLSchema(
            query=query_type,
            mutation=mutation_type
        )

    def build_routes(self) -> list[Route]:
        """Build GraphQL routes."""
        schema = self._build_schema()

        async def graphql_endpoint(request: Request) -> JSONResponse:
            try:
                body = await request.json()
                query = body.get('query', '')
                variables = body.get('variables', {})

                result = await graphql(schema, query, variable_values=variables)

                return JSONResponse({
                    'data': result.data,
                    'errors': [str(e) for e in result.errors] if result.errors else None
                })
            except Exception as e:
                return JSONResponse({'error': str(e)}, status_code=400)

        return [Route('/graphql', endpoint=graphql_endpoint, methods=['POST'])]
