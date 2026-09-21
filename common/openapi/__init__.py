"""
OpenAPI/Swagger Documentation for PyFault framework.
"""

from pyfault.common.openapi.generator import OpenAPIGenerator
from pyfault.common.openapi.schema import OpenAPISchema
from pyfault.common.openapi.decorators import api, operation, schema

__all__ = [
    "OpenAPIGenerator",
    "OpenAPISchema", 
    "api",
    "operation",
    "schema",
]