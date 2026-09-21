"""
Base Serverless Adapter for PyFault framework.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs


@dataclass
class ServerlessRequest:
    """Normalized serverless request."""
    method: str
    path: str
    headers: Dict[str, str] = field(default_factory=dict)
    query_params: Dict[str, str] = field(default_factory=dict)
    body: Optional[str] = None
    path_params: Dict[str, str] = field(default_factory=dict)
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
    headers: Dict[str, str] = field(default_factory=dict)
    body: str = ""
    is_base64_encoded: bool = False

    def to_dict(self) -> Dict[str, Any]:
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
        self._app = None

    async def initialize(self):
        """Initialize the application."""
        if self._app is None:
            self._app = await self.app_factory()

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
        
        # Handle request
        response = await self._handle_request(scope)
        
        # Format response
        return self.format_response(response)

    def _request_to_scope(self, request: ServerlessRequest) -> Dict[str, Any]:
        """Convert normalized request to ASGI scope."""
        return {
            "type": "http",
            "method": request.method,
            "path": request.path,
            "query_string": self._encode_query_string(request.query_params),
            "headers": [(k.lower().encode(), v.encode()) for k, v in request.headers.items()],
            "path_params": request.path_params,
        }

    def _encode_query_string(self, params: Dict[str, str]) -> bytes:
        """Encode query parameters."""
        return "&".join(f"{k}={v}" for k, v in params.items()).encode()

    @abstractmethod
    async def _handle_request(self, scope: Dict[str, Any]) -> ServerlessResponse:
        """Handle ASGI request."""
        pass

    def _parse_json_body(self, body: str) -> Dict[str, Any]:
        """Parse JSON body."""
        import json
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {}

    def _parse_form_body(self, body: str) -> Dict[str, str]:
        """Parse form-encoded body."""
        return {k: v[0] for k, v in parse_qs(body).items()}


from urllib.parse import parse_qs