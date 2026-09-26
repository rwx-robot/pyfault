"""
Middleware for CQRS.
"""

from functools import wraps
from typing import TYPE_CHECKING, Any, Callable, TypeVar, cast

if TYPE_CHECKING:
    from pyfault.common.cqrs.command import Command, CommandResult
    from pyfault.common.cqrs.query import Query, QueryResult

from pyfault.common.cqrs.core import (
    CommandMiddleware,
    IdempotencyMiddleware,
    LoggingMiddleware,
    Middleware,
    MiddlewareChain,
    MiddlewareChainBuilder,
    QueryMiddleware,
    RetryMiddleware,
    TransactionMiddleware,
    ValidationMiddleware,
)

__all__ = [
    "Middleware",
    "CommandMiddleware",
    "QueryMiddleware",
    "MiddlewareChain",
    "LoggingMiddleware",
    "ValidationMiddleware",
    "RetryMiddleware",
    "IdempotencyMiddleware",
    "TransactionMiddleware",
    "MiddlewareChainBuilder",
    "with_middleware",
    "MessageDispatcher",
]

T = TypeVar("T")
R = TypeVar("R")


# Decorators for middleware
def with_middleware(*middlewares: Any) -> Callable[..., Any]:
    """Decorator to add middleware to a handler."""
    def decorator(handler: Callable) -> Any:
        @wraps(handler)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            chain = MiddlewareChain(list(middlewares), handler)
            return await chain.execute(args[0] if args else None)
        return wrapper
    return decorator


# Message dispatcher for unified command/query handling
class MessageDispatcher:
    """Unified dispatcher for commands and queries."""

    def __init__(self) -> None:
        from pyfault.common.cqrs.command import CommandBus
        from pyfault.common.cqrs.query import QueryBus
        self.command_bus = CommandBus()
        self.query_bus = QueryBus()
        self._command_middleware: list = []
        self._query_middleware: list = []

    def add_command_middleware(self, middleware: Any) -> None:
        self._command_middleware.append(middleware)

    def add_query_middleware(self, middleware: Any) -> None:
        self._query_middleware.append(middleware)

    def register_command_handler(self, handler: Any) -> None:
        self.command_bus.register(handler)

    def register_query_handler(self, handler: Any) -> None:
        self.query_bus.register(handler)

    async def dispatch_command(self, command: "Command") -> "CommandResult":
        from pyfault.common.cqrs.core import MiddlewareChain
        chain = MiddlewareChain(self._command_middleware, self.command_bus.dispatch)
        return cast("CommandResult", await chain.execute(command))

    async def dispatch_query(self, query: "Query") -> "QueryResult":
        from pyfault.common.cqrs.core import MiddlewareChain
        chain = MiddlewareChain(self._query_middleware, self.query_bus.dispatch)
        return cast("QueryResult", await chain.execute(query))

    async def dispatch(self, message: Any) -> Any:
        """Dispatch either a command or query based on type."""
        if hasattr(message, 'command_id'):
            return await self.dispatch_command(message)
        elif hasattr(message, 'query_id'):
            return await self.dispatch_query(message)
        else:
            raise ValueError("Message must be either a Command or Query")

    def register_command_middleware(self, middleware: Any) -> None:
        self._command_middleware.append(middleware)

    def register_query_middleware(self, middleware: Any) -> None:
        self._query_middleware.append(middleware)
