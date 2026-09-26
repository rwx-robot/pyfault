"""
Snapshot Store for Event Sourcing.
"""

import json
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional, TypeVar

from pyfault.common.eventsourcing.aggregate import AggregateSnapshot

S = TypeVar("S", bound="AggregateSnapshot")


class SnapshotStoreType(str, Enum):
    """Snapshot store types."""
    MEMORY = "memory"
    POSTGRES = "postgres"
    MONGODB = "mongodb"
    REDIS = "redis"
    S3 = "s3"


class SnapshotStore(ABC):
    """
    Abstract snapshot store interface.

    Snapshot stores persist aggregate snapshots for fast recovery.
    """

    @abstractmethod
    async def save(self, snapshot: AggregateSnapshot) -> None:
        """Save a snapshot."""
        pass

    @abstractmethod
    async def get_latest(self, aggregate_id: str) -> Optional[AggregateSnapshot]:
        """Get the latest snapshot for an aggregate."""
        pass

    @abstractmethod
    async def get_by_version(self, aggregate_id: str, version: int) -> Optional[AggregateSnapshot]:
        """Get a snapshot at or before a specific version."""
        pass

    @abstractmethod
    async def delete_old_snapshots(self, aggregate_id: str, keep_count: int = 5) -> int:
        """Delete old snapshots, keeping only the most recent N."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the snapshot store."""
        pass


class InMemorySnapshotStore(SnapshotStore):
    """
    In-memory snapshot store implementation.
    """

    def __init__(self) -> None:
        self._snapshots: dict[str, list[AggregateSnapshot]] = {}

    async def save(self, snapshot: AggregateSnapshot) -> None:
        if snapshot.aggregate_id not in self._snapshots:
            self._snapshots[snapshot.aggregate_id] = []
        self._snapshots[snapshot.aggregate_id].append(snapshot)

    async def get_latest(self, aggregate_id: str) -> Optional[AggregateSnapshot]:
        if aggregate_id not in self._snapshots:
            return None
        snapshots = self._snapshots[aggregate_id]
        if not snapshots:
            return None
        return max(snapshots, key=lambda s: s.version)

    async def get_by_version(self, aggregate_id: str, version: int) -> Optional[AggregateSnapshot]:
        if aggregate_id not in self._snapshots:
            return None
        snapshots = self._snapshots[aggregate_id]
        candidates = [s for s in snapshots if s.version <= version]
        if not candidates:
            return None
        return max(candidates, key=lambda s: s.version)

    async def delete_old_snapshots(self, aggregate_id: str, keep_count: int = 5) -> int:
        if aggregate_id not in self._snapshots:
            return 0

        snapshots = sorted(self._snapshots[aggregate_id], key=lambda s: s.version, reverse=True)
        if len(snapshots) <= keep_count:
            return 0

        to_delete = snapshots[keep_count:]
        deleted_count = len(to_delete)

        # Keep only the most recent
        self._snapshots[aggregate_id] = snapshots[:keep_count]

        return deleted_count

    async def close(self) -> None:
        pass

    def clear(self) -> None:
        """Clear all snapshots (for testing)."""
        self._snapshots.clear()


class PostgresSnapshotStore(SnapshotStore):
    """
    PostgreSQL snapshot store implementation.
    """

    def __init__(
        self,
        connection_string: str,
        table_name: str = "snapshots",
        schema_name: str = "public",
    ):
        self.connection_string = connection_string
        self.table_name = table_name
        self.schema_name = schema_name
        self._pool: Any = None

    async def initialize(self) -> None:
        """Initialize the database connection and create tables."""
        import asyncpg

        self._pool = await asyncpg.create_pool(self.connection_string)

        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                CREATE SCHEMA IF NOT EXISTS {self.schema_name};

                CREATE TABLE IF NOT EXISTS {self.schema_name}.{self.table_name} (
                    snapshot_id UUID PRIMARY KEY,
                    aggregate_id UUID NOT NULL,
                    aggregate_type VARCHAR(255) NOT NULL,
                    version INTEGER NOT NULL,
                    state JSONB NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );

                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_aggregate
                    ON {self.schema_name}.{self.table_name} (aggregate_id);
                CREATE INDEX IF NOT EXISTS idx_{self.table_name}_aggregate_version
                    ON {self.schema_name}.{self.table_name} (aggregate_id, version);
            """)

    async def save(self, snapshot: AggregateSnapshot) -> None:

        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                INSERT INTO {self.schema_name}.{self.table_name} (
                    snapshot_id, aggregate_id, aggregate_type, version, state, timestamp
                ) VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (snapshot_id) DO UPDATE SET
                    state = EXCLUDED.state,
                    version = EXCLUDED.version,
                    timestamp = EXCLUDED.timestamp
            """,
                snapshot.aggregate_id,  # Using aggregate_id as snapshot_id for simplicity
                snapshot.aggregate_id,
                snapshot.aggregate_type,
                snapshot.version,
                json.dumps(snapshot.state),
                snapshot.timestamp,
            )

    async def get_latest(self, aggregate_id: str) -> Optional[AggregateSnapshot]:

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                SELECT * FROM {self.schema_name}.{self.table_name}
                WHERE aggregate_id = $1
                ORDER BY version DESC
                LIMIT 1
            """, aggregate_id)

            if row:
                return AggregateSnapshot.from_dict(dict(row))
            return None

    async def get_by_version(self, aggregate_id: str, version: int) -> Optional[AggregateSnapshot]:

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(f"""
                SELECT * FROM {self.schema_name}.{self.table_name}
                WHERE aggregate_id = $1 AND version <= $2
                ORDER BY version DESC
                LIMIT 1
            """, aggregate_id, version)

            if row:
                return AggregateSnapshot.from_dict(dict(row))
            return None

    async def delete_old_snapshots(self, aggregate_id: str, keep_count: int = 5) -> int:

        async with self._pool.acquire() as conn:
            # Delete older snapshots
            result = await conn.execute(f"""
                DELETE FROM {self.schema_name}.{self.table_name}
                WHERE aggregate_id = $1
                AND snapshot_id NOT IN (
                    SELECT snapshot_id FROM {self.schema_name}.{self.table_name}
                    WHERE aggregate_id = $1
                    ORDER BY version DESC
                    LIMIT $2
                )
            """, aggregate_id, keep_count)

            # Extract affected row count
            return int(result.split()[-1]) if result else 0

    async def close(self) -> None:
        if hasattr(self, '_pool') and self._pool:
            await self._pool.close()


class SnapshotStoreFactory:
    """Factory for creating snapshot stores."""

    @staticmethod
    def create(
        store_type: "SnapshotStoreType",
        **kwargs: Any
    ) -> "SnapshotStore":
        if store_type == SnapshotStoreType.MEMORY:
            return InMemorySnapshotStore()
        elif store_type == SnapshotStoreType.POSTGRES:
            connection_string = kwargs.get("connection_string")
            if not isinstance(connection_string, str):
                raise ValueError("connection_string is required for the postgres snapshot store")
            return PostgresSnapshotStore(connection_string)
        elif store_type == SnapshotStoreType.MONGODB:
            raise NotImplementedError("MongoDB snapshot store not yet implemented")
        elif store_type == SnapshotStoreType.REDIS:
            raise NotImplementedError("Redis snapshot store not yet implemented")
        elif store_type == SnapshotStoreType.S3:
            raise NotImplementedError("S3 snapshot store not yet implemented")
        else:
            raise ValueError(f"Unknown snapshot store type: {store_type}")
