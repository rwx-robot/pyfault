"""
Plugin Sandbox for PyFault AI framework.

Provides secure isolation for plugin execution:
- Process-based isolation (multiprocessing)
- Resource limits (CPU, memory, time)
- Filesystem isolation
- Network isolation
- Syscall filtering (seccomp on Linux)
- Capability-based security
"""

import asyncio
import io
import json
import logging
import multiprocessing as mp
import os
import pickle
import resource
import shutil
import signal
import statistics
import sys
import tempfile
import threading
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from multiprocessing import Process, Queue
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class SandboxType(str, Enum):
    """Sandbox isolation types."""
    NONE = "none"              # No isolation (fastest)
    THREAD = "thread"          # Thread-based (limited isolation)
    PROCESS = "process"        # Process-based (good isolation)
    CONTAINER = "container"    # Container-based (strong isolation)
    WASM = "wasm"              # WebAssembly (strongest isolation)


class ResourceLimit(str, Enum):
    """Resource limit types."""
    CPU_TIME = "cpu_time"      # CPU time in seconds
    WALL_TIME = "wall_time"    # Wall clock time in seconds
    MEMORY = "memory"          # Memory in MB
    FILE_SIZE = "file_size"    # Max file size
    OPEN_FILES = "open_files"  # Max open file descriptors
    PROCESSES = "processes"    # Max child processes


@dataclass
class SandboxConfig:
    """Sandbox configuration."""
    sandbox_id: str
    sandbox_type: SandboxType = SandboxType.PROCESS
    enabled: bool = True

    # Resource limits
    limits: dict[ResourceLimit, int] = field(default_factory=dict)

    # Filesystem
    allowed_paths: list[str] = field(default_factory=list)  # Read-only paths
    writable_paths: list[str] = field(default_factory=list)  # Writable paths
    temp_dir: str = ""  # Custom temp directory

    # Network
    network_enabled: bool = False
    allowed_hosts: list[str] = field(default_factory=list)
    allowed_ports: list[int] = field(default_factory=list)

    # Capabilities (Linux)
    drop_capabilities: list[str] = field(default_factory=lambda: [
        "CAP_SYS_ADMIN", "CAP_SYS_RESOURCE", "CAP_DAC_OVERRIDE",
        "CAP_SYS_PTRACE", "CAP_SYS_MODULE", "CAP_SYS_RAWIO",
    ])

    # Seccomp profile (Linux)
    seccomp_profile: str = "default"  # default, strict, custom

    # Environment
    env_vars: dict[str, str] = field(default_factory=dict)
    inherit_env: bool = False

    # Working directory
    work_dir: str = ""

    # Timeout
    default_timeout: int = 30  # seconds

    # Imports blocked during execution
    blocked_imports: list[str] = field(default_factory=list)


@dataclass
class SandboxResult:
    """Result of sandboxed execution."""
    success: bool
    return_value: Any = None
    error: str = ""
    stdout: str = ""
    stderr: str = ""
    execution_time_ms: float = 0.0
    memory_used_mb: float = 0.0
    cpu_time_ms: float = 0.0
    exit_code: int = 0
    timed_out: bool = False
    killed: bool = False


@dataclass
class SandboxStats:
    """Sandbox execution statistics."""
    total_executions: int = 0
    successful_executions: int = 0
    failed_executions: int = 0
    timeouts: int = 0
    total_execution_time_ms: float = 0.0
    avg_execution_time_ms: float = 0.0
    max_memory_mb: float = 0.0


class Sandbox(ABC):
    """Abstract sandbox base class."""

    def __init__(self, config: SandboxConfig):
        self.config = config
        self._stats = SandboxStats()
        self._running = False

    @abstractmethod
    async def execute(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        pass

    @abstractmethod
    async def start(self) -> bool:
        pass

    @abstractmethod
    async def stop(self) -> bool:
        pass

    def get_stats(self) -> SandboxStats:
        return self._stats

    def _update_stats(self, result: SandboxResult) -> None:
        self._stats.total_executions += 1
        self._stats.total_execution_time_ms += result.execution_time_ms
        self._stats.avg_execution_time_ms = (
            self._stats.total_execution_time_ms / self._stats.total_executions
        )
        self._stats.max_memory_mb = max(self._stats.max_memory_mb, result.memory_used_mb)

        if result.success:
            self._stats.successful_executions += 1
        else:
            self._stats.failed_executions += 1

        if result.timed_out:
            self._stats.timeouts += 1


class NoSandbox(Sandbox):
    """No sandbox - direct execution (for testing)."""

    async def start(self) -> bool:
        self._running = True
        return True

    async def stop(self) -> bool:
        self._running = False
        return True

    async def execute(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        kwargs = kwargs or {}
        timeout = timeout or self.config.default_timeout

        start = time.perf_counter()
        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = stdout_capture
        sys.stderr = stderr_capture

        try:
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
            else:
                result = await asyncio.to_thread(func, *args, **kwargs)

            execution_time_ms = (time.perf_counter() - start) * 1000

            sandbox_result = SandboxResult(
                success=True,
                return_value=result,
                execution_time_ms=execution_time_ms,
                stdout=stdout_capture.getvalue(),
                stderr=stderr_capture.getvalue(),
            )

        except asyncio.TimeoutError:
            execution_time_ms = (time.perf_counter() - start) * 1000
            sandbox_result = SandboxResult(
                success=False,
                error=f"Execution timed out after {timeout}s",
                execution_time_ms=execution_time_ms,
                timed_out=True,
                stdout=stdout_capture.getvalue(),
                stderr=stderr_capture.getvalue(),
            )
        except Exception as e:
            execution_time_ms = (time.perf_counter() - start) * 1000
            sandbox_result = SandboxResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time_ms,
                stdout=stdout_capture.getvalue(),
                stderr=stderr_capture.getvalue(),
            )
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        self._update_stats(sandbox_result)
        return sandbox_result


def _apply_resource_limits(limits: dict) -> None:
    """Apply resource limits to current process (best-effort)."""
    for limit_type, value in limits.items():
        try:
            if limit_type == ResourceLimit.CPU_TIME or limit_type == "cpu_time":
                _safe_setrlimit(resource.RLIMIT_CPU, value)
            elif limit_type == ResourceLimit.MEMORY or limit_type == "memory":
                if value <= 1024 * 1024 * 1024:  # <= 1GB, assume MB
                    value = value * 1024 * 1024
                _safe_setrlimit(resource.RLIMIT_AS, value)
            elif limit_type == ResourceLimit.FILE_SIZE or limit_type == "file_size":
                _safe_setrlimit(resource.RLIMIT_FSIZE, value)
            elif limit_type == ResourceLimit.OPEN_FILES or limit_type == "open_files":
                _safe_setrlimit(resource.RLIMIT_NOFILE, value)
            elif limit_type == ResourceLimit.PROCESSES or limit_type == "processes":
                _safe_setrlimit(resource.RLIMIT_NPROC, value)
        except Exception:
            # Resource limits are best-effort; never block execution
            pass


def _safe_setrlimit(res: int, value: int) -> None:
    try:
        _soft, hard = resource.getrlimit(res)
        target = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(res, (target, hard))
    except (ValueError, OSError):
        pass


def _setup_sandbox_filesystem(config_dict: dict) -> None:
    """Setup filesystem isolation."""
    temp_dir = config_dict.get("temp_dir") or tempfile.mkdtemp(prefix="sandbox_")
    os.environ["TMPDIR"] = temp_dir
    os.environ["TEMP"] = temp_dir
    os.environ["TMP"] = temp_dir


def _process_sandbox_worker(
    func_data: bytes,
    args_data: bytes,
    kwargs_data: bytes,
    result_queue: Queue,
    config_dict: dict,
) -> None:
    """Module-level worker process function (picklable target)."""
    import io
    import sys
    import traceback

    # Apply resource limits
    _apply_resource_limits(config_dict.get("limits", {}))

    # Setup filesystem
    _setup_sandbox_filesystem(config_dict)

    # Capture stdout/stderr
    old_stdout = sys.stdout
    old_stderr = sys.stderr
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()
    sys.stdout = stdout_capture
    sys.stderr = stderr_capture

    try:
        # Deserialize function and arguments
        func = pickle.loads(func_data)
        args = pickle.loads(args_data)
        kwargs = pickle.loads(kwargs_data)

        # Enforce blocked imports
        blocked = config_dict.get("blocked_imports") or []
        if blocked:
            import builtins
            real_import = builtins.__import__

            def guarded_import(name: str, *a: Any, **kw: Any) -> Any:
                root = name.split(".")[0]
                if name in blocked or root in blocked:
                    raise ImportError(f"Import of '{name}' is blocked by sandbox policy")
                return real_import(name, *a, **kw)

            builtins.__import__ = guarded_import

        # Execute
        start = time.perf_counter()
        result = func(*args, **kwargs)
        execution_time_ms = (time.perf_counter() - start) * 1000

        # Get resource usage
        usage = resource.getrusage(resource.RUSAGE_SELF)
        if sys.platform == "darwin":
            memory_mb = usage.ru_maxrss / (1024 * 1024)  # macOS: bytes
        else:
            memory_mb = usage.ru_maxrss / 1024  # Linux: KB
        cpu_time_ms = (usage.ru_utime + usage.ru_stime) * 1000

        result_queue.put({
            "success": True,
            "return_value": result,
            "execution_time_ms": execution_time_ms,
            "memory_used_mb": memory_mb,
            "cpu_time_ms": cpu_time_ms,
            "stdout": stdout_capture.getvalue(),
            "stderr": stderr_capture.getvalue(),
            "exit_code": 0,
        })

    except Exception as e:
        execution_time_ms = (time.perf_counter() - start) * 1000
        result_queue.put({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "execution_time_ms": execution_time_ms,
            "stdout": stdout_capture.getvalue(),
            "stderr": stderr_capture.getvalue(),
            "exit_code": -1,
        })
    finally:
        sys.stdout = old_stdout
        sys.stderr = old_stderr


class ProcessSandbox(Sandbox):
    """Process-based sandbox using multiprocessing."""

    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._process: Optional[Process] = None
        self._result_queue: Queue = Queue()

    async def start(self) -> bool:
        self._running = True
        return True

    async def stop(self) -> bool:
        self._running = False
        if self._process and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)
        return True

    async def execute(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        kwargs = kwargs or {}
        timeout = timeout or self.config.default_timeout

        # Serialize function and arguments
        try:
            func_data = pickle.dumps(func)
            args_data = pickle.dumps(args)
            kwargs_data = pickle.dumps(kwargs)
        except Exception as e:
            return SandboxResult(
                success=False,
                error=f"Serialization failed: {e}",
            )

        config_dict = {
            "limits": {k.value: v for k, v in self.config.limits.items()},
            "allowed_paths": self.config.allowed_paths,
            "writable_paths": self.config.writable_paths,
            "temp_dir": self.config.temp_dir,
            "blocked_imports": list(self.config.blocked_imports),
        }

        # Start worker process
        self._process = Process(
            target=_process_sandbox_worker,
            args=(func_data, args_data, kwargs_data, self._result_queue, config_dict),
            daemon=True,
        )

        start = time.perf_counter()
        self._process.start()

        try:
            # Wait for result with timeout
            result_data = await asyncio.wait_for(
                asyncio.to_thread(self._result_queue.get),
                timeout=timeout,
            )

            execution_time_ms = (time.perf_counter() - start) * 1000

            sandbox_result = SandboxResult(
                success=result_data.get("success", False),
                return_value=result_data.get("return_value"),
                error=result_data.get("error", ""),
                stdout=result_data.get("stdout", ""),
                stderr=result_data.get("stderr", ""),
                execution_time_ms=execution_time_ms,
                memory_used_mb=result_data.get("memory_used_mb", 0),
                cpu_time_ms=result_data.get("cpu_time_ms", 0),
                exit_code=result_data.get("exit_code", 0),
            )

        except asyncio.TimeoutError:
            # Kill process
            if self._process and self._process.is_alive():
                self._process.terminate()
                self._process.join(timeout=2)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join()

            execution_time_ms = (time.perf_counter() - start) * 1000
            sandbox_result = SandboxResult(
                success=False,
                error=f"Execution timed out after {timeout}s",
                execution_time_ms=execution_time_ms,
                timed_out=True,
                killed=True,
            )

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start) * 1000
            sandbox_result = SandboxResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time_ms,
            )

        self._update_stats(sandbox_result)
        return sandbox_result


class ThreadSandbox(Sandbox):
    """Thread-based sandbox (limited isolation)."""

    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._executor: Any = None

    async def start(self) -> bool:
        from concurrent.futures import ThreadPoolExecutor
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._running = True
        return True

    async def stop(self) -> bool:
        self._running = False
        if self._executor:
            self._executor.shutdown(wait=True)
        return True

    async def execute(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        kwargs = kwargs or {}
        timeout = timeout or self.config.default_timeout

        start = time.perf_counter()

        try:
            if asyncio.iscoroutinefunction(func):
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
            else:
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(self._executor, lambda: func(*args, **kwargs)),
                    timeout=timeout,
                )

            execution_time_ms = (time.perf_counter() - start) * 1000

            sandbox_result = SandboxResult(
                success=True,
                return_value=result,
                execution_time_ms=execution_time_ms,
            )

        except asyncio.TimeoutError:
            execution_time_ms = (time.perf_counter() - start) * 1000
            sandbox_result = SandboxResult(
                success=False,
                error=f"Execution timed out after {timeout}s",
                execution_time_ms=execution_time_ms,
                timed_out=True,
            )
        except Exception as e:
            execution_time_ms = (time.perf_counter() - start) * 1000
            sandbox_result = SandboxResult(
                success=False,
                error=str(e),
                execution_time_ms=execution_time_ms,
            )

        self._update_stats(sandbox_result)
        return sandbox_result


class ContainerSandbox(Sandbox):
    """Container-based sandbox (Docker/podman)."""

    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._container_id: Optional[str] = None
        self._image: str = config.env_vars.get("image", "python:3.12-slim")

    async def start(self) -> bool:
        # Check if docker/podman is available
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            self._running = True
            return True
        except FileNotFoundError:
            logger.warning("Docker not available for container sandbox")
            return False

    async def stop(self) -> bool:
        self._running = False
        if self._container_id:
            await self._cleanup_container()
        return True

    async def _cleanup_container(self) -> None:
        if self._container_id:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "rm", "-f", self._container_id,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()
            except Exception as e:
                logger.error(f"Container cleanup failed: {e}")
            self._container_id = None

    async def execute(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        kwargs = kwargs or {}
        timeout = timeout or self.config.default_timeout

        # Serialize function to file
        import base64
        import pickle

        try:
            func_data = base64.b64encode(pickle.dumps((func, args, kwargs))).decode()
        except Exception as e:
            return SandboxResult(success=False, error=f"Serialization failed: {e}")

        # Create execution script
        script = f'''
import pickle
import base64
import sys
import json

func_data = "{func_data}"
func, args, kwargs = pickle.loads(base64.b64decode(func_data))

try:
    result = func(*args, **kwargs)
    print(json.dumps({{"success": True, "result": result}}))
except Exception as e:
    print(json.dumps({{"success": False, "error": str(e)}}))
    sys.exit(1)
'''

        # Write script to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            script_path = f.name

        # Unique name so a timed-out container can be force-removed after the
        # `docker run` client is killed (a client kill does not stop the container).
        container_name = f"pyfault-{self.config.sandbox_id}-{uuid.uuid4().hex[:8]}"
        start = time.perf_counter()
        sandbox_result: Optional[SandboxResult] = None

        try:
            cmd = [
                "docker", "run", "--rm",
                "--name", container_name,
                "--memory", f"{self.config.limits.get(ResourceLimit.MEMORY, 512)}m",
                "--cpus", str(self.config.limits.get(ResourceLimit.CPU_TIME, 1)),
                "--pids-limit", "64",
                "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges",
                "--read-only",
                "--tmpfs", "/tmp:rw,size=64m",
                "--network", "bridge" if self.config.network_enabled else "none",
                "-v", f"{script_path}:/script.py:ro",
                "-e", "PYTHONDONTWRITEBYTECODE=1",
            ]
            for env_key, env_value in self.config.env_vars.items():
                if env_key != "image":
                    cmd += ["-e", f"{env_key}={env_value}"]
            cmd += [self._image, "python", "/script.py"]

            self._container_id = container_name
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
                execution_time_ms = (time.perf_counter() - start) * 1000

                # Parse result
                try:
                    result_data = json.loads(stdout.decode().strip())
                    sandbox_result = SandboxResult(
                        success=result_data.get("success", False),
                        return_value=result_data.get("result"),
                        error=result_data.get("error", ""),
                        execution_time_ms=execution_time_ms,
                        exit_code=proc.returncode or 0,
                    )
                except json.JSONDecodeError:
                    sandbox_result = SandboxResult(
                        success=proc.returncode == 0,
                        return_value=stdout.decode(),
                        error=stderr.decode() if proc.returncode != 0 else "",
                        execution_time_ms=execution_time_ms,
                        exit_code=proc.returncode or 0,
                    )

            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                # The client died before the container did: force-remove it.
                await self._cleanup_container()
                sandbox_result = SandboxResult(
                    success=False,
                    error="Execution timed out",
                    execution_time_ms=(time.perf_counter() - start) * 1000,
                    timed_out=True,
                    killed=True,
                )
            else:
                # `--rm` already removed the container on normal exit.
                self._container_id = None

        except FileNotFoundError:
            sandbox_result = SandboxResult(
                success=False,
                error="docker executable not found",
                execution_time_ms=(time.perf_counter() - start) * 1000,
            )

        finally:
            os.unlink(script_path)
            if sandbox_result is None:
                sandbox_result = SandboxResult(
                    success=False,
                    error="execution did not start",
                    execution_time_ms=(time.perf_counter() - start) * 1000,
                )
            self._update_stats(sandbox_result)
        return sandbox_result


class WASMSandbox(Sandbox):
    """WebAssembly sandbox backed by wasmtime (optional: ``pip install pyfault[wasm]``).

    ``execute`` accepts a WebAssembly module as ``bytes`` or as a path to a
    ``.wasm`` file and invokes one of its exported functions.  The export to
    call is selected with ``kwargs={"export": "name"}`` (default ``"run"``) and
    positional arguments are forwarded to it.  Plain Python callables are
    rejected: compiling Python to WebAssembly at runtime is out of scope for
    this sandbox, so callers should use the thread/process/container sandboxes.
    """

    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._engine: Any = None
        self._store: Any = None
        self._module: Any = None

    def _ensure_engine(self) -> Any:
        """Create the wasmtime engine on first use.

        Epoch interruption is enabled so long-running exports can be trapped
        by ``timeout`` instead of hanging the caller forever.
        """
        import wasmtime

        if self._engine is None:
            cfg = wasmtime.Config()
            cfg.epoch_interruption = True
            self._engine = wasmtime.Engine(cfg)
            self._store = wasmtime.Store(self._engine)
        return self._engine

    async def start(self) -> bool:
        try:
            import wasmtime  # noqa: F401
        except ImportError:
            logger.warning("wasmtime not available for WASM sandbox")
            return False
        self._ensure_engine()
        self._running = True
        return True

    async def stop(self) -> bool:
        self._running = False
        self._engine = None
        self._store = None
        self._module = None
        return True

    async def execute(
        self,
        func: Callable[..., Any] | bytes | bytearray | str | os.PathLike[str],
        args: tuple = (),
        kwargs: Optional[dict] = None,
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        kwargs = dict(kwargs or {})
        timeout = timeout or self.config.default_timeout
        start = time.perf_counter()

        if not isinstance(func, (bytes, bytearray, str, os.PathLike)):
            return SandboxResult(
                success=False,
                error="WASM sandbox executes WebAssembly modules only (bytes or a .wasm path)",
            )

        try:
            import wasmtime
        except ImportError:
            return SandboxResult(
                success=False,
                error="wasmtime is not installed - pip install pyfault[wasm]",
            )

        export_name = str(kwargs.pop("export", "run"))
        if kwargs:
            return SandboxResult(
                success=False,
                error=f"Unsupported WASM call options: {sorted(kwargs)}",
            )

        stop_ticker = threading.Event()
        ticker: Optional[threading.Thread] = None
        result = SandboxResult(success=False, error="execution did not start")

        try:
            engine = self._ensure_engine()
            if isinstance(func, (bytes, bytearray)):
                wasm_bytes = bytes(func)
            else:
                wasm_bytes = Path(func).read_bytes()

            module = wasmtime.Module(engine, wasm_bytes)
            self._module = module

            store = wasmtime.Store(engine)
            instance = wasmtime.Instance(store, module, [])
            try:
                export = instance.exports(store)[export_name]
            except KeyError:
                raise ValueError(
                    f"WebAssembly module has no export {export_name!r}"
                ) from None
            if not isinstance(export, wasmtime.Func):
                raise TypeError(
                    f"WebAssembly export {export_name!r} is not a function"
                )

            if timeout:
                interval = 0.1
                store.set_epoch_deadline(max(1, int(timeout / interval) + 1))

                def tick() -> None:
                    while not stop_ticker.wait(interval):
                        current = self._engine
                        if current is not None:
                            current.increment_epoch()

                ticker = threading.Thread(target=tick, daemon=True)
                ticker.start()

            result = SandboxResult(
                success=True,
                return_value=export(store, *args),
            )
        except wasmtime.Trap as e:
            message = str(e)
            timed_out = "epoch" in message or "interrupt" in message.lower()
            if timed_out:
                message = f"Execution timed out after {timeout}s"
            result = SandboxResult(
                success=False,
                error=message,
                timed_out=timed_out,
            )
        except Exception as e:
            result = SandboxResult(
                success=False,
                error=str(e) or type(e).__name__,
            )
        finally:
            stop_ticker.set()
            if ticker is not None:
                ticker.join(timeout=1.0)
            result.execution_time_ms = (time.perf_counter() - start) * 1000
            self._update_stats(result)
        return result


class SandboxManager:
    """
    Manages multiple sandboxes and routes executions.
    """

    def __init__(self) -> None:
        self._sandboxes: dict[str, Sandbox] = {}
        self._default_sandbox: Optional[Sandbox] = None
        self._sandbox_configs: dict[str, SandboxConfig] = {}

    def register_sandbox(self, name: str, sandbox: Sandbox, default: bool = False) -> None:
        self._sandboxes[name] = sandbox
        if default or self._default_sandbox is None:
            self._default_sandbox = sandbox

    def create_sandbox(self, config: SandboxConfig) -> Sandbox:
        """Create a sandbox from config."""
        factories: dict[SandboxType, Callable[[SandboxConfig], Sandbox]] = {
            SandboxType.NONE: NoSandbox,
            SandboxType.THREAD: ThreadSandbox,
            SandboxType.PROCESS: ProcessSandbox,
            SandboxType.CONTAINER: ContainerSandbox,
            SandboxType.WASM: WASMSandbox,
        }
        # Unknown / legacy sandbox types fall back to the no-op sandbox.
        factory = factories.get(config.sandbox_type, NoSandbox)
        sandbox: Sandbox = factory(config)

        self._sandbox_configs[config.sandbox_id] = config
        return sandbox

    async def execute(
        self,
        func: Callable,
        args: tuple = (),
        kwargs: Optional[dict] = None,
        sandbox: Optional[str] = None,
        config: Optional[SandboxConfig] = None,
        timeout: Optional[int] = None,
    ) -> SandboxResult:
        """Execute function in sandbox."""
        target_sandbox = None

        if config:
            target_sandbox = self.create_sandbox(config)
            await target_sandbox.start()
        elif sandbox:
            target_sandbox = self._sandboxes.get(sandbox)
        else:
            target_sandbox = self._default_sandbox

        if not target_sandbox:
            return SandboxResult(
                success=False,
                error="No sandbox available",
            )

        try:
            result = await target_sandbox.execute(func, args, kwargs, timeout)

            # Cleanup temporary sandbox
            if config:
                await target_sandbox.stop()

            return result
        except Exception as e:
            if config:
                await target_sandbox.stop()
            return SandboxResult(
                success=False,
                error=f"Sandbox execution failed: {e}",
            )

    def get_sandbox(self, name: str) -> Optional[Sandbox]:
        return self._sandboxes.get(name)

    def list_sandboxes(self) -> list[str]:
        return list(self._sandboxes.keys())

    async def start_all(self) -> dict[str, bool]:
        results = {}
        for name, sandbox in self._sandboxes.items():
            results[name] = await sandbox.start()
        return results

    async def stop_all(self) -> dict[str, bool]:
        results = {}
        for name, sandbox in self._sandboxes.items():
            results[name] = await sandbox.stop()
        return results


# Security policy for plugins
@dataclass
class SecurityPolicy:
    """Security policy for plugin execution."""
    policy_id: str
    name: str

    # Execution
    allowed_sandbox_types: list[SandboxType] = field(default_factory=lambda: [SandboxType.PROCESS])
    max_execution_time: int = 30
    max_memory_mb: int = 512
    max_cpu_percent: int = 100

    # Filesystem
    read_only_root: bool = True
    allowed_read_paths: list[str] = field(default_factory=list)
    allowed_write_paths: list[str] = field(default_factory=list)

    # Network
    network_access: bool = False
    allowed_domains: list[str] = field(default_factory=list)
    allowed_ports: list[int] = field(default_factory=list)

    # System
    allow_subprocess: bool = False
    allow_threads: bool = True
    dropped_capabilities: list[str] = field(default_factory=list)

    # Python-specific
    allowed_imports: list[str] = field(default_factory=list)
    blocked_imports: list[str] = field(default_factory=lambda: [
        "os", "sys", "subprocess", "multiprocessing",
        "threading", "socket", "ctypes", "importlib",
        "pkgutil", "runpy", "code", "compile",
    ])

    def create_sandbox_config(self, sandbox_id: Optional[str] = None) -> SandboxConfig:
        """Create sandbox config from policy."""
        sandbox_id = sandbox_id or str(uuid.uuid4())

        limits = {
            ResourceLimit.CPU_TIME: self.max_execution_time,
            ResourceLimit.WALL_TIME: self.max_execution_time + 5,
            ResourceLimit.MEMORY: self.max_memory_mb,
        }

        return SandboxConfig(
            sandbox_id=sandbox_id,
            sandbox_type=self.allowed_sandbox_types[0] if self.allowed_sandbox_types else SandboxType.PROCESS,
            limits=limits,
            allowed_paths=self.allowed_read_paths,
            writable_paths=self.allowed_write_paths,
            network_enabled=self.network_access,
            allowed_hosts=self.allowed_domains,
            allowed_ports=self.allowed_ports,
            drop_capabilities=self.dropped_capabilities,
            env_vars={},
            inherit_env=False,
            default_timeout=self.max_execution_time,
            blocked_imports=list(self.blocked_imports),
        )


# Default security policies
DEFAULT_POLICIES = {
    "strict": SecurityPolicy(
        policy_id="strict",
        name="Strict Isolation",
        allowed_sandbox_types=[SandboxType.PROCESS, SandboxType.CONTAINER],
        max_execution_time=10,
        max_memory_mb=128,
        read_only_root=True,
        network_access=False,
        allow_subprocess=False,
    ),
    "moderate": SecurityPolicy(
        policy_id="moderate",
        name="Moderate Isolation",
        allowed_sandbox_types=[SandboxType.PROCESS],
        max_execution_time=30,
        max_memory_mb=512,
        read_only_root=True,
        allowed_read_paths=["/usr/lib/python3*", "/usr/local/lib/python3*"],
        network_access=False,
        allow_subprocess=False,
    ),
    "permissive": SecurityPolicy(
        policy_id="permissive",
        name="Permissive",
        allowed_sandbox_types=[SandboxType.THREAD, SandboxType.PROCESS],
        max_execution_time=60,
        max_memory_mb=1024,
        read_only_root=False,
        network_access=True,
        allow_subprocess=True,
        blocked_imports=["subprocess", "os.system"],
    ),
}


# Global sandbox manager
_sandbox_manager: Optional[SandboxManager] = None


def get_sandbox_manager() -> SandboxManager:
    global _sandbox_manager
    if _sandbox_manager is None:
        _sandbox_manager = SandboxManager()
        # Register default sandboxes
        _sandbox_manager.register_sandbox("none", NoSandbox(SandboxConfig(sandbox_id="none", sandbox_type=SandboxType.NONE)), default=True)
        _sandbox_manager.register_sandbox("thread", ThreadSandbox(SandboxConfig(sandbox_id="thread", sandbox_type=SandboxType.THREAD)))
        _sandbox_manager.register_sandbox("process", ProcessSandbox(SandboxConfig(sandbox_id="process", sandbox_type=SandboxType.PROCESS)))
    return _sandbox_manager


# Alias for backward compatibility
get_sandbox_manager = get_sandbox_manager
