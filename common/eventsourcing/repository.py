"""
Event Sourced Repository for Event Sourcing.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar, Generic, Callable
from abc import ABC

from pyfault.common.eventsourcing.events import Event, DomainEvent, EventMetadata
from pyfault.common.eventsourcing.store import EventStore, InMemoryEventStore
from pyfault.common.eventsourcing.aggregate import AggregateRoot, AggregateSnapshot, AggregateState
from pyfault.common.eventsourcing.events import Event


A = TypeVar("A", bound="AggregateRoot")


@dataclass
class RepositoryOptions:
    """Options for event sourced repository."""
    snapshot_interval: int = 100  # Create snapshot every N events
    enable_snapshots: bool = True
    max_events_per_read: int = 1000


class EventSourcedRepository(Generic[A]):
    """
    Repository for event sourced aggregates.
    
    Handles loading/saving aggregates from/to the event store.
    Supports snapshotting for performance.
    """
    
    def __init__(
        self,
        aggregate_class: Type[A],
        event_store: Optional[EventStore] = None,
        options: Optional[RepositoryOptions] = None,
    ):
        self.aggregate_class = aggregate_class
        self.event_store = event_store or InMemoryEventStore()
        self.options = options or RepositoryOptions()
        self._snapshots: Dict[str, Any] = {}  # In-memory snapshot cache

    async def get(self, aggregate_id: str) -> Optional[A]:
        """Load an aggregate by ID."""
        # Try to load from snapshot first
        snapshot = await self._load_snapshot(aggregate_id)
        
        if snapshot and self.options.enable_snapshots:
            aggregate = self._create_aggregate(aggregate_id)
            aggregate.restore_from_snapshot(snapshot)
            from_version = snapshot.version
        else:
            aggregate = self._create_aggregate(aggregate_id)
            from_version = 0
        
        # Load events from event store
        events = await self.event_store.get_events(
            aggregate_id,
            from_version=snapshot.version if snapshot else 0,
        )
        
        # Apply events to rebuild state
        for event in events:
            if aggregate.can_apply_event(event):
                aggregate._apply_event(event)
        
        if aggregate.state == AggregateState.NEW and not aggregate.has_uncommitted_events():
            return None
        
        return aggregate

    async def get_by_correlation_id(self, correlation_id: str) -> List[A]:
        """Get aggregates by correlation ID."""
        events = await self.event_store.get_events_by_correlation_id(correlation_id)
        
        aggregates = {}
        for event in events:
            aggregate_id = event.aggregate_id
            if aggregate_id not in aggregates:
                aggregate = await self.get(aggregate_id)
                if aggregate:
                    aggregates[aggregate_id] = aggregate
        
        return list(aggregates.values())

    async def save(self, aggregate: A) -> None:
        """Save aggregate by persisting uncommitted events."""
        if not aggregate.has_uncommitted_events():
            return
        
        events = aggregate.uncommitted_events
        
        # Persist events to event store
        await self.event_store.append(events)
        
        # Mark events as committed
        aggregate.mark_committed(events)
        
        # Create snapshot if needed
        if self.options.enable_snapshots and self._should_snapshot(aggregate):
            await self._save_snapshot(aggregate)

    async def _load_snapshot(self, aggregate_id: str) -> Optional["AggregateSnapshot"]:
        """Load latest snapshot for aggregate."""
        # Check in-memory cache first
        cache_key = f"{self.aggregate_class.__name__}:{aggregate_id}"
        if cache_key in self._snapshots:
            return self._snapshots[cache_key]
        return None

    async def _save_snapshot(self, aggregate: A) -> None:
        """Save aggregate snapshot."""
        if not self.options.enable_snapshots:
            return
        
        if aggregate.version - (aggregate._snapshot_version or 0) >= self.options.snapshot_interval:
            snapshot = aggregate.create_snapshot()
            
            # Cache in memory
            cache_key = f"{self.aggregate_class.__name__}:{aggregate.id}"
            self._snapshots[cache_key] = snapshot
            
            # In production, would persist to snapshot store
            # await self.snapshot_store.save(snapshot)

    def _should_snapshot(self, aggregate) -> bool:
        if not self.options.enable_snapshots:
            return False
        
        last_snapshot = aggregate._snapshot_version or 0
        return aggregate.version - last_snapshot >= self.options.snapshot_interval

    def _create_aggregate(self, aggregate_id: str = None) -> A:
        return self.aggregate_class(aggregate_id)


class AggregateRepository(Generic[A]):
    """
    Simplified repository interface for aggregates.
    """
    
    def __init__(
        self,
        aggregate_class: Type[A],
        event_store: Optional[EventStore] = None,
    ):
        self._repository = EventSourcedRepository(
            aggregate_class=aggregate_class,
            event_store=event_store or InMemoryEventStore(),
        )
    
    async def get(self, aggregate_id: str) -> Optional[A]:
        return await self._repository.get(aggregate_id)
    
    async def save(self, aggregate: A) -> None:
        await self._repository.save(aggregate)
    
    async def get_by_correlation_id(self, correlation_id: str) -> List[A]:
        return await self._repository.get_by_correlation_id(correlation_id)


class AggregateFactory:
    """Factory for creating aggregate instances."""
    
    def __init__(self):
        self._aggregate_types: Dict[str, Type[AggregateRoot]] = {}
        self._factories: Dict[str, Callable] = {}
    
    def register(self, aggregate_type: str, aggregate_class: Type[AggregateRoot]) -> None:
        """Register an aggregate type."""
        self._aggregate_types[aggregate_type] = aggregate_class
    
    def register_factory(self, aggregate_type: str, factory: Callable) -> None:
        """Register a custom factory function."""
        self._factories[aggregate_type] = factory
    
    def create(self, aggregate_type: str, aggregate_id: str = None, **kwargs) -> AggregateRoot:
        """Create a new aggregate instance."""
        if aggregate_type in self._factories:
            return self._factories[aggregate_type](aggregate_id=aggregate_id, **kwargs)
        
        if aggregate_type in self._aggregate_types:
            aggregate_class = self._aggregate_types[aggregate_type]
            return aggregate_class(aggregate_id=aggregate_id, **kwargs)
        
        raise ValueError(f"Unknown aggregate type: {aggregate_type}")
    
    def get_aggregate_class(self, aggregate_type: str) -> Optional[type]:
        return self._aggregate_types.get(aggregate_type)


class RepositoryManager:
    """
    Manages multiple repositories.
    """
    
    def __init__(self, event_store: Optional[EventStore] = None):
        self.event_store = event_store or InMemoryEventStore()
        self._repositories: Dict[str, EventSourcedRepository] = {}
    
    def get_repository(self, aggregate_class: Type[A]) -> EventSourcedRepository:
        """Get or create repository for aggregate class."""
        key = aggregate_class.__name__
        
        if key not in self._repositories:
            self._repositories[key] = EventSourcedRepository(
                aggregate_class=aggregate_class,
                event_store=self.event_store,
            )
        
        return self._repositories[key]
    
    def register_aggregate(self, aggregate_type: str, aggregate_class: Type[AggregateRoot]) -> None:
        """Register an aggregate type."""
        key = aggregate_type
        self._repositories[key] = EventSourcedRepository(
            aggregate_class=aggregate_class,
            event_store=self.event_store,
        )
    
    async def save_all(self, aggregates: List[AggregateRoot]) -> None:
        """Save multiple aggregates in a single transaction."""
        all_events = []
        for aggregate in aggregates:
            if aggregate.has_uncommitted_events():
                all_events.extend(aggregate.uncommitted_events)
        
        if all_events:
            await self._event_store.append(all_events)
            
            for aggregate in aggregates:
                aggregate.mark_committed(aggregate.uncommitted_events)