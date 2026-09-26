"""
Google Cloud Functions Adapter for PyFault framework.
"""

import base64
import json
from typing import Any, Callable

from pyfault.common.serverless.base import (
    ServerlessAdapter,
    ServerlessRequest,
    ServerlessResponse,
)


class GCFAdapter(ServerlessAdapter):
    """Google Cloud Functions adapter for PyFault applications."""

    def parse_event(self, event: dict[str, Any], context: Any = None) -> ServerlessRequest:
        """Parse GCF event into normalized request."""
        # HTTP trigger events
        if "httpMethod" in event:
            return self._parse_http_event(event)

        # CloudEvent (Eventarc, etc.)
        if "specversion" in event:
            return self._parse_cloudevent(event)

        # Background/PubSub trigger
        if "data" in event and "message" in event.get("data", {}):
            return self._parse_pubsub_event(event)

        return self._parse_generic_event(event)

    def _parse_http_event(self, event: dict[str, Any]) -> ServerlessRequest:
        """Parse HTTP-triggered GCF event."""
        headers = event.get("headers", {}) or {}

        return ServerlessRequest(
            method=event.get("method", event.get("httpMethod", "GET")),
            path=event.get("path", "/"),
            headers=headers,
            query_params=event.get("query", event.get("queryStringParameters", {})) or {},
            body=event.get("body"),
            path_params={},
            raw_event=event,
        )

    def _parse_cloudevent(self, event: dict[str, Any]) -> ServerlessRequest:
        """Parse CloudEvent."""
        return ServerlessRequest(
            method="POST",
            path=f"/cloudevent/{event.get('type', 'unknown')}",
            headers={k: str(v) for k, v in event.items() if k != "data"},
            query_params={},
            body=json.dumps(event.get("data", {})),
            path_params={},
            raw_event=event,
        )

    def _parse_pubsub_event(self, event: dict[str, Any]) -> ServerlessRequest:
        """Parse Pub/Sub event."""
        message = event.get("message", {})
        data = message.get("data", "")

        # Decode base64 data if needed
        try:
            decoded = base64.b64decode(data).decode("utf-8")
        except Exception:
            decoded = data

        return ServerlessRequest(
            method="POST",
            path=f"/pubsub/{message.get('topic', 'unknown')}",
            headers={"content-type": "application/json"},
            query_params={},
            body=decoded,
            path_params={},
            raw_event=event,
        )

    def _parse_generic_event(self, event: dict[str, Any]) -> ServerlessRequest:
        """Parse generic event as fallback."""
        return ServerlessRequest(
            method=event.get("method", "POST"),
            path=event.get("path", "/"),
            headers=event.get("headers", {}) or {},
            query_params=event.get("query", {}) or {},
            body=event.get("body") or json.dumps(event),
            path_params={},
            raw_event=event,
        )

    def format_response(self, response: Any) -> dict[str, Any]:
        """Format ServerlessResponse for GCF."""
        if isinstance(response, dict):
            return response

        if hasattr(response, "to_dict"):
            as_dict: dict[str, Any] = response.to_dict()
            return as_dict

        return {
            "statusCode": getattr(response, "status_code", 200),
            "headers": getattr(response, "headers", {"content-type": "application/json"}),
            "body": getattr(response, "body", ""),
        }

    async def _handle_request(self, scope: dict[str, Any]) -> "ServerlessResponse":
        """Handle ASGI request."""
        from pyfault.common.serverless.base import ServerlessResponse

        return ServerlessResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='{"message": "GCF adapter working"}',
        )


def create_gcf_handler(app_factory: Callable) -> Callable:
    """Create a GCF handler from an app factory."""
    adapter = GCFAdapter(app_factory)

    async def handler(request: Any) -> Any:
        # GCF passes request directly
        if hasattr(request, "headers"):
            # Flask-like request object
            event = {
                "method": request.method,
                "path": request.path,
                "headers": dict(request.headers),
                "query": dict(request.args),
                "body": request.get_data(as_text=True),
            }
        else:
            event = request

        return await adapter.handle(event)

    return handler
