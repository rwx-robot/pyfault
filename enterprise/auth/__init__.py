"""
Enterprise Authentication & Authorization for PyFault framework.

Comprehensive auth system:
- Multi-tenant isolation
- RBAC with hierarchical roles
- OAuth2/OIDC integration
- API key management
- Session management
- Audit logging
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
import uuid
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union
from urllib.parse import urlencode

import bcrypt
import jwt

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


def _naive_utc_epoch(dt: datetime) -> int:
    """Epoch seconds for a naive-UTC datetime.

    datetime.timestamp() would interpret a naive datetime as local time,
    shifting iat/exp by the UTC offset and minting tokens that are already
    expired (or long-lived) on non-UTC hosts.
    """
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


class AuthProvider(str, Enum):
    """Authentication providers."""
    LOCAL = "local"
    OAUTH2 = "oauth2"
    OIDC = "oidc"
    SAML = "saml"
    LDAP = "ldap"
    API_KEY = "api_key"


class TokenType(str, Enum):
    """Token types."""
    ACCESS = "access"
    REFRESH = "refresh"
    API_KEY = "api_key"
    SESSION = "session"
    MFA = "mfa"


class Permission(str, Enum):
    """System permissions."""
    # User management
    USER_CREATE = "user:create"
    USER_READ = "user:read"
    USER_UPDATE = "user:update"
    USER_DELETE = "user:delete"
    USER_LIST = "user:list"

    # Role management
    ROLE_CREATE = "role:create"
    ROLE_READ = "role:read"
    ROLE_UPDATE = "role:update"
    ROLE_DELETE = "role:delete"
    ROLE_ASSIGN = "role:assign"

    # Tenant management
    TENANT_CREATE = "tenant:create"
    TENANT_READ = "tenant:read"
    TENANT_UPDATE = "tenant:update"
    TENANT_DELETE = "tenant:delete"

    # Resource access
    RESOURCE_READ = "resource:read"
    RESOURCE_WRITE = "resource:write"
    RESOURCE_DELETE = "resource:delete"

    # Admin
    ADMIN_ACCESS = "admin:access"
    AUDIT_READ = "audit:read"
    CONFIG_WRITE = "config:write"

    # API keys
    API_KEY_CREATE = "apikey:create"
    API_KEY_READ = "apikey:read"
    API_KEY_REVOKE = "apikey:revoke"

    # Monitoring
    METRICS_READ = "metrics:read"
    LOGS_READ = "logs:read"
    ALERTS_MANAGE = "alerts:manage"


class RoleType(str, Enum):
    """Role types."""
    SYSTEM = "system"        # Built-in system roles
    TENANT = "tenant"        # Tenant-specific roles
    CUSTOM = "custom"        # User-defined roles


@dataclass
class PermissionSet:
    """Set of permissions with metadata."""
    permissions: set[Permission] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)

    def has(self, permission: Permission) -> bool:
        return permission in self.permissions

    def has_any(self, permissions: set[Permission]) -> bool:
        return bool(self.permissions & permissions)

    def has_all(self, permissions: set[Permission]) -> bool:
        return permissions.issubset(self.permissions)

    def add(self, permission: Permission) -> None:
        self.permissions.add(permission)

    def remove(self, permission: Permission) -> None:
        self.permissions.discard(permission)

    def copy(self) -> "PermissionSet":
        return PermissionSet(
            permissions=set(self.permissions),
            metadata=dict(self.metadata),
        )

    def union(self, other: "PermissionSet") -> "PermissionSet":
        return PermissionSet(permissions=self.permissions | other.permissions)

    def intersection(self, other: "PermissionSet") -> "PermissionSet":
        return PermissionSet(permissions=self.permissions & other.permissions)

    def to_list(self) -> list[str]:
        return [p.value for p in self.permissions]

    @classmethod
    def from_list(cls, permissions: list[str]) -> "PermissionSet":
        return cls(permissions={Permission(p) for p in permissions})


@dataclass
class Role:
    """Role definition."""
    role_id: str
    name: str
    description: str = ""
    role_type: RoleType = RoleType.CUSTOM
    tenant_id: str = ""  # Empty for system roles
    permissions: PermissionSet = field(default_factory=PermissionSet)
    parent_roles: list[str] = field(default_factory=list)  # Role inheritance
    is_system: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get_all_permissions(
        self, role_registry: "RoleRegistry", _seen: Optional[set[str]] = None
    ) -> PermissionSet:
        """Get all permissions including inherited ones."""
        if _seen is None:
            _seen = set()
        if self.role_id in _seen:
            return PermissionSet()
        _seen.add(self.role_id)

        all_perms = self.permissions.copy()

        for parent_id in self.parent_roles:
            parent = role_registry.get_role(parent_id)
            if parent:
                all_perms = all_perms.union(
                    parent.get_all_permissions(role_registry, _seen)
                )

        return all_perms

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_id": self.role_id,
            "name": self.name,
            "description": self.description,
            "role_type": self.role_type.value,
            "tenant_id": self.tenant_id,
            "permissions": self.permissions.to_list(),
            "parent_roles": self.parent_roles,
            "is_system": self.is_system,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class Tenant:
    """Tenant/Organization."""
    tenant_id: str
    name: str
    display_name: str = ""
    description: str = ""
    domain: str = ""  # Custom domain
    status: str = "active"  # active, suspended, deleted
    plan: str = "free"  # free, starter, pro, enterprise
    settings: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, int] = field(default_factory=dict)  # Resource limits
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    deleted_at: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "domain": self.domain,
            "status": self.status,
            "plan": self.plan,
            "settings": self.settings,
            "limits": self.limits,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class User:
    """User account."""
    user_id: str
    tenant_id: str
    username: str
    email: str
    display_name: str = ""
    password_hash: str = ""  # Empty for SSO users
    status: str = "active"  # active, locked, disabled, pending
    email_verified: bool = False
    mfa_enabled: bool = False
    mfa_secret: str = ""
    roles: list[str] = field(default_factory=list)  # Role IDs
    groups: list[str] = field(default_factory=list)
    last_login: Optional[datetime] = None
    last_failed_login: Optional[datetime] = None
    failed_login_count: int = 0
    password_changed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_sensitive: bool = False) -> dict[str, Any]:
        data = {
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "status": self.status,
            "email_verified": self.email_verified,
            "mfa_enabled": self.mfa_enabled,
            "roles": self.roles,
            "groups": self.groups,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

        if include_sensitive:
            data["password_hash"] = self.password_hash
            data["mfa_secret"] = self.mfa_secret
            data["failed_login_count"] = self.failed_login_count

        return data


@dataclass
class Session:
    """User session."""
    session_id: str
    user_id: str
    tenant_id: str
    access_token: str
    refresh_token: str
    token_type: TokenType = TokenType.SESSION
    ip_address: str = ""
    user_agent: str = ""
    device_fingerprint: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(hours=24))
    last_activity: datetime = field(default_factory=datetime.utcnow)
    revoked: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self) -> bool:
        return datetime.utcnow() >= self.expires_at

    def is_valid(self) -> bool:
        return not self.revoked and not self.is_expired()

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "tenant_id": self.tenant_id,
            "token_type": self.token_type.value,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "revoked": self.revoked,
        }


@dataclass
class APIKey:
    """API key for programmatic access."""
    key_id: str
    tenant_id: str
    user_id: str
    name: str
    key_hash: str  # Hashed key
    key_prefix: str  # First 8 chars for identification
    permissions: PermissionSet = field(default_factory=PermissionSet)
    status: str = "active"  # active, revoked, expired
    expires_at: Optional[datetime] = None
    last_used: Optional[datetime] = None
    usage_count: int = 0
    rate_limit: int = 1000  # Requests per hour
    created_at: datetime = field(default_factory=datetime.utcnow)
    revoked_at: Optional[datetime] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_valid(self) -> bool:
        if self.status != "active":
            return False
        return not (self.expires_at and datetime.utcnow() >= self.expires_at)

    def to_dict(self, include_key: bool = False) -> dict[str, Any]:
        data = {
            "key_id": self.key_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "name": self.name,
            "key_prefix": self.key_prefix,
            "permissions": self.permissions.to_list(),
            "status": self.status,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "last_used": self.last_used.isoformat() if self.last_used else None,
            "usage_count": self.usage_count,
            "rate_limit": self.rate_limit,
            "created_at": self.created_at.isoformat(),
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }

        if include_key:
            # This would only be returned on creation
            pass

        return data


class TokenManager:
    """JWT token management."""

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        access_token_ttl: int = 3600,  # 1 hour
        refresh_token_ttl: int = 604800,  # 7 days
        issuer: str = "pyfault",
        audience: str = "pyfault-api",
    ):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.access_token_ttl = access_token_ttl
        self.refresh_token_ttl = refresh_token_ttl
        self.issuer = issuer
        self.audience = audience

    def create_access_token(
        self,
        user_id: str,
        tenant_id: str,
        roles: list[str],
        permissions: list[str],
        session_id: Optional[str] = None,
        extra_claims: Optional[dict[str, Any]] = None,
    ) -> str:
        now = datetime.utcnow()
        payload = {
            "sub": user_id,
            "tid": tenant_id,
            "roles": roles,
            "perms": permissions,
            "sid": session_id,
            "iat": _naive_utc_epoch(now),
            "exp": _naive_utc_epoch(now + timedelta(seconds=self.access_token_ttl)),
            "iss": self.issuer,
            "aud": self.audience,
            "type": TokenType.ACCESS.value,
        }

        if extra_claims:
            payload.update(extra_claims)

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_refresh_token(
        self,
        user_id: str,
        tenant_id: str,
        session_id: Optional[str] = None,
    ) -> str:
        now = datetime.utcnow()
        payload = {
            "sub": user_id,
            "tid": tenant_id,
            "sid": session_id,
            "iat": _naive_utc_epoch(now),
            "exp": _naive_utc_epoch(now + timedelta(seconds=self.refresh_token_ttl)),
            "iss": self.issuer,
            "aud": self.audience,
            "type": TokenType.REFRESH.value,
        }

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def create_api_key_token(
        self,
        key_id: str,
        tenant_id: str,
        user_id: str,
        permissions: list[str],
        expires_at: Optional[datetime] = None,
    ) -> str:
        now = datetime.utcnow()
        payload = {
            "sub": user_id,
            "tid": tenant_id,
            "kid": key_id,
            "perms": permissions,
            "iat": _naive_utc_epoch(now),
            "iss": self.issuer,
            "aud": self.audience,
            "type": TokenType.API_KEY.value,
        }

        if expires_at:
            payload["exp"] = _naive_utc_epoch(expires_at)

        return jwt.encode(payload, self.secret_key, algorithm=self.algorithm)

    def decode_token(self, token: str) -> dict[str, Any]:
        return jwt.decode(
            token,
            self.secret_key,
            algorithms=[self.algorithm],
            audience=self.audience,
            issuer=self.issuer,
        )

    def validate_token(self, token: str) -> tuple[bool, dict[str, Any]]:
        try:
            payload = self.decode_token(token)
            return True, payload
        except jwt.ExpiredSignatureError:
            return False, {"error": "Token expired"}
        except jwt.InvalidTokenError as e:
            return False, {"error": str(e)}

    def refresh_access_token(self, refresh_token: str) -> Optional[str]:
        try:
            payload = self.decode_token(refresh_token)
            if payload.get("type") != TokenType.REFRESH.value:
                return None

            # Create new access token
            return self.create_access_token(
                user_id=payload["sub"],
                tenant_id=payload["tid"],
                roles=payload.get("roles", []),
                permissions=payload.get("perms", []),
                session_id=payload.get("sid"),
            )
        except Exception:
            return None


class PasswordManager:
    """Password hashing and validation."""

    def __init__(self, rounds: int = 12):
        self.rounds = rounds

    def hash_password(self, password: str) -> str:
        salt = bcrypt.gensalt(rounds=self.rounds)
        return bcrypt.hashpw(password.encode(), salt).decode()

    def verify_password(self, password: str, password_hash: str) -> bool:
        return bcrypt.checkpw(password.encode(), password_hash.encode())

    def needs_rehash(self, password_hash: str) -> bool:
        try:
            # Hash format: $2b$<rounds>$<salt+hash>
            parts = password_hash.split("$")
            return int(parts[2]) < self.rounds
        except (IndexError, ValueError):
            return True

    def generate_secure_password(self, length: int = 16) -> str:
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*"
        return ''.join(secrets.choice(alphabet) for _ in range(length))


class MFAManager:
    """Multi-factor authentication."""

    def __init__(self, issuer: str = "PyFault"):
        self.issuer = issuer

    def generate_secret(self) -> str:
        return base64.b32encode(secrets.token_bytes(20)).decode()

    def get_totp_uri(self, email: str, secret: str) -> str:
        return f"otpauth://totp/{self.issuer}:{email}?secret={secret}&issuer={self.issuer}"

    def verify_totp(self, secret: str, token: str, window: int = 1) -> bool:
        """Verify TOTP token."""
        try:
            import pyotp
            totp = pyotp.TOTP(secret)
            return totp.verify(token, valid_window=window)
        except ImportError:
            # Fallback: simple time-based verification
            return self._verify_totp_fallback(secret, token, window)

    def _verify_totp_fallback(self, secret: str, token: str, window: int) -> bool:
        """Fallback TOTP verification without pyotp."""
        try:
            import base64
            import hmac
            import time

            time_step = 30
            counter = int(time.time() // time_step)

            for i in range(-window, window + 1):
                test_counter = counter + i
                test_token = self._generate_totp(secret, test_counter)
                if hmac.compare_digest(test_token, token):
                    return True
            return False
        except Exception:
            return False

    def _generate_totp(self, secret: str, counter: int) -> str:
        import base64
        import hashlib
        import struct

        key = base64.b32decode(secret)
        msg = struct.pack(">Q", counter)
        hmac_digest = hmac.new(key, msg, hashlib.sha1).digest()

        offset = hmac_digest[-1] & 0x0F
        code = (struct.unpack(">I", hmac_digest[offset:offset+4])[0] & 0x7FFFFFFF) % 1000000
        return f"{code:06d}"

    def generate_backup_codes(self, count: int = 10, length: int = 8) -> list[str]:
        codes = []
        for _ in range(count):
            code = secrets.token_hex(length // 2).upper()
            codes.append('-'.join([code[i:i+4] for i in range(0, len(code), 4)]))
        return codes


class RoleRegistry:
    """Registry for role management."""

    def __init__(self) -> None:
        self._roles: dict[str, Role] = {}
        self._tenant_roles: dict[str, set[str]] = defaultdict(set)  # tenant_id -> role_ids

        # Create system roles
        self._create_system_roles()

    def _create_system_roles(self) -> None:
        # Super Admin
        super_admin = Role(
            role_id="super_admin",
            name="Super Admin",
            description="Full system access across all tenants",
            role_type=RoleType.SYSTEM,
            permissions=PermissionSet(permissions=set(Permission)),
            is_system=True,
        )
        self._roles[super_admin.role_id] = super_admin

        # Tenant Admin
        tenant_admin = Role(
            role_id="tenant_admin",
            name="Tenant Admin",
            description="Full access within tenant",
            role_type=RoleType.SYSTEM,
            permissions=PermissionSet(permissions={
                Permission.USER_CREATE, Permission.USER_READ, Permission.USER_UPDATE,
                Permission.USER_DELETE, Permission.USER_LIST,
                Permission.ROLE_CREATE, Permission.ROLE_READ, Permission.ROLE_UPDATE,
                Permission.ROLE_DELETE, Permission.ROLE_ASSIGN,
                Permission.RESOURCE_READ, Permission.RESOURCE_WRITE, Permission.RESOURCE_DELETE,
                Permission.API_KEY_CREATE, Permission.API_KEY_READ, Permission.API_KEY_REVOKE,
                Permission.METRICS_READ, Permission.LOGS_READ, Permission.ALERTS_MANAGE,
            }),
            is_system=True,
        )
        self._roles[tenant_admin.role_id] = tenant_admin

        # Developer
        developer = Role(
            role_id="developer",
            name="Developer",
            description="Resource access for development",
            role_type=RoleType.SYSTEM,
            permissions=PermissionSet(permissions={
                Permission.RESOURCE_READ, Permission.RESOURCE_WRITE,
                Permission.METRICS_READ, Permission.LOGS_READ,
                Permission.API_KEY_CREATE, Permission.API_KEY_READ,
            }),
            is_system=True,
        )
        self._roles[developer.role_id] = developer

        # Viewer
        viewer = Role(
            role_id="viewer",
            name="Viewer",
            description="Read-only access",
            role_type=RoleType.SYSTEM,
            permissions=PermissionSet(permissions={
                Permission.USER_READ, Permission.ROLE_READ,
                Permission.RESOURCE_READ, Permission.METRICS_READ,
            }),
            is_system=True,
        )
        self._roles[viewer.role_id] = viewer

        # API Service
        api_service = Role(
            role_id="api_service",
            name="API Service",
            description="Programmatic API access",
            role_type=RoleType.SYSTEM,
            permissions=PermissionSet(permissions=set(Permission)),
            is_system=True,
        )
        self._roles[api_service.role_id] = api_service

    def create_role(
        self,
        name: str,
        description: str,
        tenant_id: str,
        permissions: list[Permission],
        parent_roles: Optional[list[str]] = None,
    ) -> Role:
        role = Role(
            role_id=str(uuid.uuid4()),
            name=name,
            description=description,
            role_type=RoleType.TENANT,
            tenant_id=tenant_id,
            permissions=PermissionSet.from_list([p.value for p in permissions]),
            parent_roles=parent_roles or [],
        )

        self._roles[role.role_id] = role
        self._tenant_roles[tenant_id].add(role.role_id)
        return role

    def get_role(self, role_id: str) -> Optional[Role]:
        return self._roles.get(role_id)

    def get_tenant_roles(self, tenant_id: str) -> list[Role]:
        role_ids = self._tenant_roles.get(tenant_id, set())
        return [self._roles[rid] for rid in role_ids if rid in self._roles]

    def get_system_roles(self) -> list[Role]:
        return [r for r in self._roles.values() if r.is_system]

    def update_role(self, role_id: str, updates: dict[str, Any]) -> bool:
        role = self._roles.get(role_id)
        if not role or role.is_system:
            return False

        for key, value in updates.items():
            if hasattr(role, key) and key != "role_id":
                setattr(role, key, value)

        role.updated_at = datetime.utcnow()
        return True

    def delete_role(self, role_id: str) -> bool:
        role = self._roles.get(role_id)
        if not role or role.is_system:
            return False

        self._tenant_roles[role.tenant_id].discard(role_id)
        del self._roles[role_id]
        return True


class AuthManager:
    """Main authentication and authorization manager."""

    def __init__(
        self,
        token_manager: TokenManager,
        password_manager: PasswordManager,
        mfa_manager: MFAManager,
        role_registry: RoleRegistry,
    ):
        self.token_manager = token_manager
        self.password_manager = password_manager
        self.mfa_manager = mfa_manager
        self.role_registry = role_registry

        # Storage
        self._users: dict[str, User] = {}
        self._tenants: dict[str, Tenant] = {}
        self._sessions: dict[str, Session] = {}
        self._api_keys: dict[str, APIKey] = {}
        self._user_by_email: dict[str, str] = {}  # email -> user_id
        self._user_by_username: dict[str, str] = {}  # username -> user_id

        # Rate limiting
        self._login_attempts: dict[str, list[datetime]] = defaultdict(list)
        self._max_login_attempts = 5
        self._lockout_duration = timedelta(minutes=15)

    # Tenant management
    def create_tenant(
        self,
        name: str,
        display_name: str = "",
        plan: str = "free",
        domain: str = "",
    ) -> Tenant:
        tenant = Tenant(
            tenant_id=str(uuid.uuid4()),
            name=name,
            display_name=display_name or name,
            plan=plan,
            domain=domain,
        )

        self._tenants[tenant.tenant_id] = tenant

        # Create tenant admin role
        self.role_registry.create_role(
            name=f"{name}_admin",
            description=f"Admin for {display_name or name}",
            tenant_id=tenant.tenant_id,
            permissions=[p for p in Permission],
            parent_roles=["tenant_admin"],
        )

        return tenant

    def get_tenant(self, tenant_id: str) -> Optional[Tenant]:
        return self._tenants.get(tenant_id)

    def update_tenant(self, tenant_id: str, updates: dict[str, Any]) -> bool:
        tenant = self._tenants.get(tenant_id)
        if not tenant:
            return False

        for key, value in updates.items():
            if hasattr(tenant, key) and key != "tenant_id":
                setattr(tenant, key, value)

        tenant.updated_at = datetime.utcnow()
        return True

    # User management
    def create_user(
        self,
        tenant_id: str,
        username: str,
        email: str,
        password: Optional[str] = None,
        display_name: str = "",
        roles: Optional[list[str]] = None,
    ) -> User:
        if email in self._user_by_email:
            raise ValueError("Email already registered")
        if username in self._user_by_username:
            raise ValueError("Username already taken")

        user = User(
            user_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            username=username,
            email=email,
            display_name=display_name or username,
        )

        if password:
            user.password_hash = self.password_manager.hash_password(password)
            user.password_changed_at = datetime.utcnow()

        if roles:
            user.roles = roles
        else:
            # Assign default viewer role
            viewer = self.role_registry.get_role("viewer")
            if viewer:
                user.roles.append(viewer.role_id)

        self._users[user.user_id] = user
        self._user_by_email[email] = user.user_id
        self._user_by_username[username] = user.user_id

        return user

    def get_user(self, user_id: str) -> Optional[User]:
        return self._users.get(user_id)

    def get_user_by_email(self, email: str) -> Optional[User]:
        user_id = self._user_by_email.get(email)
        return self._users.get(user_id) if user_id else None

    def get_user_by_username(self, username: str) -> Optional[User]:
        user_id = self._user_by_username.get(username)
        return self._users.get(user_id) if user_id else None

    def update_user(self, user_id: str, updates: dict[str, Any]) -> bool:
        user = self._users.get(user_id)
        if not user:
            return False

        for key, value in updates.items():
            if hasattr(user, key) and key not in ["user_id", "tenant_id", "password_hash"]:
                setattr(user, key, value)

        user.updated_at = datetime.utcnow()
        return True

    def authenticate_user(
        self,
        tenant_id: str,
        username_or_email: str,
        password: str,
        ip_address: str = "",
        user_agent: str = "",
    ) -> tuple[bool, Optional[User], str]:
        """Authenticate user with username/email and password."""
        # Find user
        user = self.get_user_by_email(username_or_email) or self.get_user_by_username(username_or_email)

        if not user or user.tenant_id != tenant_id:
            return False, None, "Invalid credentials"

        if user.status != "active":
            return False, None, f"Account is {user.status}"

        # Check rate limiting
        key = f"{tenant_id}:{username_or_email}:{ip_address}"
        now = datetime.utcnow()
        attempts = self._login_attempts[key]
        attempts = [a for a in attempts if now - a < self._lockout_duration]

        if len(attempts) >= self._max_login_attempts:
            return False, None, "Too many failed attempts. Try again later."

        # Verify password
        if not user.password_hash or not self.password_manager.verify_password(password, user.password_hash):
            attempts.append(now)
            self._login_attempts[key] = attempts
            user.failed_login_count += 1
            user.last_failed_login = now
            return False, None, "Invalid credentials"

        # Success
        self._login_attempts[key] = []
        user.failed_login_count = 0
        user.last_login = now
        return True, user, "Success"

    def create_session(
        self,
        user: User,
        ip_address: str = "",
        user_agent: str = "",
        remember_me: bool = False,
    ) -> Session:
        session = Session(
            session_id=str(uuid.uuid4()),
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            access_token="",
            refresh_token="",
            ip_address=ip_address,
            user_agent=user_agent,
            device_fingerprint=hashlib.sha256(f"{user_agent}:{ip_address}".encode()).hexdigest()[:16],
        )

        # Set expiry
        if remember_me:
            session.expires_at = datetime.utcnow() + timedelta(days=30)
        else:
            session.expires_at = datetime.utcnow() + timedelta(hours=24)

        # Generate tokens
        permissions = set()
        for role_id in user.roles:
            role = self.role_registry.get_role(role_id)
            if role:
                perms = role.get_all_permissions(self.role_registry)
                permissions.update(perms.permissions)

        session.access_token = self.token_manager.create_access_token(
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            roles=user.roles,
            permissions=[p.value for p in permissions],
            session_id=session.session_id,
        )

        session.refresh_token = self.token_manager.create_refresh_token(
            user_id=user.user_id,
            tenant_id=user.tenant_id,
            session_id=session.session_id,
        )

        self._sessions[session.session_id] = session
        return session

    def validate_session(self, access_token: str) -> tuple[bool, Optional[Session], dict[str, Any]]:
        valid, payload = self.token_manager.validate_token(access_token)

        if not valid:
            return False, None, payload

        session_id = payload.get("sid")
        if session_id:
            session = self._sessions.get(session_id)
            if not session or not session.is_valid():
                return False, None, {"error": "Session invalid or expired"}

            # Update last activity
            session.last_activity = datetime.utcnow()
            return True, session, payload

        # Stateless token
        return True, None, payload

    def revoke_session(self, session_id: str) -> bool:
        session = self._sessions.get(session_id)
        if session:
            session.revoked = True
            return True
        return False

    def revoke_all_user_sessions(self, user_id: str) -> int:
        count = 0
        for session in self._sessions.values():
            if session.user_id == user_id and not session.revoked:
                session.revoked = True
                count += 1
        return count

    def refresh_tokens(self, refresh_token: str) -> tuple[Optional[str], Optional[str]]:
        """Refresh access and refresh tokens."""
        new_access = self.token_manager.refresh_access_token(refresh_token)
        if not new_access:
            return None, None

        # Create new refresh token
        try:
            payload = self.token_manager.decode_token(refresh_token)
            new_refresh = self.token_manager.create_refresh_token(
                user_id=payload["sub"],
                tenant_id=payload["tid"],
                session_id=payload.get("sid"),
            )
            return new_access, new_refresh
        except Exception:
            return new_access, None

    # API Key management
    def create_api_key(
        self,
        tenant_id: str,
        user_id: str,
        name: str,
        permissions: list[Permission],
        expires_at: Optional[datetime] = None,
        rate_limit: int = 1000,
    ) -> tuple[APIKey, str]:
        # Generate key
        raw_key = f"pf_{secrets.token_urlsafe(32)}"
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        key_prefix = raw_key[:12]

        api_key = APIKey(
            key_id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_id=user_id,
            name=name,
            key_hash=key_hash,
            key_prefix=key_prefix,
            permissions=PermissionSet.from_list([p.value for p in permissions]),
            expires_at=expires_at,
            rate_limit=rate_limit,
        )

        self._api_keys[api_key.key_id] = api_key

        # Generate token
        token = self.token_manager.create_api_key_token(
            key_id=api_key.key_id,
            tenant_id=tenant_id,
            user_id=user_id,
            permissions=[p.value for p in permissions],
            expires_at=expires_at,
        )

        return api_key, f"{raw_key}.{token}"

    def validate_api_key(self, token: str) -> tuple[bool, Optional[APIKey], dict[str, Any]]:
        # Parse token format: prefix.jwt
        parts = token.split('.', 1)
        if len(parts) != 2:
            return False, None, {"error": "Invalid token format"}

        prefix, jwt_token = parts

        # Find key by hashing the presented raw key segment
        provided_hash = hashlib.sha256(prefix.encode()).hexdigest()
        api_key = None
        for key in self._api_keys.values():
            if hmac.compare_digest(key.key_hash, provided_hash):
                api_key = key
                break

        if not api_key:
            return False, None, {"error": "Invalid API key"}

        if not api_key.is_valid():
            return False, None, {"error": "API key expired or revoked"}

        # Verify JWT
        valid, payload = self.token_manager.validate_token(jwt_token)
        if not valid:
            return False, None, payload

        if payload.get("kid") != api_key.key_id:
            return False, None, {"error": "Key mismatch"}

        # Update usage
        api_key.last_used = datetime.utcnow()
        api_key.usage_count += 1

        return True, api_key, payload

    def revoke_api_key(self, key_id: str) -> bool:
        api_key = self._api_keys.get(key_id)
        if api_key:
            api_key.status = "revoked"
            api_key.revoked_at = datetime.utcnow()
            return True
        return False

    # Permission checking
    def check_permission(
        self,
        user: User,
        permission: Permission,
        tenant_id: Optional[str] = None,
    ) -> bool:
        if tenant_id and user.tenant_id != tenant_id:
            return False

        # Get all user permissions
        user_permissions = set()
        for role_id in user.roles:
            role = self.role_registry.get_role(role_id)
            if role:
                perms = role.get_all_permissions(self.role_registry)
                user_permissions.update(perms.permissions)

        return permission in user_permissions

    def check_any_permission(
        self,
        user: User,
        permissions: set[Permission],
        tenant_id: Optional[str] = None,
    ) -> bool:
        if tenant_id and user.tenant_id != tenant_id:
            return False

        user_permissions = set()
        for role_id in user.roles:
            role = self.role_registry.get_role(role_id)
            if role:
                perms = role.get_all_permissions(self.role_registry)
                user_permissions.update(perms.permissions)

        return bool(user_permissions & permissions)

    def get_user_permissions(self, user: User) -> PermissionSet:
        permissions = set()
        for role_id in user.roles:
            role = self.role_registry.get_role(role_id)
            if role:
                perms = role.get_all_permissions(self.role_registry)
                permissions.update(perms.permissions)
        return PermissionSet(permissions=permissions)


# Global instances
_auth_manager: Optional[AuthManager] = None


def get_auth_manager() -> AuthManager:
    global _auth_manager
    if _auth_manager is None:
        # Default configuration
        token_manager = TokenManager(
            secret_key=os.environ.get("JWT_SECRET", secrets.token_urlsafe(32)),
        )
        password_manager = PasswordManager()
        mfa_manager = MFAManager()
        role_registry = RoleRegistry()

        _auth_manager = AuthManager(
            token_manager=token_manager,
            password_manager=password_manager,
            mfa_manager=mfa_manager,
            role_registry=role_registry,
        )
    return _auth_manager


def init_auth_manager(
    secret_key: Optional[str] = None,
    access_token_ttl: int = 3600,
    refresh_token_ttl: int = 604800,
) -> AuthManager:
    global _auth_manager

    token_manager = TokenManager(
        secret_key=secret_key or secrets.token_urlsafe(32),
        access_token_ttl=access_token_ttl,
        refresh_token_ttl=refresh_token_ttl,
    )
    password_manager = PasswordManager()
    mfa_manager = MFAManager()
    role_registry = RoleRegistry()

    _auth_manager = AuthManager(
        token_manager=token_manager,
        password_manager=password_manager,
        mfa_manager=mfa_manager,
        role_registry=role_registry,
    )

    return _auth_manager


# Alias for backward compatibility
get_auth_manager = get_auth_manager


__all__ = [
    "AuthProvider",
    "TokenType",
    "Permission",
    "RoleType",
    "PermissionSet",
    "Role",
    "Tenant",
    "User",
    "Session",
    "APIKey",
    "TokenManager",
    "PasswordManager",
    "MFAManager",
    "RoleRegistry",
    "AuthManager",
    "get_auth_manager",
    "init_auth_manager",
]
