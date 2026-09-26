"""
Testing Utilities for PyFault framework.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Callable, Optional


class TestModule:
    """Test module for testing PyFault applications."""

    def __init__(self) -> None:
        self._fixtures: dict[str, Any] = {}
        self._mocks: dict[str, Callable] = {}

    def fixture(self, name: Optional[str] = None) -> Callable:
        """Decorator for registering test fixtures."""
        def decorator(func: Any) -> Any:
            fixture_name = name or func.__name__
            self._fixtures[fixture_name] = func
            return func
        return decorator

    def mock(self, name: Optional[str] = None) -> Callable:
        """Decorator for registering mocks."""
        def decorator(func: Any) -> Any:
            mock_name = name or func.__name__
            self._mocks[mock_name] = func
            return func
        return decorator

    def get_fixture(self, name: str) -> Optional[Callable]:
        """Get fixture by name."""
        return self._fixtures.get(name)

    def get_mock(self, name: str) -> Optional[Callable]:
        """Get mock by name."""
        return self._mocks.get(name)


class TestClient:
    """Test client for testing HTTP endpoints."""

    def __init__(self, app: Any = None):
        self.app = app
        self._headers: dict[str, str] = {}

    def set_header(self, key: str, value: str) -> None:
        """Set request header."""
        self._headers[key] = value

    def get(self, url: str, **kwargs: Any) -> 'TestResponse':
        """Send GET request."""
        return self._request('GET', url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> 'TestResponse':
        """Send POST request."""
        return self._request('POST', url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> 'TestResponse':
        """Send PUT request."""
        return self._request('PUT', url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> 'TestResponse':
        """Send DELETE request."""
        return self._request('DELETE', url, **kwargs)

    def _request(self, method: str, url: str, **kwargs: Any) -> 'TestResponse':
        """Send HTTP request."""
        # Simulated response for testing
        return TestResponse(
            status_code=200,
            json_data={"method": method, "url": url}
        )


class TestResponse:
    """Test response object."""

    def __init__(self, status_code: int = 200, json_data: Any = None,
                 text: Optional[str] = None, headers: Optional[dict[str, str]] = None):
        self.status_code = status_code
        self.json_data = json_data
        self.text = text or ""
        self.headers = headers or {}

    def json(self) -> Any:
        """Get JSON data."""
        return self.json_data

    def raise_for_status(self) -> None:
        """Raise exception for error status codes."""
        if self.status_code >= 400:
            from pyfault.common.errors.handler import BadRequestException
            if self.status_code == 400:
                raise BadRequestException(f"HTTP Error: {self.status_code}")
            elif self.status_code == 401:
                from pyfault.common.errors.handler import UnauthorizedException
                raise UnauthorizedException(f"HTTP Error: {self.status_code}")
            elif self.status_code == 403:
                from pyfault.common.errors.handler import ForbiddenException
                raise ForbiddenException(f"HTTP Error: {self.status_code}")
            elif self.status_code == 404:
                from pyfault.common.errors.handler import NotFoundException
                raise NotFoundException(f"HTTP Error: {self.status_code}")
            elif self.status_code == 409:
                from pyfault.common.errors.handler import ConflictException
                raise ConflictException(f"HTTP Error: {self.status_code}")
            elif self.status_code >= 500:
                from pyfault.common.errors.handler import InternalErrorException
                raise InternalErrorException(f"HTTP Error: {self.status_code}")
            raise Exception(f"HTTP Error: {self.status_code}")


@asynccontextmanager
async def create_test_app(app_factory: Callable) -> AsyncIterator[Any]:
    """Create test app context."""
    app = app_factory()
    try:
        yield app
    finally:
        # Cleanup
        pass


class MockService:
    """Mock service for testing."""

    def __init__(self) -> None:
        self._calls: list[tuple[str, tuple, dict]] = []
        self._return_values: dict[str, Any] = {}

    def set_return(self, method: str, value: Any) -> None:
        """Set return value for method."""
        self._return_values[method] = value

    def __getattr__(self, name: str) -> Any:
        """Get attribute."""
        def method(*args: Any, **kwargs: Any) -> Any:
            self._calls.append((name, args, kwargs))
            return self._return_values.get(name)
        return method

    def get_calls(self, method: Optional[str] = None) -> list[tuple[str, tuple, dict]]:
        """Get calls made to mock."""
        if method:
            return [c for c in self._calls if c[0] == method]
        return self._calls
