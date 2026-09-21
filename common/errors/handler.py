"""
Error Handling for PyFault framework.
"""

from enum import Enum
from typing import Any, Optional


class ErrorCode(str, Enum):
    """Error codes."""
    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    CONFLICT = "CONFLICT"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"


class AppException(Exception):
    """Application exception."""

    def __init__(self, code: ErrorCode, message: str, details: Optional[dict[str, Any]] = None, status_code: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
        self.status_code = status_code


class BadRequestException(AppException):
    """Bad request exception."""

    def __init__(self, message: str = "Bad request", details: dict[str, Any] = None):
        super().__init__(
            code=ErrorCode.BAD_REQUEST,
            message=message,
            details=details,
            status_code=400
        )


class UnauthorizedException(AppException):
    """Unauthorized exception."""

    def __init__(self, message: str = "Unauthorized", details: dict[str, Any] = None):
        super().__init__(
            code=ErrorCode.UNAUTHORIZED,
            message=message,
            details=details,
            status_code=401
        )


class ForbiddenException(AppException):
    """Forbidden exception."""

    def __init__(self, message: str = "Forbidden", details: dict[str, Any] = None):
        super().__init__(
            code=ErrorCode.FORBIDDEN,
            message=message,
            details=details,
            status_code=403
        )


class NotFoundException(AppException):
    """Not found exception."""

    def __init__(self, message: str = "Not found", details: dict[str, Any] = None):
        super().__init__(
            code=ErrorCode.NOT_FOUND,
            message=message,
            details=details,
            status_code=404
        )


class ConflictException(AppException):
    """Conflict exception."""

    def __init__(self, message: str = "Conflict", details: dict[str, Any] = None):
        super().__init__(
            code=ErrorCode.CONFLICT,
            message=message,
            details=details,
            status_code=409
        )


class InternalErrorException(AppException):
    """Internal error exception."""

    def __init__(self, message: str = "Internal error", details: dict[str, Any] = None):
        super().__init__(
            code=ErrorCode.INTERNAL_ERROR,
            message=message,
            details=details,
            status_code=500
        )


class ErrorHandler:
    """Error handler for global exception handling."""

    def __init__(self):
        self._handlers: dict[ErrorCode, Any] = {}

    def register_handler(self, error_code: ErrorCode, handler):
        """Register error handler."""
        self._handlers[error_code] = handler

    def handle(self, exception: AppException) -> dict[str, Any]:
        """Handle exception."""
        if exception.code in self._handlers:
            return self._handlers[exception.code](exception)

        return {
            "error": {
                "code": exception.code.value,
                "message": exception.message,
                "details": exception.details
            }
        }
