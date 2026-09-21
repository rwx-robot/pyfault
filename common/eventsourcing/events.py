"""
Event definitions for Event Sourcing.
"""

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar
from enum import Enum


class EventType(str, Enum):
    """Standard event types."""
    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    STATE_CHANGED = "state_changed"


@dataclass
class EventMetadata:
    """Metadata for an event."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    tags: Dict[str, str] = field(default_factory=dict)
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "timestamp": self.timestamp.isoformat(),
            "user_id": self.user_id,
            "session_id": self.session_id,
            "tags": self.tags,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventMetadata":
        return cls(
            event_id=data.get("event_id", str(uuid.uuid4())),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.utcnow(),
            user_id=data.get("user_id"),
            session_id=data.get("session_id"),
            tags=data.get("tags", {}),
            ip_address=data.get("ip_address"),
            user_agent=data.get("user_agent"),
        )


E = TypeVar("E", bound="Event")


@dataclass
class Event(ABC):
    """Base event class."""
    aggregate_id: str
    aggregate_type: str
    event_type: str
    version: int
    metadata: EventMetadata = field(default_factory=EventMetadata)
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.metadata.event_id,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "event_type": self.event_type,
            "version": self.version,
            "timestamp": self.metadata.timestamp.isoformat(),
            "correlation_id": self.metadata.correlation_id,
            "causation_id": self.metadata.causation_id,
            "user_id": self.metadata.user_id,
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls: Type[E], data: Dict[str, Any]) -> E:
        return cls(
            aggregate_id=data["aggregate_id"],
            aggregate_type=data["aggregate_type"],
            event_type=data["event_type"],
            version=data["version"],
            metadata=EventMetadata.from_dict(data) if "event_id" in data else EventMetadata(),
            payload=data.get("payload", {}),
        )

    @classmethod
    def from_json(cls: Type[E], json_str: str) -> E:
        return cls.from_dict(json.loads(json_str))


@dataclass
class DomainEvent(Event):
    """Domain event with aggregate root reference."""
    aggregate_root_id: str = ""

    def __post_init__(self):
        if not self.aggregate_root_id:
            self.aggregate_root_id = self.aggregate_id


class EventFactory:
    """Factory for creating events."""

    @staticmethod
    def create_event(
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        payload: Dict[str, Any],
        version: int,
        metadata: Optional[EventMetadata] = None,
    ) -> Event:
        return Event(
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            event_type=event_type,
            version=version,
            metadata=metadata or EventMetadata(),
            payload=payload,
        )

    @staticmethod
    def create_domain_event(
        aggregate_id: str,
        aggregate_type: str,
        event_type: str,
        payload: Dict[str, Any],
        version: int,
        aggregate_root_id: str,
        metadata: Optional[EventMetadata] = None,
    ) -> DomainEvent:
        return DomainEvent(
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            event_type=event_type,
            version=version,
            metadata=metadata or EventMetadata(),
            payload=payload,
            aggregate_root_id=aggregate_root_id,
        )


class EventSerializer:
    """Serializer for events."""

    @staticmethod
    def serialize(event: Event) -> str:
        return event.to_json()

    @staticmethod
    def deserialize(event_type: Type[Event], data: str) -> Event:
        return Event.from_json(data)

    @staticmethod
    def serialize_batch(events: List[Event]) -> str:
        return json.dumps([e.to_dict() for e in events])

    @staticmethod
    def deserialize_batch(event_type: Type[Event], data: str) -> List[Event]:
        return [Event.from_dict(e) for e in json.loads(data)]