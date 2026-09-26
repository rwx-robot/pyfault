"""
Base Serverless Adapter for PyFault framework.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, cast
from urllib.parse import parse_qs, urlencode


@dataclass
class ServerlessRequest:
    """Normalized serverless request."""
    method: str
    path: str
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None
    path_params: dict[str, str] = field(default_factory=dict)
    raw_event: Any = None
    context: Any = None

    def get_header(self, name: str, default: str = "") -> str:
        """Get header value (case-insensitive)."""
        for k, v in self.headers.items():
            if k.lower() == name.lower():
                return v
        return default


@dataclass
class ServerlessResponse:
    """Normalized serverless response."""
    status_code: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: str = ""
    is_base64_encoded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "statusCode": self.status_code,
            "headers": self.headers,
            "body": self.body,
            "isBase64Encoded": self.is_base64_encoded,
        }


class ServerlessAdapter(ABC):
    """Base class for serverless platform adapters."""

    def __init__(self, app_factory: Callable):
        self.app_factory = app_factory
        self._app: Any = None

    async def initialize(self) -> None:
        """Initialize the application.

        ``app_factory`` may be either a plain callable returning the ASGI app
        or an async callable (awaited) — both forms are supported.
        """
        if self._app is None:
            import inspect

            result = self.app_factory()
            if inspect.isawaitable(result):
                result = await result
            self._app = result

    @abstractmethod
    def parse_event(self, event: Any, context: Any = None) -> ServerlessRequest:
        """Parse platform-specific event into normalized request."""
        pass

    @abstractmethod
    def format_response(self, response: ServerlessResponse) -> Any:
        """Format normalized response into platform-specific response."""
        pass

    async def handle(self, event: Any, context: Any = None) -> Any:
        """Handle serverless invocation."""
        await self.initialize()

        # Parse event
        request = self.parse_event(event, context)

        # Convert to ASGI scope
        scope = self._request_to_scope(request)

        # Handle request through the real ASGI application
        body = (request.body or "").encode("utf-8") if isinstance(request.body, str) else (request.body or b"")
        response = await self._handle_request(scope, body)

        # Format response
        return self.format_response(response)

    def _request_to_scope(self, request: ServerlessRequest) -> dict[str, Any]:
        """Convert normalized request to ASGI scope."""
        from urllib.parse import urlparse

        parsed_path = urlparse(request.path)
        path = parsed_path.path or "/" if parsed_path.scheme else request.path
        raw_query = parsed_path.query if parsed_path.scheme else ""
        query_string = self._encode_query_string(request.query_params)
        if raw_query:
            query_string = (
                f"{query_string.decode()}&{raw_query}".encode()
                if query_string
                else raw_query.encode()
            )

        return {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": request.method,
            "scheme": "http",
            "server": ("localhost", 80),
            "client": ("127.0.0.1", 0),
            "root_path": "",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": query_string,
            "headers": [(k.lower().encode(), v.encode()) for k, v in request.headers.items()],
            "path_params": request.path_params,
        }

    def _encode_query_string(self, params: dict[str, str]) -> bytes:
        """Encode query parameters."""
        return urlencode(params).encode()

    async def _handle_request(
        self, scope: dict[str, Any], body: bytes = b""
    ) -> ServerlessResponse:
        """Run the ASGI application for this scope and collect the response."""
        status_code = 500
        response_headers: dict[str, str] = {}
        body_parts: list[bytes] = []
        received_request = False

        async def receive() -> dict[str, Any]:
            nonlocal received_request
            if not received_request:
                received_request = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 500)
                response_headers.clear()
                for key, value in message.get("headers", []):
                    response_headers[key.decode("latin-1")] = value.decode(
                        "latin-1"
                    )
            elif message["type"] == "http.response.body":
                body_parts.append(message.get("body", b"") or b"")

        assert self._app is not None, "ASGI app not initialized"
        await self._app(scope, receive, send)

        raw = b"".join(body_parts)
        try:
            text = raw.decode("utf-8")
            return ServerlessResponse(
                status_code=status_code,
                headers=response_headers,
                body=text,
                is_base64_encoded=False,
            )
        except UnicodeDecodeError:
            import base64 as _base64

            return ServerlessResponse(
                status_code=status_code,
                headers=response_headers,
                body=_base64.b64encode(raw).decode("ascii"),
                is_base64_encoded=True,
            )

    def _parse_json_body(self, body: str) -> dict[str, Any]:
        """Parse JSON body."""
        import json
        try:
            return cast(dict[str, Any], json.loads(body))
        except json.JSONDecodeError:
            return {}

    def _parse_form_body(self, body: str) -> dict[str, str]:
        """Parse form-encoded body."""
        return {k: v[0] for k, v in parse_qs(body).items()}


