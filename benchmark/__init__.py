"""
Benchmark Suite for PyFault framework.

Comprehensive performance benchmarking:
- Latency benchmarks (p50, p95, p99, p999)
- Throughput benchmarks (RPS, concurrent requests)
- Cold start benchmarks
- Memory and CPU profiling
- Regression detection
- Comparative benchmarks
"""

import asyncio
import gc
import logging
import os
import statistics
import time
import uuid
import warnings
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union

import psutil

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class BenchmarkType(str, Enum):
    """Types of benchmarks."""
    LATENCY = "latency"
    THROUGHPUT = "throughput"
    COLD_START = "cold_start"
    MEMORY = "memory"
    CPU = "cpu"
    CONCURRENCY = "concurrency"
    STRESS = "stress"
    REGRESSION = "regression"


class BenchmarkStatus(str, Enum):
    """Benchmark execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class BenchmarkConfig:
    """Configuration for a benchmark run."""
    name: str
    benchmark_type: BenchmarkType
    description: str = ""

    # Execution parameters
    duration_seconds: int = 60
    warmup_seconds: int = 10
    concurrency: int = 10
    requests_per_second: Optional[int] = None  # None = max

    # Target
    target_function: Optional[Callable] = None
    target_args: tuple = field(default_factory=tuple)
    target_kwargs: dict[str, Any] = field(default_factory=dict)

    # Thresholds for pass/fail
    latency_p50_threshold_ms: Optional[float] = None
    latency_p95_threshold_ms: Optional[float] = None
    latency_p99_threshold_ms: Optional[float] = None
    throughput_threshold_rps: Optional[float] = None
    error_rate_threshold: float = 0.01
    memory_threshold_mb: Optional[float] = None
    cpu_threshold_percent: Optional[float] = None

    # Comparison
    baseline_results: Optional["BenchmarkResults"] = None
    regression_threshold_percent: float = 10.0  # 10% regression

    # Environment
    tags: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResults:
    """Results of a benchmark run."""
    benchmark_id: str
    config: BenchmarkConfig
    status: BenchmarkStatus = BenchmarkStatus.PENDING

    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: float = 0

    # Latency metrics (milliseconds)
    latency_samples: list[float] = field(default_factory=list)
    latency_p50: float = 0
    latency_p95: float = 0
    latency_p99: float = 0
    latency_p999: float = 0
    latency_min: float = 0
    latency_max: float = 0
    latency_mean: float = 0
    latency_std: float = 0

    # Throughput
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    error_rate: float = 0
    throughput_rps: float = 0

    # Resource usage
    peak_memory_mb: float = 0
    avg_memory_mb: float = 0
    peak_cpu_percent: float = 0
    avg_cpu_percent: float = 0

    # Cold start
    cold_start_samples: list[float] = field(default_factory=list)
    cold_start_p50: float = 0
    cold_start_p95: float = 0

    # Errors
    errors: list[str] = field(default_factory=list)
    error_types: dict[str, int] = field(default_factory=dict)

    # Regression
    regression_detected: bool = False
    regression_details: dict[str, Any] = field(default_factory=dict)

    # Pass/Fail
    passed: bool = True
    failure_reasons: list[str] = field(default_factory=list)

    def calculate_latency_percentiles(self) -> None:
        """Calculate latency percentiles from samples."""
        if not self.latency_samples:
            return

        sorted_samples = sorted(self.latency_samples)
        n = len(sorted_samples)

        self.latency_p50 = sorted_samples[int(n * 0.5)]
        self.latency_p95 = sorted_samples[int(n * 0.95)]
        self.latency_p99 = sorted_samples[int(n * 0.99)]
        self.latency_p999 = sorted_samples[min(int(n * 0.999), n - 1)]
        self.latency_min = sorted_samples[0]
        self.latency_max = sorted_samples[-1]
        self.latency_mean = statistics.mean(sorted_samples)
        self.latency_std = statistics.stdev(sorted_samples) if n > 1 else 0

    def calculate_throughput(self) -> None:
        """Calculate throughput metrics."""
        if self.duration_seconds > 0:
            self.throughput_rps = self.total_requests / self.duration_seconds

        if self.total_requests > 0:
            self.error_rate = self.failed_requests / self.total_requests

    def evaluate_thresholds(self) -> None:
        """Evaluate results against thresholds."""
        self.passed = True
        self.failure_reasons = []

        if self.config.latency_p50_threshold_ms and self.latency_p50 > self.config.latency_p50_threshold_ms:
            self.passed = False
            self.failure_reasons.append(f"P50 latency {self.latency_p50:.1f}ms exceeds threshold {self.config.latency_p50_threshold_ms}ms")

        if self.config.latency_p95_threshold_ms and self.latency_p95 > self.config.latency_p95_threshold_ms:
            self.passed = False
            self.failure_reasons.append(f"P95 latency {self.latency_p95:.1f}ms exceeds threshold {self.config.latency_p95_threshold_ms}ms")

        if self.config.latency_p99_threshold_ms and self.latency_p99 > self.config.latency_p99_threshold_ms:
            self.passed = False
            self.failure_reasons.append(f"P99 latency {self.latency_p99:.1f}ms exceeds threshold {self.config.latency_p99_threshold_ms}ms")

        if self.config.throughput_threshold_rps and self.throughput_rps < self.config.throughput_threshold_rps:
            self.passed = False
            self.failure_reasons.append(f"Throughput {self.throughput_rps:.1f} RPS below threshold {self.config.throughput_threshold_rps}")

        if self.error_rate > self.config.error_rate_threshold:
            self.passed = False
            self.failure_reasons.append(f"Error rate {self.error_rate:.2%} exceeds threshold {self.config.error_rate_threshold:.2%}")

        if self.config.memory_threshold_mb and self.peak_memory_mb > self.config.memory_threshold_mb:
            self.passed = False
            self.failure_reasons.append(f"Peak memory {self.peak_memory_mb:.1f} MB exceeds threshold {self.config.memory_threshold_mb} MB")

        if self.config.cpu_threshold_percent and self.peak_cpu_percent > self.config.cpu_threshold_percent:
            self.passed = False
            self.failure_reasons.append(f"Peak CPU {self.peak_cpu_percent:.1f}% exceeds threshold {self.config.cpu_threshold_percent}%")

        # Regression check
        if self.config.baseline_results:
            self._check_regression()

    def _check_regression(self) -> None:
        """Check for performance regression against baseline."""
        baseline = self.config.baseline_results
        if baseline is None:
            return
        threshold = self.config.regression_threshold_percent / 100.0

        regressions = []

        # Latency regression
        for metric in ['latency_p50', 'latency_p95', 'latency_p99']:
            current = getattr(self, metric)
            baseline_val = getattr(baseline, metric)
            if baseline_val > 0:
                change = (current - baseline_val) / baseline_val
                if change > threshold:
                    regressions.append(f"{metric}: {change:.1%} increase (baseline: {baseline_val:.1f}, current: {current:.1f})")

        # Throughput regression
        if baseline.throughput_rps > 0:
            change = (baseline.throughput_rps - self.throughput_rps) / baseline.throughput_rps
            if change > threshold:
                regressions.append(f"throughput: {change:.1%} decrease")

        # Error rate regression
        if self.error_rate > baseline.error_rate * (1 + threshold):
            if baseline.error_rate > 0:
                detail = f"{(self.error_rate - baseline.error_rate) / baseline.error_rate:.1%} increase"
            else:
                detail = f"from {baseline.error_rate:.2%} to {self.error_rate:.2%}"
            regressions.append(f"error_rate: {detail}")

        if regressions:
            self.regression_detected = True
            self.regression_details = {"regressions": regressions}
            self.passed = False
            self.failure_reasons.extend(regressions)

    def to_dict(self) -> dict[str, Any]:
        return {
            "benchmark_id": self.benchmark_id,
            "config": self.config.to_dict() if hasattr(self.config, 'to_dict') else str(self.config),
            "status": self.status.value,
            "duration_seconds": self.duration_seconds,
            "latency": {
                "p50": self.latency_p50,
                "p95": self.latency_p95,
                "p99": self.latency_p99,
                "p999": self.latency_p999,
                "min": self.latency_min,
                "max": self.latency_max,
                "mean": self.latency_mean,
                "std": self.latency_std,
            },
            "throughput": {
                "total_requests": self.total_requests,
                "successful": self.successful_requests,
                "failed": self.failed_requests,
                "error_rate": self.error_rate,
                "rps": self.throughput_rps,
            },
            "resources": {
                "peak_memory_mb": self.peak_memory_mb,
                "avg_memory_mb": self.avg_memory_mb,
                "peak_cpu_percent": self.peak_cpu_percent,
                "avg_cpu_percent": self.avg_cpu_percent,
            },
            "cold_start": {
                "p50": self.cold_start_p50,
                "p95": self.cold_start_p95,
                "samples": len(self.cold_start_samples),
            },
            "errors": {
                "count": len(self.errors),
                "types": self.error_types,
            },
            "regression": {
                "detected": self.regression_detected,
                "details": self.regression_details,
            },
            "passed": self.passed,
            "failure_reasons": self.failure_reasons,
        }


class BenchmarkRunner:
    """
    Executes benchmarks and collects results.
    """

    def __init__(self) -> None:
        self._running = False
        self._results: list[BenchmarkResults] = []
        self._current_results: Optional[BenchmarkResults] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._process = psutil.Process()

    async def run(self, config: BenchmarkConfig) -> BenchmarkResults:
        """Run a benchmark with the given configuration."""
        results = BenchmarkResults(
            benchmark_id=str(uuid.uuid4()),
            config=config,
        )
        results.status = BenchmarkStatus.RUNNING
        results.started_at = datetime.utcnow()

        self._current_results = results
        self._running = True

        # Start resource monitoring
        self._monitor_task = asyncio.create_task(self._monitor_resources(results))

        try:
            # Warmup
            if config.warmup_seconds > 0:
                await self._warmup(config, config.warmup_seconds)

            # Run benchmark
            if config.benchmark_type == BenchmarkType.LATENCY:
                await self._run_latency_benchmark(config, results)
            elif config.benchmark_type == BenchmarkType.THROUGHPUT:
                await self._run_throughput_benchmark(config, results)
            elif config.benchmark_type == BenchmarkType.COLD_START:
                await self._run_cold_start_benchmark(config, results)
            elif config.benchmark_type == BenchmarkType.CONCURRENCY:
                await self._run_concurrency_benchmark(config, results)
            elif config.benchmark_type == BenchmarkType.STRESS:
                await self._run_stress_benchmark(config, results)
            else:
                await self._run_latency_benchmark(config, results)

            results.status = BenchmarkStatus.COMPLETED

        except Exception as e:
            logger.error(f"Benchmark failed: {e}")
            results.status = BenchmarkStatus.FAILED
            results.errors.append(str(e))

        finally:
            results.completed_at = datetime.utcnow()
            if results.started_at:
                results.duration_seconds = (results.completed_at - results.started_at).total_seconds()

            self._running = False
            if self._monitor_task:
                self._monitor_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._monitor_task

            # Calculate metrics
            results.calculate_latency_percentiles()
            results.calculate_throughput()
            results.evaluate_thresholds()

            self._results.append(results)
            self._current_results = None

        return results

    async def _warmup(self, config: BenchmarkConfig, warmup_seconds: int) -> None:
        """Run warmup requests."""
        if not config.target_function:
            return

        end_time = time.time() + warmup_seconds
        while time.time() < end_time:
            try:
                if asyncio.iscoroutinefunction(config.target_function):
                    await config.target_function(*config.target_args, **config.target_kwargs)
                else:
                    await asyncio.to_thread(config.target_function, *config.target_args, **config.target_kwargs)
            except Exception:
                pass  # Ignore warmup errors
            await asyncio.sleep(0.01)

    async def _run_latency_benchmark(self, config: BenchmarkConfig, results: BenchmarkResults) -> None:
        """Run latency benchmark - sequential requests measuring latency."""
        if not config.target_function:
            return

        end_time = time.time() + config.duration_seconds
        request_count = 0

        while time.time() < end_time:
            start = time.perf_counter()
            try:
                if asyncio.iscoroutinefunction(config.target_function):
                    await config.target_function(*config.target_args, **config.target_kwargs)
                else:
                    await asyncio.to_thread(config.target_function, *config.target_args, **config.target_kwargs)
                latency_ms = (time.perf_counter() - start) * 1000
                results.latency_samples.append(latency_ms)
                results.successful_requests += 1
            except Exception as e:
                latency_ms = (time.perf_counter() - start) * 1000
                results.latency_samples.append(latency_ms)
                results.failed_requests += 1
                results.errors.append(str(e))
                error_type = type(e).__name__
                results.error_types[error_type] = results.error_types.get(error_type, 0) + 1

            request_count += 1
            results.total_requests += 1

            # Small delay to prevent overwhelming
            await asyncio.sleep(0.001)

    async def _run_throughput_benchmark(self, config: BenchmarkConfig, results: BenchmarkResults) -> None:
        """Run throughput benchmark - maximize RPS."""
        if not config.target_function:
            return

        end_time = time.time() + config.duration_seconds

        # Use semaphore for concurrency control
        semaphore = asyncio.Semaphore(config.concurrency)

        async def make_request() -> None:
            target_fn = config.target_function
            if target_fn is None:
                return
            async with semaphore:
                start = time.perf_counter()
                try:
                    if asyncio.iscoroutinefunction(target_fn):
                        await target_fn(*config.target_args, **config.target_kwargs)
                    else:
                        await asyncio.to_thread(target_fn, *config.target_args, **config.target_kwargs)
                    latency_ms = (time.perf_counter() - start) * 1000
                    results.latency_samples.append(latency_ms)
                    results.successful_requests += 1
                except Exception as e:
                    latency_ms = (time.perf_counter() - start) * 1000
                    results.latency_samples.append(latency_ms)
                    results.failed_requests += 1
                    results.errors.append(str(e))
                    error_type = type(e).__name__
                    results.error_types[error_type] = results.error_types.get(error_type, 0) + 1
                results.total_requests += 1

        # Run requests as fast as possible
        tasks = []
        while time.time() < end_time:
            task = asyncio.create_task(make_request())
            tasks.append(task)

            # Limit pending tasks
            if len(tasks) >= config.concurrency * 2:
                _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                tasks = list(pending)

        # Wait for remaining
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_cold_start_benchmark(self, config: BenchmarkConfig, results: BenchmarkResults) -> None:
        """Run cold start benchmark - measure first request latency after idle."""
        if not config.target_function:
            return

        # Number of cold start measurements
        num_measurements = config.duration_seconds // 5  # Every 5 seconds

        for i in range(num_measurements):
            # Force garbage collection to simulate cold start
            gc.collect()
            await asyncio.sleep(0.1)

            # Measure cold start
            start = time.perf_counter()
            try:
                if asyncio.iscoroutinefunction(config.target_function):
                    await config.target_function(*config.target_args, **config.target_kwargs)
                else:
                    await asyncio.to_thread(config.target_function, *config.target_args, **config.target_kwargs)
                latency_ms = (time.perf_counter() - start) * 1000
                results.cold_start_samples.append(latency_ms)
                results.successful_requests += 1
            except Exception as e:
                latency_ms = (time.perf_counter() - start) * 1000
                results.cold_start_samples.append(latency_ms)
                results.failed_requests += 1
                results.errors.append(str(e))

            results.total_requests += 1

            # Wait before next cold start
            if i < num_measurements - 1:
                await asyncio.sleep(5)

        # Calculate cold start percentiles
        if results.cold_start_samples:
            sorted_samples = sorted(results.cold_start_samples)
            n = len(sorted_samples)
            results.cold_start_p50 = sorted_samples[int(n * 0.5)]
            results.cold_start_p95 = sorted_samples[int(n * 0.95)]

    async def _run_concurrency_benchmark(self, config: BenchmarkConfig, results: BenchmarkResults) -> None:
        """Run concurrency benchmark - test different concurrency levels."""
        if not config.target_function:
            return

        concurrency_levels = [1, 2, 5, 10, 20, 50, 100]
        duration_per_level = config.duration_seconds // len(concurrency_levels)

        for concurrency in concurrency_levels:
            if not self._running:
                break

            end_time = time.time() + duration_per_level
            semaphore = asyncio.Semaphore(concurrency)

            async def make_request(_sem: Any = semaphore) -> None:
                target_fn = config.target_function
                if target_fn is None:
                    return
                async with _sem:
                    start = time.perf_counter()
                    try:
                        if asyncio.iscoroutinefunction(target_fn):
                            await target_fn(*config.target_args, **config.target_kwargs)
                        else:
                            await asyncio.to_thread(target_fn, *config.target_args, **config.target_kwargs)
                        latency_ms = (time.perf_counter() - start) * 1000
                        results.latency_samples.append(latency_ms)
                        results.successful_requests += 1
                    except Exception as e:
                        latency_ms = (time.perf_counter() - start) * 1000
                        results.latency_samples.append(latency_ms)
                        results.failed_requests += 1
                        results.errors.append(str(e))
                    results.total_requests += 1

            tasks = []
            while time.time() < end_time:
                task = asyncio.create_task(make_request())
                tasks.append(task)
                if len(tasks) >= concurrency * 2:
                    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    tasks = list(pending)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # Brief pause between levels
            await asyncio.sleep(1)

    async def _run_stress_benchmark(self, config: BenchmarkConfig, results: BenchmarkResults) -> None:
        """Run stress test - push to limits."""
        if not config.target_function:
            return

        # Gradually increase load
        max_concurrency = 500
        step = 50
        step_duration = config.duration_seconds // (max_concurrency // step)

        for concurrency in range(step, max_concurrency + 1, step):
            if not self._running:
                break

            end_time = time.time() + step_duration
            semaphore = asyncio.Semaphore(concurrency)

            async def make_request(_sem: Any = semaphore) -> None:
                target_fn = config.target_function
                if target_fn is None:
                    return
                async with _sem:
                    start = time.perf_counter()
                    try:
                        if asyncio.iscoroutinefunction(target_fn):
                            await target_fn(*config.target_args, **config.target_kwargs)
                        else:
                            await asyncio.to_thread(target_fn, *config.target_args, **config.target_kwargs)
                        latency_ms = (time.perf_counter() - start) * 1000
                        results.latency_samples.append(latency_ms)
                        results.successful_requests += 1
                    except Exception as e:
                        latency_ms = (time.perf_counter() - start) * 1000
                        results.latency_samples.append(latency_ms)
                        results.failed_requests += 1
                        results.errors.append(str(e))
                    results.total_requests += 1

            tasks = []
            while time.time() < end_time:
                task = asyncio.create_task(make_request())
                tasks.append(task)
                if len(tasks) >= concurrency * 2:
                    _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    tasks = list(pending)

            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

            # Check if error rate is too high
            if results.total_requests > 100 and results.error_rate > 0.5:
                logger.warning(f"Stress test stopped at concurrency {concurrency}: error rate {results.error_rate:.1%}")
                break

            await asyncio.sleep(1)

    async def _monitor_resources(self, results: BenchmarkResults) -> None:
        """Monitor CPU and memory usage during benchmark."""
        memory_samples = []
        cpu_samples = []

        try:
            while self._running:
                # Memory
                mem_info = self._process.memory_info()
                memory_mb = mem_info.rss / (1024 * 1024)
                memory_samples.append(memory_mb)
                results.peak_memory_mb = max(results.peak_memory_mb, memory_mb)

                # CPU
                cpu_percent = self._process.cpu_percent(interval=0.1)
                cpu_samples.append(cpu_percent)
                results.peak_cpu_percent = max(results.peak_cpu_percent, cpu_percent)

                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        finally:
            if memory_samples:
                results.avg_memory_mb = statistics.mean(memory_samples)
            if cpu_samples:
                results.avg_cpu_percent = statistics.mean(cpu_samples)

    def get_results(self) -> list[BenchmarkResults]:
        return self._results

    def get_latest_results(self) -> Optional[BenchmarkResults]:
        return self._results[-1] if self._results else None


class BenchmarkSuite:
    """
    Manages a collection of benchmarks.
    """

    def __init__(self) -> None:
        self._benchmarks: dict[str, BenchmarkConfig] = {}
        self._runner = BenchmarkRunner()
        self._history: list[BenchmarkResults] = []

    def add_benchmark(self, config: BenchmarkConfig) -> None:
        self._benchmarks[config.name] = config

    def remove_benchmark(self, name: str) -> bool:
        if name in self._benchmarks:
            del self._benchmarks[name]
            return True
        return False

    def get_benchmark(self, name: str) -> Optional[BenchmarkConfig]:
        return self._benchmarks.get(name)

    def list_benchmarks(self) -> list[BenchmarkConfig]:
        return list(self._benchmarks.values())

    async def run_benchmark(self, name: str) -> Optional[BenchmarkResults]:
        config = self._benchmarks.get(name)
        if not config:
            return None
        result = await self._runner.run(config)
        if result:
            self._history.append(result)
        return result

    async def run_all(self) -> list[BenchmarkResults]:
        results = []
        for name in self._benchmarks:
            result = await self.run_benchmark(name)
            if result:
                results.append(result)
        return results

    def get_history(self, name: Optional[str] = None, limit: int = 100) -> list[BenchmarkResults]:
        history = self._history
        if name:
            history = [r for r in history if r.config.name == name]
        return history[-limit:]

    def compare_results(self, name: str, current: BenchmarkResults, baseline: BenchmarkResults) -> dict[str, Any]:
        """Compare current results with baseline."""
        comparison: dict[str, Any] = {
            "benchmark": name,
            "timestamp": datetime.utcnow().isoformat(),
            "current": current.to_dict(),
            "baseline": baseline.to_dict(),
            "deltas": {},
            "regression": False,
        }

        for metric in ['latency_p50', 'latency_p95', 'latency_p99', 'throughput_rps', 'error_rate']:
            current_val = getattr(current, metric)
            baseline_val = getattr(baseline, metric)

            if baseline_val != 0:
                delta = (current_val - baseline_val) / baseline_val * 100
                comparison["deltas"][metric] = {
                    "current": current_val,
                    "baseline": baseline_val,
                    "delta_percent": delta,
                    "regressed": delta > 10 if metric != 'throughput_rps' else delta < -10,
                }

        comparison["regression"] = any(d.get("regressed", False) for d in comparison["deltas"].values())
        return comparison


class Profiler:
    """
    Code profiler for identifying bottlenecks.
    """

    def __init__(self) -> None:
        self._profiling = False
        self._profile_data: list[dict[str, Any]] = []

    @asynccontextmanager
    async def profile(self, name: str = "default") -> AsyncIterator[None]:
        """Context manager for profiling a code block."""
        import cProfile
        import io
        import pstats

        profiler = cProfile.Profile()
        profiler.enable()

        start = time.perf_counter()
        try:
            yield
        finally:
            profiler.disable()
            elapsed = time.perf_counter() - start

            # Get stats
            s = io.StringIO()
            ps = pstats.Stats(profiler, stream=s).sort_stats('cumulative')
            ps.print_stats(20)

            self._profile_data.append({
                "name": name,
                "duration": elapsed,
                "stats": s.getvalue(),
                "timestamp": datetime.utcnow().isoformat(),
            })

    def get_profiles(self) -> list[dict[str, Any]]:
        return self._profile_data

    def clear(self) -> None:
        self._profile_data.clear()


class MemoryProfiler:
    """
    Memory profiler for tracking allocations.
    """

    def __init__(self) -> None:
        self._snapshots: list[dict[str, Any]] = []
        try:
            import tracemalloc
            self._tracemalloc: Any = tracemalloc
        except ImportError:
            self._tracemalloc = None

    def start(self) -> None:
        if self._tracemalloc:
            self._tracemalloc.start()

    def stop(self) -> None:
        if self._tracemalloc:
            self._tracemalloc.stop()

    def snapshot(self, label: str = "") -> dict[str, Any]:
        if not self._tracemalloc:
            return {"error": "tracemalloc not available"}

        if not self._tracemalloc.is_tracing():
            return {"error": "tracemalloc is not tracing - call start() first"}

        snapshot = self._tracemalloc.take_snapshot()
        top_stats = snapshot.statistics('lineno')

        stats = []
        for stat in top_stats[:20]:
            stats.append({
                "file": str(stat.traceback[0]) if stat.traceback else "unknown",
                "line": stat.traceback[0].lineno if stat.traceback else 0,
                "size_mb": stat.size / (1024 * 1024),
                "count": stat.count,
            })

        result = {
            "label": label,
            "timestamp": datetime.utcnow().isoformat(),
            "top_allocations": stats,
        }
        self._snapshots.append(result)
        return result

    def compare(self, snapshot1: str, snapshot2: str) -> list[dict[str, Any]]:
        """Compare two snapshots by label."""
        snap1 = next((s for s in self._snapshots if s["label"] == snapshot1), None)
        snap2 = next((s for s in self._snapshots if s["label"] == snapshot2), None)

        if not snap1 or not snap2:
            return []

        # This would need actual snapshot objects to compare
        return []


# Predefined benchmark configurations
def create_latency_benchmark(
    name: str,
    target_function: Callable,
    duration: int = 60,
    p50_threshold: float = 50,
    p95_threshold: float = 200,
    p99_threshold: float = 500,
    **kwargs: Any
) -> BenchmarkConfig:
    return BenchmarkConfig(
        name=name,
        benchmark_type=BenchmarkType.LATENCY,
        target_function=target_function,
        duration_seconds=duration,
        latency_p50_threshold_ms=p50_threshold,
        latency_p95_threshold_ms=p95_threshold,
        latency_p99_threshold_ms=p99_threshold,
        **kwargs
    )


def create_throughput_benchmark(
    name: str,
    target_function: Callable,
    duration: int = 60,
    concurrency: int = 50,
    rps_threshold: float = 1000,
    **kwargs: Any
) -> BenchmarkConfig:
    return BenchmarkConfig(
        name=name,
        benchmark_type=BenchmarkType.THROUGHPUT,
        target_function=target_function,
        duration_seconds=duration,
        concurrency=concurrency,
        throughput_threshold_rps=rps_threshold,
        **kwargs
    )


def create_cold_start_benchmark(
    name: str,
    target_function: Callable,
    num_measurements: int = 20,
    p50_threshold: float = 100,
    **kwargs: Any
) -> BenchmarkConfig:
    return BenchmarkConfig(
        name=name,
        benchmark_type=BenchmarkType.COLD_START,
        target_function=target_function,
        duration_seconds=num_measurements * 5,
        **kwargs
    )


def create_stress_benchmark(
    name: str,
    target_function: Callable,
    duration: int = 300,
    max_concurrency: int = 500,
    **kwargs: Any
) -> BenchmarkConfig:
    return BenchmarkConfig(
        name=name,
        benchmark_type=BenchmarkType.STRESS,
        target_function=target_function,
        duration_seconds=duration,
        **kwargs
    )


# Global instances
_benchmark_suite: Optional[BenchmarkSuite] = None
_profiler: Optional[Profiler] = None
_memory_profiler: Optional[MemoryProfiler] = None


def get_benchmark_suite() -> BenchmarkSuite:
    global _benchmark_suite
    if _benchmark_suite is None:
        _benchmark_suite = BenchmarkSuite()
    return _benchmark_suite


def get_profiler() -> Profiler:
    global _profiler
    if _profiler is None:
        _profiler = Profiler()
    return _profiler


def get_memory_profiler() -> MemoryProfiler:
    global _memory_profiler
    if _memory_profiler is None:
        _memory_profiler = MemoryProfiler()
    return _memory_profiler


