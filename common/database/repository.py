"""
Repository Pattern for PyFault framework.
"""

from typing import Any, Generic, List, Optional, Type, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from pyfault.common.database.session import session_scope, async_session_scope


T = TypeVar("T")


class BaseRepository(Generic[T]):
    """Base repository with common CRUD operations."""

    def __init__(self, model_class: Type[T]):
        self.model_class = model_class

    # Sync methods
    def get(self, id: Any) -> Optional[T]:
        """Get entity by ID."""
        with session_scope() as session:
            return session.get(self.model_class, id)

    def get_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """Get all entities with pagination."""
        with session_scope() as session:
            stmt = select(self.model_class).limit(limit).offset(offset)
            return list(session.scalars(stmt))

    def find_by(self, **kwargs) -> List[T]:
        """Find entities by criteria."""
        with session_scope() as session:
            stmt = select(self.model_class).filter_by(**kwargs)
            return list(session.scalars(stmt))

    def find_one_by(self, **kwargs) -> Optional[T]:
        """Find single entity by criteria."""
        with session_scope() as session:
            stmt = select(self.model_class).filter_by(**kwargs)
            return session.scalar(stmt)

    def create(self, **kwargs) -> T:
        """Create new entity."""
        with session_scope() as session:
            entity = self.model_class(**kwargs)
            session.add(entity)
            session.flush()
            session.refresh(entity)
            return entity

    def update(self, id: Any, **kwargs) -> Optional[T]:
        """Update entity by ID."""
        with session_scope() as session:
            entity = session.get(self.model_class, id)
            if entity:
                for key, value in kwargs.items():
                    setattr(entity, key, value)
                session.flush()
                session.refresh(entity)
            return entity

    def delete(self, id: Any) -> bool:
        """Delete entity by ID."""
        with session_scope() as session:
            entity = session.get(self.model_class, id)
            if entity:
                session.delete(entity)
                return True
            return False

    def count(self) -> int:
        """Count total entities."""
        with session_scope() as session:
            from sqlalchemy import func
            stmt = select(func.count()).select_from(self.model_class)
            return session.scalar(stmt) or 0

    # Async methods
    async def aget(self, id: Any) -> Optional[T]:
        """Get entity by ID (async)."""
        async with async_session_scope() as session:
            return await session.get(self.model_class, id)

    async def aget_all(self, limit: int = 100, offset: int = 0) -> List[T]:
        """Get all entities with pagination (async)."""
        async with async_session_scope() as session:
            stmt = select(self.model_class).limit(limit).offset(offset)
            result = await session.scalars(stmt)
            return list(result)

    async def afind_by(self, **kwargs) -> List[T]:
        """Find entities by criteria (async)."""
        async with async_session_scope() as session:
            stmt = select(self.model_class).filter_by(**kwargs)
            result = await session.scalars(stmt)
            return list(result)

    async def afind_one_by(self, **kwargs) -> Optional[T]:
        """Find single entity by criteria (async)."""
        async with async_session_scope() as session:
            stmt = select(self.model_class).filter_by(**kwargs)
            return await session.scalar(stmt)

    async def acreate(self, **kwargs) -> T:
        """Create new entity (async)."""
        async with async_session_scope() as session:
            entity = self.model_class(**kwargs)
            session.add(entity)
            await session.flush()
            await session.refresh(entity)
            return entity

    async def aupdate(self, id: Any, **kwargs) -> Optional[T]:
        """Update entity by ID (async)."""
        async with async_session_scope() as session:
            entity = await session.get(self.model_class, id)
            if entity:
                for key, value in kwargs.items():
                    setattr(entity, key, value)
                await session.flush()
                await session.refresh(entity)
            return entity

    async def adelete(self, id: Any) -> bool:
        """Delete entity by ID (async)."""
        async with async_session_scope() as session:
            entity = await session.get(self.model_class, id)
            if entity:
                await session.delete(entity)
                return True
            return False

    async def acount(self) -> int:
        """Count total entities (async)."""
        async with async_session_scope() as session:
            from sqlalchemy import func
            stmt = select(func.count()).select_from(self.model_class)
            return await session.scalar(stmt) or 0


class RepositoryMixin:
    """Mixin to add repository to a service class."""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def repository(self, model_class: Type[T]) -> BaseRepository[T]:
        """Create a repository for the given model."""
        return BaseRepository(model_class)