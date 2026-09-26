"""
AWS Lambda Adapter for PyFault framework.
"""

import base64
from typing import Any, Callable

from pyfault.common.serverless.base import (
    ServerlessAdapter,
    ServerlessRequest,
)


class AWSLambdaAdapter(ServerlessAdapter):
    """AWS Lambda adapter for PyFault applications."""

    def parse_event(self, event: dict[str, Any], context: Any = None) -> ServerlessRequest:
        """Parse Lambda event into normalized request."""
        # Handle API Gateway events
        if "httpMethod" in event:
            return self._parse_api_gateway_event(event)

        # Handle ALB events
        if "requestContext" in event and "elb" in event["requestContext"]:
            return self._parse_alb_event(event)

        # Handle Function URL events (domain looks like
        # <id>.lambda-url.<region>.on.aws — "function" never appears there)
        if (
            "requestContext" in event
            and "domainName" in event["requestContext"]
            and "lambda-url"
            in str(event["requestContext"].get("domainName", ""))
        ):
            return self._parse_function_url_event(event)

        # Default: try to parse as generic HTTP event
        return self._parse_generic_event(event)

    def _parse_api_gateway_event(self, event: dict[str, Any]) -> ServerlessRequest:
        """Parse API Gateway REST/HTTP API event."""
        headers = event.get("headers", {}) or {}
        multi_value_headers = event.get("multiValueHeaders", {}) or {}

        # Use multi-value headers if available
        parsed_headers = {}
        for k, v in multi_value_headers.items():
            if len(v) == 1:
                parsed_headers[k] = v[0]
            else:
                parsed_headers[k] = ", ".join(v)

        # Fall back to single-value headers
        for k, v in headers.items():
            if k not in parsed_headers:
                parsed_headers[k] = v

        # Parse query parameters
        query_params = event.get("queryStringParameters") or {}

        # Parse path parameters
        path_params = event.get("pathParameters") or {}

        # Parse body
        body = event.get("body")
        is_base64 = event.get("isBase64Encoded", False)
        if body and is_base64:
            body = base64.b64decode(body).decode("utf-8")

        return ServerlessRequest(
            method=event.get("httpMethod", "GET"),
            path=event.get("path", "/"),
            headers=parsed_headers,
            query_params=query_params,
            body=body,
            path_params=path_params,
            raw_event=event,
        )

    def _parse_alb_event(self, event: dict[str, Any]) -> ServerlessRequest:
        """Parse Application Load Balancer event."""
        headers = event.get("headers", {}) or {}

        return ServerlessRequest(
            method=event.get("httpMethod", "GET"),
            path=event.get("path", "/"),
            headers=headers,
            query_params=event.get("queryStringParameters") or {},
            body=event.get("body"),
            path_params={},
            raw_event=event,
        )

    def _parse_function_url_event(self, event: dict[str, Any]) -> ServerlessRequest:
        """Parse Lambda Function URL event."""
        headers = event.get("headers", {}) or {}

        return ServerlessRequest(
            method=event.get("requestContext", {}).get("http", {}).get("method", "GET"),
            path=event.get("requestContext", {}).get("http", {}).get("path", "/"),
            headers=headers,
            query_params=event.get("queryStringParameters") or {},
            body=event.get("body"),
            path_params={},
            raw_event=event,
        )

    def _parse_generic_event(self, event: dict[str, Any]) -> ServerlessRequest:
        """Parse generic event as fallback."""
        return ServerlessRequest(
            method=event.get("method", event.get("httpMethod", "GET")),
            path=event.get("path", "/"),
            headers=event.get("headers", {}) or {},
            query_params=event.get("query", event.get("queryStringParameters", {})) or {},
            body=event.get("body"),
            path_params=event.get("pathParameters", {}) or {},
            raw_event=event,
        )

    def format_response(self, response: Any) -> dict[str, Any]:
        """Format ServerlessResponse for Lambda."""
        if isinstance(response, dict):
            # Already formatted
            return response

        if hasattr(response, "to_dict"):
            as_dict: dict[str, Any] = response.to_dict()
            return as_dict

        # Assume it's a ServerlessResponse
        return {
            "statusCode": getattr(response, "status_code", 200),
            "headers": getattr(response, "headers", {}),
            "body": getattr(response, "body", ""),
            "isBase64Encoded": getattr(response, "is_base64_encoded", False),
        }

def create_lambda_handler(app_factory: Callable) -> Callable:
    """Create a Lambda handler from an app factory."""
    adapter = AWSLambdaAdapter(app_factory)

    async def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
        result: dict[str, Any] = await adapter.handle(event, context)
        return result

    # Support synchronous invocation
    def sync_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
        import asyncio
        return asyncio.run(adapter.handle(event, context))

    # Detect whether we are created inside a running event loop. Only
    # get_running_loop is reliable here: get_event_loop would emit a
    # DeprecationWarning (and create a loop) in synchronous contexts.
    import asyncio
    try:
        asyncio.get_running_loop()
        return handler
    except RuntimeError:
        return sync_handler
