"""
Core CQRS types and utilities.
"""

from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, TypeVar

T = TypeVar("T")
R = TypeVar("R")


class Middleware(ABC):
    """Base middleware class."""

    @abstractmethod
    async def execute(self, message: Any, next_handler: Callable) -> Any:
        """Execute middleware logic."""
        pass


class CommandMiddleware:
    """Middleware for command processing."""

    async def execute(self, command: Any, next_handler: Callable) -> Any:
        return await next_handler(command)


class QueryMiddleware:
    """Middleware for query processing."""

    async def execute(self, query: Any, next_handler: Callable) -> Any:
        return await next_handler(query)


class MiddlewareChain:
    """Chain of middleware for command/query processing."""

    def __init__(self, middleware: list, final_handler: Callable):
        self._middleware = middleware
        self._final_handler = final_handler

    async def execute(self, message: Any) -> Any:
        """Execute the middleware chain."""
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
class LoggingMiddleware:
    """Middleware for logging commands/queries."""

    def __init__(self, logger: Any = None):
        self.logger = logger or print

    async def execute(self, message: Any, next_handler: Callable) -> Any:
        import time
        start = time.time()

        msg_type = "Command" if hasattr(message, 'command_id') else "Query"
        self.logger(f"[{msg_type}] {type(message).__name__} [{getattr(message, 'command_id', getattr(message, 'query_id', 'unknown'))}] - START")

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


class ValidationMiddleware:
    """Middleware for additional validation."""

    def __init__(self, validators: Optional[dict] = None):
        self.validators = validators or {}

    async def execute(self, command: Any, next_handler: Callable) -> Any:
        # Run custom validators
        validator = self.validators.get(type(command))
        if validator:
            errors = await validator(command) if callable(validator) and __import__('asyncio').iscoroutinefunction(validator) else validator(command)
            if errors:
                return type('CommandResult', (), {
                    'success': False,
                    'command_id': command.command_id,
                    'error': f"Custom validation failed: {', '.join(errors)}",
                })()

        return await next_handler(command)


class RetryMiddleware:
    """Middleware for retrying failed commands."""

    def __init__(self, max_retries: int = 3, delay: float = 1.0, backoff: float = 2.0):
        self.max_retries = max_retries
        self.delay = delay
        self.backoff = backoff

    async def execute(self, command: Any, next_handler: Callable) -> Any:
        last_error = None
        delay = self.delay

        for attempt in range(self.max_retries + 1):
            try:
                result = await next_handler(command)
                if result.success:
                    return result
                last_error = result.error
            except Exception as e:
                last_error = str(e)

            if attempt < self.max_retries:
                import asyncio
                await asyncio.sleep(delay)
                delay *= self.backoff

        return type('CommandResult', (), {
            'success': False,
            'command_id': getattr(command, 'command_id', 'unknown'),
            'error': f"Failed after {self.max_retries + 1} attempts: {last_error}",
        })()


class IdempotencyMiddleware:
    """Middleware for command idempotency."""

    def __init__(self, store: Optional[dict] = None):
        # Keep the caller's dict when provided (even if empty) so results
        # can be inspected or shared from outside.
        self._processed = store if store is not None else {}

    async def execute(self, command: Any, next_handler: Callable) -> Any:
        # Check if command was already processed
        if command.command_id in self._processed:
            return type('CommandResult', (), {
                'success': True,
                'command_id': command.command_id,
                'metadata': {"idempotent": True, "original": self._processed[command.command_id].__dict__},
            })()

        result = await next_handler(command)

        # Store successful results
        if result.success:
            self._processed[command.command_id] = result

        return result


class TransactionMiddleware:
    """Middleware for transactional command execution."""

    def __init__(self, transaction_manager: Any = None):
        self.transaction_manager = transaction_manager

    async def execute(self, command: Any, next_handler: Callable) -> Any:
        if not self.transaction_manager:
            return await next_handler(command)

        async with self.transaction_manager.transaction():
            return await next_handler(command)


# Middleware chain builder
class MiddlewareChainBuilder:
    """Builder for middleware chains."""

    def __init__(self) -> None:
        self._middleware: list[Any] = []

    def add(self, middleware: Any) -> "MiddlewareChainBuilder":
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
