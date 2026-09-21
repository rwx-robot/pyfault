"""
Event Store for Event Sourcing.
"""

import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, TypeVar
from enum import Enum

from pyfault.common.eventsourcing.events import Event, DomainEvent, EventMetadata


E = TypeVar("E", bound="Event")


class EventStoreType(str, Enum):
    """Event store types."""
    MEMORY = "memory"
    POSTGRES = "postgres"
    MONGODB = "mongodb"
    REDIS = "redis"


@dataclass
class StoredEvent:
    """Event as stored in the event store."""
    event_id: str
    aggregate_id: str
    aggregate_type: str
    event_type: str
    version: int
    timestamp: datetime
    correlation_id: Optional[str]
    causation_id: Optional[str]
    user_id: Optional[str]
    payload: Dict
    metadata: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "aggregate_id": self.aggregate_id,
            "aggregate_type": self.aggregate_type,
            "event_type": self.event_type,
            "version": self.version,
            "timestamp": self.timestamp.isoformat(),
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "user_id": self.user_id,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    @classmethod
    def from_event(cls, event: "Event") -> "StoredEvent":
        return cls(
            event_id=event.metadata.event_id,
            aggregate_id=event.aggregate_id,
            aggregate_type=event.aggregate_type,
            event_type=event.event_type,
            version=event.version,
            timestamp=event.metadata.timestamp,
            correlation_id=event.metadata.correlation_id,
            causation_id=event.metadata.causation_id,
            user_id=event.metadata.user_id,
            payload=event.payload,
            metadata=event.metadata.to_dict(),
        )

    def to_event(self, event_class: Type = None) -> "Event":
        """Convert back to Event."""
        from pyfault.common.eventsourcing.events import Event, DomainEvent, EventMetadata, EventFactory
        
        metadata = EventMetadata.from_dict(self.metadata)
        
        if self.event_type.startswith("domain."):
            event = DomainEvent(
                aggregate_id=self.aggregate_id,
                aggregate_type=self.aggregate_type,
                event_type=self.event_type,
                version=self.version,
                metadata=EventMetadata.from_dict(self.metadata),
                payload=self.payload,
            )
        else:
            event = EventFactory.create_event(
                aggregate_id=self.aggregate_id,
                aggregate_type=self.aggregate_type,
                event_type=self.event_type,
                payload=self.payload,
                version=self.version,
                metadata=EventMetadata.from_dict(self.metadata),
            )
        
        event._version = self.version
        return event


class EventStore(ABC):
    """
    Abstract event store interface.
    
    Event stores are append-only stores that persist events as an immutable log.
    """

    @abstractmethod
    async def append(self, events: List[Event]) -> None:
        """Append events to the store."""
        pass

    @abstractmethod
    async def get_events(
        self,
        aggregate_id: str,
        from_version: int = 0,
        to_version: Optional[int] = None,
    ) -> List[Event]:
        """Get events for an aggregate."""
        pass

    @abstractmethod
    async def get_events_by_correlation_id(self, correlation_id: str) -> List[Event]:
        """Get events by correlation ID."""
        pass

    @abstractmethod
    async def get_events_by_type(
        self,
        event_type: str,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Event]:
        """Get events by type within time range."""
        pass

    @abstractmethod
    async def get_all_events(
        self,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[Event]:
        """Get all events within time range."""
        pass

    @abstractmethod
    async def get_aggregate_version(self, aggregate_id: str) -> int:
        """Get the current version of an aggregate."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the event store."""
        pass


class InMemoryEventStore(EventStore):
    """
    In-memory event store implementation.
    
    Suitable for development, testing, and single-instance deployments.
    """
    
    def __init__(self):
        self._events: Dict[str, List[StoredEvent]] = {}
        self._by_correlation: Dict[str, List[str]] = {}
        self._by_type: Dict[str, List[str]] = {}
        self._all_events: List[str] = []
        self._aggregate_versions: Dict[str, int] = {}

    def _store_event(self, event: "Event") -> None:
        """Store an event in memory."""
        stored = StoredEvent.from_event(event)
        
        # Index by aggregate
        if event.aggregate_id not in self._events:
            self._events[event.aggregate_id] = []
        self._events[event.aggregate_id].append(stored)
        
        # Index by correlation ID
        if stored.correlation_id:
            if stored.correlation_id not in self._by_correlation:
                self._by_correlation[stored.correlation_id] = []
            self._by_correlation[stored.correlation_id].append(stored.event_id)
        
        # Index by type
        if stored.event_type not in self._by_type:
            self._by_type[stored.event_type] = []
        self._by_type[stored.event_type].append(stored.event_id)
        
        # Track all events
        self._all_events.append(stored.event_id)
        
        # Update aggregate version
        if event.aggregate_id not in self._aggregate_versions:
            self._aggregate_versions[event.aggregate_id] = 0
        self._aggregate_versions[event.aggregate_id] = max(
            self._aggregate_versions[event.aggregate_id],
            event.version
        )

    async def append(self, events: List["Event"]) -> None:
        for event in events:
            self._store_event(event)

    async def get_events(
        self,
        aggregate_id: str,
        from_version: int = 0,
        to_version: Optional[int] = None,
    ) -> List["Event"]:
        if aggregate_id not in self._events:
            return []
        
        stored_events = self._events[aggregate_id]
        events = [e.to_event() for e in stored_events if e.version > from_version]
        
        if to_version is not None:
            events = [e for e in events if e.version <= to_version]
        
        return sorted(events, key=lambda e: e.version)

    async def get_events_by_correlation_id(self, correlation_id: str) -> List["Event"]:
        if correlation_id not in self._by_correlation:
            return []
        
        events = []
        for event_id in self._by_correlation[correlation_id]:
            # Find event across all aggregates
            for aggregate_events in self._events.values():
                for stored in aggregate_events:
                    if stored.event_id == event_id:
                        events.append(stored.to_event())
                        break
        
        return sorted(events, key=lambda e: e.metadata.timestamp)

    async def get_events_by_type(
        self,
        event_type: str,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
        limit: int = 100,
    ) -> List["Event"]:
        if event_type not in self._by_type:
            return []
        
        events = []
        for event_id in self._by_type[event_type][-limit:]:
            for aggregate_events in self._events.values():
                for stored in aggregate_events:
                    if stored.event_id == event_id:
                        event = stored.to_event()
                        if from_timestamp and event.metadata.timestamp < from_timestamp:
                            continue
                        if to_timestamp and event.metadata.timestamp > to_timestamp:
                            continue
                        events.append(event)
                        break
        
        return sorted(events, key=lambda e: e.metadata.timestamp, reverse=True)[:limit]

    async def get_all_events(
        self,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
        limit: int = 100,
    ) -> List["Event"]:
        events = []
        for event_id in self._all_events[-limit:]:
            for aggregate_events in self._events.values():
                for stored in aggregate_events:
                    if stored.event_id == event_id:
                        event = stored.to_event()
                        if from_timestamp and event.metadata.timestamp < from_timestamp:
                            continue
                        if to_timestamp and event.metadata.timestamp > to_timestamp:
                            continue
                        events.append(event)
                        break
        
        return sorted(events, key=lambda e: e.metadata.timestamp, reverse=True)[:limit]

    async def get_aggregate_version(self, aggregate_id: str) -> int:
        return self._aggregate_versions.get(aggregate_id, 0)

    async def close(self) -> None:
        pass

    # Utility methods for testing
    def clear(self) -> None:
        """Clear all events (for testing)."""
        self._events.clear()
        self._by_correlation.clear()
        self._by_type.clear()
        self._all_events.clear()
        self._aggregate_versions.clear()

    def get_all_aggregates(self) -> List[str]:
        """Get all aggregate IDs."""
        return list(self._events.keys())


class PostgresEventStore(EventStore):
    """
    PostgreSQL event store implementation.
    
    Uses a single table with JSONB for flexible event storage.
    """
    
    def __init__(
        self,
        connection_string: str,
        table_name: str = "events",
        schema_name: str = "public",
    ):
        self.connection_string = connection_string
        self.table_name = table_name
        self.schema_name = schema_name
        self._pool = None
    
    async def initialize(self) -> None:
        """Initialize the database connection and create tables."""
        import asyncpg
        
        self._pool = await asyncpg.create_pool(self.connection_string)
        
        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                CREATE SCHEMA IF NOT EXISTS {self.schema_name};
                
                CREATE TABLE IF NOT EXISTS {self.schema_name}.{self.table_name} (
                    event_id UUID PRIMARY KEY,
                    aggregate_id UUID NOT NULL,
                    aggregate_type VARCHAR(255) NOT NULL,
                    event_type VARCHAR(255) NOT NULL,
                    version INTEGER NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    correlation_id UUID,
                    causation_id UUID,
                    user_id UUID,
                    payload JSONB NOT NULL,
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_aggregate 
                    ON {self.schema_name}.{self.table_name} (aggregate_id);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_correlation 
                    ON {self.schema_name}.{self.table_name} (correlation_id);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_type 
                    ON {self.schema_name}.{self.table_name} (event_type);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_timestamp 
                    ON {self.schema_name}.{self.table_name} (timestamp);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_aggregate_version 
                    ON {self.schema_name}.{self.table_name} (aggregate_id, version);
            """)

    async def append(self, events: List["Event"]) -> None:
        import asyncpg
        
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for event in events:
                    stored = StoredEvent.from_event(event)
                    await conn.execute(f"""
                        INSERT INTO {self.schema_name}.{self.table_name} (
                            event_id, aggregate_id, aggregate_type, event_type,
                            version, timestamp, correlation_id, causation_id,
                            user_id, payload, metadata
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $10)
                    """,
                        stored.event_id,
                        stored.aggregate_id,
                        stored.aggregate_type,
                        stored.event_type,
                        stored.version,
                        stored.timestamp,
                        stored.correlation_id,
                        stored.causation_id,
                        stored.user_id,
                        json.dumps(stored.payload),
                        json.dumps(stored.metadata),
                    )

    def _row_to_event(self, row: Dict) -> "Event":
        """Convert database row to Event."""
        from pyfault.common.eventsourcing.events import Event, DomainEvent, EventFactory, EventMetadata
        
        metadata = EventMetadata.from_dict(row["metadata"])
        
        if row["event_type"].startswith("domain."):
            event = DomainEvent(
                aggregate_id=row["aggregate_id"],
                aggregate_type=row["aggregate_type"],
                event_type=row["event_type"],
                version=row["version"],
                metadata=EventMetadata.from_dict(row["metadata"]),
                payload=row["payload"],
            )
        else:
            event = EventFactory.create_event(
                aggregate_id=row["aggregate_id"],
                aggregate_type=row["aggregate_type"],
                event_type=row["event_type"],
                payload=row["payload"],
                version=row["version"],
                metadata=EventMetadata.from_dict(row["metadata"]),
            )
        
        event._version = row["version"]
        return event

    async def get_events(
        self,
        aggregate_id: str,
        from_version: int = 0,
        to_version: Optional[int] = None,
    ) -> List["Event"]:
        import asyncpg
        
        query = f"""
            SELECT * FROM {self.schema_name}.{self.table_name}
            WHERE aggregate_id = $1 AND version > $2
        """
        params = [aggregate_id, from_version]
        
        if to_version is not None:
            query += " AND version <= $3"
            # We'll handle this in Python for simplicity
        
        query += " ORDER BY version ASC"
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            events = [self._row_to_event(dict(row)) for row in rows]
            
            if to_version is not None:
                events = [e for e in events if e.version <= to_version]
            
            return events

    async def get_events_by_correlation_id(self, correlation_id: str) -> List["Event"]:
        import asyncpg
        
        query = f"""
            SELECT * FROM {self.schema_name}.{self.table_name}
            WHERE correlation_id = $1
            ORDER BY timestamp ASC
        """
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, correlation_id)
            return [self._row_to_event(dict(row)) for row in rows]

    async def get_events_by_type(
        self,
        event_type: str,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
        limit: int = 100,
    ) -> List["Event"]:
        import asyncpg
        
        query = f"""
            SELECT * FROM {self.schema_name}.{self.table_name}
            WHERE event_type = $1
        """
        params = [event_type]
        param_idx = 2
        
        if from_timestamp:
            query += f" AND timestamp >= ${param_idx}"
            params.append(from_timestamp)
            param_idx += 1
        
        if to_timestamp:
            query += f" AND timestamp <= ${param_idx}"
            params.append(to_timestamp)
            param_idx += 1
        
        query += f" ORDER BY timestamp DESC LIMIT ${param_idx}"
        params.append(limit)
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_event(dict(row)) for row in rows]

    async def get_all_events(
        self,
        from_timestamp: Optional[datetime] = None,
        to_timestamp: Optional[datetime] = None,
        limit: int = 100,
    ) -> List["Event"]:
        import asyncpg
        
        query = f"""
            SELECT * FROM {self.schema_name}.{self.table_name}
            WHERE 1=1
        """
        params = []
        param_idx = 1
        
        if from_timestamp:
            query += f" AND timestamp >= ${param_idx}"
            params.append(from_timestamp)
            param_idx += 1
        
        if to_timestamp:
            query += f" AND timestamp <= ${param_idx}"
            params.append(to_timestamp)
            param_idx += 1
        
        query += f" ORDER BY timestamp DESC LIMIT ${param_idx}"
        params.append(limit)
        
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_event(dict(row)) for row in rows]

    async def get_aggregate_version(self, aggregate_id: str) -> int:
        import asyncpg
        
        query = f"""
            SELECT MAX(version) FROM {self.schema_name}.{self.table_name}
            WHERE aggregate_id = $1
        """
        
        async with self._pool.acquire() as conn:
            result = await conn.fetchval(query, aggregate_id)
            return result or 0

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()


class EventStoreFactory:
    """Factory for creating event stores."""
    
    @staticmethod
    def create(
        store_type: EventStoreType,
        **kwargs
    ) -> EventStore:
        if store_type == EventStoreType.MEMORY:
            return InMemoryEventStore()
        elif store_type == EventStoreType.POSTGRES:
            return PostgresEventStore(kwargs.get("connection_string"))
        elif store_type == EventStoreType.MONGODB:
            raise NotImplementedError("MongoDB event store not yet implemented")
        elif store_type == EventStoreType.REDIS:
            raise NotImplementedError("Redis event store not yet implemented")
        else:
            raise ValueError(f"Unknown event store type: {store_type}")