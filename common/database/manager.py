"""
Database Manager for PyFault framework - SQLAlchemy integration.
"""

from typing import Any, Optional

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase, declarative_base

from pyfault.common.database.session import SessionManager, init_session_manager, get_session_manager


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models."""
    metadata = MetaData()


class DatabaseManager:
    """Database manager for SQLAlchemy integration."""

    def __init__(
        self,
        url: str = "sqlite:///pyfault.db",
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        auto_create_tables: bool = False,
    ):
        self.url = url
        self.echo = echo
        self.pool_size = pool_size
        self.max_overflow = max_overflow
        self.pool_timeout = pool_timeout
        self.pool_recycle = pool_recycle
        self.auto_create_tables = auto_create_tables

        self._session_manager: Optional[SessionManager] = None
        self._initialized = False

    def initialize(self) -> "DatabaseManager":
        """Initialize the database connection."""
        if self._initialized:
            return self

        self._session_manager = init_session_manager(
            url=self.url,
            echo=self.echo,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_timeout=self.pool_timeout,
            pool_recycle=self.pool_recycle,
        )

        if self.auto_create_tables:
            self.create_tables()

        self._initialized = True
        return self

    def create_tables(self):
        """Create all tables defined in models."""
        engine = self._session_manager.sync_engine
        Base.metadata.create_all(engine)

    def drop_tables(self):
        """Drop all tables."""
        engine = self._session_manager.sync_engine
        Base.metadata.drop_all(engine)

    def get_session_manager(self) -> SessionManager:
        """Get the session manager."""
        if self._session_manager is None:
            self.initialize()
        return self._session_manager

    def get_session(self):
        """Get a new database session."""
        return self.get_session_manager().get_sync_session()

    def get_async_session(self):
        """Get a new async database session."""
        return self.get_session_manager().get_async_session()

    def session_scope(self):
        """Get a transactional session scope."""
        return self.get_session_manager().session_scope()

    def async_session_scope(self):
        """Get an async transactional session scope."""
        return self.get_session_manager().async_session_scope()

    def close(self):
        """Close database connections."""
        if self._session_manager:
            self._session_manager.close()
            self._session_manager = None
        self._initialized = False


class DatabaseModule:
    """Database module for dependency injection."""

    def __init__(
        self,
        url: str = "sqlite:///pyfault.db",
        echo: bool = False,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: int = 30,
        pool_recycle: int = 3600,
        auto_create_tables: bool = False,
    ):
        self.manager = DatabaseManager(
            url=url,
            echo=echo,
            pool_size=pool_size,
            max_overflow=max_overflow,
            pool_timeout=pool_timeout,
            pool_recycle=pool_recycle,
            auto_create_tables=auto_create_tables,
        )

    def initialize(self) -> "DatabaseModule":
        """Initialize the database module."""
        self.manager.initialize()
        return self

    def get_manager(self) -> DatabaseManager:
        """Get the database manager."""
        return self.manager

    def get_session(self):
        """Get a database session."""
        return self.manager.get_session()

    def get_async_session(self):
        """Get an async database session."""
        return self.manager.get_async_session()

    def session_scope(self):
        """Get a transactional session scope."""
        return self.manager.session_scope()

    def async_session_scope(self):
        """Get an async transactional session scope."""
        return self.manager.async_session_scope()

    def create_tables(self):
        """Create all tables."""
        self.manager.create_tables()

    def drop_tables(self):
        """Drop all tables."""
        self.manager.drop_tables()

    def close(self):
        """Close database connections."""
        self.manager.close()