"""
PyFault Platform Module
"""

from pyfault.platform.graphql import GraphQLAdapter
from pyfault.platform.http import HttpAdapter
from pyfault.platform.websocket import WebSocketAdapter

__all__ = [
    "HttpAdapter",
    "WebSocketAdapter",
    "GraphQLAdapter",
]
