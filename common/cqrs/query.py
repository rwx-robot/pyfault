"""
Query and Query Handler for CQRS.
"""

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Generic, Optional, TypeVar

from pyfault.common.cqrs.core import MiddlewareChain, QueryMiddleware
from pyfault.common.time import utc_now


class QueryStatus(str, Enum):
    """Query execution status."""
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


Q = TypeVar("Q", bound="Query")
R = TypeVar("R")


@dataclass
class Query:
    """
    Base query class.

    A query represents a request for data without side effects.
    Queries are read-only and should not modify state.
    """
    query_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: Optional[str] = None
    timestamp: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        query_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> None:
        self.query_id = query_id or str(uuid.uuid4())
        self.correlation_id = correlation_id
        self.timestamp = timestamp or utc_now()
        self.metadata = metadata or {}
        # Apply subclass fields passed as keyword arguments
        for key, value in kwargs.items():
            setattr(self, key, value)

    def validate(self) -> list[str]:
        """Validate the query. Return list of validation errors."""
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Query":
        return cls(
            query_id=data.get("query_id", str(uuid.uuid4())),
            correlation_id=data.get("correlation_id"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else utc_now(),
            metadata=data.get("metadata", {}),
        )


@dataclass
class QueryResult(Generic[R]):
    """Result of query execution."""
    success: bool
    query_id: str
    data: Optional[R] = None
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    execution_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "query_id": self.query_id,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
            "execution_time_ms": self.execution_time_ms,
        }


class QueryHandler(ABC, Generic[Q, R]):
    """
    Abstract base class for query handlers.

    A query handler contains the logic for executing a query and returning data.
    """

    @property
    @abstractmethod
    def query_type(self) -> type[Q]:
        """The type of query this handler handles."""
        pass

    @abstractmethod
    async def handle(self, query: Q) -> QueryResult:
        """Execute the query and return result."""
        pass

    async def validate(self, query: Q) -> list[str]:
        """Validate the query before execution."""
        return query.validate()

    def can_handle(self, query: Q) -> bool:
        """Check if this handler can handle the given query."""
        return isinstance(query, self.query_type)


class QueryBus:
    """
    Query bus for dispatching queries to handlers.

    The query bus routes queries to their registered handlers
    and manages the query execution pipeline.
    """

    def __init__(self) -> None:
        self._handlers: dict[type[Query], QueryHandler] = {}
        self._middleware: list[QueryMiddleware] = []
        self._default_handler: Optional[QueryHandler] = None

    def register(self, handler: QueryHandler) -> None:
        """Register a query handler."""
        self._handlers[handler.query_type] = handler

    def unregister(self, query_type: type["Query"]) -> bool:
        """Unregister a query handler."""
        if query_type in self._handlers:
            del self._handlers[query_type]
            return True
        return False

    def add_middleware(self, middleware: "QueryMiddleware") -> None:
        """Add middleware to the query pipeline."""
        self._middleware.append(middleware)

    def set_default_handler(self, handler: QueryHandler) -> None:
        """Set default handler for unregistered queries."""
        self._default_handler = handler

    async def dispatch(self, query: "Query") -> "QueryResult":
        """Dispatch a query to its handler."""
        # Validate query
        errors = query.validate()
        if errors:
            return QueryResult(
                success=False,
                query_id=query.query_id,
                error=f"Validation failed: {', '.join(errors)}",
            )

        # Find handler
        handler = self._handlers.get(type(query))
        if not handler:
            if self._default_handler:
                handler = self._default_handler
            else:
                return QueryResult(
                    success=False,
                    query_id=query.query_id,
                    error=f"No handler registered for query type: {type(query).__name__}",
                )

        # Apply middleware chain
        async def execute_handler(q: "Query") -> "QueryResult":
            import time
            start = time.time()
            result = await handler.handle(q)
            result.execution_time_ms = (time.time() - start) * 1000
            return result

        # Build middleware chain
        chain = MiddlewareChain(self._middleware, execute_handler)
        result: QueryResult[Any] = await chain.execute(query)
        return result

    async def dispatch_batch(self, queries: list["Query"]) -> list["QueryResult"]:
        """Dispatch multiple queries."""
        results = []
        for query in queries:
            result = await self.dispatch(query)
            results.append(result)
        return results


@dataclass
class QueryOptions:
    """Options for query execution."""
    page: int = 1
    page_size: int = 20
    sort_by: Optional[str] = None
    sort_order: str = "asc"  # asc or desc
    filters: dict[str, Any] = field(default_factory=dict)
    include_related: list[str] = field(default_factory=list)
    projection: list[str] = field(default_factory=list)


@dataclass
class PaginatedQueryResult(Generic[R]):
    """Paginated query result."""
    items: list[R] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": [item.to_dict() if hasattr(item, 'to_dict') else item for item in self.items],
            "total": self.total,
            "page": self.page,
            "page_size": self.page_size,
            "total_pages": self.total_pages,
        }


def query(cls: Optional[type] = None, *, query_type: Optional[type[Query]] = None) -> Callable[..., Any]:
    """Decorator for creating query classes (usable bare: ``@query``)."""
    def decorator(target: type) -> type:
        # Only skip when THIS class declares its own fields
        if "__dataclass_fields__" not in target.__dict__:
            target = dataclass(target)
        if not issubclass(target, Query):
            raise TypeError("Query class must inherit from Query")
        return target

    if cls is None:
        return decorator
    return decorator(cls)


# Built-in queries
@query
@dataclass
class GetEntityQuery(Query):
    """Query to get a single entity by ID."""
    entity_type: str = ""
    entity_id: str = ""
    include_related: list[str] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.entity_type:
            errors.append("entity_type is required")
        if not self.entity_id:
            errors.append("entity_id is required")
        return errors


@query
@dataclass
class ListEntitiesQuery(Query):
    """Query to list entities with pagination and filtering."""
    entity_type: str = ""
    options: "QueryOptions" = field(default_factory=QueryOptions)

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.entity_type:
            errors.append("entity_type is required")
        return errors


@query
@dataclass
class SearchEntitiesQuery(Query):
    """Query to search entities with text search."""
    entity_type: str = ""
    search_term: str = ""
    options: "QueryOptions" = field(default_factory=QueryOptions)

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.entity_type:
            errors.append("entity_type is required")
        if not self.search_term:
            errors.append("search_term is required")
        return errors


@query
@dataclass
class CountEntitiesQuery(Query):
    """Query to count entities with optional filters."""
    entity_type: str = ""
    filters: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errors = super().validate()
        if not self.entity_type:
            errors.append("entity_type is required")
        return errors
