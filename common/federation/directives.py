"""
Federation Directives for PyFault framework.
"""

from typing import Any, Dict, List

from graphql import (
    GraphQLDirective,
    GraphQLArgument,
    GraphQLNonNull,
    GraphQLString,
    GraphQLList,
    GraphQLBoolean,
    DirectiveLocation,
)


# @key directive - specifies the key fields for an entity
KeyDirective = GraphQLDirective(
    name="key",
    description="Specifies the key fields for an entity type",
    locations=[
        DirectiveLocation.OBJECT,
        DirectiveLocation.INTERFACE,
    ],
    args={
        "fields": GraphQLArgument(
            GraphQLNonNull(GraphQLString),
            description="The key fields selection set",
        ),
    },
)

# @extends directive - indicates a type extends another service's type
ExtendsDirective = GraphQLDirective(
    name="extends",
    description="Indicates that this type extends a type from another service",
    locations=[
        DirectiveLocation.OBJECT,
        DirectiveLocation.INTERFACE,
    ],
    args={},
)

# @external directive - marks a field as owned by another service
ExternalDirective = GraphQLDirective(
    name="external",
    description="Marks a field as owned by another service",
    locations=[
        DirectiveLocation.FIELD_DEFINITION,
    ],
    args={},
)

# @requires directive - specifies required fields from other services
RequiresDirective = GraphQLDirective(
    name="requires",
    description="Specifies which fields are required from other services",
    locations=[
        DirectiveLocation.FIELD_DEFINITION,
    ],
    args={
        "fields": GraphQLArgument(
            GraphQLNonNull(GraphQLString),
            description="The required fields selection set",
        ),
    },
)

# @provides directive - specifies fields this service can provide
ProvidesDirective = GraphQLDirective(
    name="provides",
    description="Specifies which fields this service can provide",
    locations=[
        DirectiveLocation.FIELD_DEFINITION,
    ],
    args={
        "fields": GraphQLArgument(
            GraphQLNonNull(GraphQLString),
            description="The provided fields selection set",
        ),
    },
)

# @tag directive - adds metadata tags to schema elements
TagDirective = GraphQLDirective(
    name="tag",
    description="Adds metadata tags to schema elements",
    locations=[
        DirectiveLocation.OBJECT,
        DirectiveLocation.INTERFACE,
        DirectiveLocation.FIELD_DEFINITION,
        DirectiveLocation.ARGUMENT_DEFINITION,
        DirectiveLocation.SCALAR,
        DirectiveLocation.ENUM,
        DirectiveLocation.ENUM_VALUE,
        DirectiveLocation.INPUT_OBJECT,
        DirectiveLocation.INPUT_FIELD_DEFINITION,
        DirectiveLocation.UNION,
    ],
    args={
        "name": GraphQLArgument(
            GraphQLNonNull(GraphQLString),
            description="The tag name",
        ),
    },
)

# @inaccessible directive - marks fields as inaccessible to clients
InaccessibleDirective = GraphQLDirective(
    name="inaccessible",
    description="Marks a field as inaccessible to clients",
    locations=[
        DirectiveLocation.FIELD_DEFINITION,
        DirectiveLocation.OBJECT,
        DirectiveLocation.INTERFACE,
        DirectiveLocation.ARGUMENT_DEFINITION,
        DirectiveLocation.SCALAR,
        DirectiveLocation.ENUM,
        DirectiveLocation.ENUM_VALUE,
        DirectiveLocation.INPUT_OBJECT,
        DirectiveLocation.INPUT_FIELD_DEFINITION,
        DirectiveLocation.UNION,
    ],
    args={},
)

# @shareable directive - marks fields as shareable across services
ShareableDirective = GraphQLDirective(
    name="shareable",
    description="Marks a field as shareable across services",
    locations=[
        DirectiveLocation.FIELD_DEFINITION,
        DirectiveLocation.OBJECT,
    ],
    args={},
)

# Federation directive collections
FEDERATION_DIRECTIVES = [
    KeyDirective,
    ExtendsDirective,
    ExternalDirective,
    RequiresDirective,
    ProvidesDirective,
    TagDirective,
    InaccessibleDirective,
    ShareableDirective,
]

FEDERATION_DIRECTIVE_SPECS = {
    "key": {
        "description": "Specifies the key fields for an entity type",
        "locations": ["OBJECT", "INTERFACE"],
        "args": {
            "fields": {"type": "String!", "description": "The key fields selection set"},
        },
    },
    "extends": {
        "description": "Indicates that this type extends a type from another service",
        "locations": ["OBJECT", "INTERFACE"],
        "args": {},
    },
    "external": {
        "description": "Marks a field as owned by another service",
        "locations": ["FIELD_DEFINITION"],
        "args": {},
    },
    "requires": {
        "description": "Specifies which fields are required from other services",
        "locations": ["FIELD_DEFINITION"],
        "args": {
            "fields": {"type": "String!", "description": "The required fields selection set"},
        },
    },
    "provides": {
        "description": "Specifies which fields this service can provide",
        "locations": ["FIELD_DEFINITION"],
        "args": {
            "fields": {"type": "String!", "description": "The provided fields selection set"},
        },
    },
    "tag": {
        "description": "Adds metadata tags to schema elements",
        "locations": [
            "OBJECT", "INTERFACE", "FIELD_DEFINITION", "ARGUMENT_DEFINITION",
            "SCALAR", "ENUM", "ENUM_VALUE", "INPUT_OBJECT", "INPUT_FIELD_DEFINITION", "UNION",
        ],
        "args": {
            "name": {"type": "String!", "description": "The tag name"},
        },
    },
    "inaccessible": {
        "description": "Marks a field as inaccessible to clients",
        "locations": [
            "FIELD_DEFINITION", "OBJECT", "INTERFACE", "ARGUMENT_DEFINITION",
            "SCALAR", "ENUM", "ENUM_VALUE", "INPUT_OBJECT", "INPUT_FIELD_DEFINITION", "UNION",
        ],
        "args": {},
    },
    "shareable": {
        "description": "Marks a field as shareable across services",
        "locations": ["FIELD_DEFINITION", "OBJECT"],
        "args": {},
    },
}

FEDERATION_DIRECTIVE_NAMES = [
    "key",
    "extends",
    "external",
    "requires",
    "provides",
    "tag",
    "inaccessible",
    "shareable",
]


def get_federation_directives() -> List:
    """Get all federation directives."""
    return FEDERATION_DIRECTIVES


def get_federation_directive_specs() -> Dict[str, Any]:
    """Get federation directive specifications."""
    return FEDERATION_DIRECTIVE_SPECS