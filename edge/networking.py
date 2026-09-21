"""
Edge Networking for PyFault framework.

Networking layer for edge functions with:
- DNS-based traffic routing
- Load balancing
- CDN integration
- TLS termination
- Rate limiting
- WAF integration
"""

import asyncio
import logging
import time
import uuid
import hashlib
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from collections import defaultdict, deque
import asyncio

logger = logging.getLogger(__name__)


class LoadBalancerAlgorithm(str, Enum):
    """Load balancing algorithms."""
    ROUND_ROBIN = "round_robin"
    LEAST_CONNECTIONS = "least_connections"
    WEIGHTED = "weighted"
    IP_HASH = "ip_hash"
    LATENCY_BASED = "latency_based"
    HEALTH_BASED = "health_based"


class TLSMode(str, Enum):
    """TLS termination modes."""
    OFFLOAD = "offload"        # Terminate at edge
    PASSTHROUGH = "passthrough"  # Pass through to backend
    RE_ENCRYPT = "re_encrypt"  # Terminate and re-encrypt


class RateLimitStrategy(str, Enum):
    """Rate limiting strategies."""
    FIXED_WINDOW = "fixed_window"
    SLIDING_WINDOW = "sliding_window"
    TOKEN_BUCKET = "token_bucket"
    LEAKY_BUCKET = "leaky_bucket"


@dataclass
class BackendEndpoint:
    """Backend service endpoint."""
    endpoint_id: str
    host: str
    port: int
    protocol: str = "http"
    path: str = "/"
    weight: int = 100
    max_connections: int = 1000
    current_connections: int = 0
    healthy: bool = True
    region: str = ""
    zone: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_health_check: Optional[datetime] = None
    
    @property
    def url(self) -> str:
        return f"{self.protocol}://{self.host}:{self.port}{self.path}"
    
    @property
    def available_capacity(self) -> float:
        if self.max_connections == 0:
            return 1.0
        return 1.0 - (self.current_connections / self.max_connections)


@dataclass
class DNSRecord:
    """DNS record for edge routing."""
    record_id: str
    name: str
    record_type: str = "A"  # A, AAAA, CNAME, TXT
    value: str = ""
    ttl: int = 300
    region: str = ""
    weight: int = 100
    health_check: str = ""
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RateLimitRule:
    """Rate limiting rule."""
    rule_id: str
    name: str
    strategy: RateLimitStrategy = RateLimitStrategy.SLIDING_WINDOW
    requests_per_window: int = 1000
    window_seconds: int = 60
    burst_allowance: int = 0
    key_extractor: str = "ip"  # ip, header:x-api-key, custom
    action: str = "reject"  # reject, delay, queue
    delay_ms: int = 0
    scopes: List[str] = field(default_factory=list)  # global, region, function, ip
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class WAFRule:
    """Web Application Firewall rule."""
    rule_id: str
    name: str
    priority: int = 100
    action: str = "block"  # block, allow, monitor, challenge
    conditions: List[Dict[str, Any]] = field(default_factory=list)
    # condition example: {"field": "header.user-agent", "operator": "contains", "value": "bot"}
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TLSConfig:
    """TLS configuration."""
    cert_id: str
    domains: List[str]
    mode: TLSMode = TLSMode.OFFLOAD
    cert_data: str = ""  # PEM format
    key_data: str = ""   # PEM format
    ca_data: str = ""    # CA bundle
    min_version: str = "TLSv1.2"
    cipher_suites: List[str] = field(default_factory=list)
    hsts_enabled: bool = True
    hsts_max_age: int = 31536000
    ocsp_stapling: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None


class LoadBalancer:
    """
    Load balancer for distributing traffic across backends.
    """
    
    def __init__(
        self,
        algorithm: LoadBalancerAlgorithm = LoadBalancerAlgorithm.LEAST_CONNECTIONS,
    ):
        self.algorithm = algorithm
        self._backends: Dict[str, BackendEndpoint] = {}
        self._rr_index = 0
        self._lock = asyncio.Lock()
    
    def add_backend(self, backend: BackendEndpoint) -> None:
        self._backends[backend.endpoint_id] = backend
    
    def remove_backend(self, endpoint_id: str) -> bool:
        if endpoint_id in self._backends:
            del self._backends[endpoint_id]
            return True
        return False
    
    def get_backend(self, endpoint_id: str) -> Optional[BackendEndpoint]:
        return self._backends.get(endpoint_id)
    
    def list_backends(self) -> List[BackendEndpoint]:
        return list(self._backends.values())
    
    def get_healthy_backends(self) -> List[BackendEndpoint]:
        return [b for b in self._backends.values() if b.healthy]
    
    async def select_backend(
        self,
        client_ip: str = None,
        headers: Dict[str, str] = None,
    ) -> Optional[BackendEndpoint]:
        """Select backend based on algorithm."""
        healthy = self.get_healthy_backends()
        if not healthy:
            return None
        
        if self.algorithm == LoadBalancerAlgorithm.ROUND_ROBIN:
            return self._round_robin(healthy)
        elif self.algorithm == LoadBalancerAlgorithm.LEAST_CONNECTIONS:
            return self._least_connections(healthy)
        elif self.algorithm == LoadBalancerAlgorithm.WEIGHTED:
            return self._weighted(healthy)
        elif self.algorithm == LoadBalancerAlgorithm.IP_HASH:
            return self._ip_hash(healthy, client_ip)
        elif self.algorithm == LoadBalancerAlgorithm.LATENCY_BASED:
            return self._latency_based(healthy)
        elif self.algorithm == LoadBalancerAlgorithm.HEALTH_BASED:
            return self._health_based(healthy)
        
        return healthy[0]
    
    def _round_robin(self, backends: List[BackendEndpoint]) -> BackendEndpoint:
        backend = backends[self._rr_index % len(backends)]
        self._rr_index = (self._rr_index + 1) % len(backends)
        return backend
    
    def _least_connections(self, backends: List[BackendEndpoint]) -> BackendEndpoint:
        return min(backends, key=lambda b: b.current_connections)
    
    def _weighted(self, backends: List[BackendEndpoint]) -> BackendEndpoint:
        total_weight = sum(b.weight for b in backends)
        if total_weight == 0:
            return backends[0]
        
        rand = random.randint(1, total_weight)
        current = 0
        for backend in backends:
            current += backend.weight
            if rand <= current:
                return backend
        return backends[-1]
    
    def _ip_hash(self, backends: List[BackendEndpoint], client_ip: str) -> BackendEndpoint:
        if not client_ip:
            return backends[0]
        hash_val = int(hashlib.md5(client_ip.encode()).hexdigest(), 16)
        return backends[hash_val % len(backends)]
    
    def _latency_based(self, backends: List[BackendEndpoint]) -> BackendEndpoint:
        # Would need latency metrics
        return min(backends, key=lambda b: b.metadata.get("avg_latency_ms", 0))
    
    def _health_based(self, backends: List[BackendEndpoint]) -> BackendEndpoint:
        # Prefer backends with better health scores
        return max(backends, key=lambda b: b.metadata.get("health_score", 1.0))
    
    async def acquire_connection(self, endpoint_id: str) -> bool:
        backend = self._backends.get(endpoint_id)
        if backend and backend.current_connections < backend.max_connections:
            backend.current_connections += 1
            return True
        return False
    
    async def release_connection(self, endpoint_id: str) -> None:
        backend = self._backends.get(endpoint_id)
        if backend:
            backend.current_connections = max(0, backend.current_connections - 1)
    
    def update_health(self, endpoint_id: str, healthy: bool, latency_ms: float = 0) -> None:
        backend = self._backends.get(endpoint_id)
        if backend:
            backend.healthy = healthy
            backend.last_health_check = datetime.utcnow()
            if latency_ms > 0:
                # Exponential moving average
                alpha = 0.3
                current = backend.metadata.get("avg_latency_ms", latency_ms)
                backend.metadata["avg_latency_ms"] = alpha * latency_ms + (1 - alpha) * current


class DNSManager:
    """
    DNS management for edge routing.
    """
    
    def __init__(self):
        self._records: Dict[str, DNSRecord] = {}
        self._zone_cache: Dict[str, List[DNSRecord]] = defaultdict(list)
    
    def add_record(self, record: DNSRecord) -> None:
        self._records[record.record_id] = record
        self._zone_cache[record.name].append(record)
        self._zone_cache[record.name].sort(key=lambda r: r.weight, reverse=True)
    
    def remove_record(self, record_id: str) -> bool:
        if record_id not in self._records:
            return False
        record = self._records[record_id]
        if record in self._zone_cache[record.name]:
            self._zone_cache[record.name].remove(record)
        del self._records[record_id]
        return True
    
    def get_record(self, record_id: str) -> Optional[DNSRecord]:
        return self._records.get(record_id)
    
    def resolve(
        self,
        name: str,
        record_type: str = "A",
        client_region: str = None,
    ) -> List[DNSRecord]:
        """Resolve DNS name."""
        records = self._zone_cache.get(name, [])
        results = [r for r in records if r.record_type == record_type and r.enabled]
        
        # Filter by region if specified
        if client_region:
            regional = [r for r in results if r.region == client_region or not r.region]
            if regional:
                return regional
        
        return results
    
    def get_all_records(self) -> List[DNSRecord]:
        return list(self._records.values())


class RateLimiter:
    """
    Distributed rate limiter.
    """
    
    def __init__(self):
        self._rules: Dict[str, RateLimitRule] = {}
        self._counters: Dict[str, deque] = defaultdict(deque)
        self._token_buckets: Dict[str, Tuple[float, float]] = {}  # key -> (tokens, last_refill)
        self._lock = asyncio.Lock()
    
    def add_rule(self, rule: RateLimitRule) -> None:
        self._rules[rule.rule_id] = rule
    
    def remove_rule(self, rule_id: str) -> bool:
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False
    
    def get_rule(self, rule_id: str) -> Optional[RateLimitRule]:
        return self._rules.get(rule_id)
    
    async def check_limit(
        self,
        rule_id: str,
        identifier: str,
        scope: str = "global",
    ) -> Tuple[bool, Dict[str, Any]]:
        """Check if request is within rate limit."""
        rule = self._rules.get(rule_id)
        if not rule or not rule.enabled:
            return True, {"allowed": True, "remaining": rule.requests_per_window if rule else 0}
        
        key = f"{rule_id}:{scope}:{identifier}"
        now = time.time()
        
        if rule.strategy == RateLimitStrategy.FIXED_WINDOW:
            return await self._fixed_window(key, rule, now)
        elif rule.strategy == RateLimitStrategy.SLIDING_WINDOW:
            return await self._sliding_window(key, rule, now)
        elif rule.strategy == RateLimitStrategy.TOKEN_BUCKET:
            return await self._token_bucket(key, rule, now)
        elif rule.strategy == RateLimitStrategy.LEAKY_BUCKET:
            return await self._leaky_bucket(key, rule, now)
        
        return True, {"allowed": True}
    
    async def _fixed_window(
        self,
        key: str,
        rule: RateLimitRule,
        now: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        window_start = int(now / rule.window_seconds) * rule.window_seconds
        window_key = f"{key}:{window_start}"
        
        async with self._lock:
            count = self._counters.get(window_key, 0)
            
            if count >= rule.requests_per_window:
                return False, {
                    "allowed": False,
                    "remaining": 0,
                    "reset_at": window_start + rule.window_seconds,
                    "retry_after": rule.window_seconds - (now - window_start),
                }
            
            self._counters[window_key] = count + 1
            return True, {
                "allowed": True,
                "remaining": rule.requests_per_window - count - 1,
                "reset_at": window_start + rule.window_seconds,
            }
    
    async def _sliding_window(
        self,
        key: str,
        rule: RateLimitRule,
        now: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        cutoff = now - rule.window_seconds
        
        async with self._lock:
            # Clean old entries
            timestamps = self._counters[key]
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()
            
            if len(timestamps) >= rule.requests_per_window:
                return False, {
                    "allowed": False,
                    "remaining": 0,
                    "reset_at": timestamps[0] + rule.window_seconds if timestamps else now + rule.window_seconds,
                    "retry_after": rule.window_seconds - (now - timestamps[0]) if timestamps else rule.window_seconds,
                }
            
            timestamps.append(now)
            return True, {
                "allowed": True,
                "remaining": rule.requests_per_window - len(timestamps),
            }
    
    async def _token_bucket(
        self,
        key: str,
        rule: RateLimitRule,
        now: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        rate = rule.requests_per_window / rule.window_seconds  # tokens per second
        capacity = rule.requests_per_window + rule.burst_allowance
        
        async with self._lock:
            tokens, last_refill = self._token_buckets.get(key, (capacity, now))
            
            # Refill tokens
            elapsed = now - last_refill
            tokens = min(capacity, tokens + elapsed * rate)
            
            if tokens >= 1:
                tokens -= 1
                self._token_buckets[key] = (tokens, now)
                return True, {
                    "allowed": True,
                    "remaining": int(tokens),
                    "capacity": capacity,
                }
            
            self._token_buckets[key] = (tokens, now)
            return False, {
                "allowed": False,
                "remaining": 0,
                "retry_after": (1 - tokens) / rate,
            }
    
    async def _leaky_bucket(
        self,
        key: str,
        rule: RateLimitRule,
        now: float,
    ) -> Tuple[bool, Dict[str, Any]]:
        # Similar to token bucket but with constant leak rate
        return await self._token_bucket(key, rule, now)
    
    def reset_limit(self, rule_id: str, identifier: str, scope: str = "global") -> None:
        key = f"{rule_id}:{scope}:{identifier}"
        if key in self._counters:
            del self._counters[key]
        if key in self._token_buckets:
            del self._token_buckets[key]


class WAF:
    """
    Web Application Firewall.
    """
    
    def __init__(self):
        self._rules: List[WAFRule] = []
        self._blocked_ips: Set[str] = set()
        self._blocked_patterns: List[str] = []
    
    def add_rule(self, rule: WAFRule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority)
    
    def remove_rule(self, rule_id: str) -> bool:
        for i, rule in enumerate(self._rules):
            if rule.rule_id == rule_id:
                self._rules.pop(i)
                return True
        return False
    
    def block_ip(self, ip: str) -> None:
        self._blocked_ips.add(ip)
    
    def unblock_ip(self, ip: str) -> None:
        self._blocked_ips.discard(ip)
    
    async def inspect(
        self,
        request: Dict[str, Any],
    ) -> Tuple[str, Optional[WAFRule]]:
        """Inspect request and return action."""
        client_ip = request.get("client_ip", "")
        
        # Check IP blocklist
        if client_ip in self._blocked_ips:
            return "block", None
        
        # Check rules
        for rule in self._rules:
            if not rule.enabled:
                continue
            
            if await self._match_conditions(request, rule.conditions):
                return rule.action, rule
        
        return "allow", None
    
    async def _match_conditions(
        self,
        request: Dict[str, Any],
        conditions: List[Dict[str, Any]],
    ) -> bool:
        for condition in conditions:
            field = condition.get("field", "")
            operator = condition.get("operator", "")
            value = condition.get("value", "")
            
            # Extract field value
            field_value = self._extract_field(request, field)
            if field_value is None:
                return False
            
            # Apply operator
            if operator == "equals":
                if field_value != value:
                    return False
            elif operator == "contains":
                if value not in str(field_value):
                    return False
            elif operator == "starts_with":
                if not str(field_value).startswith(value):
                    return False
            elif operator == "ends_with":
                if not str(field_value).endswith(value):
                    return False
            elif operator == "regex":
                import re
                if not re.search(value, str(field_value)):
                    return False
            elif operator == "in":
                if field_value not in value:
                    return False
            elif operator == "not_in":
                if field_value in value:
                    return False
        
        return True
    
    def _extract_field(self, request: Dict[str, Any], field: str) -> Any:
        parts = field.split(".")
        value = request
        
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
            
            if value is None:
                return None
        
        return value


class EdgeNetworkManager:
    """
    Manages networking for edge functions.
    """
    
    def __init__(self):
        self.load_balancer = LoadBalancer()
        self.dns_manager = DNSManager()
        self.rate_limiter = RateLimiter()
        self.waf = WAF()
        self._tls_configs: Dict[str, TLSConfig] = {}
        self._function_routes: Dict[str, Dict[str, Any]] = {}  # function_id -> route config
    
    def configure_function_route(
        self,
        function_id: str,
        domain: str,
        path: str = "/",
        backends: List[BackendEndpoint] = None,
        rate_limit_rules: List[str] = None,
        waf_rules: List[str] = None,
        tls_config: TLSConfig = None,
    ) -> None:
        """Configure networking for a function."""
        self._function_routes[function_id] = {
            "domain": domain,
            "path": path,
            "backends": backends or [],
            "rate_limit_rules": rate_limit_rules or [],
            "waf_rules": waf_rules or [],
            "tls_config": tls_config,
        }
        
        # Add backends to load balancer
        if backends:
            for backend in backends:
                self.load_balancer.add_backend(backend)
        
        # Add DNS record
        if domain:
            record = DNSRecord(
                record_id=str(uuid.uuid4()),
                name=domain,
                record_type="CNAME",
                value=f"{function_id}.edge.pyfault.io",
            )
            self.dns_manager.add_record(record)
    
    async def handle_request(
        self,
        function_id: str,
        request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Handle incoming request with full networking stack."""
        route = self._function_routes.get(function_id)
        if not route:
            return {"status": 404, "error": "Function not found"}
        
        client_ip = request.get("client_ip", "")
        
        # WAF inspection
        waf_action, waf_rule = await self.waf.inspect(request)
        if waf_action == "block":
            return {"status": 403, "error": "Blocked by WAF"}
        elif waf_action == "challenge":
            return {"status": 429, "error": "Challenge required"}
        
        # Rate limiting
        for rule_id in route.get("rate_limit_rules", []):
            allowed, info = await self.rate_limiter.check_limit(
                rule_id,
                client_ip,
                scope="function",
            )
            if not allowed:
                return {
                    "status": 429,
                    "error": "Rate limited",
                    "retry_after": info.get("retry_after", 60),
                }
        
        # Select backend
        backend = await self.load_balancer.select_backend(client_ip, request.get("headers", {}))
        if not backend:
            return {"status": 503, "error": "No healthy backends"}
        
        # Acquire connection
        acquired = await self.load_balancer.acquire_connection(backend.endpoint_id)
        if not acquired:
            return {"status": 503, "error": "Backend at capacity"}
        
        try:
            # Forward request to backend
            # In practice, would make HTTP request
            response = await self._forward_request(backend, request)
            
            # Update load balancer metrics
            self.load_balancer.update_health(
                backend.endpoint_id,
                True,
                response.get("latency_ms", 0),
            )
            
            return response
            
        finally:
            await self.load_balancer.release_connection(backend.endpoint_id)
    
    async def _forward_request(
        self,
        backend: BackendEndpoint,
        request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Forward request to backend."""
        # Simulated forwarding
        start = time.perf_counter()
        await asyncio.sleep(0.01)  # Simulate network latency
        latency_ms = (time.perf_counter() - start) * 1000
        
        return {
            "status": 200,
            "body": {"result": "ok"},
            "latency_ms": latency_ms,
            "backend": backend.endpoint_id,
        }
    
    def get_tls_config(self, cert_id: str) -> Optional[TLSConfig]:
        return self._tls_configs.get(cert_id)
    
    def add_tls_config(self, config: TLSConfig) -> None:
        self._tls_configs[config.cert_id] = config
    
    def get_network_stats(self) -> Dict[str, Any]:
        return {
            "load_balancer": {
                "backends": len(self.load_balancer._backends),
                "healthy": len(self.load_balancer.get_healthy_backends()),
                "algorithm": self.load_balancer.algorithm.value,
            },
            "dns": {
                "records": len(self.dns_manager._records),
                "zones": len(self.dns_manager._zone_cache),
            },
            "rate_limiter": {
                "rules": len(self.rate_limiter._rules),
                "active_counters": len(self.rate_limiter._counters),
            },
            "waf": {
                "rules": len(self.waf._rules),
                "blocked_ips": len(self.waf._blocked_ips),
            },
            "tls": {
                "certificates": len(self._tls_configs),
            },
            "functions": len(self._function_routes),
        }


# Global network manager
_edge_network: Optional[EdgeNetworkManager] = None


def get_edge_network() -> EdgeNetworkManager:
    global _edge_network
    if _edge_network is None:
        _edge_network = EdgeNetworkManager()
    return _edge_network


def get_edge_network() -> EdgeNetworkManager:
    return get_edge_network()