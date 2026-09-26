"""
Event Sourcing for PyFault framework.
"""

from pyfault.common.eventsourcing.aggregate import (
    AggregateRoot,
    AggregateSnapshot,
    AggregateState,
    AggregateVersion,
)
from pyfault.common.eventsourcing.events import (
    DomainEvent,
    Event,
    EventFactory,
    EventMetadata,
    EventType,
)
from pyfault.common.eventsourcing.projection import (
    AggregationProjection,
    Projection,
    ProjectionManager,
    ProjectionType,
    ReadModelProjection,
)
from pyfault.common.eventsourcing.repository import EventSourcedRepository
from pyfault.common.eventsourcing.snapshot import (
    InMemorySnapshotStore,
    PostgresSnapshotStore,
    SnapshotStore,
)
from pyfault.common.eventsourcing.store import (
    EventStore,
    InMemoryEventStore,
    PostgresEventStore,
)

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
