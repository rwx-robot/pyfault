"""
Cache Manager for PyFault framework.
"""

import asyncio
import time
from functools import wraps
from typing import Any, Callable, Optional


class CacheManager:
    """In-memory cache manager."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[Any, float]] = {}
        self._default_ttl: int = 300  # 5 minutes

    def get(self, key: str, default: Any = None) -> Any:
        """Get value from cache.

        Returns ``default`` (``None`` by default) when the key is missing or
        expired, so a *stored* ``None`` is distinguishable from a cache miss.
        """
        if key in self._cache:
            value, expiry = self._cache[key]
            if expiry > time.time():
                return value
            else:
                del self._cache[key]
        return default

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set value in cache."""
        if ttl is None:
            ttl = self._default_ttl
        self._cache[key] = (value, time.time() + ttl)

    def delete(self, key: str) -> None:
        """Delete value from cache."""
        if key in self._cache:
            del self._cache[key]

    def clear(self) -> None:
        """Clear all cache."""
        self._cache.clear()

    def has(self, key: str) -> bool:
        """Check if key exists in cache."""
        return self.get(key) is not None

    def cache(self, ttl: Optional[int] = None) -> Callable[..., Any]:
        """Decorator for caching function results.

        Works for both synchronous and coroutine functions. ``None`` is a valid
        cached value (distinguished from a miss via a per-decoration sentinel),
        so a function returning ``None`` is cached exactly once.
        """
        def decorator(func: Any) -> Any:
            sentinel = object()  # unique per-decoration miss marker

            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
                cached = self.get(key, sentinel)
                if cached is not sentinel:
                    return cached
                result = func(*args, **kwargs)
                self.set(key, result, ttl)
                return result

            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
                cached = self.get(key, sentinel)
                if cached is not sentinel:
                    return cached
                result = await func(*args, **kwargs)
                self.set(key, result, ttl)
                return result

            return async_wrapper if asyncio.iscoroutinefunction(func) else sync_wrapper
        return decorator


class CacheModule:
    """Cache module for dependency injection."""

    def __init__(self) -> None:
        self.manager = CacheManager()

    def get_manager(self) -> CacheManager:
        """Get cache manager."""
        return self.manager
