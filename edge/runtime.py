"""
Edge Runtime for PyFault framework.

Lightweight runtime for executing functions at the edge with:
- Fast cold start optimization
- Function isolation and sandboxing
- Resource limits and quotas
- Streaming and batch processing
- WebAssembly and native support
"""

import asyncio
import builtins
import collections
import functools
import hashlib
import itertools
import json
import logging
import math
import random
import re
import string
import time
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

# Restricted execution environment for user-supplied function code.
#
# NOTE: This is *defense-in-depth*, not a hard security boundary. ``exec`` with
# a curated builtins table still cannot stop a determined attacker who can reach
# object internals via literals (e.g. ``().__class__.__bases__[0].__subclasses__()``).
# Untrusted code MUST additionally run inside OS-level isolation (separate
# process / container / seccomp). We still remove import/eval/exec/file IO and
# pre-inject a small set of safe, commonly-needed modules.
_SAFE_MODULES: dict[str, Any] = {
    "json": json,
    "math": math,
    "re": re,
    "random": random,
    "string": string,
    "collections": collections,
    "itertools": itertools,
    "functools": functools,
    "time": time,
    "datetime": datetime,
}

# Allowed builtins for function code. Deliberately excludes import/eval/exec/
# compile/open/globals/locals/vars/getattr/setattr/delattr/input/exit/quit/help
# and other escape primitives.
_SAFE_BUILTIN_NAMES: tuple[str, ...] = (
    "abs", "all", "any", "ascii", "bin", "bool", "bytearray", "bytes",
    "callable", "chr", "complex", "dict", "divmod", "enumerate", "filter",
    "float", "format", "frozenset", "hex", "int", "isinstance", "issubclass",
    "iter", "len", "list", "map", "max", "min", "next", "object", "oct",
    "ord", "pow", "print", "range", "repr", "reversed", "round", "set",
    "slice", "sorted", "str", "sum", "tuple", "type", "zip",
    "BaseException", "Exception", "ValueError", "TypeError", "KeyError",
    "IndexError", "RuntimeError", "StopIteration", "AttributeError",
    "ArithmeticError", "ZeroDivisionError", "OverflowError",
    "FileNotFoundError", "NotImplementedError", "Warning", "UserWarning",
)

_SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(builtins, name)
    for name in _SAFE_BUILTIN_NAMES
    if hasattr(builtins, name)
}

# Globals dict handed to exec() for every user function.
PYTHON_EXECUTOR_SAFE_GLOBALS: dict[str, Any] = {
    "__builtins__": _SAFE_BUILTINS,
    "__name__": "__edge_function__",
    **_SAFE_MODULES,
}


class FunctionRuntime(str, Enum):
    """Supported function runtimes."""
    PYTHON = "python"
    JAVASCRIPT = "javascript"
    WASM = "wasm"
    NATIVE = "native"
    DOCKER = "docker"


class FunctionStatus(str, Enum):
    """Function deployment status."""
    PENDING = "pending"
    DEPLOYING = "deploying"
    READY = "ready"
    ERROR = "error"
    STOPPED = "stopped"
    DEPRECATED = "deprecated"


@dataclass
class FunctionConfig:
    """Function configuration."""
    function_id: str
    name: str
    runtime: FunctionRuntime = FunctionRuntime.PYTHON
    handler: str = "handler"
    code: str = ""
    code_hash: str = ""
    memory_mb: int = 128
    timeout_ms: int = 30000
    env_vars: dict[str, str] = field(default_factory=dict)
    secrets: dict[str, str] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    triggers: list[dict[str, Any]] = field(default_factory=list)
    concurrency_limit: int = 100
    reserved_concurrency: int = 0
    vpc_config: dict[str, Any] = field(default_factory=dict)
    layers: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def compute_hash(self) -> str:
        content = f"{self.code}:{self.handler}:{self.runtime.value}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


@dataclass
class InvocationRequest:
    """Function invocation request."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    function_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    query_params: dict[str, str] = field(default_factory=dict)
    path_params: dict[str, str] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_span_id: Optional[str] = None


@dataclass
class InvocationResponse:
    """Function invocation response."""
    request_id: str
    function_id: str
    status_code: int = 200
    payload: Any = None
    headers: dict[str, str] = field(default_factory=dict)
    error: Optional[str] = None
    duration_ms: float = 0.0
    cold_start: bool = False
    timestamp: datetime = field(default_factory=datetime.utcnow)
    trace_id: str = ""
    span_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "function_id": self.function_id,
            "status_code": self.status_code,
            "payload": self.payload,
            "headers": self.headers,
            "error": self.error,
            "duration_ms": self.duration_ms,
            "cold_start": self.cold_start,
            "timestamp": self.timestamp.isoformat(),
            "trace_id": self.trace_id,
            "span_id": self.span_id,
        }


@dataclass
class FunctionMetrics:
    """Function execution metrics."""
    function_id: str = ""
    invocations: int = 0
    errors: int = 0
    cold_starts: int = 0
    total_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0
    max_duration_ms: float = 0.0
    min_duration_ms: float = float('inf')
    p50_duration_ms: float = 0.0
    p95_duration_ms: float = 0.0
    p99_duration_ms: float = 0.0
    last_invocation: Optional[datetime] = None
    memory_used_mb: float = 0.0
    cpu_used_percent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "function_id": self.function_id,
            "invocations": self.invocations,
            "errors": self.errors,
            "cold_starts": self.cold_starts,
            "error_rate": self.errors / max(1, self.invocations),
            "cold_start_rate": self.cold_starts / max(1, self.invocations),
            "avg_duration_ms": self.avg_duration_ms,
            "max_duration_ms": self.max_duration_ms,
            "min_duration_ms": self.min_duration_ms if self.min_duration_ms != float('inf') else 0,
            "p50_duration_ms": self.p50_duration_ms,
            "p95_duration_ms": self.p95_duration_ms,
            "p99_duration_ms": self.p99_duration_ms,
            "last_invocation": self.last_invocation.isoformat() if self.last_invocation else None,
            "memory_used_mb": self.memory_used_mb,
            "cpu_used_percent": self.cpu_used_percent,
        }


class FunctionExecutor(ABC):
    """Abstract function executor."""

    @abstractmethod
    async def initialize(self, config: FunctionConfig) -> bool:
        """Initialize the executor with function config."""
        pass

    @abstractmethod
    async def invoke(
        self,
        config: FunctionConfig,
        request: InvocationRequest,
    ) -> InvocationResponse:
        """Invoke the function."""
        pass

    @abstractmethod
    async def shutdown(self) -> None:
        """Shutdown the executor."""
        pass

    @abstractmethod
    def is_ready(self) -> bool:
        """Check if executor is ready."""
        pass


class PythonExecutor(FunctionExecutor):
    """Python function executor with sandboxing."""

    def __init__(self) -> None:
        self._globals: dict[str, Any] = {}
        self._initialized = False
        self._config: Optional[FunctionConfig] = None

    async def initialize(self, config: FunctionConfig) -> bool:
        self._config = config
        try:
            # Execute function code in a *restricted* namespace. Only the curated
            # builtins and pre-injected safe modules are visible; import/eval/
            # exec/file IO are unavailable to user code. Each deployment gets a
            # fresh copy so functions cannot leak state into one another.
            safe_globals = dict(PYTHON_EXECUTOR_SAFE_GLOBALS)
            exec(config.code, safe_globals)
            self._globals = safe_globals

            # Verify handler exists
            if config.handler not in self._globals:
                raise ValueError(f"Handler {config.handler} not found in code")

            self._initialized = True
            logger.info(f"Python executor initialized for {config.function_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Python executor: {e}")
            return False

    async def invoke(
        self,
        config: FunctionConfig,
        request: InvocationRequest,
    ) -> InvocationResponse:
        if not self._initialized:
            return InvocationResponse(
                request_id=request.request_id,
                function_id=config.function_id,
                status_code=500,
                error="Executor not initialized",
                trace_id=request.trace_id,
            )

        start = time.perf_counter()
        cold_start = not hasattr(self, '_warmed_up')
        self._warmed_up = True

        try:
            handler = self._globals[config.handler]

            # Prepare invocation context
            context = {
                "request_id": request.request_id,
                "trace_id": request.trace_id,
                "function_name": config.name,
                "memory_limit_mb": config.memory_mb,
                "timeout_ms": config.timeout_ms,
                **request.context,
            }

            # Invoke handler
            if asyncio.iscoroutinefunction(handler):
                result = await asyncio.wait_for(
                    handler(request.payload, context),
                    timeout=config.timeout_ms / 1000,
                )
            else:
                result = await asyncio.wait_for(
                    asyncio.to_thread(handler, request.payload, context),
                    timeout=config.timeout_ms / 1000,
                )

            duration_ms = (time.perf_counter() - start) * 1000

            return InvocationResponse(
                request_id=request.request_id,
                function_id=config.function_id,
                status_code=200,
                payload=result,
                duration_ms=duration_ms,
                cold_start=cold_start,
                trace_id=request.trace_id,
                span_id=str(uuid.uuid4())[:16],
            )

        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start) * 1000
            return InvocationResponse(
                request_id=request.request_id,
                function_id=config.function_id,
                status_code=504,
                error=f"Function timeout after {config.timeout_ms}ms",
                duration_ms=duration_ms,
                cold_start=cold_start,
                trace_id=request.trace_id,
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(f"Function invocation error: {e}")
            return InvocationResponse(
                request_id=request.request_id,
                function_id=config.function_id,
                status_code=500,
                error=str(e),
                duration_ms=duration_ms,
                cold_start=cold_start,
                trace_id=request.trace_id,
            )

    async def shutdown(self) -> None:
        self._globals.clear()
        self._initialized = False

    def is_ready(self) -> bool:
        return self._initialized


class EdgeRuntime:
    """
    Edge function runtime manager.
    """

    def __init__(
        self,
        max_concurrent_invocations: int = 1000,
        default_memory_mb: int = 128,
        default_timeout_ms: int = 30000,
    ):
        self.max_concurrent = max_concurrent_invocations
        self.default_memory = default_memory_mb
        self.default_timeout = default_timeout_ms

        self._functions: dict[str, FunctionConfig] = {}
        self._executors: dict[str, FunctionExecutor] = {}
        self._metrics: dict[str, FunctionMetrics] = defaultdict(FunctionMetrics)
        self._invocation_semaphore = asyncio.Semaphore(max_concurrent_invocations)
        self._reserved_semaphores: dict[str, asyncio.Semaphore] = {}
        self._running = False

    async def deploy_function(self, config: FunctionConfig) -> bool:
        """Deploy a function to the edge runtime."""
        if config.function_id in self._functions:
            return await self.update_function(config)

        config.code_hash = config.compute_hash()
        config.updated_at = datetime.utcnow()

        # Create executor
        executor = self._create_executor(config.runtime)
        if not executor:
            return False

        success = await executor.initialize(config)
        if not success:
            return False

        self._functions[config.function_id] = config
        self._executors[config.function_id] = executor
        self._metrics[config.function_id] = FunctionMetrics(function_id=config.function_id)

        # Per-function reserved concurrency limiter (falls back to the global
        # limiter when not configured). Replaces the previous no-op placeholder.
        cap = config.reserved_concurrency if (config.reserved_concurrency or 0) > 0 else self.max_concurrent
        self._reserved_semaphores[config.function_id] = asyncio.Semaphore(cap)

        logger.info(f"Deployed function: {config.name} ({config.function_id})")
        return True

    def _create_executor(self, runtime: FunctionRuntime) -> Optional[FunctionExecutor]:
        if runtime == FunctionRuntime.PYTHON:
            return PythonExecutor()
        # Add other runtimes
        return None

    async def update_function(self, config: FunctionConfig) -> bool:
        """Update an existing function."""
        if config.function_id not in self._functions:
            return False

        old_config = self._functions[config.function_id]
        if config.code_hash == old_config.code_hash:
            # Only config changed, update in place
            config.updated_at = datetime.utcnow()
            self._functions[config.function_id] = config
            return True

        # Code changed, recreate executor
        await self.undeploy_function(config.function_id)
        return await self.deploy_function(config)

    async def undeploy_function(self, function_id: str) -> bool:
        """Remove a function from the runtime."""
        if function_id not in self._functions:
            return False

        executor = self._executors.get(function_id)
        if executor:
            await executor.shutdown()
            del self._executors[function_id]

        del self._functions[function_id]
        del self._metrics[function_id]
        self._reserved_semaphores.pop(function_id, None)

        logger.info(f"Undeployed function: {function_id}")
        return True

    async def invoke(
        self,
        function_id: str,
        payload: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        context: Optional[dict[str, Any]] = None,
        trace_id: Optional[str] = None,
    ) -> InvocationResponse:
        """Invoke a function."""
        config = self._functions.get(function_id)
        if not config:
            return InvocationResponse(
                request_id=str(uuid.uuid4()),
                function_id=function_id,
                status_code=404,
                error=f"Function not found: {function_id}",
            )

        executor = self._executors.get(function_id)
        if not executor or not executor.is_ready():
            return InvocationResponse(
                request_id=str(uuid.uuid4()),
                function_id=function_id,
                status_code=503,
                error="Function not ready",
            )

        # Enforce per-function reserved concurrency (if configured), layered on
        # top of the global invocation limiter.
        reserved = self._reserved_semaphores.get(function_id)

        async def _run() -> InvocationResponse:
            async with self._invocation_semaphore:
                request = InvocationRequest(
                    function_id=function_id,
                    payload=payload or {},
                    headers=headers or {},
                    context=context or {},
                    trace_id=trace_id or str(uuid.uuid4()),
                )

                response = await executor.invoke(config, request)

                # Update metrics
                self._update_metrics(function_id, response)

                return response

        if reserved is not None:
            async with reserved:
                return await _run()

        return await _run()

    def _update_metrics(self, function_id: str, response: InvocationResponse) -> None:
        metrics = self._metrics[function_id]
        metrics.invocations += 1
        metrics.last_invocation = datetime.utcnow()

        if response.error:
            metrics.errors += 1
        if response.cold_start:
            metrics.cold_starts += 1

        metrics.total_duration_ms += response.duration_ms
        metrics.avg_duration_ms = metrics.total_duration_ms / metrics.invocations
        metrics.max_duration_ms = max(metrics.max_duration_ms, response.duration_ms)
        metrics.min_duration_ms = min(metrics.min_duration_ms, response.duration_ms)

    def get_function(self, function_id: str) -> Optional[FunctionConfig]:
        return self._functions.get(function_id)

    def list_functions(self) -> list[FunctionConfig]:
        return list(self._functions.values())

    def get_metrics(self, function_id: Optional[str] = None) -> dict[str, Any]:
        if function_id:
            metrics = self._metrics.get(function_id)
            return metrics.to_dict() if metrics else {}
        return {fid: m.to_dict() for fid, m in self._metrics.items()}

    async def start(self) -> None:
        self._running = True
        logger.info("Edge runtime started")

    async def stop(self) -> None:
        self._running = False
        for function_id in list(self._functions.keys()):
            await self.undeploy_function(function_id)
        logger.info("Edge runtime stopped")


class FunctionPool:
    """
    Pre-warmed function pool for cold start reduction.
    """

    def __init__(self, runtime: EdgeRuntime, pool_size: int = 10):
        self.runtime = runtime
        self.pool_size = pool_size
        self._warmed_functions: set[str] = set()
        self._warm_tasks: dict[str, asyncio.Task] = {}

    async def warm_function(
        self,
        function_id: str,
        warm_payload: Optional[dict[str, Any]] = None,
    ) -> bool:
        """Pre-warm a function by invoking it."""
        if function_id in self._warmed_functions:
            return True

        response = await self.runtime.invoke(
            function_id,
            payload=warm_payload or {"_warm": True},
            context={"_prewarm": True},
        )

        if response.status_code == 200:
            self._warmed_functions.add(function_id)
            logger.info(f"Function warmed: {function_id}")
            return True

        return False

    async def warm_all(self, warm_payload: Optional[dict[str, Any]] = None) -> dict[str, bool]:
        """Warm all deployed functions."""
        results: dict[str, bool] = {}
        for config in self.runtime.list_functions():
            results[config.function_id] = await self.warm_function(config.function_id, warm_payload)
        return results

    def is_warmed(self, function_id: str) -> bool:
        return function_id in self._warmed_functions

    async def maintain_pool(self, interval: int = 300) -> None:
        """Periodically re-warm functions to keep pool hot."""
        while True:
            await asyncio.sleep(interval)
            for function_id in list(self._warmed_functions):
                await self.warm_function(function_id)


# Global runtime
_edge_runtime: Optional[EdgeRuntime] = None


def get_runtime() -> EdgeRuntime:
    global _edge_runtime
    if _edge_runtime is None:
        _edge_runtime = EdgeRuntime()
    return _edge_runtime


def set_runtime(runtime: EdgeRuntime) -> None:
    global _edge_runtime
    _edge_runtime = runtime


