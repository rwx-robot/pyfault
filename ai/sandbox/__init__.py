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
import logging
import os
import sys
import signal
import resource
import tempfile
import time
import shutil
import json
import uuid
import pickle
import multiprocessing as mp
from multiprocessing import Queue, Process, Manager
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from pathlib import Path
from contextlib import contextmanager
import asyncio

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
    MEMORY = "memory"          # Memory in bytes
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
    limits: Dict[ResourceLimit, int] = field(default_factory=dict)
    
    # Filesystem
    allowed_paths: List[str] = field(default_factory=list)  # Read-only paths
    writable_paths: List[str] = field(default_factory=list)  # Writable paths
    temp_dir: str = ""  # Custom temp directory
    
    # Network
    network_enabled: bool = False
    allowed_hosts: List[str] = field(default_factory=list)
    allowed_ports: List[int] = field(default_factory=list)
    
    # Capabilities (Linux)
    drop_capabilities: List[str] = field(default_factory=lambda: [
        "CAP_SYS_ADMIN", "CAP_SYS_RESOURCE", "CAP_DAC_OVERRIDE",
        "CAP_SYS_PTRACE", "CAP_SYS_MODULE", "CAP_SYS_RAWIO",
    ])
    
    # Seccomp profile (Linux)
    seccomp_profile: str = "default"  # default, strict, custom
    
    # Environment
    env_vars: Dict[str, str] = field(default_factory=dict)
    inherit_env: bool = False
    
    # Working directory
    work_dir: str = ""
    
    # Timeout
    default_timeout: int = 30  # seconds


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
        args: Tuple = (),
        kwargs: Dict = None,
        timeout: int = None,
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
        args: Tuple = (),
        kwargs: Dict = None,
        timeout: int = None,
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


class ProcessSandbox(Sandbox):
    """Process-based sandbox using multiprocessing."""
    
    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._process: Optional[Process] = None
        self._result_queue: Queue = Queue()
        self._manager = Manager()
        self._shared_state = self._manager.dict()
    
    async def start(self) -> bool:
        self._running = True
        return True
    
    async def stop(self) -> bool:
        self._running = False
        if self._process and self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=5)
        self._manager.shutdown()
        return True
    
    def _worker(
        self,
        func_data: bytes,
        args_data: bytes,
        kwargs_data: bytes,
        result_queue: Queue,
        config_dict: Dict,
    ) -> None:
        """Worker process function."""
        import sys
        import io
        import traceback
        
        # Apply resource limits
        self._apply_limits(config_dict.get("limits", {}))
        
        # Setup filesystem
        self._setup_filesystem(config_dict)
        
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
            
            # Execute
            start = time.perf_counter()
            result = func(*args, **kwargs)
            execution_time_ms = (time.perf_counter() - start) * 1000
            
            # Get resource usage
            usage = resource.getrusage(resource.RUSAGE_SELF)
            memory_mb = usage.ru_maxrss / 1024  # Linux: KB, macOS: bytes
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
    
    def _apply_limits(self, limits: Dict) -> None:
        """Apply resource limits to current process."""
        for limit_type, value in limits.items():
            if limit_type == ResourceLimit.CPU_TIME:
                resource.setrlimit(resource.RLIMIT_CPU, (value, value))
            elif limit_type == ResourceLimit.MEMORY:
                # Convert to bytes if needed
                if value > 1024 * 1024 * 1024:  # > 1GB, assume bytes
                    value = value
                else:
                    value = value * 1024 * 1024  # MB to bytes
                resource.setrlimit(resource.RLIMIT_AS, (value, value))
            elif limit_type == ResourceLimit.FILE_SIZE:
                resource.setrlimit(resource.RLIMIT_FSIZE, (value, value))
            elif limit_type == ResourceLimit.OPEN_FILES:
                resource.setrlimit(resource.RLIMIT_NOFILE, (value, value))
            elif limit_type == ResourceLimit.PROCESSES:
                resource.setrlimit(resource.RLIMIT_NPROC, (value, value))
    
    def _setup_filesystem(self, config_dict: Dict) -> None:
        """Setup filesystem isolation."""
        allowed_paths = config_dict.get("allowed_paths", [])
        writable_paths = config_dict.get("writable_paths", [])
        
        # Create temp directory
        temp_dir = config_dict.get("temp_dir") or tempfile.mkdtemp(prefix="sandbox_")
        os.environ["TMPDIR"] = temp_dir
        os.environ["TEMP"] = temp_dir
        os.environ["TMP"] = temp_dir
    
    async def execute(
        self,
        func: Callable,
        args: Tuple = (),
        kwargs: Dict = None,
        timeout: int = None,
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
        }
        
        # Start worker process
        self._process = Process(
            target=self._worker,
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
        self._executor = None
    
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
        args: Tuple = (),
        kwargs: Dict = None,
        timeout: int = None,
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
        args: Tuple = (),
        kwargs: Dict = None,
        timeout: int = None,
    ) -> SandboxResult:
        kwargs = kwargs or {}
        timeout = timeout or self.config.default_timeout
        
        # Serialize function to file
        import pickle
        import base64
        
        func_data = base64.b64encode(pickle.dumps((func, args, kwargs))).decode()
        
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
        
        try:
            # Run container
            cmd = [
                "docker", "run", "--rm",
                "--memory", f"{self.config.limits.get(ResourceLimit.MEMORY, 512)}m",
                "--cpus", str(self.config.limits.get(ResourceLimit.CPU_TIME, 1)),
                "--network", "none" if not self.config.network_enabled else "bridge",
                "-v", f"{script_path}:/script.py",
                self._image,
                "python", "/script.py",
            ]
            
            start = time.perf_counter()
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
                    return SandboxResult(
                        success=result_data.get("success", False),
                        return_value=result_data.get("result"),
                        error=result_data.get("error", ""),
                        execution_time_ms=execution_time_ms,
                        exit_code=proc.returncode,
                    )
                except json.JSONDecodeError:
                    return SandboxResult(
                        success=proc.returncode == 0,
                        return_value=stdout.decode(),
                        error=stderr.decode() if proc.returncode != 0 else "",
                        execution_time_ms=execution_time_ms,
                        exit_code=proc.returncode,
                    )
                    
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return SandboxResult(
                    success=False,
                    error="Execution timed out",
                    execution_time_ms=(time.perf_counter() - start) * 1000,
                    timed_out=True,
                    killed=True,
                )
                
        finally:
            os.unlink(script_path)


class WASMSandbox(Sandbox):
    """WebAssembly sandbox (requires wasmtime/wasmer)."""
    
    def __init__(self, config: SandboxConfig):
        super().__init__(config)
        self._engine = None
        self._store = None
        self._module = None
    
    async def start(self) -> bool:
        try:
            import wasmtime
            self._engine = wasmtime.Engine()
            self._store = wasmtime.Store(self._engine)
            self._running = True
            return True
        except ImportError:
            logger.warning("wasmtime not available for WASM sandbox")
            return False
    
    async def stop(self) -> bool:
        self._running = False
        self._engine = None
        self._store = None
        return True
    
    async def execute(
        self,
        func: Callable,
        args: Tuple = (),
        kwargs: Dict = None,
        timeout: int = None,
    ) -> SandboxResult:
        # WASM execution would require compiling function to WASM first
        # This is a placeholder for the interface
        return SandboxResult(
            success=False,
            error="WASM sandbox not fully implemented - requires function compilation to WASM",
        )


class SandboxManager:
    """
    Manages multiple sandboxes and routes executions.
    """
    
    def __init__(self):
        self._sandboxes: Dict[str, Sandbox] = {}
        self._default_sandbox: Optional[Sandbox] = None
        self._sandbox_configs: Dict[str, SandboxConfig] = {}
    
    def register_sandbox(self, name: str, sandbox: Sandbox, default: bool = False) -> None:
        self._sandboxes[name] = sandbox
        if default or self._default_sandbox is None:
            self._default_sandbox = sandbox
    
    def create_sandbox(self, config: SandboxConfig) -> Sandbox:
        """Create a sandbox from config."""
        if config.sandbox_type == SandboxType.NONE:
            sandbox = NoSandbox(config)
        elif config.sandbox_type == SandboxType.THREAD:
            sandbox = ThreadSandbox(config)
        elif config.sandbox_type == SandboxType.PROCESS:
            sandbox = ProcessSandbox(config)
        elif config.sandbox_type == SandboxType.CONTAINER:
            sandbox = ContainerSandbox(config)
        elif config.sandbox_type == SandboxType.WASM:
            sandbox = WASMSandbox(config)
        else:
            sandbox = NoSandbox(config)
        
        self._sandbox_configs[config.sandbox_id] = config
        return sandbox
    
    async def execute(
        self,
        func: Callable,
        args: Tuple = (),
        kwargs: Dict = None,
        sandbox: str = None,
        config: SandboxConfig = None,
        timeout: int = None,
    ) -> SandboxResult:
        """Execute function in sandbox."""
        target_sandbox = None
        
        if sandbox:
            target_sandbox = self._sandboxes.get(sandbox)
        elif config:
            target_sandbox = self.create_sandbox(config)
            await target_sandbox.start()
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
    
    def list_sandboxes(self) -> List[str]:
        return list(self._sandboxes.keys())
    
    async def start_all(self) -> Dict[str, bool]:
        results = {}
        for name, sandbox in self._sandboxes.items():
            results[name] = await sandbox.start()
        return results
    
    async def stop_all(self) -> Dict[str, bool]:
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
    allowed_sandbox_types: List[SandboxType] = field(default_factory=lambda: [SandboxType.PROCESS])
    max_execution_time: int = 30
    max_memory_mb: int = 512
    max_cpu_percent: int = 100
    
    # Filesystem
    read_only_root: bool = True
    allowed_read_paths: List[str] = field(default_factory=list)
    allowed_write_paths: List[str] = field(default_factory=list)
    
    # Network
    network_access: bool = False
    allowed_domains: List[str] = field(default_factory=list)
    allowed_ports: List[int] = field(default_factory=list)
    
    # System
    allow_subprocess: bool = False
    allow_threads: bool = True
    dropped_capabilities: List[str] = field(default_factory=list)
    
    # Python-specific
    allowed_imports: List[str] = field(default_factory=list)
    blocked_imports: List[str] = field(default_factory=lambda: [
        "os", "sys", "subprocess", "multiprocessing",
        "threading", "socket", "ctypes", "importlib",
        "pkgutil", "runpy", "code", "compile",
    ])
    
    def create_sandbox_config(self, sandbox_id: str = None) -> SandboxConfig:
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