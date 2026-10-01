"""
Aggregate Root for Event Sourcing.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, TypeVar

from pyfault.common.eventsourcing.events import (
    DomainEvent,
    Event,
    EventFactory,
    EventMetadata,
)
from pyfault.common.time import utc_now


class AggregateState(str, Enum):
    """Aggregate lifecycle states."""
    NEW = "new"
    ACTIVE = "active"
    DELETED = "deleted"
    ARCHIVED = "archived"


A = TypeVar("A", bound="AggregateRoot")


@dataclass
class AggregateVersion:
    """Aggregate version information."""
    version: int = 0
    last_event_id: Optional[str] = None
    last_updated: datetime = field(default_factory=utc_now)

    def increment(self, event_id: str) -> "AggregateVersion":
        return AggregateVersion(
            version=self.version + 1,
            last_event_id=event_id,
            last_updated=utc_now(),
        )


class AggregateRoot(ABC):
    """
    Base class for aggregate roots in Event Sourcing.

    An aggregate root is the entry point to a cluster of related objects (aggregate).
    It ensures consistency within the aggregate by controlling all modifications.
    """

    def __init__(
        self,
        aggregate_id: Optional[str] = None,
        aggregate_type: Optional[str] = None,
    ):
        self._id = aggregate_id or str(uuid.uuid4())
        self._aggregate_type = aggregate_type or self.__class__.__name__
        self._version = 0
        self._state = AggregateState.NEW
        self._uncommitted_events: list[Event] = []
        self._applied_events: list[str] = []
        self._snapshot_version: Optional[int] = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def aggregate_type(self) -> str:
        return self._aggregate_type

    @property
    def version(self) -> int:
        return self._version

    @property
    def state(self) -> AggregateState:
        return self._state

    @property
    def uncommitted_events(self) -> list[Event]:
        return self._uncommitted_events.copy()

    def mark_committed(self, events: list[Event]) -> None:
        """Mark events as committed after successful persistence."""
        for event in events:
            self._applied_events.append(event.metadata.event_id)
        self._uncommitted_events = [e for e in self._uncommitted_events if e not in events]

    @property
    def uncommitted_count(self) -> int:
        return len(self._uncommitted_events)

    def has_uncommitted_events(self) -> bool:
        return len(self._uncommitted_events) > 0

    def _apply_event(self, event: Event) -> None:
        """Apply an event to the aggregate (for rebuilding from history)."""
        self._version = event.version
        self._apply_event_internal(event)
        self._applied_events.append(event.metadata.event_id)

    def _emit_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        metadata: Optional[EventMetadata] = None,
    ) -> Event:
        """Emit a new event from the aggregate."""
        self._version += 1

        event = EventFactory.create_event(
            aggregate_id=self._id,
            aggregate_type=self._aggregate_type,
            event_type=event_type,
            payload=payload,
            version=self._version,
            metadata=metadata,
        )

        self._apply_event_internal(event)
        self._uncommitted_events.append(event)

        return event

    def _emit_domain_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        aggregate_root_id: str,
        metadata: Optional[EventMetadata] = None,
    ) -> "DomainEvent":
        """Emit a domain event."""
        self._version += 1

        event = EventFactory.create_domain_event(
            aggregate_id=self._id,
            aggregate_type=self._aggregate_type,
            event_type=event_type,
            payload=payload,
            version=self._version,
            aggregate_root_id=aggregate_root_id,
            metadata=metadata,
        )

        self._apply_event_internal(event)
        self._uncommitted_events.append(event)

        return event

    @abstractmethod
    def _apply_event_internal(self, event: Event) -> None:
        """Apply event to aggregate state - must be implemented by subclass."""
        pass

    # Snapshot support
    def create_snapshot(self) -> "AggregateSnapshot":
        """Create a snapshot of the current aggregate state."""
        return AggregateSnapshot(
            aggregate_id=self._id,
            aggregate_type=self._aggregate_type,
            version=self._version,
            state=self._get_state(),
            timestamp=utc_now(),
        )

    def restore_from_snapshot(self, snapshot: "AggregateSnapshot") -> None:
        """Restore aggregate from a snapshot."""
        self._version = snapshot.version
        self._snapshot_version = snapshot.version
        self._restore_state(snapshot.state)

    @abstractmethod
    def _get_state(self) -> dict[str, Any]:
        """Get the current state for snapshotting."""
        pass

    @abstractmethod
    def _restore_state(self, state: dict[str, Any]) -> None:
        """Restore state from snapshot."""
        pass

    def can_apply_event(self, event: Event) -> bool:
        """Check if an event can be applied."""
        return event.aggregate_id == self._id and event.aggregate_type == self._aggregate_type


@dataclass
class AggregateSnapshot:
    """Snapshot of aggregate state."""
    aggregate_id: str
    aggregate_type: str
    version: int
    state: dict[str, Any]
    timestamp: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "version": self.version,
            "state": self.state,
            "timestamp": self.timestamp.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AggregateSnapshot":
        return cls(
            aggregate_id=data["aggregate_id"],
            aggregate_type=data["aggregate_type"],
            version=data["version"],
            state=data["state"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )
