"""
WebSocket Adapter for PyFault framework.
"""

import contextlib
from typing import Callable

from starlette.routing import BaseRoute, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState


class WebSocketAdapter:
    """
    WebSocket Adapter for handling WebSocket connections.
    """

    def __init__(self) -> None:
        self.routes: list[BaseRoute] = []
        self._handlers: dict[str, Callable] = {}

    def register_handler(self, path: str, handler: Callable) -> None:
        """Register a WebSocket handler."""
        self._handlers[path] = handler

    def add_websocket_route(self, path: str, handler: Callable) -> None:
        """Add a WebSocket route."""
        async def websocket_endpoint(websocket: WebSocket) -> None:
            await websocket.accept()
            try:
                while websocket.client_state == WebSocketState.CONNECTED:
                    try:
                        data = await websocket.receive_json()
                    except WebSocketDisconnect:
                        break
                    except RuntimeError as e:
                        if "not connected" in str(e) or "closed" in str(e).lower():
                            break
                        raise

                    if path in self._handlers:
                        try:
                            result = await self._handlers[path](websocket, data)
                            # Try to send response; if connection closed, break
                            try:
                                if websocket.client_state == WebSocketState.CONNECTED:
                                    await websocket.send_json(result)
                            except RuntimeError:
                                break
                        except WebSocketDisconnect:
                            break
                        except Exception:
                            # Close connection on handler error
                            with contextlib.suppress(RuntimeError):
                                await websocket.close()
                            break
            except WebSocketDisconnect:
                pass

        route = WebSocketRoute(path, endpoint=websocket_endpoint)
        self.routes.append(route)

    def ws(self, path: str) -> Callable[[Callable], Callable]:
        """Decorator for WebSocket route."""
        def decorator(func: Callable) -> Callable:
            self._handlers[path] = func

            async def websocket_endpoint(websocket: WebSocket) -> None:
                await websocket.accept()
                try:
                    while websocket.client_state == WebSocketState.CONNECTED:
                        try:
                            data = await websocket.receive_json()
                        except WebSocketDisconnect:
                            break
                        except RuntimeError as e:
                            if "not connected" in str(e) or "closed" in str(e).lower():
                                break
                            raise

                        try:
                            result = await func(websocket, data)
                            # Try to send response; if connection closed, break
                            try:
                                if websocket.client_state == WebSocketState.CONNECTED:
                                    await websocket.send_json(result)
                            except RuntimeError:
                                break
                        except WebSocketDisconnect:
                            break
                        except Exception:
                            # Close connection on handler error
                            with contextlib.suppress(RuntimeError):
                                await websocket.close()
                            break
                except WebSocketDisconnect:
                    pass

            route = WebSocketRoute(path, endpoint=websocket_endpoint)
            self.routes.append(route)
            return func
        return decorator

    def build_routes(self) -> list[BaseRoute]:
        """Build WebSocket routes."""
        return self.routes
