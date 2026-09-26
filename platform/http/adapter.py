"""
HTTP Adapter for PyFault framework.
"""

from typing import Any, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route


class HttpAdapter:
    """
    HTTP Adapter for handling HTTP requests.
    """

    def __init__(self) -> None:
        self._routes: list[dict] = []  # Store route info before building
        self.middleware: list[Callable] = []
        self._controllers: dict[type, Any] = {}

    @property
    def routes(self) -> list:
        """Return routes for backward compatibility."""
        return self._routes

    def register_controller(self, controller_class: type, instance: Any) -> None:
        """Register a controller instance and bind its methods to routes."""
        self._controllers[controller_class] = instance
        # Update existing routes to use bound methods
        for route_info in self._routes:
            handler = route_info['handler']
            # Check if this handler belongs to the registered controller
            for attr_name in dir(instance):
                attr = getattr(instance, attr_name)
                if hasattr(attr, '__func__') and attr.__func__ is handler or attr is handler:
                    route_info['handler'] = attr
                    break

    def add_route(self, method: str, path: str, handler: Callable) -> None:
        """Add a route."""
        self._routes.append({
            'method': method,
            'path': path,
            'handler': handler
        })

    def build(self) -> Starlette:
        """Build the Starlette application with middleware."""
        # Build the base app with routes
        routes = []
        for route_info in self._routes:
            handler = route_info['handler']
            method = route_info['method']
            path = route_info['path']

            import inspect
            sig = inspect.signature(handler)
            handler_params = set(sig.parameters.keys())

            async def endpoint(
                request: Request,
                handler: Callable[..., Any] = handler,
                handler_params: set[str] = handler_params,
                sig: inspect.Signature = sig,
            ) -> JSONResponse:
                # Get path parameters
                path_params = request.path_params

                # Get query parameters
                query_params = dict(request.query_params)

                # Get request body
                body = None
                if request.method in ['POST', 'PUT', 'PATCH']:
                    try:
                        body = await request.json()
                    except Exception:
                        body = None

                # Build kwargs for handler
                kwargs = {}

                # Add path params (highest priority, should not be overridden)
                for key, value in path_params.items():
                    if key in handler_params:
                        kwargs[key] = value

                # Add query params
                for key, value in query_params.items():
                    if key in handler_params:
                        # Convert string to appropriate type based on annotation
                        param = sig.parameters.get(key)
                        if param and param.annotation != inspect.Parameter.empty:
                            try:
                                if param.annotation is int:
                                    value = int(value)
                                elif param.annotation is float:
                                    value = float(value)
                                elif param.annotation is bool:
                                    value = value.lower() in ('true', '1', 'yes')
                            except (ValueError, AttributeError):
                                pass
                        kwargs[key] = value

                # Add body params (can override query params)
                if body and isinstance(body, dict):
                    for key, value in body.items():
                        if key in handler_params:
                            kwargs[key] = value

                # Add request object if handler accepts it
                if 'request' in handler_params:
                    kwargs['request'] = request

                # Call handler
                if inspect.iscoroutinefunction(handler):
                    result = await handler(**kwargs)
                else:
                    result = handler(**kwargs)

                return JSONResponse(result)

            # Apply middleware chain to the endpoint (Express-style middleware)
            final_endpoint = endpoint
            for middleware in reversed(self.middleware):
                final_endpoint = middleware(final_endpoint)

            route = Route(path, endpoint=final_endpoint, methods=[method])
            routes.append(route)

        return Starlette(routes=routes)

    def get(self, path: str) -> Callable[..., Any]:
        """Decorator for GET route."""
        def decorator(func: Callable) -> Any:
            self.add_route('GET', path, func)
            return func
        return decorator

    def post(self, path: str) -> Callable[..., Any]:
        """Decorator for POST route."""
        def decorator(func: Callable) -> Any:
            self.add_route('POST', path, func)
            return func
        return decorator

    def put(self, path: str) -> Callable[..., Any]:
        """Decorator for PUT route."""
        def decorator(func: Callable) -> Any:
            self.add_route('PUT', path, func)
            return func
        return decorator

    def delete(self, path: str) -> Callable[..., Any]:
        """Decorator for DELETE route."""
        def decorator(func: Callable) -> Any:
            self.add_route('DELETE', path, func)
            return func
        return decorator
