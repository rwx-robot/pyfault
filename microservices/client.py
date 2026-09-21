"""
Microservices support for PyFault framework.
"""

import asyncio
import json
from typing import Any, Callable


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
        self._connection = None

    async def connect(self):
        """Connect to microservice."""
        if self.options.transport == 'tcp':
            self._connection = await asyncio.open_connection(
                self.options.host,
                self.options.port
            )

    async def send(self, pattern: str, data: Any = None) -> Any:
        """Send a message."""
        message = json.dumps({'pattern': pattern, 'data': data})
        if self._connection:
            reader, writer = self._connection
            writer.write(message.encode())
            await writer.drain()
            response = await reader.read(1024)
            return json.loads(response.decode())
        return None

    async def close(self):
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
        self._server = None

    def register_handler(self, pattern: str, handler: Callable):
        """Register a message handler."""
        self._handlers[pattern] = handler

    def MessagePattern(self, pattern: str):
        """Decorator for registering a message handler."""
        def decorator(func: Callable):
            self._handlers[pattern] = func
            return func
        return decorator

    async def start(self):
        """Start the server."""
        async def handle_client(reader, writer):
            try:
                while True:
                    data = await reader.read(1024)
                    if not data:
                        break

                    message = json.loads(data.decode())
                    pattern = message.get('pattern')
                    payload = message.get('data')

                    if pattern in self._handlers:
                        result = await self._handlers[pattern](payload)
                        writer.write(json.dumps(result).encode())
                        await writer.drain()
            except Exception as e:
                print(f"Error: {e}")
            finally:
                writer.close()

        self._server = await asyncio.start_server(
            handle_client,
            self.options.host,
            self.options.port
        )

    async def stop(self):
        """Stop the server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
