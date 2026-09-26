"""
Projections for Event Sourcing.
"""

import asyncio
import contextlib
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from pyfault.common.eventsourcing.events import Event
from pyfault.common.eventsourcing.store import EventStore, InMemoryEventStore


class ProjectionType(str, Enum):
    """Projection types."""
    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"
    ON_DEMAND = "on_demand"


@dataclass
class ProjectionStatus:
    """Projection status information."""
    name: str
    type: ProjectionType
    last_event_id: Optional[str] = None
    last_processed_timestamp: Optional[datetime] = None
    events_processed: int = 0
    errors: int = 0
    last_error: Optional[str] = None
    is_running: bool = False
    last_updated: datetime = field(default_factory=datetime.utcnow)


class Projection(ABC):
    """
    Base class for projections.

    Projections transform events into read models optimized for specific queries.
    """

    def __init__(
        self,
        name: str,
        event_types: Optional[list[str]] = None,
        projection_type: ProjectionType = ProjectionType.SYNCHRONOUS,
    ):
        self.name = name
        self.event_types = event_types or []
        self.projection_type = projection_type
        self.status = ProjectionStatus(name=name, type=projection_type)
        self._handlers: dict[str, Callable] = {}
        self._is_running = False

    def handles(self, event_type: str) -> bool:
        """Check if this projection handles the given event type."""
        return not self.event_types or event_type in self.event_types

    def register_handler(self, event_type: str, handler: Callable) -> None:
        """Register an event handler."""
        self._handlers[event_type] = handler

    def unregister_handler(self, event_type: str) -> None:
        """Unregister an event handler."""
        self._handlers.pop(event_type, None)

    async def handle_event(self, event: Event) -> None:
        """Handle an event."""
        if not self.handles(event.event_type):
            return

        handler = self._handlers.get(event.event_type)
        if handler:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception as e:
                self.status.errors += 1
                self.status.last_error = str(e)
                self.status.last_updated = datetime.utcnow()
                raise

        self.status.events_processed += 1
        self.status.last_event_id = getattr(event.metadata, 'event_id', None)
        self.status.last_processed_timestamp = datetime.utcnow()
        self.status.last_updated = datetime.utcnow()

    @abstractmethod
    async def project(self, event: Event) -> None:
        """Project an event - to be implemented by subclasses."""
        pass

    def get_state(self) -> dict[str, Any]:
        """Get projection state for persistence."""
        return {
            "name": self.name,
            "type": self.projection_type.value,
            "last_event_id": self.status.last_event_id,
            "last_processed_timestamp": self.status.last_processed_timestamp.isoformat() if self.status.last_processed_timestamp else None,
            "events_processed": self.status.events_processed,
            "errors": self.status.errors,
        }

    def restore_state(self, state: dict[str, Any]) -> None:
        """Restore projection state."""
        self.status.last_event_id = state.get("last_event_id")
        self.status.last_processed_timestamp = datetime.fromisoformat(state["last_processed_timestamp"]) if state.get("last_processed_timestamp") else None
        self.status.events_processed = state.get("events_processed", 0)
        self.status.errors = state.get("errors", 0)


class ReadModelProjection(Projection):
    """
    Projection that builds a read model (denormalized view).
    """

    def __init__(self, name: str, event_types: Optional[list[str]] = None):
        super().__init__(name, event_types)
        self._data: dict[str, Any] = {}
        self._indexes: dict[str, dict] = defaultdict(dict)

    def register_handler(self, event_type: str, handler: Callable) -> None:
        self._handlers[event_type] = handler

    async def project(self, event: Event) -> None:
        """Project event by calling registered handler."""
        await self.handle_event(event)

    def get(self, key: str) -> Optional[Any]:
        """Get entity by key."""
        return self._data.get(key)

    def get_all(self) -> list[Any]:
        return list(self._data.values())

    def query(self, filters: Optional[dict[str, Any]] = None) -> list[Any]:
        """Query entities with filters."""
        results = list(self._data.values())

        if filters:
            for key, value in filters.items():
                results = [item for item in results if item.get(key) == value]

        return results

    def _upsert(self, key: str, entity: dict[str, Any]) -> None:
        self._data[key] = entity
        # Update indexes
        for index_name, index in self._indexes.items():
            if index_name in entity:
                index[entity[index_name]] = key

    def _delete(self, key: str) -> None:
        if key in self._data:
            entity = self._data[key]
            # Remove from indexes
            for index_name, index in self._indexes.items():
                if index_name in entity:
                    index.pop(entity[index_name], None)
            del self._data[key]

    def create_index(self, field_name: str) -> None:
        """Create an index on a field."""
        if field_name not in self._indexes:
            self._indexes[field_name] = {}
            # Rebuild index
            for key, entity in self._data.items():
                if field_name in entity:
                    self._indexes[field_name][entity[field_name]] = key

    def get_by_index(self, field_name: str, value: Any) -> Optional[dict]:
        """Get entity by indexed field."""
        index = self._indexes.get(field_name)
        if not index:
            return None
        key = index.get(value)
        return self._data.get(key) if key else None


class AggregationProjection(Projection):
    """
    Projection that computes aggregated values.
    """

    def __init__(
        self,
        name: str,
        event_types: Optional[list[str]] = None,
        aggregation_functions: Optional[dict[str, Callable]] = None,
    ):
        super().__init__(name, event_types)
        self._aggregations: dict[str, Any] = {}
        self._aggregation_functions = aggregation_functions or {}
        self._events: list[Event] = []

    def register_aggregation(self, name: str, func: Callable) -> None:
        """Register an aggregation function."""
        self._aggregation_functions[name] = func

    async def handle_event(self, event: Event) -> None:
        """Handle an event and update aggregations."""
        if not self.handles(event.event_type):
            return

        # Store event for aggregation computation
        self._events.append(event)

        # Recompute aggregations
        for name, func in self._aggregation_functions.items():
            try:
                self._aggregations[name] = func(self._events)
            except Exception as e:
                self.status.errors += 1
                self.status.last_error = str(e)
                self.status.last_updated = datetime.utcnow()

        # Call parent handle_event for status updates
        await super().handle_event(event)

    async def project(self, event: Event) -> None:
        await self.handle_event(event)

    def get_aggregation(self, name: str) -> Any:
        return self._aggregations.get(name)

    def get_all_aggregations(self) -> dict[str, Any]:
        return self._aggregations.copy()


class ProjectionManager:
    """
    Manages multiple projections.
    """

    def __init__(self, event_store: Optional[EventStore] = None):
        self.event_store = event_store or InMemoryEventStore()
        self._projections: dict[str, Projection] = {}
        self._running = False
        self._processing_task: Optional[asyncio.Task] = None
        self._poll_interval = 1.0  # seconds

    def register(self, projection: Projection) -> None:
        """Register a projection."""
        self._projections[projection.name] = projection

    def unregister(self, name: str) -> bool:
        """Unregister a projection."""
        if name in self._projections:
            del self._projections[name]
            return True
        return False

    def get_projection(self, name: str) -> Optional[Projection]:
        """Get a projection by name."""
        return self._projections.get(name)

    def get_all_projections(self) -> list[Projection]:
        return list(self._projections.values())

    def get_status(self) -> dict[str, ProjectionStatus]:
        """Get status of all projections."""
        return {name: p.status for name, p in self._projections.items()}

    async def process_event(self, event: Event) -> None:
        """Process a single event through all relevant projections."""
        for projection in self._projections.values():
            if projection.handles(event.event_type):
                await projection.handle_event(event)

    async def process_events_batch(self, events: list) -> None:
        """Process a batch of events."""
        for event in events:
            await self.process_event(event)

    async def start(self, poll_interval: float = 1.0) -> None:
        """Start the projection manager (for async projections)."""
        self._running = True
        self._poll_interval = 1.0
        self._processing_task = asyncio.create_task(self._process_loop())

    async def stop(self) -> None:
        """Stop the projection manager."""
        self._running = False
        if self._processing_task:
            self._processing_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._processing_task

    async def _process_loop(self) -> None:
        """Background processing loop for async projections."""
        while self._running:
            try:
                # Process async projections
                for projection in self._projections.values():
                    if projection.projection_type == ProjectionType.ASYNCHRONOUS and projection.status.is_running:
                        # Would fetch and process new events here
                        pass

                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Projection manager error: {e}")
                await asyncio.sleep(self._poll_interval)

    async def replay(
        self,
        projection_name: str,
        from_event_id: Optional[str] = None,
        from_timestamp: Optional[datetime] = None,
    ) -> None:
        """Replay events for a specific projection."""
        projection = self._projections.get(projection_name)
        if not projection:
            raise ValueError(f"Projection not found: {projection_name}")

        # Reset projection state
        projection.status = ProjectionStatus(
            name=projection.name,
            type=projection.projection_type,
        )

        # Fetch and process events
        events = await self.event_store.get_all_events(
            from_timestamp=projection.status.last_processed_timestamp,
        )

        await self.process_events_batch(events)

    def get_projection_state(self, name: str) -> Optional[dict[str, Any]]:
        """Get serialized projection state."""
        projection = self._projections.get(name)
        if not projection:
            return None
        return projection.get_state()

    def restore_projection_state(self, name: str, state: dict[str, Any]) -> bool:
        """Restore projection state."""
        projection = self._projections.get(name)
        if not projection:
            return False
        projection.restore_state(state)
        return True


class EventHandlerRegistry:
    """Registry for event handlers across projections."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable]] = defaultdict(list)

    def register(self, event_type: str, handler: Callable) -> None:
        """Register a handler for an event type."""
        self._handlers[event_type].append(handler)

    def unregister(self, event_type: str, handler: Callable) -> bool:
        """Unregister a handler."""
        if event_type in self._handlers:
            try:
                self._handlers[event_type].remove(handler)
                return True
            except ValueError:
                pass
        return False

    def get_handlers(self, event_type: str) -> list[Callable]:
        return self._handlers.get(event_type, [])

    def handle_event(self, event: Event) -> list[Any]:
        """Execute all handlers for an event."""
        results = []
        for handler in self._handlers.get(event.event_type, []):
            try:
                result = handler(event)
                if asyncio.iscoroutinefunction(handler):
                    # Would need to be awaited in async context
                    pass
                results.append(result)
            except Exception:
                pass
        return results
