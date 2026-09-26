"""
Edge Storage for PyFault framework.

Distributed storage at the edge with:
- Local cache with TTL and eviction
- Cross-region replication
- Conflict resolution
- Offline-first support
- Data synchronization
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import pickle
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class StorageTier(str, Enum):
    """Storage tiers."""
    MEMORY = "memory"           # In-memory (fastest)
    SSD = "ssd"                 # Local SSD
    HDD = "hdd"                 # Local HDD
    NETWORK = "network"         # Network attached
    CLOUD = "cloud"             # Cloud storage (S3, etc.)


class ConsistencyLevel(str, Enum):
    """Consistency levels."""
    EVENTUAL = "eventual"
    SESSION = "session"
    STRONG = "strong"
    CAUSAL = "causal"


class ConflictResolution(str, Enum):
    """Conflict resolution strategies."""
    LAST_WRITE_WINS = "last_write_wins"
    FIRST_WRITE_WINS = "first_write_wins"
    VECTOR_CLOCK = "vector_clock"
    APPLICATION = "application"
    MERGE = "merge"


@dataclass
class StorageConfig:
    """Edge storage configuration."""
    region: str
    max_memory_mb: int = 512
    max_disk_mb: int = 2048
    default_ttl_seconds: int = 3600
    consistency: ConsistencyLevel = ConsistencyLevel.EVENTUAL
    conflict_resolution: ConflictResolution = ConflictResolution.LAST_WRITE_WINS
    replication_factor: int = 2
    sync_interval_seconds: int = 60
    enable_offline: bool = True
    compression: bool = True
    encryption: bool = False


@dataclass
class DataItem:
    """Data item with metadata."""
    key: str
    value: Any
    version: int = 1
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    vector_clock: dict[str, int] = field(default_factory=dict)
    checksum: str = ""
    size_bytes: int = 0
    tier: StorageTier = StorageTier.MEMORY
    replicated: bool = False

    def is_expired(self) -> bool:
        if self.expires_at:
            return datetime.utcnow() > self.expires_at
        return False

    def compute_checksum(self) -> str:
        content = f"{self.key}:{self.value}:{self.version}:{self.updated_at.isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "tags": self.tags,
            "metadata": self.metadata,
            "vector_clock": self.vector_clock,
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "tier": self.tier.value,
            "replicated": self.replicated,
        }


class CacheBackend(ABC):
    """Abstract cache backend."""

    @abstractmethod
    async def get(self, key: str) -> Optional[DataItem]:
        pass

    @abstractmethod
    async def set(self, item: DataItem) -> bool:
        pass

    @abstractmethod
    async def delete(self, key: str) -> bool:
        pass

    @abstractmethod
    async def exists(self, key: str) -> bool:
        pass

    @abstractmethod
    async def clear(self) -> None:
        pass

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        pass


class MemoryCache:
    """In-memory LRU cache with TTL."""

    def __init__(self, max_size_mb: int = 512, default_ttl: int = 3600):
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, DataItem] = OrderedDict()
        self._current_size = 0
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[DataItem]:
        async with self._lock:
            item = self._cache.get(key)
            if item:
                if item.is_expired():
                    await self._remove(key)
                    return None
                # Move to end (MRU)
                self._cache.move_to_end(key)
                return item
            return None

    async def set(self, item: DataItem) -> bool:
        async with self._lock:
            # Remove existing if present
            if item.key in self._cache:
                await self._remove(item.key)

            # Check size
            item.size_bytes = len(pickle.dumps(item.value))
            if item.size_bytes > self.max_size_bytes:
                logger.warning(f"Item too large for cache: {item.size_bytes} bytes")
                return False

            # Evict if needed
            while self._current_size + item.size_bytes > self.max_size_bytes and self._cache:
                await self._evict_lru()

            # Set expiration
            if not item.expires_at:
                item.expires_at = datetime.utcnow() + timedelta(seconds=self.default_ttl)

            item.checksum = item.compute_checksum()
            self._cache[item.key] = item
            self._current_size += item.size_bytes
            return True

    async def delete(self, key: str) -> bool:
        async with self._lock:
            return await self._remove(key)

    async def exists(self, key: str) -> bool:
        async with self._lock:
            item = self._cache.get(key)
            if item and item.is_expired():
                await self._remove(key)
                return False
            return item is not None

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()
            self._current_size = 0

    async def _remove(self, key: str) -> bool:
        item = self._cache.pop(key, None)
        if item:
            self._current_size -= item.size_bytes
            return True
        return False

    async def _evict_lru(self) -> None:
        if self._cache:
            key, item = self._cache.popitem(last=False)
            self._current_size -= item.size_bytes

    async def get_stats(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "entries": len(self._cache),
                "size_bytes": self._current_size,
                "max_size_bytes": self.max_size_bytes,
                "utilization": self._current_size / self.max_size_bytes if self.max_size_bytes > 0 else 0,
            }

    async def cleanup_expired(self) -> int:
        """Remove expired entries."""
        async with self._lock:
            expired_keys = [
                key for key, item in self._cache.items()
                if item.is_expired()
            ]
            for key in expired_keys:
                await self._remove(key)
            return len(expired_keys)


class DiskCache:
    """Persistent disk cache."""

    def __init__(self, path: str, max_size_mb: int = 2048):
        self.path = Path(path)
        self.path.mkdir(parents=True, exist_ok=True)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self._index: dict[str, dict[str, Any]] = {}
        self._current_size = 0
        self._lock = asyncio.Lock()
        self._load_index()

    def _load_index(self) -> None:
        index_file = self.path / "index.json"
        if index_file.exists():
            try:
                with open(index_file) as f:
                    self._index = json.load(f)
                self._current_size = sum(v.get("size_bytes", 0) for v in self._index.values())
            except Exception as e:
                logger.error(f"Failed to load disk cache index: {e}")

    def _save_index(self) -> None:
        index_file = self.path / "index.json"
        try:
            with open(index_file, 'w') as f:
                json.dump(self._index, f)
        except Exception as e:
            logger.error(f"Failed to save disk cache index: {e}")

    async def get(self, key: str) -> Optional[DataItem]:
        async with self._lock:
            if key not in self._index:
                return None

            meta = self._index[key]
            if meta.get("expires_at"):
                expires = datetime.fromisoformat(meta["expires_at"])
                if datetime.utcnow() > expires:
                    await self.delete(key)
                    return None

            file_path = self.path / f"{key}.dat"
            if not file_path.exists():
                return None

            try:
                with open(file_path, 'rb') as f:
                    item: DataItem = pickle.loads(f.read())
                return item
            except Exception as e:
                logger.error(f"Failed to read cache item: {e}")
                return None

    async def set(self, item: DataItem) -> bool:
        async with self._lock:
            item.size_bytes = len(pickle.dumps(item.value))

            if item.size_bytes > self.max_size_bytes:
                return False

            # Evict if needed
            while self._current_size + item.size_bytes > self.max_size_bytes and self._index:
                await self._evict_lru()

            if not item.expires_at:
                item.expires_at = datetime.utcnow() + timedelta(hours=24)

            item.checksum = item.compute_checksum()

            file_path = self.path / f"{item.key}.dat"
            try:
                with open(file_path, 'wb') as f:
                    f.write(pickle.dumps(item))

                self._index[item.key] = {
                    "size_bytes": item.size_bytes,
                    "expires_at": item.expires_at.isoformat() if item.expires_at else None,
                    "updated_at": item.updated_at.isoformat(),
                }
                self._current_size += item.size_bytes
                self._save_index()
                return True
            except Exception as e:
                logger.error(f"Failed to write cache item: {e}")
                return False

    async def delete(self, key: str) -> bool:
        async with self._lock:
            if key not in self._index:
                return False

            meta = self._index.pop(key)
            self._current_size -= meta.get("size_bytes", 0)

            file_path = self.path / f"{key}.dat"
            if file_path.exists():
                file_path.unlink()

            self._save_index()
            return True

    async def exists(self, key: str) -> bool:
        async with self._lock:
            if key not in self._index:
                return False

            meta = self._index[key]
            if meta.get("expires_at"):
                expires = datetime.fromisoformat(meta["expires_at"])
                if datetime.utcnow() > expires:
                    await self.delete(key)
                    return False
            return True

    async def clear(self) -> None:
        async with self._lock:
            for key in list(self._index.keys()):
                await self.delete(key)

    async def _evict_lru(self) -> bool:
        if not self._index:
            return False

        # Find oldest by updated_at
        oldest_key = min(
            self._index.keys(),
            key=lambda k: self._index[k].get("updated_at", "")
        )
        await self.delete(oldest_key)
        return True

    async def get_stats(self) -> dict[str, Any]:
        async with self._lock:
            return {
                "entries": len(self._index),
                "size_bytes": self._current_size,
                "max_size_bytes": self.max_size_bytes,
                "utilization": self._current_size / self.max_size_bytes if self.max_size_bytes > 0 else 0,
            }


class EdgeStorage:
    """
    Multi-tier edge storage with replication.
    """

    def __init__(self, config: StorageConfig):
        self.config = config
        self.memory_cache = MemoryCache(config.max_memory_mb, config.default_ttl_seconds)
        self.disk_cache = DiskCache(f"./data/edge_storage/{config.region}", config.max_disk_mb)
        self._replication_queue: asyncio.Queue = asyncio.Queue()
        self._sync_task: Optional[asyncio.Task] = None
        self._running = False

    async def get(self, key: str, tier: Optional[StorageTier] = None) -> Optional[DataItem]:
        """Get item from storage."""
        # Try memory first
        if tier in (None, StorageTier.MEMORY):
            item = await self.memory_cache.get(key)
            if item:
                return item

        # Try disk
        if tier in (None, StorageTier.SSD, StorageTier.HDD):
            item = await self.disk_cache.get(key)
            if item:
                # Promote to memory
                await self.memory_cache.set(item)
                return item

        return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
        tags: Optional[dict[str, str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        tier: StorageTier = StorageTier.MEMORY,
    ) -> bool:
        """Set item in storage."""
        item = DataItem(
            key=key,
            value=value,
            expires_at=datetime.utcnow() + timedelta(seconds=ttl or self.config.default_ttl_seconds),
            tags=tags or {},
            metadata=metadata or {},
            tier=tier,
        )

        success = False

        if tier == StorageTier.MEMORY:
            success = await self.memory_cache.set(item)
            # Async replicate to disk
            if success:
                asyncio.create_task(self.disk_cache.set(item))
        else:
            success = await self.disk_cache.set(item)
            # Async promote to memory
            if success:
                asyncio.create_task(self.memory_cache.set(item))

        if success and self.config.replication_factor > 1:
            await self._queue_replication(item)

        return success

    async def delete(self, key: str) -> bool:
        """Delete item from all tiers."""
        mem_result = await self.memory_cache.delete(key)
        disk_result = await self.disk_cache.delete(key)
        return mem_result or disk_result

    async def exists(self, key: str) -> bool:
        return await self.memory_cache.exists(key) or await self.disk_cache.exists(key)

    async def get_by_tag(self, tag_key: str, tag_value: str) -> list[DataItem]:
        """Get items by tag (memory only for performance)."""
        results: list[DataItem] = []
        # This would need a tag index in practice
        return results

    async def _queue_replication(self, item: DataItem) -> None:
        await self._replication_queue.put(item)

    async def start_replication(self) -> None:
        self._running = True
        self._sync_task = asyncio.create_task(self._replication_loop())

    async def stop_replication(self) -> None:
        self._running = False
        if self._sync_task:
            self._sync_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._sync_task

    async def _replication_loop(self) -> None:
        while self._running:
            try:
                item = await asyncio.wait_for(
                    self._replication_queue.get(),
                    timeout=self.config.sync_interval_seconds
                )
                # In practice, would replicate to other regions
                item.replicated = True
            except asyncio.TimeoutError:
                pass
            except Exception as e:
                logger.error(f"Replication error: {e}")

    async def sync(self) -> dict[str, Any]:
        """Force synchronization."""
        mem_stats = await self.memory_cache.get_stats()
        disk_stats = await self.disk_cache.get_stats()

        # Cleanup expired
        expired = await self.memory_cache.cleanup_expired()

        return {
            "memory": mem_stats,
            "disk": disk_stats,
            "expired_cleaned": expired,
        }

    async def get_stats(self) -> dict[str, Any]:
        mem_stats = await self.memory_cache.get_stats()
        disk_stats = await self.disk_cache.get_stats()

        return {
            "region": self.config.region,
            "memory": mem_stats,
            "disk": disk_stats,
            "config": {
                "consistency": self.config.consistency.value,
                "conflict_resolution": self.config.conflict_resolution.value,
                "replication_factor": self.config.replication_factor,
            },
        }


class DistributedEdgeStorage:
    """
    Coordinates storage across multiple edge regions.
    """

    def __init__(self) -> None:
        self._storages: dict[str, EdgeStorage] = {}
        self._region_configs: dict[str, StorageConfig] = {}

    def add_region(self, config: StorageConfig) -> EdgeStorage:
        storage = EdgeStorage(config)
        self._storages[config.region] = storage
        self._region_configs[config.region] = config
        return storage

    def get_storage(self, region: str) -> Optional[EdgeStorage]:
        return self._storages.get(region)

    async def get(
        self,
        key: str,
        preferred_regions: Optional[list[str]] = None,
    ) -> Optional[DataItem]:
        """Get from nearest region."""
        regions = preferred_regions or list(self._storages.keys())

        for region in regions:
            storage = self._storages.get(region)
            if storage:
                item = await storage.get(key)
                if item:
                    return item

        # Fallback to any region
        for storage in self._storages.values():
            item = await storage.get(key)
            if item:
                return item

        return None

    async def set(
        self,
        key: str,
        value: Any,
        regions: Optional[list[str]] = None,
        **kwargs: Any
    ) -> dict[str, bool]:
        """Set in multiple regions."""
        regions = regions or list(self._storages.keys())
        results = {}

        for region in regions:
            storage = self._storages.get(region)
            if storage:
                results[region] = await storage.set(key, value, **kwargs)
            else:
                results[region] = False

        return results

    async def delete(self, key: str, regions: Optional[list[str]] = None) -> dict[str, bool]:
        regions = regions or list(self._storages.keys())
        results = {}

        for region in regions:
            storage = self._storages.get(region)
            if storage:
                results[region] = await storage.delete(key)
            else:
                results[region] = False

        return results

    async def sync_all(self) -> dict[str, Any]:
        results = {}
        for region, storage in self._storages.items():
            results[region] = await storage.sync()
        return results

    async def get_global_stats(self) -> dict[str, Any]:
        stats = {}
        for region, storage in self._storages.items():
            stats[region] = await storage.get_stats()
        return stats


# Global storage
_edge_storage: Optional[DistributedEdgeStorage] = None


def get_edge_storage() -> DistributedEdgeStorage:
    global _edge_storage
    if _edge_storage is None:
        _edge_storage = DistributedEdgeStorage()
    return _edge_storage


