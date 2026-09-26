"""
Decorators for CQRS.
"""

import asyncio
from typing import Any, Callable, Optional, TypeVar, cast

from pyfault.common.cqrs.command import Command, CommandHandler, CommandResult
from pyfault.common.cqrs.query import Query, QueryHandler, QueryResult
from pyfault.common.eventsourcing.events import Event

C = TypeVar("C")
R = TypeVar("R")
Q = TypeVar("Q")


def command_handler(command_type: type) -> Callable:
    """Decorator to register a command handler."""
    def decorator(cls: Any) -> Any:
        return cls
    return decorator


def query_handler(query_type: type) -> Callable:
    """Decorator to register a query handler."""
    def decorator(cls: Any) -> Any:
        return cls
    return decorator


def command(command_type: type) -> Callable:
    """Decorator for creating command classes."""
    def decorator(cls: Any) -> Any:
        from dataclasses import dataclass
        cls = dataclass(cls)
        if not issubclass(cls, Command):
            raise TypeError("Command class must inherit from Command")
        return cls
    return decorator


def query(query_type: type) -> Callable:
    """Decorator for creating query classes."""
    def decorator(cls: Any) -> Any:
        from dataclasses import dataclass
        cls = dataclass(cls)
        if not issubclass(cls, Query):
            raise TypeError("Query class must inherit from Query")
        return cls
    return decorator


def handles(command_or_query_type: type) -> Callable:
    """Decorator to specify which command/query a handler handles."""
    def decorator(cls: Any) -> Any:
        cls._handles_type = command_or_query_type
        return cls
    return decorator


def validates(*command_or_query_types: type) -> Callable:
    """Decorator to add custom validation to a command/query."""
    def decorator(cls: Any) -> Any:
        cls._custom_validators = list(command_or_query_types)
        return cls
    return decorator


def emits(*event_types: type) -> Callable:
    """Decorator to declare which events a command emits."""
    def decorator(cls: Any) -> Any:
        cls._emits_events = list(event_types)
        return cls
    return decorator


def requires(*field_names: str) -> Callable:
    """Decorator to specify required fields for a command/query."""
    def decorator(cls: Any) -> Any:
        cls._required_fields = list(field_names)
        return cls
    return decorator


# Handler base classes with decorator support
class BaseCommandHandler(CommandHandler):
    """Base command handler with decorator support."""

    def __init__(self) -> None:
        self._handles_type = getattr(self, '_handles_type', None)

    @property
    def command_type(self) -> type:
        return cast(type, self._handles_type)


class BaseQueryHandler(QueryHandler):
    """Base query handler with decorator support."""

    def __init__(self) -> None:
        self._handles_type = getattr(self, '_handles_type', None)

    @property
    def query_type(self) -> type:
        return cast(type, self._handles_type)


# Helper functions for creating handlers
def create_command_handler(
    command_type: type,
    handler_func: Callable,
    validators: Optional[list[Callable]] = None,
    emits_events: Optional[list[type]] = None,
) -> CommandHandler:
    """Create a command handler from a function."""

    class DynamicCommandHandler(CommandHandler):
        @property
        def command_type(self) -> type:
            return command_type

        async def handle(self, command: Any) -> "CommandResult":
            # Validate
            if validators:
                for validator in validators:
                    errors = await validator(command) if asyncio.iscoroutinefunction(validator) else validator(command)
                    if errors:
                        from pyfault.common.cqrs.command import CommandResult
                        return CommandResult(
                            success=False,
                            command_id=command.command_id,
                            error=f"Validation failed: {', '.join(errors)}",
                        )

            # Execute handler
            result = await handler_func(command) if asyncio.iscoroutinefunction(handler_func) else handler_func(command)

            # Return result
            if isinstance(result, CommandResult):
                return result
            elif isinstance(result, list) and all(isinstance(e, Event) for e in result):
                return CommandResult(
                    success=True,
                    command_id=command.command_id,
                    events=result,
                )
            elif isinstance(result, Event):
                return CommandResult(
                    success=True,
                    command_id=command.command_id,
                    events=[result],
                )
            else:
                return CommandResult(
                    success=True,
                    command_id=command.command_id,
                    data=result,
                )

    return DynamicCommandHandler()


def create_query_handler(
    query_type: type,
    handler_func: Callable,
    validators: Optional[list[Callable]] = None,
) -> QueryHandler:
    """Create a query handler from a function."""

    class DynamicQueryHandler(QueryHandler):
        @property
        def query_type(self) -> type:
            return query_type

        async def handle(self, query: Any) -> "QueryResult":
            # Validate
            if validators:
                for validator in validators:
                    errors = await validator(query) if asyncio.iscoroutinefunction(validator) else validator(query)
                    if errors:
                        return QueryResult(
                            success=False,
                            query_id=query.query_id,
                            error=f"Validation failed: {', '.join(errors)}",
                        )

            # Execute handler
            result = await handler_func(query) if asyncio.iscoroutinefunction(handler_func) else handler_func(query)

            if isinstance(result, QueryResult):
                return result
            else:
                return QueryResult(
                    success=True,
                    query_id=query.query_id,
                    data=result,
                )

    return DynamicQueryHandler()


# Registry for auto-discovery
class HandlerRegistry:
    """Registry for command and query handlers."""

    def __init__(self) -> None:
        self._command_handlers: dict[type, CommandHandler] = {}
        self._query_handlers: dict[type, QueryHandler] = {}

    def register_command_handler(self, handler: CommandHandler) -> None:
        self._command_handlers[handler.command_type] = handler

    def register_query_handler(self, handler: QueryHandler) -> None:
        self._query_handlers[handler.query_type] = handler

    def get_command_handler(self, command_type: type) -> Optional[CommandHandler]:
        return self._command_handlers.get(command_type)

    def get_query_handler(self, query_type: type) -> Optional[QueryHandler]:
        return self._query_handlers.get(query_type)

    def get_all_command_handlers(self) -> dict[type, CommandHandler]:
        return self._command_handlers.copy()

    def get_all_query_handlers(self) -> dict[type, QueryHandler]:
        return self._query_handlers.copy()


# Global registry instance
_global_registry = HandlerRegistry()


def get_handler_registry() -> HandlerRegistry:
    """Get the global handler registry."""
    return _global_registry


def set_handler_registry(registry: HandlerRegistry) -> None:
    global _global_registry
    _global_registry = registry


def register_handler(handler: Any) -> Any:
    """Decorator to auto-register a handler."""
    if isinstance(handler, CommandHandler):
        _global_registry.register_command_handler(handler)
    elif isinstance(handler, QueryHandler):
        _global_registry.register_query_handler(handler)
    return handler
