"""
Event Sourcing for PyFault framework.
"""

from pyfault.common.eventsourcing.store import EventStore, InMemoryEventStore, PostgresEventStore
from pyfault.common.eventsourcing.aggregate import AggregateRoot, AggregateVersion, AggregateState, AggregateSnapshot
from pyfault.common.eventsourcing.events import Event, DomainEvent, EventMetadata, EventFactory, EventType
from pyfault.common.eventsourcing.repository import EventSourcedRepository
from pyfault.common.eventsourcing.projection import Projection, ProjectionManager, ReadModelProjection, AggregationProjection, ProjectionType
from pyfault.common.eventsourcing.snapshot import SnapshotStore, InMemorySnapshotStore, PostgresSnapshotStore

__all__ = [
    "EventStore",
    "InMemoryEventStore",
    "PostgresEventStore",
    "AggregateRoot",
    "AggregateVersion",
    "AggregateState",
    "AggregateSnapshot",
    "Event",
    "DomainEvent",
    "EventMetadata",
    "EventFactory",
    "EventType",
    "EventSourcedRepository",
    "Projection",
    "ProjectionManager",
    "ReadModelProjection",
    "AggregationProjection",
    "ProjectionType",
    "SnapshotStore",
    "InMemorySnapshotStore",
    "PostgresSnapshotStore",
]