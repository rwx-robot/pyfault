"""
Microservices support for PyFault framework.
"""

import asyncio
import json
from typing import Any, Callable, Optional


class MicroserviceOptions:
    """Microservice options."""

    def __init__(self, transport: str = 'tcp', host: str = 'localhost', port: int = 3000):
        self.transport = transport
        self.host = host
        self.port = port


class MicroserviceClient:
    """Microservice client for sending messages."""

    def __init__(self, options: MicroserviceOptions):
        self.options = options
        self._connection: Optional[tuple[asyncio.StreamReader, asyncio.StreamWriter]] = None

    async def connect(self) -> None:
        """Connect to microservice."""
        if self.options.transport == 'tcp':
            self._connection = await asyncio.open_connection(
                self.options.host,
                self.options.port
            )

    async def send(self, pattern: str, data: Any = None) -> Any:
        """Send a message and read the full JSON response (handles chunking)."""
        message = json.dumps({'pattern': pattern, 'data': data})
        if self._connection:
            reader, writer = self._connection
            writer.write(message.encode())
            await writer.drain()
            raw = b''
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                raw += chunk
                try:
                    return json.loads(raw.decode())
                except json.JSONDecodeError:
                    # Response may span multiple reads; keep buffering.
                    continue
            if not raw:
                return None
            return json.loads(raw.decode())
        return None

    async def close(self) -> None:
        """Close connection."""
        if self._connection:
            reader, writer = self._connection
            writer.close()
            await writer.wait_closed()


class MicroserviceServer:
    """Microservice server for handling messages."""

    def __init__(self, options: MicroserviceOptions):
        self.options = options
        self._handlers: dict[str, Callable] = {}
        self._server: Optional[asyncio.Server] = None

    def register_handler(self, pattern: str, handler: Callable) -> None:
        """Register a message handler."""
        self._handlers[pattern] = handler

    def MessagePattern(self, pattern: str) -> Callable[..., Any]:
        """Decorator for registering a message handler."""
        def decorator(func: Callable) -> Any:
            self._handlers[pattern] = func
            return func
        return decorator

    async def start(self) -> None:
        """Start the server."""
        async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = b''
                    while True:
                        chunk = await reader.read(4096)
                        if not chunk:
                            break
                        data += chunk
                        try:
                            message = json.loads(data.decode())
                            break
                        except json.JSONDecodeError:
                            continue
                    if not data:
                        break

                    pattern = message.get('pattern')
                    payload = message.get('data')

                    if pattern in self._handlers:
                        try:
                            result = self._handlers[pattern](payload)
                            # Support both sync handlers and coroutine handlers.
                            if asyncio.iscoroutine(result):
                                result = await result
                            response = {'success': True, 'data': result}
                        except Exception as e:  # surface handler errors as structured response
                            response = {'success': False, 'error': str(e)}
                    else:
                        response = {'success': False, 'error': f'No handler for pattern: {pattern}'}

                    writer.write(json.dumps(response).encode())
                    await writer.drain()
            except Exception as e:
                # Last-resort: never let a stray error kill the server silently.
                try:
                    writer.write(json.dumps({'success': False, 'error': str(e)}).encode())
                    await writer.drain()
                except Exception:
                    pass
            finally:
                writer.close()

        self._server = await asyncio.start_server(
            handle_client,
            self.options.host,
            self.options.port
        )

    async def stop(self) -> None:
        """Stop the server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
