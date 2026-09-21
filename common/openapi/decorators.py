"""
OpenAPI Decorators for PyFault framework.
"""

from functools import wraps
from typing import Any, Callable, Dict, List, Optional

from pyfault.common.openapi.schema import (
    Info, Server, Operation, Parameter, RequestBody, Response, 
    PathItem, Components, SecurityScheme, OpenAPISchema
)


# Global OpenAPI document
_openapi_doc: Optional[OpenAPISchema] = None


def init_openapi(
    title: str,
    version: str,
    description: str = "",
    servers: List[Dict[str, str]] = None,
    contact: Dict[str, str] = None,
    license: Dict[str, str] = None,
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
    tags: List[str] = None,
    parameters: List[Parameter] = None,
    request_body: Optional[RequestBody] = None,
    responses: Dict[str, Response] = None,
    security: List[Dict[str, List[str]]] = None,
    deprecated: bool = False,
    operation_id: str = "",
):
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
        if path not in _openapi_doc.paths:
            _openapi_doc.paths[path] = PathItem()
        
        path_item = _openapi_doc.paths[path]
        setattr(path_item, method.lower(), operation)
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator


def operation(
    summary: str = "",
    description: str = "",
    tags: List[str] = None,
    parameters: List[Parameter] = None,
    request_body: Optional[RequestBody] = None,
    responses: Dict[str, Response] = None,
    security: List[Dict[str, List[str]]] = None,
    deprecated: bool = False,
    operation_id: str = "",
):
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
        if not hasattr(func, '__openapi__'):
            func.__openapi__ = {}
        
        func.__openapi__.update({
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


def schema(name: str = "", example: Any = None):
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
        
        if _openapi_doc.components is None:
            _openapi_doc.components = Components()
        
        # Generate schema from class annotations
        schema_dict = _generate_schema_from_class(cls, example)
        schema_name = name or cls.__name__
        _openapi_doc.components.schemas[schema_name] = schema_dict
        
        # Store schema reference on class
        cls.__openapi_schema__ = schema_name
        return cls
    return decorator


def _generate_schema_from_class(cls: type, example: Any = None) -> Dict[str, Any]:
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


def _type_to_schema(py_type: Any) -> Dict[str, Any]:
    """Convert Python type to OpenAPI schema."""
    # Handle basic types
    if py_type == str:
        return {"type": "string"}
    elif py_type == int:
        return {"type": "integer"}
    elif py_type == float:
        return {"type": "number"}
    elif py_type == bool:
        return {"type": "boolean"}
    elif py_type == list:
        return {"type": "array", "items": {}}
    elif py_type == dict:
        return {"type": "object"}
    
    # Handle Optional
    if hasattr(py_type, '__origin__'):
        from typing import Optional, List, Dict as TypingDict
        origin = py_type.__origin__
        
        if origin is Optional:
            # Optional[T] = Union[T, None]
            args = py_type.__args__
            non_none = [a for a in args if a is not type(None)]
            if non_none:
                return _type_to_schema(non_none[0])
        elif origin is List:
            args = py_type.__args__
            if args:
                return {"type": "array", "items": _type_to_schema(args[0])}
            return {"type": "array", "items": {}}
        elif origin is TypingDict:
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
        return yaml.dump(doc.to_dict(), allow_unicode=True, sort_keys=False)
    except ImportError:
        return "# PyYAML not installed. Install with: pip install pyyaml\n" + generate_openapi_json()