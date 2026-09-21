"""
PyFault - A Python web framework inspired by NestJS
"""

__version__ = "1.1.0"
__author__ = "PyFault Team"

from pyfault.common.audit import AuditInterceptor, AuditModule
from pyfault.common.auth import AuthGuard, AuthModule
from pyfault.common.cache import CacheManager, CacheModule
from pyfault.common.config import ConfigManager, ConfigModule
from pyfault.common.errors import AppException, ErrorCode, ErrorHandler
from pyfault.common.monitoring import HealthCheck, MetricsCollector, MonitoringModule
from pyfault.common.performance import (
    PerformanceMonitor,
    RateLimiter,
    monitor,
    rate_limit,
)
from pyfault.common.queue import QueueModule, TaskQueue
from pyfault.common.openapi import OpenAPIGenerator, OpenAPISchema, api, operation, schema
from pyfault.common.testing import MockService, TestClient, TestModule
from pyfault.core.container import Container
from pyfault.core.factory import PyFaultFactory
from pyfault.core.injector import Injector
from pyfault.core.scanner import MetadataScanner
from pyfault.microservices import (
    MicroserviceClient,
    MicroserviceOptions,
    MicroserviceServer,
)
from pyfault.platform.graphql import GraphQLAdapter
from pyfault.platform.http import HttpAdapter
from pyfault.platform.websocket import WebSocketAdapter

__all__ = [
    "Container",
    "Injector",
    "MetadataScanner",
    "PyFaultFactory",
    "HttpAdapter",
    "WebSocketAdapter",
    "GraphQLAdapter",
    "MicroserviceClient",
    "MicroserviceServer",
    "MicroserviceOptions",
    "CacheManager",
    "CacheModule",
    "TaskQueue",
    "QueueModule",
    "HealthCheck",
    "MetricsCollector",
    "MonitoringModule",
    "AuthModule",
    "AuthGuard",
    "AuditModule",
    "AuditInterceptor",
    "AppException",
    "ErrorHandler",
    "ErrorCode",
    "PerformanceMonitor",
    "RateLimiter",
    "monitor",
    "rate_limit",
    "ConfigManager",
    "ConfigModule",
    "TestModule",
    "TestClient",
    "MockService",
    "OpenAPIGenerator",
    "OpenAPISchema",
    "api",
    "operation",
    "schema",
]
