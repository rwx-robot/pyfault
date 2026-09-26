"""
Cache Manager for PyFault framework.
"""

import time
from functools import wraps
from typing import Any, Callable, Optional


class CacheManager:
    """In-memory cache manager."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[Any, float]] = {}
        self._default_ttl: int = 300  # 5 minutes

    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if key in self._cache:
            value, expiry = self._cache[key]
            if expiry > time.time():
                return value
            else:
                del self._cache[key]
        return None

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
        """Decorator for caching function results."""
        def decorator(func: Any) -> Any:
            @wraps(func)
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Create cache key from function name and arguments
                key = f"{func.__name__}:{str(args)}:{str(kwargs)}"

                # Try to get from cache
                cached = self.get(key)
                if cached is not None:
                    return cached

                # Execute function and cache result
                result = await func(*args, **kwargs)
                self.set(key, result, ttl)
                return result
            return wrapper
        return decorator


class CacheModule:
    """Cache module for dependency injection."""

    def __init__(self) -> None:
        self.manager = CacheManager()

    def get_manager(self) -> CacheManager:
        """Get cache manager."""
        return self.manager
