"""
Database Session Management for PyFault framework.
"""

from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager
from typing import Optional

from sqlalchemy import Engine, create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker


class SessionManager:
    """Manages database sessions."""

    def __init__(
        self,
        url: str,
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
    ):
        self.url = url
        self.echo = echo
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle

        self._sync_engine: Optional[Engine] = None
        self._async_engine: Optional[AsyncEngine] = None
        self._sync_session_factory: Optional[sessionmaker[Session]] = None
        self._async_session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    @property
    def sync_engine(self) -> Engine:
        """Get or create synchronous engine."""
        if self._sync_engine is None:
            self._sync_engine = create_engine(
                self.url,
                echo=self.echo,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_timeout=self.pool_timeout,
                pool_recycle=self.pool_recycle,
            )
        return self._sync_engine

    @property
    def async_engine(self) -> AsyncEngine:
        """Get or create asynchronous engine."""
        if self._async_engine is None:
            # Convert sync URL to async if needed
            async_url = self.url
            if async_url.startswith("postgresql://"):
                async_url = async_url.replace("postgresql://", "postgresql+asyncpg://")
            elif async_url.startswith("mysql://"):
                async_url = async_url.replace("mysql://", "mysql+aiomysql://")
            elif async_url.startswith("sqlite://"):
                async_url = async_url.replace("sqlite://", "sqlite+aiosqlite://")

            self._async_engine = create_async_engine(
                async_url,
                echo=self.echo,
                pool_size=self.pool_size,
                max_overflow=self.max_overflow,
                pool_timeout=self.pool_timeout,
                pool_recycle=self.pool_recycle,
            )
        return self._async_engine

    @property
    def sync_session_factory(self) -> sessionmaker[Session]:
        """Get or create synchronous session factory."""
        if self._sync_session_factory is None:
            self._sync_session_factory = sessionmaker(
                bind=self.sync_engine,
                expire_on_commit=False,
            )
        return self._sync_session_factory

    @property
    def async_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Get or create asynchronous session factory."""
        if self._async_session_factory is None:
            self._async_session_factory = async_sessionmaker(
                bind=self.async_engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )
        return self._async_session_factory

    def get_sync_session(self) -> Session:
        """Create a new synchronous session."""
        return self.sync_session_factory()

    def get_async_session(self) -> AsyncSession:
        """Create a new asynchronous session."""
        return self.async_session_factory()

    @contextmanager
    def session_scope(self) -> Generator[Session, None, None]:
        """Provide a transactional scope around a series of operations."""
        session = self.get_sync_session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @asynccontextmanager
    async def async_session_scope(self) -> AsyncGenerator[AsyncSession, None]:
        """Provide a transactional scope around a series of async operations."""
        session = self.get_async_session()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    def close(self) -> None:
        """Close all engines."""
        if self._sync_engine:
            self._sync_engine.dispose()
        if self._async_engine:
            import asyncio
            asyncio.create_task(self._async_engine.dispose())


# Global session manager instance
_session_manager: Optional[SessionManager] = None


def init_session_manager(
    url: str,
    echo: bool = False,
    pool_size: int = 5,
    max_overflow: int = 10,
    pool_timeout: int = 30,
    pool_recycle: int = 3600,
) -> SessionManager:
    """Initialize global session manager."""
    global _session_manager
    _session_manager = SessionManager(
        url=url,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=pool_timeout,
        pool_recycle=pool_recycle,
    )
    return _session_manager


def get_session_manager() -> Optional[SessionManager]:
    """Get global session manager."""
    return _session_manager


def get_session() -> Session:
    """Get a session from global manager."""
    if _session_manager is None:
        raise RuntimeError("Session manager not initialized. Call init_session_manager() first.")
    return _session_manager.get_sync_session()


def get_async_session() -> AsyncSession:
    """Get an async session from global manager."""
    if _session_manager is None:
        raise RuntimeError("Session manager not initialized. Call init_session_manager() first.")
    return _session_manager.get_async_session()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Get a session from global manager."""
    if _session_manager is None:
        raise RuntimeError("Session manager not initialized. Call init_session_manager() first.")
    with _session_manager.session_scope() as session:
        yield session


@asynccontextmanager
async def async_session_scope() -> AsyncGenerator[AsyncSession, None]:
    """Get an async session from global manager."""
    if _session_manager is None:
        raise RuntimeError("Session manager not initialized. Call init_session_manager() first.")
    async with _session_manager.async_session_scope() as session:
        yield session
