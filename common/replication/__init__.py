"""
Data Replication for PyFault framework.
"""

import asyncio
import hashlib
import json
import statistics
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar

from pyfault.common.time import utc_now


class ReplicationMode(str, Enum):
    """Replication mode."""
    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"
    SEMI_SYNCHRONOUS = "semi_synchronous"


class ReplicationStatus(str, Enum):
    """Replication status."""
    ACTIVE = "active"
    PAUSED = "paused"
    LAGGING = "lagging"
    ERROR = "error"
    STOPPED = "stopped"


@dataclass
class ReplicationConfig:
    """Replication configuration."""
    source_region: str
    target_regions: list[str]
    mode: ReplicationMode = ReplicationMode.ASYNCHRONOUS
    batch_size: int = 100
    flush_interval_ms: int = 100
    max_lag_ms: int = 5000
    retry_interval_ms: int = 1000
    max_retries: int = 3
    conflict_resolution: str = "last_write_wins"  # last_write_wins, first_write_wins, custom
    compression: bool = True
    encryption: bool = False


@dataclass
class ReplicationEvent:
    """A replication event."""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_region: str = ""
    target_region: str = ""
    entity_type: str = ""
    entity_id: str = ""
    operation: str = ""  # create, update, delete
    payload: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    timestamp: datetime = field(default_factory=utc_now)
    checksum: str = ""

    def compute_checksum(self) -> str:
        """Compute checksum for the event."""
        data = f"{self.source_region}:{self.target_region}:{self.entity_type}:{self.entity_id}:{self.operation}:{self.version}:{self.timestamp.isoformat()}"
        return hashlib.sha256(data.encode()).hexdigest()[:16]


@dataclass
class ReplicationStats:
    """Replication statistics."""
    total_events: int = 0
    replicated_events: int = 0
    failed_events: int = 0
    pending_events: int = 0
    lag_ms: float = 0.0
    last_sync: Optional[datetime] = None
    throughput_per_sec: float = 0.0
    error_rate: float = 0.0


class ReplicationBackend(ABC):
    """Abstract replication backend."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the replication backend."""
        pass

    @abstractmethod
    async def replicate(self, events: list[Any]) -> bool:
        """Replicate events to target."""
        pass

    @abstractmethod
    async def get_lag(self, target_region: str) -> float:
        """Get replication lag in milliseconds."""
        pass

    @abstractmethod
    async def pause(self) -> None:
        """Pause replication."""
        pass

    @abstractmethod
    async def resume(self) -> None:
        """Resume replication."""
        pass

    @abstractmethod
    async def get_status(self) -> ReplicationStatus:
        """Get replication status."""
        pass

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        """Get replication statistics."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the replication backend."""
        pass


class InMemoryReplicationBackend(ReplicationBackend):
    """In-memory replication backend for testing."""

    def __init__(self, config: ReplicationConfig):
        self.config = config
        self._queue: asyncio.Queue = asyncio.Queue()
        self._status = ReplicationStatus.ACTIVE
        self._stats = ReplicationStats()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._events: list[ReplicationEvent] = []

    async def initialize(self) -> None:
        pass

    async def replicate(self, events: list[Any]) -> bool:
        if self._status != ReplicationStatus.ACTIVE:
            return False

        for event in events:
            await self._queue.put(event)
            self._events.append(event)
            self._stats.total_events += 1

        return True

    async def get_lag(self, target_region: str) -> float:
        # In-memory has minimal lag
        return 0.0

    async def pause(self) -> None:
        self._status = ReplicationStatus.PAUSED

    async def resume(self) -> None:
        self._status = ReplicationStatus.ACTIVE

    async def get_status(self) -> ReplicationStatus:
        return self._status

    async def get_stats(self) -> dict[str, Any]:
        return {
            "total_events": self._stats.total_events,
            "replicated_events": self._stats.replicated_events,
            "failed_events": self._stats.failed_events,
            "pending_events": self._queue.qsize(),
            "lag_ms": self._stats.lag_ms,
            "last_sync": self._stats.last_sync.isoformat() if self._stats.last_sync else None,
            "throughput_per_sec": self._stats.throughput_per_sec,
            "error_rate": self._stats.error_rate,
        }

    async def close(self) -> None:
        if self._task:
            self._task.cancel()


class _ReplicationManager:
    """
    Manages data replication across regions.
    """

    def __init__(self) -> None:
        self._backends: dict[str, ReplicationBackend] = {}
        self._configs: dict[str, ReplicationConfig] = {}
        self._running = False

    def add_replication(
        self,
        name: str,
        config: ReplicationConfig,
        backend: Optional["ReplicationBackend"] = None,
    ) -> None:
        """Add a replication configuration."""
        self._configs[name] = config
        if backend:
            self._backends[name] = backend
        else:
            self._backends[name] = InMemoryReplicationBackend(config)

    def remove_replication(self, name: str) -> bool:
        """Remove a replication configuration."""
        removed = False
        if name in self._backends:
            del self._backends[name]
            removed = True
        if name in self._configs:
            del self._configs[name]
            removed = True
        return removed

    def get_backend(self, name: str) -> Optional["ReplicationBackend"]:
        """Get replication backend by name."""
        return self._backends.get(name)

    def get_config(self, name: str) -> Optional[ReplicationConfig]:
        """Get replication configuration by name."""
        return self._configs.get(name)

    def list_replications(self) -> list[str]:
        """List all replication configurations."""
        return list(self._configs.keys())

    async def start_replication(self, name: str) -> bool:
        """Start replication for a configuration."""
        backend = self._backends.get(name)
        if not backend:
            return False
        await backend.resume()
        return True

    async def stop_replication(self, name: str) -> bool:
        """Stop replication for a configuration."""
        backend = self._backends.get(name)
        if not backend:
            return False
        await backend.pause()
        return True

    async def get_replication_status(self, name: str) -> Optional[dict[str, Any]]:
        """Get replication status."""
        backend = self._backends.get(name)
        if not backend:
            return None

        status = await backend.get_status()
        stats = await backend.get_stats()
        config = self._configs.get(name)

        return {
            "name": name,
            "status": status.value,
            "config": config.__dict__ if config else None,
            "stats": stats,
        }

    async def get_all_statuses(self) -> list[dict[str, Any]]:
        """Get status of all replications."""
        results = []
        for name in self._backends:
            status = await self.get_replication_status(name)
            if status:
                results.append(status)
        return results

    async def replicate_event(self, event: Any) -> dict[str, bool]:
        """Replicate an event to all configured targets."""
        results = {}
        for name, backend in self._backends.items():
            try:
                results[name] = await self._replicate_to_backend(backend, event)
            except Exception:
                results[name] = False
        return results

    async def _replicate_to_backend(
        self, backend: "ReplicationBackend", event: Any
    ) -> bool:
        """Replicate event to a specific backend."""
        return await backend.replicate([event])


class ReplicationManager:
    """Singleton replication manager."""
    _instance: Optional["ReplicationManager"] = None
    _initialized: bool

    def __new__(cls) -> "ReplicationManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._manager = _ReplicationManager()
        self._initialized = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self._manager, name)


def get_replication_manager() -> "ReplicationManager":
    """Get the global replication manager."""
    return ReplicationManager()


async def initialize_replication(configs: Optional[list[ReplicationConfig]] = None) -> ReplicationManager:
    """Initialize replication with configurations."""
    manager = get_replication_manager()
    if configs:
        for config in configs:
            backend = InMemoryReplicationBackend(config)
            manager.add_replication(config.source_region, config, backend)
    return manager


__all__ = [
    "ReplicationMode",
    "ReplicationStatus",
    "ReplicationConfig",
    "ReplicationEvent",
    "ReplicationStats",
    "ReplicationBackend",
    "InMemoryReplicationBackend",
    "ReplicationManager",
    "get_replication_manager",
    "initialize_replication",
]
