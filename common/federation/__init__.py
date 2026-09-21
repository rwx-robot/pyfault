"""
GraphQL Federation for PyFault framework.
"""

from pyfault.common.federation.gateway import GraphQLGateway, create_federation_gateway, ServiceConfig
from pyfault.common.federation.schema import FederationSchema, build_federation_schema
from pyfault.common.federation.resolver import (
    FederationResolver,
    FederatedObjectType,
    create_federation_resolver,
    federated_type,
    federated_field,
    federated_key,
    federated_requires,
    federated_provides,
    federated_external,
)
from pyfault.common.federation.directives import (
    KeyDirective,
    ExtendsDirective,
    ExternalDirective,
    RequiresDirective,
    ProvidesDirective,
    TagDirective,
    InaccessibleDirective,
    ShareableDirective,
)

__all__ = [
    "GraphQLGateway",
    "create_federation_gateway",
    "ServiceConfig",
    "FederationSchema",
    "build_federation_schema",
    "FederationResolver",
    "FederatedObjectType",
    "KeyDirective",
    "ExtendsDirective",
    "ExternalDirective",
    "RequiresDirective",
    "ProvidesDirective",
    "TagDirective",
    "InaccessibleDirective",
    "ShareableDirective",
    "federated_type",
    "federated_field",
    "federated_key",
    "federated_requires",
    "federated_provides",
    "federated_external",
    "create_federation_resolver",
]