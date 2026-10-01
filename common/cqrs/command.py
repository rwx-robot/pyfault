"""
Command and Command Handler for CQRS.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar

from pyfault.common.cqrs.core import CommandMiddleware
from pyfault.common.cqrs.middleware import MiddlewareChain
from pyfault.common.eventsourcing.events import Event
from pyfault.common.time import utc_now


class CommandStatus(str, Enum):
    """Command execution status."""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


C = TypeVar("C", bound="Command")
R = TypeVar("R")


@dataclass
class Command:
    """
    Base command class.

    A command represents an intent to change state.
    Commands are immutable and should be validated before execution.
    """
    command_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    aggregate_id: Optional[str] = None
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        command_id: Optional[str] = None,
        aggregate_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self.command_id = command_id or str(uuid.uuid4())
        self.aggregate_id = aggregate_id
        self.correlation_id = correlation_id
        self.causation_id = causation_id or self.command_id
        self.timestamp = timestamp or utc_now()
        self.metadata = metadata or {}
        # Apply subclass fields passed as keyword arguments
        for key, value in kwargs.items():
            setattr(self, key, value)

    def __post_init__(self) -> None:
        if not self.causation_id:
            self.causation_id = self.command_id

    def validate(self) -> list[str]:
        """Validate the command. Return list of validation errors."""
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "command_id": self.command_id,
            "aggregate_id": self.aggregate_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Command":
        return cls(
            command_id=data.get("command_id", str(uuid.uuid4())),
            aggregate_id=data.get("aggregate_id"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else utc_now(),
            metadata=data.get("metadata", {}),
        )


@dataclass
class CommandResult:
    """Result of command execution."""
    success: bool
    command_id: str
    aggregate_id: Optional[str] = None
    events: list[Event] = field(default_factory=list)
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    data: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "command_id": self.command_id,
            "aggregate_id": self.aggregate_id,
            "events": [e.to_dict() for e in self.events],
            "error": self.error,
            "metadata": self.metadata,
        }


class CommandHandler(ABC, Generic[C, R]):
    """
    Abstract base class for command handlers.

    A command handler contains the business logic for executing a command.
    """

    @property
    @abstractmethod
    def command_type(self) -> type[C]:
        """The type of command this handler handles."""
        pass

    @abstractmethod
    async def handle(self, command: C) -> CommandResult:
        """Execute the command and return result."""
        pass

    async def validate(self, command: C) -> list[str]:
        """Validate the command before execution."""
        return command.validate()

    def can_handle(self, command: Command) -> bool:
        """Check if this handler can handle the given command."""
        return isinstance(command, self.command_type)


class CommandBus:
    """
    Command bus for dispatching commands to handlers.

    The command bus routes commands to their registered handlers
    and manages the command execution pipeline.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Command], CommandHandler] = {}
        self._middleware: list[CommandMiddleware] = []
        self._default_handler: Optional[CommandHandler] = None

    def register(self, handler: CommandHandler) -> None:
        """Register a command handler."""
        self._handlers[handler.command_type] = handler

    def unregister(self, command_type: type[Command]) -> bool:
        """Unregister a command handler."""
        if command_type in self._handlers:
            del self._handlers[command_type]
            return True
        return False

    def add_middleware(self, middleware: "CommandMiddleware") -> None:
        """Add middleware to the command pipeline."""
        self._middleware.append(middleware)

    def set_default_handler(self, handler: CommandHandler) -> None:
        """Set default handler for unregistered commands."""
        self._default_handler = handler

    async def dispatch(self, command: Command) -> CommandResult:
        """Dispatch a command to its handler."""
        # Validate command
        errors = command.validate()
        if errors:
            return CommandResult(
                success=False,
                command_id=command.command_id,
                error=f"Validation failed: {', '.join(errors)}",
            )

        # Find handler
        handler = self._handlers.get(type(command))
        if not handler:
            if self._default_handler:
                handler = self._default_handler
            else:
                return CommandResult(
                    success=False,
                    command_id=command.command_id,
                    error=f"No handler registered for command type: {type(command).__name__}",
                )

        # Apply middleware chain
        async def execute_handler(cmd: Command) -> CommandResult:
            return await handler.handle(cmd)

        # Build middleware chain
        chain = MiddlewareChain(self._middleware, execute_handler)
        result: CommandResult = await chain.execute(command)
        return result

    async def dispatch_batch(self, commands: list[Command]) -> list[CommandResult]:
        """Dispatch multiple commands."""
        results = []
        for command in commands:
            result = await self.dispatch(command)
            results.append(result)
        return results


def command(cls: Optional[type] = None, *, command_type: Optional[type[Command]] = None) -> Callable[..., Any]:
    """Decorator for creating command classes."""
    def decorator(cls: type) -> type:
        # Only skip when THIS class declares its own fields
        # (hasattr would match fields inherited from the Command base)
        if "__dataclass_fields__" not in cls.__dict__:
            cls = dataclass(cls)
        # Ensure it inherits from Command
        if not issubclass(cls, Command):
            raise TypeError("Command class must inherit from Command")
        return cls

    if cls is None:
        return decorator
    return decorator(cls)


# Built-in commands
@command
@dataclass
class CreateEntityCommand(Command):
    """Command to create a new entity."""
    entity_type: str = field(default="")
    payload: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.entity_type:
            errors.append("entity_type is required")
        if not self.payload:
            errors.append("payload is required")
        return errors


@command
@dataclass
class UpdateEntityCommand(Command):
    """Command to update an existing entity."""
    entity_type: str = field(default="")
    entity_id: str = field(default="")
    payload: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.entity_type:
            errors.append("entity_type is required")
        if not self.entity_id:
            errors.append("entity_id is required")
        return errors


@command
@dataclass
class DeleteEntityCommand(Command):
    """Command to delete an entity."""
    entity_type: str = field(default="")
    entity_id: str = field(default="")

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.entity_type:
            errors.append("entity_type is required")
        if not self.entity_id:
            errors.append("entity_id is required")
        return errors
