"""
OpenAPI Decorators for PyFault framework.
"""

from functools import wraps
from types import UnionType
from typing import Any, Callable, Optional, Union

from pyfault.common.openapi.schema import (
    Components,
    Info,
    OpenAPISchema,
    Operation,
    Parameter,
    PathItem,
    RequestBody,
    Response,
    Server,
)

# Global OpenAPI document
_openapi_doc: Optional[OpenAPISchema] = None


def init_openapi(
    title: str,
    version: str,
    description: str = "",
    servers: Optional[list[dict[str, str]]] = None,
    contact: Optional[dict[str, str]] = None,
    license: Optional[dict[str, str]] = None,
) -> OpenAPISchema:
    """Initialize OpenAPI document."""
    global _openapi_doc

    info = Info(
        title=title,
        version=version,
        description=description,
        contact=contact,
        license=license,
    )

    server_list = []
    if servers:
        for s in servers:
            server_list.append(Server(url=s.get("url", ""), description=s.get("description", "")))

    _openapi_doc = OpenAPISchema(info=info, servers=server_list)
    return _openapi_doc


def get_openapi_doc() -> Optional[OpenAPISchema]:
    """Get current OpenAPI document."""
    return _openapi_doc


def api(
    path: str,
    method: str,
    summary: str = "",
    description: str = "",
    tags: Optional[list[str]] = None,
    parameters: Optional[list[Parameter]] = None,
    request_body: Optional[RequestBody] = None,
    responses: Optional[dict[str, Response]] = None,
    security: Optional[list[dict[str, list[str]]]] = None,
    deprecated: bool = False,
    operation_id: str = "",
) -> Callable[..., Any]:
    """
    Decorator for documenting an API endpoint.

    Usage:
        @api("/users", "GET", summary="List users", tags=["Users"])
        @get("/users")
        def list_users(self):
            ...
    """
    def decorator(func: Callable) -> Callable:
        global _openapi_doc

        if _openapi_doc is None:
            # Auto-initialize with defaults
            init_openapi("PyFault API", "1.0.0")

        doc = _openapi_doc
        if doc is None:
            raise RuntimeError("OpenAPI document is not initialized")

        # Create operation
        operation = Operation(
            tags=tags or [],
            summary=summary,
            description=description,
            operation_id=operation_id or f"{func.__module__}.{func.__name__}",
            parameters=parameters or [],
            request_body=request_body,
            responses=responses or {
                "200": Response(description="Successful response"),
                "400": Response(description="Bad request"),
                "500": Response(description="Internal server error"),
            },
            security=security or [],
            deprecated=deprecated,
        )

        # Create or update path item
        if path not in doc.paths:
            doc.paths[path] = PathItem()

        path_item = doc.paths[path]
        setattr(path_item, method.lower(), operation)

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)
        return wrapper
    return decorator


def operation(
    summary: str = "",
    description: str = "",
    tags: Optional[list[str]] = None,
    parameters: Optional[list[Parameter]] = None,
    request_body: Optional[RequestBody] = None,
    responses: Optional[dict[str, Response]] = None,
    security: Optional[list[dict[str, list[str]]]] = None,
    deprecated: bool = False,
    operation_id: str = "",
) -> Callable[..., Any]:
    """
    Decorator for adding OpenAPI operation metadata to a route handler.
    Can be used alongside @get, @post, etc.

    Usage:
        @get("/users/{id}")
        @operation(summary="Get user by ID", tags=["Users"])
        def get_user(self, id: str):
            ...
    """
    def decorator(func: Callable) -> Callable:
        # Store metadata on the function
        func_any: Any = func
        if not hasattr(func_any, '__openapi__'):
            func_any.__openapi__ = {}
        metadata: dict[str, Any] = func_any.__openapi__

        metadata.update({
            "summary": summary,
            "description": description,
            "tags": tags or [],
            "parameters": parameters or [],
            "request_body": request_body,
            "responses": responses or {
                "200": Response(description="Successful response"),
            },
            "security": security or [],
            "deprecated": deprecated,
            "operation_id": operation_id,
        })
        return func
    return decorator


def schema(name: str = "", example: Any = None) -> Callable[..., Any]:
    """
    Decorator for defining OpenAPI schema for a data class.

    Usage:
        @schema("User")
        class User:
            id: str
            name: str
            email: str
    """
    def decorator(cls: type) -> type:
        global _openapi_doc

        if _openapi_doc is None:
            init_openapi("PyFault API", "1.0.0")

        doc = _openapi_doc
        if doc is None:
            raise RuntimeError("OpenAPI document is not initialized")

        if doc.components is None:
            doc.components = Components()

        # Generate schema from class annotations
        schema_dict = _generate_schema_from_class(cls, example)
        schema_name = name or cls.__name__
        doc.components.schemas[schema_name] = schema_dict

        # Store schema reference on class
        cls_any: Any = cls
        cls_any.__openapi_schema__ = schema_name
        return cls
    return decorator


def _generate_schema_from_class(cls: type, example: Any = None) -> dict[str, Any]:
    """Generate OpenAPI schema from Python class with type annotations."""
    properties = {}
    required = []

    annotations = getattr(cls, '__annotations__', {})

    for field_name, field_type in annotations.items():
        prop_schema = _type_to_schema(field_type)
        properties[field_name] = prop_schema

        # Check if required (no default value)
        if not hasattr(cls, field_name):
            required.append(field_name)

    schema = {
        "type": "object",
        "properties": properties,
    }

    if required:
        schema["required"] = required

    if example:
        schema["example"] = example

    return schema


def _type_to_schema(py_type: Any) -> dict[str, Any]:
    """Convert Python type to OpenAPI schema."""
    # Handle basic types
    if py_type is str:
        return {"type": "string"}
    elif py_type is int:
        return {"type": "integer"}
    elif py_type is float:
        return {"type": "number"}
    elif py_type is bool:
        return {"type": "boolean"}
    elif py_type is list:
        return {"type": "array", "items": {}}
    elif py_type is dict:
        return {"type": "object"}

    # Handle Optional/Union: typing.Optional[T] has __origin__ == Union
    # (NOT Optional), and PEP 604 unions (T | None) are types.UnionType.
    origin = getattr(py_type, "__origin__", None)
    if origin is Union or isinstance(py_type, UnionType):
        non_none = [a for a in py_type.__args__ if a is not type(None)]
        if len(non_none) == 1:
            return _type_to_schema(non_none[0])
        return {"anyOf": [_type_to_schema(a) for a in non_none]}
    elif origin is list:
        # bare typing.List has __origin__ == list but no __args__
        args = getattr(py_type, "__args__", None)
        if args:
            return {"type": "array", "items": _type_to_schema(args[0])}
        return {"type": "array", "items": {}}
    elif origin is dict:
        return {"type": "object"}

    # Handle custom classes with annotations
    if hasattr(py_type, '__annotations__'):
        return {"$ref": f"#/components/schemas/{py_type.__name__}"}

    return {"type": "string"}


def generate_openapi_json() -> str:
    """Generate OpenAPI document as JSON string."""
    import json
    doc = get_openapi_doc()
    if doc is None:
        return "{}"
    return json.dumps(doc.to_dict(), indent=2, ensure_ascii=False)


def generate_openapi_yaml() -> str:
    """Generate OpenAPI document as YAML string."""
    try:
        import yaml
        doc = get_openapi_doc()
        if doc is None:
            return ""
        dumped: str = yaml.dump(doc.to_dict(), allow_unicode=True, sort_keys=False)
        return dumped
    except ImportError:
        return "# PyYAML not installed. Install with: pip install pyyaml\n" + generate_openapi_json()
