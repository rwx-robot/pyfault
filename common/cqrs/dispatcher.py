"""
Message Dispatcher for CQRS.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Sequence
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

from pyfault.common.cqrs.command import Command, CommandBus, CommandResult
from pyfault.common.cqrs.query import Query, QueryBus, QueryResult

T = TypeVar("T")
R = TypeVar("R")


class Middleware(ABC):
    """Base middleware class."""

    @abstractmethod
    async def execute(self, message: Any, next_handler: Callable) -> Any:
        """Execute middleware logic."""
        pass


class CommandMiddleware(Middleware):
    """Middleware for command processing."""

    async def execute(self, command: "Command", next_handler: Callable[..., Awaitable[CommandResult]]) -> "CommandResult":
        return await next_handler(command)


class QueryMiddleware(Middleware):
    """Middleware for query processing."""

    async def execute(self, query: "Query", next_handler: Callable[..., Awaitable[QueryResult]]) -> "QueryResult":
        return await next_handler(query)


class MiddlewareChain:
    """Chain of middleware for command/query processing."""

    def __init__(self, middleware: Sequence[Middleware], final_handler: Callable):
        self._middleware = middleware
        self._final_handler = final_handler

    async def execute(self, message: Any) -> Any:
        """Execute the middleware chain."""
        # Build the chain in reverse order (last middleware wraps the handler)
        handler = self._build_chain()
        return await handler(message)

    def _build_chain(self) -> Callable:
        handler = self._final_handler

        # Wrap handler with middleware in reverse order
        for middleware in reversed(self._middleware):
            current_handler = handler
            middleware_instance = middleware

            async def middleware_wrapper(msg: Any, next_handler: Any = current_handler, mw: Any = middleware_instance) -> Any:
                return await mw.execute(msg, next_handler)

            handler = middleware_wrapper

        return handler


# Built-in middlewares
class LoggingMiddleware(CommandMiddleware):
    """Middleware for logging commands/queries."""

    def __init__(self, logger: Any = None) -> None:
        self.logger = logger or print

    async def execute(self, message: Any, next_handler: Any) -> Any:
        start = time.time()

        msg_type = "Command" if hasattr(message, 'command_id') else "Query"
        msg_id = getattr(message, 'command_id', getattr(message, 'query_id', 'unknown'))

        self.logger(f"[{msg_type}] {type(message).__name__} [{msg_id}] - START")

        try:
            result = await next_handler(message)
            duration = (time.time() - start) * 1000
            status = "SUCCESS" if getattr(result, 'success', True) else "FAILED"
            self.logger(f"[{msg_type}] {type(message).__name__} [{getattr(message, 'command_id', getattr(message, 'query_id', 'unknown'))}] - {status} ({duration:.2f}ms)")
            return result
        except Exception as e:
            duration = (time.time() - start) * 1000
            self.logger(f"[{type(message).__name__}] {type(message).__name__} - ERROR ({duration:.2f}ms): {e}")
            raise


class ValidationMiddleware(CommandMiddleware):
    """Middleware for additional validation."""

    def __init__(self, validators: Optional[dict[type, Callable]] = None):
        self.validators = validators or {}

    async def execute(self, command: "Command", next_handler: Callable[..., Awaitable[CommandResult]]) -> "CommandResult":
        # Run custom validators
        validator = self.validators.get(type(command))
        if validator:
            errors = await validator(command) if asyncio.iscoroutinefunction(validator) else validator(command)
            if errors:
                from pyfault.common.cqrs.command import CommandResult
                return CommandResult(
                    success=False,
                    command_id=command.command_id,
                    error=f"Custom validation failed: {', '.join(errors)}",
                )
        return await next_handler(command)


class RetryMiddleware(CommandMiddleware):
    """Middleware for retrying *transient* (infrastructure) failures.

    Retries ONLY when the downstream handler raises an exception (e.g. network
    timeout, DB unavailable). A returned business result — whether ``success``
    or an explicit business failure — is **never** retried; it is returned
    immediately. This prevents business-logic failures from being silently
    masked, amplified, or turned into misleading "failed after N attempts"
    messages.
    """

    def __init__(self, max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
        self.max_retries = max_retries
        self.delay = delay
        self.backoff = backoff

    async def execute(self, command: "Command", next_handler: Callable[..., Awaitable[CommandResult]]) -> "CommandResult":
        last_error = None
        delay = self.delay

        for attempt in range(self.max_retries + 1):
            try:
                result = await next_handler(command)
            except Exception as exc:  # transient infrastructure failure -> retry
                last_error = str(exc)
            else:
                # Business result (success or explicit failure): never retry.
                return result

            # Reached only when an exception was raised.
            if attempt >= self.max_retries:
                break
            await asyncio.sleep(delay)
            delay *= self.backoff

        from pyfault.common.cqrs.command import CommandResult
        return CommandResult(
            success=False,
            command_id=getattr(command, 'command_id', 'unknown'),
            error=f"Failed after {self.max_retries + 1} attempts: {last_error}",
        )


class IdempotencyMiddleware(CommandMiddleware):
    """Middleware for command idempotency.

    Results are memoized by ``command_id`` so a duplicate command returns the
    original result instead of re-executing the handler. To prevent unbounded
    memory growth the store is bounded by ``max_size`` (oldest entries evicted
    first, FIFO) and — when ``ttl`` is set — entries expire after that many
    seconds.
    """

    def __init__(self, store: Optional[dict] = None, max_size: int = 10000, ttl: Optional[float] = None):
        # Keep the caller's dict when provided (even if empty) so results can
        # be inspected or shared from outside; otherwise use a fresh dict.
        self._processed = store if store is not None else {}
        self._max_size = max(1, int(max_size))
        self._ttl = ttl
        self._expiry: dict = {}

    def _is_expired(self, command_id: str) -> bool:
        if self._ttl is None:
            return False
        exp = self._expiry.get(command_id)
        if exp is None:
            return False
        if time.monotonic() >= exp:
            self._processed.pop(command_id, None)
            self._expiry.pop(command_id, None)
            return True
        return False

    def _evict_one(self) -> None:
        # Python dicts (3.7+) preserve insertion order, so the first key is the
        # oldest. Only called when already at capacity.
        if len(self._processed) < self._max_size:
            return
        oldest = next(iter(self._processed))
        self._processed.pop(oldest, None)
        self._expiry.pop(oldest, None)

    async def execute(self, command: "Command", next_handler: Callable[..., Awaitable[CommandResult]]) -> "CommandResult":
        command_id = command.command_id

        # Return cached result when present and not expired.
        if command_id in self._processed and not self._is_expired(command_id):
            from pyfault.common.cqrs.command import CommandResult
            return CommandResult(
                success=True,
                command_id=command_id,
                metadata={"idempotent": True, "original": self._processed[command_id].to_dict()},
            )

        result = await next_handler(command)

        # Store successful results only; bound the store to avoid leaks.
        if result.success:
            self._evict_one()
            self._processed[command_id] = result
            if self._ttl is not None:
                self._expiry[command_id] = time.monotonic() + self._ttl

        return result


class TransactionMiddleware(CommandMiddleware):
    """Middleware for transactional command execution."""

    def __init__(self, transaction_manager: Any = None) -> None:
        self.transaction_manager = transaction_manager

    async def execute(self, command: "Command", next_handler: Callable[..., Awaitable[CommandResult]]) -> "CommandResult":
        if not self.transaction_manager:
            return await next_handler(command)

        async with self.transaction_manager.transaction():
            return await next_handler(command)


# Middleware chain builder
class MiddlewareChainBuilder:
    """Builder for middleware chains."""

    def __init__(self) -> None:
        self._middleware: list[Middleware] = []

    def add(self, middleware: Middleware) -> "MiddlewareChainBuilder":
        self._middleware.append(middleware)
        return self

    def add_logging(self, logger: Any = None) -> "MiddlewareChainBuilder":
        return self.add(LoggingMiddleware(logger))

    def add_validation(self, validators: Optional[dict] = None) -> "MiddlewareChainBuilder":
        return self.add(ValidationMiddleware(validators))

    def add_retry(self, max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0) -> "MiddlewareChainBuilder":
        return self.add(RetryMiddleware(max_retries, delay=delay, backoff=backoff))

    def add_idempotency(self, store: Any = None) -> "MiddlewareChainBuilder":
        return self.add(IdempotencyMiddleware(store))

    def add_transaction(self, transaction_manager: Any = None) -> "MiddlewareChainBuilder":
        return self.add(TransactionMiddleware(transaction_manager))

    def build(self, final_handler: Callable) -> "MiddlewareChain":
        return MiddlewareChain(self._middleware, final_handler)


# Decorators for middleware
def with_middleware(*middlewares: Middleware) -> Callable:
    """Decorator to add middleware to a handler."""
    def decorator(handler: Callable) -> Callable:
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
        self.command_bus = CommandBus()
        self.query_bus = QueryBus()
        self._command_middleware: list[CommandMiddleware] = []
        self._query_middleware: list[QueryMiddleware] = []

    def add_command_middleware(self, middleware: CommandMiddleware) -> None:
        self._command_middleware.append(middleware)

    def add_query_middleware(self, middleware: QueryMiddleware) -> None:
        self._query_middleware.append(middleware)

    def register_command_handler(self, handler: Any) -> None:
        self.command_bus.register(handler)

    def register_query_handler(self, handler: Any) -> None:
        self.query_bus.register(handler)

    async def dispatch_command(self, command: "Command") -> "CommandResult":
        # Apply command middleware chain
        chain = MiddlewareChain(self._command_middleware, self.command_bus.dispatch)
        result: CommandResult = await chain.execute(command)
        return result

    async def dispatch_query(self, query: "Query") -> "QueryResult":
        chain = MiddlewareChain(self._query_middleware, self.query_bus.dispatch)
        result: QueryResult = await chain.execute(query)
        return result

    async def dispatch(self, message: Any) -> Any:
        """Dispatch either a command or query based on type."""
        if hasattr(message, 'command_id'):
            return await self.dispatch_command(message)
        elif hasattr(message, 'query_id'):
            return await self.dispatch_query(message)
        else:
            raise ValueError("Message must be either a Command or Query")

    def register_command_middleware(self, middleware: CommandMiddleware) -> None:
        self._command_middleware.append(middleware)

    def register_query_middleware(self, middleware: QueryMiddleware) -> None:
        self._query_middleware.append(middleware)
