"""
Built-in Plugins for PyFault framework.
"""

import inspect
from typing import Any, Optional

from pyfault.common.plugins.base import BasePlugin, PluginMetadata, PluginState


class LoggingPlugin(BasePlugin):
    """Logging plugin for request/response logging."""

    def _create_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="logging",
            version="1.0.0",
            description="Request/response logging plugin",
            author="PyFault Team",
            keywords=["logging", "middleware", "observability"],
        )

    async def on_load(self) -> None:
        self._logger: Any = None

    async def on_initialize(self) -> None:
        import logging
        self._logger = logging.getLogger("pyfault.request")
        self._logger.setLevel(logging.INFO)

        if not self._logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            self._logger.addHandler(handler)

    async def on_start(self) -> None:
        self._logger.info("Logging plugin started")

    async def on_stop(self) -> None:
        self._logger.info("Logging plugin stopped")


class MetricsPlugin(BasePlugin):
    """Metrics collection plugin."""

    def _create_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="metrics",
            version="1.0.0",
            description="Application metrics collection",
            author="PyFault Team",
            keywords=["metrics", "monitoring", "prometheus"],
            provides=["metrics_collector"],
        )

    async def on_load(self) -> None:
        self._metrics: dict[str, Any] = {}

    async def on_initialize(self) -> None:
        from pyfault.common.performance import PerformanceMonitor
        self._monitor = PerformanceMonitor()

    def record_request(self, method: str, path: str, duration: float, status: int) -> None:
        """Record HTTP request metrics."""
        key = f"{method} {path}"
        if key not in self._metrics:
            self._metrics[key] = {"count": 0, "total_time": 0, "errors": 0}

        self._metrics[key]["count"] += 1
        self._metrics[key]["total_time"] += duration
        if status >= 400:
            self._metrics[key]["errors"] += 1

    def get_metrics(self) -> dict:
        """Get collected metrics."""
        return self._metrics


class CorsPlugin(BasePlugin):
    """CORS middleware plugin."""

    def _create_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="cors",
            version="1.0.0",
            description="Cross-Origin Resource Sharing support",
            author="PyFault Team",
            keywords=["cors", "middleware", "security"],
            config_schema={
                "allow_origins": {"type": "array", "default": ["*"]},
                "allow_methods": {"type": "array", "default": ["*"]},
                "allow_headers": {"type": "array", "default": ["*"]},
                "allow_credentials": {"type": "boolean", "default": True},
                "max_age": {"type": "integer", "default": 3600},
            },
        )

    async def on_load(self) -> None:
        self._config = {
            "allow_origins": ["*"],
            "allow_methods": ["*"],
            "allow_headers": ["*"],
            "allow_credentials": True,
            "max_age": 3600,
        }

    async def on_initialize(self) -> None:
        # Apply config
        for key, value in self.config.items():
            if key in self._config:
                self._config[key] = value

    def get_cors_config(self) -> dict:
        return self._config


class HealthCheckPlugin(BasePlugin):
    """Health check endpoints plugin."""

    def _create_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="healthcheck",
            version="1.0.0",
            description="Health check endpoints",
            author="PyFault Team",
            keywords=["health", "monitoring", "kubernetes"],
            provides=["health_endpoints"],
        )

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._checks: dict[str, Any] = {}

    async def on_load(self) -> None:
        self._checks = {}

    def register_check(self, name: str, check_func: Any) -> None:
        """Register a health check function."""
        self._checks[name] = check_func

    async def run_checks(self) -> dict:
        """Run all health checks."""
        results = {}
        for name, check in self._checks.items():
            try:
                if inspect.iscoroutinefunction(check):
                    result = await check()
                else:
                    result = check()
                results[name] = {"status": "healthy", "details": result}
            except Exception as e:
                results[name] = {"status": "unhealthy", "error": str(e)}
        return results


class RateLimitPlugin(BasePlugin):
    """Rate limiting plugin."""

    def _create_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="ratelimit",
            version="1.0.0",
            description="Rate limiting middleware",
            author="PyFault Team",
            keywords=["ratelimit", "security", "middleware"],
            config_schema={
                "default_limit": {"type": "integer", "default": 100},
                "window_seconds": {"type": "integer", "default": 60},
                "key_prefix": {"type": "string", "default": "ratelimit:"},
            },
        )

    async def on_load(self) -> None:
        self._limits: dict[str, Any] = {}

    async def on_initialize(self) -> None:
        self._config = {
            "default_limit": self.config.get("default_limit", 100),
            "window_seconds": self.config.get("window_seconds", 60),
            "key_prefix": self.config.get("key_prefix", "ratelimit:"),
        }


class CachePlugin(BasePlugin):
    """Caching plugin with multiple backends."""

    def _create_metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="cache",
            version="1.0.0",
            description="Multi-backend caching",
            author="PyFault Team",
            keywords=["cache", "redis", "memory", "performance"],
            config_schema={
                "backend": {"type": "string", "default": "memory", "enum": ["memory", "redis"]},
                "redis_url": {"type": "string", "default": "redis://localhost:6379"},
                "default_ttl": {"type": "integer", "default": 300},
            },
        )

    async def on_load(self) -> None:
        self._cache: dict[str, Any] = {}

    async def on_initialize(self) -> None:
        backend = self.config.get("backend", "memory")
        if backend == "redis":
            self._init_redis()
        else:
            self._init_memory()

    def _init_memory(self) -> None:
        import time
        self._cache = {}
        self._expiry: dict[str, float] = {}

    def _init_redis(self) -> None:
        try:
            import redis
            self._redis = redis.from_url(self.config.get("redis_url", "redis://localhost:6379"))
        except ImportError:
            self._init_memory()

    async def get(self, key: str) -> Optional[str]:
        if hasattr(self, "_redis"):
            value = self._redis.get(key)
            return str(value.decode()) if value else None
        else:
            import time
            if key in self._cache:
                if self._expiry.get(key, 0) > time.time():
                    return str(self._cache[key])
                else:
                    del self._cache[key]
                    del self._expiry[key]
            return None

    async def set(self, key: str, value: str, ttl: Optional[int] = None) -> None:
        ttl = ttl or self.config.get("default_ttl", 300)
        if hasattr(self, "_redis"):
            self._redis.setex(key, ttl, value)
        else:
            import time
            self._cache[key] = value
            self._expiry[key] = time.time() + ttl

    async def delete(self, key: str) -> None:
        if hasattr(self, "_redis"):
            self._redis.delete(key)
        else:
            self._cache.pop(key, None)
            self._expiry.pop(key, None)
