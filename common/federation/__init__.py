"""
GraphQL Federation for PyFault framework.
"""

from pyfault.common.federation.directives import (
    ExtendsDirective,
    ExternalDirective,
    InaccessibleDirective,
    KeyDirective,
    ProvidesDirective,
    RequiresDirective,
    ShareableDirective,
    TagDirective,
)
from pyfault.common.federation.gateway import (
    GraphQLGateway,
    ServiceConfig,
    create_federation_gateway,
)
from pyfault.common.federation.resolver import (
    FederatedObjectType,
    FederationResolver,
    create_federation_resolver,
    federated_external,
    federated_field,
    federated_key,
    federated_provides,
    federated_requires,
    federated_type,
)
from pyfault.common.federation.schema import FederationSchema, build_federation_schema

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
