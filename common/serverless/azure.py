"""
Azure Functions Adapter for PyFault framework.
"""

import json
from typing import Any, Callable, Dict, Optional

from pyfault.common.serverless.base import ServerlessAdapter, ServerlessRequest, ServerlessResponse


class AzureFunctionsAdapter(ServerlessAdapter):
    """Azure Functions adapter for PyFault applications."""

    def parse_event(self, event: Any, context: Any = None) -> ServerlessRequest:
        """Parse Azure Functions event into normalized request."""
        # Handle HTTP trigger
        if hasattr(event, "method") and hasattr(event, "url"):
            return self._parse_http_trigger(event)
        
        # Handle dict-based events
        if isinstance(event, dict):
            if "request" in event:
                return self._parse_http_trigger(event["request"])
            if "data" in event:
                return self._parse_queue_trigger(event)
            if "timer" in event:
                return self._parse_timer_trigger(event)
        
        return self._parse_generic_event(event)

    def _parse_http_trigger(self, request: Any) -> ServerlessRequest:
        """Parse HTTP trigger request."""
        # Handle Azure Functions HttpRequest
        if hasattr(request, "method") and hasattr(request, "url"):
            headers = {}
            for k, v in request.headers.items():
                headers[k] = v
            
            return ServerlessRequest(
                method=request.method,
                path=request.url.path,
                headers=headers,
                query_params=dict(request.params),
                body=request.get_body().decode("utf-8") if hasattr(request, "get_body") else "",
                path_params={},
                raw_event=request,
            )
        
        # Handle dict-based request
        if isinstance(request, dict):
            return ServerlessRequest(
                method=request.get("method", "GET"),
                path=request.get("url", "/"),
                headers=request.get("headers", {}) or {},
                query_params=request.get("params", request.get("query", {})) or {},
                body=request.get("body", ""),
                path_params={},
                raw_event=request,
            )
        
        return self._parse_generic_event(request)

    def _parse_queue_trigger(self, event: Dict[str, Any]) -> ServerlessRequest:
        """Parse Queue Storage trigger."""
        return ServerlessRequest(
            method="POST",
            path=f"/queue/{event.get('queueName', 'unknown')}",
            headers={"content-type": "application/json"},
            query_params={},
            body=json.dumps(event.get("data", {})),
            path_params={},
            raw_event=event,
        )

    def _parse_timer_trigger(self, event: Dict[str, Any]) -> ServerlessRequest:
        """Parse Timer trigger."""
        return ServerlessRequest(
            method="POST",
            path="/timer",
            headers={"content-type": "application/json"},
            query_params={},
            body=json.dumps({
                "schedule": event.get("schedule", ""),
                "past_due": event.get("pastDue", False),
            }),
            path_params={},
            raw_event=event,
        )

    def _parse_generic_event(self, event: Any) -> ServerlessRequest:
        """Parse generic event as fallback."""
        if isinstance(event, dict):
            return ServerlessRequest(
                method=event.get("method", "POST"),
                path=event.get("path", event.get("url", "/")),
                headers=event.get("headers", {}) or {},
                query_params=event.get("query", event.get("params", {})) or {},
                body=event.get("body", event.get("data", "")),
                path_params={},
                raw_event=event,
            )
        
        return ServerlessRequest(
            method="POST",
            path="/",
            headers={},
            query_params={},
            body=str(event),
            path_params={},
            raw_event=event,
        )

    def format_response(self, response) -> Any:
        """Format ServerlessResponse for Azure Functions."""
        if hasattr(response, "to_dict"):
            resp_dict = response.to_dict()
        elif isinstance(response, dict):
            resp_dict = response
        else:
            resp_dict = {
                "statusCode": getattr(response, "status_code", 200),
                "headers": getattr(response, "headers", {"content-type": "application/json"}),
                "body": getattr(response, "body", ""),
            }
        
        # Azure Functions expects specific format
        return {
            "statusCode": resp_dict.get("statusCode", resp_dict.get("status", 200)),
            "headers": resp_dict.get("headers", {"Content-Type": "application/json"}),
            "body": resp_dict.get("body", ""),
        }

    async def _handle_request(self, scope: Dict[str, Any]) -> "ServerlessResponse":
        """Handle ASGI request."""
        from pyfault.common.serverless.base import ServerlessResponse
        
        return ServerlessResponse(
            status_code=200,
            headers={"content-type": "application/json"},
            body='{"message": "Azure Functions adapter working"}',
        )


def create_azure_handler(app_factory: Callable) -> Callable:
    """Create an Azure Functions handler from an app factory."""
    adapter = AzureFunctionsAdapter(app_factory)
    
    async def handler(request: Any, context: Any = None) -> Any:
        return await adapter.handle(request, context)
    
    return handler