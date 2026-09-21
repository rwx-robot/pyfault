"""
Common utilities for PyFault framework.
"""

from pyfault.common.decorators import (
    body,
    controller,
    delete,
    get,
    injectable,
    module,
    param,
    post,
    put,
)

__all__ = [
    'injectable',
    'controller',
    'module',
    'get',
    'post',
    'put',
    'delete',
    'body',
    'param',
]
