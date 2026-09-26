"""
Decorators for PyFault framework.
"""

from typing import Any, Callable

from pyfault.core.scanner import MetadataKeys, MetadataScanner


def injectable(scope: str = 'singleton') -> Callable:
    """
    Decorator to mark a class as injectable.

    Usage:
        @injectable()
        class MyService:
            pass

        @injectable(scope='transient')
        class MyOtherService:
            pass
    """
    def decorator(cls: type) -> type:
        MetadataScanner.set_metadata(cls, MetadataKeys.INJECTABLE, True)
        MetadataScanner.set_metadata(cls, MetadataKeys.SCOPE, scope)
        return cls
    return decorator


def controller(prefix: str = '') -> Callable:
    """
    Decorator to mark a class as a controller.

    Usage:
        @controller('users')
        class UserController:
            pass
    """
    def decorator(cls: type) -> type:
        MetadataScanner.set_metadata(cls, MetadataKeys.CONTROLLER, True)
        MetadataScanner.set_metadata(cls, MetadataKeys.PREFIX, prefix)
        MetadataScanner.set_metadata(cls, MetadataKeys.ROUTES, [])
        return cls
    return decorator


def module(config: dict) -> Callable:
    """
    Decorator to mark a class as a module.

    Usage:
        @module({
            'controllers': [UserController],
            'providers': [UserService],
            'imports': [DatabaseModule],
        })
        class AppModule:
            pass
    """
    def decorator(cls: type) -> type:
        MetadataScanner.set_metadata(cls, MetadataKeys.MODULE, config)
        return cls
    return decorator


def get(path: str) -> Callable:
    """
    Decorator to define a GET route.

    Usage:
        @controller('users')
        class UserController:
            @get('/')
            def find_all(self):
                return []
    """
    def decorator(method: Callable) -> Callable:
        method_any: Any = method
        if not hasattr(method_any, '__routes__'):
            method_any.__routes__ = []
        method_any.__routes__.append({
            'method': 'GET',
            'path': path,
        })
        return method
    return decorator


def post(path: str) -> Callable:
    """
    Decorator to define a POST route.

    Usage:
        @controller('users')
        class UserController:
            @post('/')
            def create(self, data: dict):
                return data
    """
    def decorator(method: Callable) -> Callable:
        method_any: Any = method
        if not hasattr(method_any, '__routes__'):
            method_any.__routes__ = []
        method_any.__routes__.append({
            'method': 'POST',
            'path': path,
        })
        return method
    return decorator


def put(path: str) -> Callable:
    """
    Decorator to define a PUT route.
    """
    def decorator(method: Callable) -> Callable:
        method_any: Any = method
        if not hasattr(method_any, '__routes__'):
            method_any.__routes__ = []
        method_any.__routes__.append({
            'method': 'PUT',
            'path': path,
        })
        return method
    return decorator


def delete(path: str) -> Callable:
    """
    Decorator to define a DELETE route.
    """
    def decorator(method: Callable) -> Callable:
        method_any: Any = method
        if not hasattr(method_any, '__routes__'):
            method_any.__routes__ = []
        method_any.__routes__.append({
            'method': 'DELETE',
            'path': path,
        })
        return method
    return decorator


def body() -> Callable:
    """
    Decorator to mark a parameter as request body.
    """
    def decorator(func: Callable) -> Callable:
        func_any: Any = func
        if not hasattr(func_any, '__params__'):
            func_any.__params__ = {}
        func_any.__params__['body'] = True
        return func
    return decorator


def param(name: str) -> Callable:
    """
    Decorator to mark a parameter as route parameter.
    """
    def decorator(func: Callable) -> Callable:
        func_any: Any = func
        if not hasattr(func_any, '__params__'):
            func_any.__params__ = {}
        func_any.__params__['param'] = name
        return func
    return decorator
