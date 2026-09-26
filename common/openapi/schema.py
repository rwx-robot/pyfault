"""
OpenAPI Schema definitions for PyFault framework.
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Server:
    """OpenAPI Server object."""
    url: str
    description: str = ""


@dataclass
class Info:
    """OpenAPI Info object."""
    title: str
    version: str
    description: str = ""
    contact: Optional[dict[str, str]] = None
    license: Optional[dict[str, str]] = None


@dataclass
class Contact:
    """OpenAPI Contact object."""
    name: str = ""
    email: str = ""
    url: str = ""


@dataclass
class License:
    """OpenAPI License object."""
    name: str
    url: str = ""


@dataclass
class Parameter:
    """OpenAPI Parameter object."""
    name: str
    in_: str  # query, path, header, cookie
    description: str = ""
    required: bool = False
    deprecated: bool = False
    schema: Optional[dict] = None
    example: Any = None


@dataclass
class Response:
    """OpenAPI Response object."""
    description: str
    content: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestBody:
    """OpenAPI RequestBody object."""
    description: str = ""
    content: dict[str, Any] = field(default_factory=dict)
    required: bool = False


@dataclass
class SecurityScheme:
    """OpenAPI Security Scheme object."""
    type: str  # http, apiKey, oauth2, openIdConnect
    scheme: Optional[str] = None  # bearer, basic, etc.
    bearer_format: Optional[str] = None
    description: str = ""


@dataclass
class Operation:
    """OpenAPI Operation object."""
    tags: list[str] = field(default_factory=list)
    summary: str = ""
    description: str = ""
    operation_id: str = ""
    parameters: list[Parameter] = field(default_factory=list)
    request_body: Optional[RequestBody] = None
    responses: dict[str, Response] = field(default_factory=dict)
    security: list[dict[str, list[str]]] = field(default_factory=list)
    deprecated: bool = False


@dataclass
class PathItem:
    """OpenAPI Path Item object."""
    summary: str = ""
    description: str = ""
    get: Optional[Operation] = None
    put: Optional[Operation] = None
    post: Optional[Operation] = None
    delete: Optional[Operation] = None
    options: Optional[Operation] = None
    head: Optional[Operation] = None
    patch: Optional[Operation] = None
    trace: Optional[Operation] = None
    servers: list[Server] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)


@dataclass
class Components:
    """OpenAPI Components object."""
    schemas: dict[str, Any] = field(default_factory=dict)
    responses: dict[str, Response] = field(default_factory=dict)
    parameters: dict[str, Parameter] = field(default_factory=dict)
    examples: dict[str, Any] = field(default_factory=dict)
    request_bodies: dict[str, RequestBody] = field(default_factory=dict)
    headers: dict[str, Any] = field(default_factory=dict)
    security_schemes: dict[str, SecurityScheme] = field(default_factory=dict)


@dataclass
class OpenAPISchema:
    """OpenAPI Document object."""
    openapi: str = "3.0.3"
    info: Optional[Info] = None
    servers: list[Server] = field(default_factory=list)
    paths: dict[str, PathItem] = field(default_factory=dict)
    components: Optional[Components] = None
    security: list[dict[str, list[str]]] = field(default_factory=list)
    tags: list[dict[str, str]] = field(default_factory=list)
    external_docs: Optional[dict[str, str]] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON/YAML serialization."""
        result: dict[str, Any] = {
            "openapi": self.openapi,
        }

        if self.info:
            result["info"] = {
                "title": self.info.title,
                "version": self.info.version,
                "description": self.info.description,
            }
            if self.info.contact:
                result["info"]["contact"] = self.info.contact
            if self.info.license:
                result["info"]["license"] = self.info.license

        if self.servers:
            result["servers"] = [{"url": s.url, "description": s.description} for s in self.servers]

        if self.paths:
            result["paths"] = {}
            for path, item in self.paths.items():
                path_dict: dict[str, Any] = {}
                if item.summary:
                    path_dict["summary"] = item.summary
                if item.description:
                    path_dict["description"] = item.description

                for method in ["get", "put", "post", "delete", "options", "head", "patch", "trace"]:
                    op = getattr(item, method)
                    if op:
                        path_dict[method] = self._operation_to_dict(op)

                if item.servers:
                    path_dict["servers"] = [{"url": s.url, "description": s.description} for s in item.servers]
                if item.parameters:
                    path_dict["parameters"] = [self._parameter_to_dict(p) for p in item.parameters]

                result["paths"][path] = path_dict

        if self.components:
            result["components"] = self._components_to_dict(self.components)

        if self.security:
            result["security"] = self.security

        if self.tags:
            result["tags"] = self.tags

        if self.external_docs:
            result["externalDocs"] = self.external_docs

        return result

    def _operation_to_dict(self, op: Operation) -> dict[str, Any]:
        """Convert Operation to dict."""
        result: dict[str, Any] = {}
        if op.tags:
            result["tags"] = op.tags
        if op.summary:
            result["summary"] = op.summary
        if op.description:
            result["description"] = op.description
        if op.operation_id:
            result["operationId"] = op.operation_id
        if op.parameters:
            result["parameters"] = [self._parameter_to_dict(p) for p in op.parameters]
        if op.request_body:
            result["requestBody"] = self._request_body_to_dict(op.request_body)
        if op.responses:
            result["responses"] = {k: self._response_to_dict(v) for k, v in op.responses.items()}
        if op.security:
            result["security"] = op.security
        if op.deprecated:
            result["deprecated"] = op.deprecated
        return result

    def _parameter_to_dict(self, param: Parameter) -> dict[str, Any]:
        """Convert Parameter to dict."""
        result: dict[str, Any] = {
            "name": param.name,
            "in": param.in_,
        }
        if param.description:
            result["description"] = param.description
        if param.required:
            result["required"] = param.required
        if param.deprecated:
            result["deprecated"] = param.deprecated
        if param.schema:
            result["schema"] = param.schema
        if param.example is not None:
            result["example"] = param.example
        return result

    def _request_body_to_dict(self, body: RequestBody) -> dict[str, Any]:
        """Convert RequestBody to dict."""
        result: dict[str, Any] = {}
        if body.description:
            result["description"] = body.description
        if body.content:
            result["content"] = body.content
        if body.required:
            result["required"] = body.required
        return result

    def _response_to_dict(self, resp: Response) -> dict[str, Any]:
        """Convert Response to dict."""
        result: dict[str, Any] = {"description": resp.description}
        if resp.content:
            result["content"] = resp.content
        if resp.headers:
            result["headers"] = resp.headers
        return result

    def _components_to_dict(self, comp: Components) -> dict[str, Any]:
        """Convert Components to dict."""
        result: dict[str, Any] = {}
        if comp.schemas:
            result["schemas"] = comp.schemas
        if comp.responses:
            result["responses"] = {k: self._response_to_dict(v) for k, v in comp.responses.items()}
        if comp.parameters:
            result["parameters"] = {k: self._parameter_to_dict(v) for k, v in comp.parameters.items()}
        if comp.examples:
            result["examples"] = comp.examples
        if comp.request_bodies:
            result["requestBodies"] = {k: self._request_body_to_dict(v) for k, v in comp.request_bodies.items()}
        if comp.headers:
            result["headers"] = comp.headers
        if comp.security_schemes:
            result["securitySchemes"] = {k: self._security_scheme_to_dict(v) for k, v in comp.security_schemes.items()}
        return result

    def _security_scheme_to_dict(self, scheme: SecurityScheme) -> dict[str, Any]:
        """Convert SecurityScheme to dict."""
        result: dict[str, Any] = {"type": scheme.type}
        if scheme.scheme:
            result["scheme"] = scheme.scheme
        if scheme.bearer_format:
            result["bearerFormat"] = scheme.bearer_format
        if scheme.description:
            result["description"] = scheme.description
        return result
