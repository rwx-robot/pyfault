"""
Metadata Scanner for PyFault framework.
"""

from typing import Any


class MetadataKeys:
    """Metadata keys for decorators."""
    INJECTABLE = '__injectable__'
    CONTROLLER = '__controller__'
    MODULE = '__pyfault_module__'
    SCOPE = '__scope__'
    PREFIX = '__prefix__'
    ROUTES = '__routes__'


class MetadataScanner:
    """
    Metadata Scanner for scanning class metadata.
    """

    @staticmethod
    def get_metadata(cls: type, key: str) -> Any:
        """Get metadata from a class."""
        return getattr(cls, key, None)

    @staticmethod
    def set_metadata(cls: type, key: str, value: Any) -> None:
        """Set metadata on a class."""
        setattr(cls, key, value)

    @staticmethod
    def is_injectable(cls: type) -> bool:
        """Check if a class is injectable."""
        return MetadataScanner.get_metadata(cls, MetadataKeys.INJECTABLE) is True

    @staticmethod
    def is_controller(cls: type) -> bool:
        """Check if a class is a controller."""
        return MetadataScanner.get_metadata(cls, MetadataKeys.CONTROLLER) is True

    @staticmethod
    def is_module(cls: type) -> bool:
        """Check if a class is a module."""
        return MetadataScanner.get_metadata(cls, MetadataKeys.MODULE) is not None

    @staticmethod
    def get_scope(cls: type) -> str:
        """Get scope of an injectable class."""
        return MetadataScanner.get_metadata(cls, MetadataKeys.SCOPE) or 'singleton'

    @staticmethod
    def get_routes(cls: type) -> list[dict]:
        """Get routes from a controller class and its methods."""
        routes = MetadataScanner.get_metadata(cls, MetadataKeys.ROUTES) or []

        # Also extract routes from methods
        for attr_name in dir(cls):
            attr = getattr(cls, attr_name)
            if callable(attr) and hasattr(attr, '__routes__'):
                method_routes = attr.__routes__
                if isinstance(method_routes, list):
                    routes.extend(method_routes)

        return routes
