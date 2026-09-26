"""
Authentication Module for PyFault framework.
"""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from pyfault.common.errors.handler import UnauthorizedException


@dataclass
class User:
    """User data class."""
    id: str
    username: str
    email: str
    password_hash: str
    roles: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class Token:
    """Token data class."""
    access_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"


class AuthModule:
    """Authentication module."""

    def __init__(self, secret_key: Optional[str] = None, token_ttl: int = 3600) -> None:
        self.secret_key = secret_key or secrets.token_hex(32)
        self.token_ttl = token_ttl
        self._users: dict[str, User] = {}
        self._refresh_tokens: dict[str, str] = {}

    def register_user(self, username: str, email: str, password: str) -> User:
        """Register a new user."""
        user_id = secrets.token_hex(16)
        password_hash = self._hash_password(password)

        user = User(
            id=user_id,
            username=username,
            email=email,
            password_hash=password_hash
        )
        self._users[user_id] = user
        return user

    def login(self, username: str, password: str) -> Optional[Token]:
        """Login and get tokens."""
        user = self._find_user_by_username(username)
        if not user:
            return None

        if not self._verify_password(password, user.password_hash):
            return None

        return self._generate_tokens(user)

    def verify_token(self, token: str) -> Optional[User]:
        """Verify access token and return user."""
        # Simple verification (in production, use JWT)
        user_id = self._decrypt_token(token)
        if user_id and user_id in self._users:
            return self._users[user_id]
        return None

    def refresh_token(self, refresh_token: str) -> Optional[Token]:
        """Refresh access token."""
        user_id = self._refresh_tokens.get(refresh_token)
        if not user_id:
            return None

        user = self._users.get(user_id)
        if not user:
            return None

        # Remove old refresh token
        del self._refresh_tokens[refresh_token]

        return self._generate_tokens(user)

    def _find_user_by_username(self, username: str) -> Optional[User]:
        """Find user by username."""
        for user in self._users.values():
            if user.username == username:
                return user
        return None

    def _hash_password(self, password: str) -> str:
        """Hash password."""
        salt = secrets.token_hex(16)
        password_hash = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode(),
            salt.encode(),
            100000
        )
        return f"{salt}:{password_hash.hex()}"

    def _verify_password(self, password: str, password_hash: str) -> bool:
        """Verify password."""
        salt, hash_hex = password_hash.split(':')
        password_hash_new = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode(),
            salt.encode(),
            100000
        )
        return password_hash_new.hex() == hash_hex

    def _generate_tokens(self, user: User) -> Token:
        """Generate access and refresh tokens."""
        access_token = self._encrypt_token(user.id)
        refresh_token = secrets.token_hex(32)

        self._refresh_tokens[refresh_token] = user.id

        return Token(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=self.token_ttl
        )

    def _encrypt_token(self, user_id: str) -> str:
        """Encrypt user ID to token."""
        # Simple encryption (in production, use JWT)
        return f"{user_id}:{secrets.token_hex(16)}"

    def _decrypt_token(self, token: str) -> Optional[str]:
        """Decrypt token to user ID."""
        # Simple decryption (in production, use JWT)
        parts = token.split(':')
        if len(parts) == 2:
            return parts[0]
        return None


class AuthGuard:
    """Authentication guard."""

    def __init__(self, auth_module: AuthModule):
        self.auth_module = auth_module

    def authenticate(self, token: str) -> Optional[User]:
        """Authenticate user from token."""
        return self.auth_module.verify_token(token)

    def require_auth(self, token: str) -> User:
        """Require authentication."""
        user = self.authenticate(token)
        if not user:
            raise UnauthorizedException("Invalid or expired token")
        return user
