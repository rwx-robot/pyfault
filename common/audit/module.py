"""
Audit Module for PyFault framework.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional


class AuditAction(str, Enum):
    """Audit action types."""
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    LOGOUT = "logout"
    ACCESS = "access"


@dataclass
class AuditLog:
    """Audit log entry."""
    id: str
    timestamp: datetime
    user_id: Optional[str]
    action: AuditAction
    resource: str
    details: dict[str, Any]
    ip_address: Optional[str] = None


class AuditModule:
    """Audit module for tracking user actions."""

    def __init__(self) -> None:
        self._logs: list[AuditLog] = []
        self._log_id_counter = 0

    def log(self, action: AuditAction, resource: str, user_id: Optional[str] = None,
            details: Optional[dict[str, Any]] = None, ip_address: Optional[str] = None) -> AuditLog:
        """Create an audit log entry."""
        self._log_id_counter += 1
        log = AuditLog(
            id=str(self._log_id_counter),
            timestamp=datetime.now(),
            user_id=user_id,
            action=action,
            resource=resource,
            details=details or {},
            ip_address=ip_address
        )
        self._logs.append(log)
        return log

    def get_logs(self, user_id: Optional[str] = None, action: Optional[AuditAction] = None,
                 resource: Optional[str] = None) -> list[AuditLog]:
        """Get audit logs with optional filters."""
        logs = self._logs

        if user_id:
            logs = [entry for entry in logs if entry.user_id == user_id]
        if action:
            logs = [entry for entry in logs if entry.action == action]
        if resource:
            logs = [entry for entry in logs if entry.resource == resource]

        return logs

    def get_recent_logs(self, limit: int = 10) -> list[AuditLog]:
        """Get recent audit logs."""
        return self._logs[-limit:]

    def clear_logs(self) -> None:
        """Clear all audit logs."""
        self._logs.clear()


class AuditInterceptor:
    """Audit interceptor for automatic logging."""

    def __init__(self, audit_module: AuditModule):
        self.audit_module = audit_module

    def intercept(self, action: AuditAction, resource: str) -> Callable[..., Any]:
        """Interceptor decorator."""
        def decorator(func: Any) -> Any:
            async def wrapper(*args: Any, **kwargs: Any) -> Any:
                # Log before execution
                user_id = kwargs.get('user_id')
                self.audit_module.log(action, resource, user_id)

                # Execute function
                result = await func(*args, **kwargs)
                return result
            return wrapper
        return decorator
