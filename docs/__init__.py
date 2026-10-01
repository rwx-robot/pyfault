"""
Documentation Generation for PyFault framework.

Automatic API documentation generation:
- OpenAPI/Swagger spec generation
- Markdown documentation from docstrings
- Architecture Decision Records (ADR)
- Changelog generation
- API reference pages
"""

import asyncio
import inspect
import json
import logging
import os
import re
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, Union

import yaml

from pyfault.common.time import utc_now

warnings.filterwarnings("ignore", category=FutureWarning)

logger = logging.getLogger(__name__)


class DocFormat(str, Enum):
    """Documentation output formats."""
    MARKDOWN = "markdown"
    HTML = "html"
    OPENAPI_JSON = "openapi_json"
    OPENAPI_YAML = "openapi_yaml"
    ADR = "adr"
    CHANGELOG = "changelog"


class DocVisibility(str, Enum):
    """Visibility of documented items."""
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"


@dataclass
class APIDocConfig:
    """Configuration for API documentation generation."""
    title: str = "PyFault API"
    version: str = "1.0.0"
    description: str = "PyFault Framework API Reference"
    base_url: str = "/api/v1"

    # Output
    output_dir: str = "./docs/api"
    formats: list[DocFormat] = field(default_factory=lambda: [DocFormat.MARKDOWN, DocFormat.OPENAPI_YAML])

    # Filtering
    include_private: bool = False
    include_internal: bool = True
    exclude_patterns: list[str] = field(default_factory=lambda: ["_*", "test_*"])

    # Grouping
    group_by_module: bool = True
    group_by_tag: bool = True

    # Examples
    include_examples: bool = True
    example_dir: str = "./examples"

    # Styling
    theme: str = "default"
    custom_css: str = ""


@dataclass
class DocString:
    """Parsed docstring information."""
    summary: str = ""
    description: str = ""
    params: dict[str, dict[str, Any]] = field(default_factory=dict)  # name -> {type, description, default}
    returns: dict[str, str] = field(default_factory=dict)  # type, description
    raises: list[dict[str, str]] = field(default_factory=list)  # exception, condition
    examples: list[str] = field(default_factory=list)
    see_also: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    deprecated: bool = False
    version_added: str = ""
    version_deprecated: str = ""


@dataclass
class EndpointDoc:
    """Documentation for an API endpoint."""
    path: str
    method: str
    summary: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[dict[str, Any]] = field(default_factory=list)  # path, query, header, body
    request_body: Optional[dict[str, Any]] = None
    responses: dict[str, dict[str, Any]] = field(default_factory=dict)  # status -> {description, schema}
    security: list[dict[str, list[str]]] = field(default_factory=list)
    deprecated: bool = False
    examples: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ModuleDoc:
    """Documentation for a module."""
    name: str
    file_path: str
    summary: str = ""
    description: str = ""
    classes: list["ClassDoc"] = field(default_factory=list)
    functions: list["FunctionDoc"] = field(default_factory=list)
    constants: dict[str, Any] = field(default_factory=dict)
    submodules: list[str] = field(default_factory=list)
    version: str = ""
    author: str = ""
    license: str = ""


@dataclass
class ClassDoc:
    """Documentation for a class."""
    name: str
    module: str
    docstring: DocString = field(default_factory=DocString)
    bases: list[str] = field(default_factory=list)
    methods: list["FunctionDoc"] = field(default_factory=list)
    attributes: list[dict[str, Any]] = field(default_factory=list)  # name, type, description
    properties: list[dict[str, Any]] = field(default_factory=list)
    classmethods: list["FunctionDoc"] = field(default_factory=list)
    staticmethods: list["FunctionDoc"] = field(default_factory=list)
    visibility: DocVisibility = DocVisibility.PUBLIC
    abstract: bool = False


@dataclass
class FunctionDoc:
    """Documentation for a function/method."""
    name: str
    module: str
    class_name: str = ""
    docstring: DocString = field(default_factory=DocString)
    signature: str = ""
    parameters: list[dict[str, Any]] = field(default_factory=list)
    return_type: str = ""
    return_description: str = ""
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    is_property: bool = False
    is_classmethod: bool = False
    is_staticmethod: bool = False
    visibility: DocVisibility = DocVisibility.PUBLIC
    overrides: str = ""


@dataclass
class ADR:
    """Architecture Decision Record."""
    id: str
    title: str
    status: str = "proposed"  # proposed, accepted, rejected, deprecated, superseded
    context: str = ""
    decision: str = ""
    consequences: str = ""
    alternatives: list[str] = field(default_factory=list)
    related_adrs: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    author: str = ""

    def to_markdown(self) -> str:
        lines = [
            f"# ADR-{self.id}: {self.title}",
            "",
            f"**Status**: {self.status}",
            f"**Date**: {self.created_at.strftime('%Y-%m-%d')}",
            f"**Author**: {self.author}",
            "",
            "## Context",
            self.context,
            "",
            "## Decision",
            self.decision,
            "",
            "## Consequences",
            self.consequences,
            "",
        ]

        if self.alternatives:
            lines.append("## Alternatives Considered")
            for alt in self.alternatives:
                lines.append(f"- {alt}")
            lines.append("")

        if self.related_adrs:
            lines.append("## Related ADRs")
            for adr in self.related_adrs:
                lines.append(f"- ADR-{adr}")
            lines.append("")

        if self.tags:
            lines.append(f"**Tags**: {', '.join(self.tags)}")

        return "\n".join(lines)


@dataclass
class ChangelogEntry:
    """Single changelog entry."""
    version: str
    date: datetime
    changes: dict[str, list[str]] = field(default_factory=dict)  # category -> [changes]
    breaking_changes: list[str] = field(default_factory=list)
    deprecated: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    security_fixes: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            f"## [{self.version}] - {self.date.strftime('%Y-%m-%d')}",
            "",
        ]

        if self.breaking_changes:
            lines.append("### ⚠️ Breaking Changes")
            for change in self.breaking_changes:
                lines.append(f"- {change}")
            lines.append("")

        for category, changes in self.changes.items():
            if changes:
                lines.append(f"### {category}")
                for change in changes:
                    lines.append(f"- {change}")
                lines.append("")

        if self.deprecated:
            lines.append("### Deprecated")
            for item in self.deprecated:
                lines.append(f"- {item}")
            lines.append("")

        if self.removed:
            lines.append("### Removed")
            for item in self.removed:
                lines.append(f"- {item}")
            lines.append("")

        if self.security_fixes:
            lines.append("### Security Fixes")
            for fix in self.security_fixes:
                lines.append(f"- {fix}")
            lines.append("")

        return "\n".join(lines)


class DocstringParser:
    """Parses docstrings into structured DocString objects."""

    # Regex patterns for different docstring formats
    GOOGLE_PATTERNS = {
        'args': re.compile(r'^\s*Args:\s*\n((?:\s{4,}.*\n)*)', re.MULTILINE),
        'returns': re.compile(r'^\s*Returns:\s*\n((?:\s{4,}.*\n)*)', re.MULTILINE),
        'raises': re.compile(r'^\s*Raises:\s*\n((?:\s{4,}.*\n)*)', re.MULTILINE),
        'yields': re.compile(r'^\s*Yields:\s*\n((?:\s{4,}.*\n)*)', re.MULTILINE),
        'example': re.compile(r'^\s*Example:\s*\n((?:\s{4,}.*\n)*)', re.MULTILINE),
        'attributes': re.compile(r'^\s*Attributes:\s*\n((?:\s{4,}.*\n)*)', re.MULTILINE),
    }

    NUMPY_PATTERNS = {
        'parameters': re.compile(r'^\s*Parameters\s*\n-{10,}\s*\n((?:\s.*\n)*)', re.MULTILINE),
        'returns': re.compile(r'^\s*Returns\s*\n-{10,}\s*\n((?:\s.*\n)*)', re.MULTILINE),
        'raises': re.compile(r'^\s*Raises\s*\n-{10,}\s*\n((?:\s.*\n)*)', re.MULTILINE),
    }

    SPHINX_PATTERNS = {
        'param': re.compile(r':param\s+(\w+):\s*(.*)'),
        'type': re.compile(r':type\s+(\w+):\s*(.*)'),
        'return': re.compile(r':return:\s*(.*)'),
        'rtype': re.compile(r':rtype:\s*(.*)'),
        'raise': re.compile(r':raise\s+(\w+):\s*(.*)'),
    }

    @classmethod
    def parse(cls, docstring: str) -> DocString:
        """Parse a docstring into DocString object."""
        if not docstring:
            return DocString()

        # Try Google style first
        result = cls._parse_google(docstring)
        if result.description or result.params:
            return result

        # Try NumPy style
        result = cls._parse_numpy(docstring)
        if result.description or result.params:
            return result

        # Try Sphinx style
        result = cls._parse_sphinx(docstring)
        if result.description or result.params:
            return result

        # Fallback: simple parsing
        return cls._parse_simple(docstring)

    @classmethod
    def _parse_google(cls, docstring: str) -> DocString:
        lines = docstring.strip().split('\n')
        result = DocString()

        # Extract summary and description
        in_section = False
        current_section = ""
        description_lines = []
        section_content = defaultdict(list)

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check for section headers
            if stripped.endswith(':') and stripped[:-1] in ['Args', 'Returns', 'Raises', 'Yields', 'Example', 'Examples', 'Attributes', 'See Also']:
                in_section = True
                current_section = stripped[:-1].lower()
                continue

            if in_section:
                if line.startswith('    ') or line.startswith('\t'):
                    section_content[current_section].append(line.strip())
                else:
                    in_section = False
                    # Check if this is a new section
                    if stripped.endswith(':') and stripped[:-1] in ['Args', 'Returns', 'Raises', 'Yields', 'Example', 'Examples', 'Attributes', 'See Also']:
                        in_section = True
                        current_section = stripped[:-1].lower()
                        continue

            if not in_section:
                if not result.summary:
                    result.summary = stripped
                else:
                    description_lines.append(stripped)

        result.description = ' '.join(description_lines)

        # Parse params
        for param_line in section_content.get('args', []):
            # Format: param_name (type): description [default: value]
            match = re.match(r'(\w+)\s*(?:\(([^)]+)\))?:\s*(.*?)(?:\s*\[default:\s*([^\]]+)\])?$', param_line)
            if match:
                name, type_hint, desc, default = match.groups()
                result.params[name] = {
                    'type': type_hint or '',
                    'description': desc,
                    'default': default or '',
                }

        # Parse returns
        for ret_line in section_content.get('returns', []):
            match = re.match(r'(?:\(([^)]+)\)\s*)?(.*)', ret_line)
            if match:
                type_hint, desc = match.groups()
                result.returns = {
                    'type': type_hint or '',
                    'description': desc,
                }

        # Parse raises
        for raise_line in section_content.get('raises', []):
            match = re.match(r'(\w+):\s*(.*)', raise_line)
            if match:
                exc_type, condition = match.groups()
                result.raises.append({'exception': exc_type, 'condition': condition})

        # Parse examples
        for ex_line in section_content.get('example', []) + section_content.get('examples', []):
            result.examples.append(ex_line)

        # Parse attributes
        for attr_line in section_content.get('attributes', []):
            match = re.match(r'(\w+)\s*(?:\(([^)]+)\))?:\s*(.*)', attr_line)
            if match:
                name, type_hint, desc = match.groups()
                result.params[name] = {
                    'type': type_hint or '',
                    'description': desc,
                    'is_attribute': True,
                }

        return result

    @classmethod
    def _parse_numpy(cls, docstring: str) -> DocString:
        # Similar to Google but with different section headers
        return cls._parse_google(docstring)  # Simplified

    @classmethod
    def _parse_sphinx(cls, docstring: str) -> DocString:
        result = DocString()
        lines = docstring.strip().split('\n')

        description_lines = []

        for line in lines:
            stripped = line.strip()

            # Check for Sphinx directives
            param_match = cls.SPHINX_PATTERNS['param'].match(stripped)
            if param_match:
                name, desc = param_match.groups()
                result.params[name] = {'description': desc}
                continue

            type_match = cls.SPHINX_PATTERNS['type'].match(stripped)
            if type_match:
                name, type_hint = type_match.groups()
                if name in result.params:
                    result.params[name]['type'] = type_hint
                else:
                    result.params[name] = {'type': type_hint}
                continue

            return_match = cls.SPHINX_PATTERNS['return'].match(stripped)
            if return_match:
                result.returns['description'] = return_match.group(1)
                continue

            rtype_match = cls.SPHINX_PATTERNS['rtype'].match(stripped)
            if rtype_match:
                result.returns['type'] = rtype_match.group(1)
                continue

            raise_match = cls.SPHINX_PATTERNS['raise'].match(stripped)
            if raise_match:
                exc_type, condition = raise_match.groups()
                result.raises.append({'exception': exc_type, 'condition': condition})
                continue

            if not stripped.startswith(':'):
                if not result.summary:
                    result.summary = stripped
                else:
                    description_lines.append(stripped)

        result.description = ' '.join(description_lines)
        return result

    @classmethod
    def _parse_simple(cls, docstring: str) -> DocString:
        """Simple fallback parser."""
        lines = [ln.strip() for ln in docstring.strip().split('\n') if ln.strip()]
        if not lines:
            return DocString()

        result = DocString()
        result.summary = lines[0]
        if len(lines) > 1:
            result.description = ' '.join(lines[1:])
        return result


class APIDocGenerator:
    """Generates API documentation from source code."""

    def __init__(self, config: Optional[APIDocConfig] = None):
        self.config = config or APIDocConfig()
        self.parser = DocstringParser()
        self._modules: dict[str, ModuleDoc] = {}
        self._endpoints: list[EndpointDoc] = []

    def scan_module(self, module_name: str) -> ModuleDoc:
        """Scan a module and generate documentation."""
        import importlib
        import pkgutil

        module = importlib.import_module(module_name)
        module_doc = ModuleDoc(
            name=module_name,
            file_path=getattr(module, '__file__', ''),
            version=getattr(module, '__version__', ''),
            author=getattr(module, '__author__', ''),
            license=getattr(module, '__license__', ''),
        )

        # Parse module docstring
        if module.__doc__:
            parsed = self.parser.parse(module.__doc__)
            module_doc.summary = parsed.summary
            module_doc.description = parsed.description

        # Scan classes and functions
        for name, obj in inspect.getmembers(module):
            if name.startswith('_') and not self.config.include_private:
                continue

            if inspect.isclass(obj) and obj.__module__ == module_name:
                class_doc = self._scan_class(obj, module_name)
                if class_doc.visibility != DocVisibility.PRIVATE or self.config.include_private:
                    module_doc.classes.append(class_doc)

            elif inspect.isfunction(obj) and obj.__module__ == module_name:
                func_doc = self._scan_function(obj, module_name)
                if func_doc.visibility != DocVisibility.PRIVATE or self.config.include_private:
                    module_doc.functions.append(func_doc)

        # Scan submodules
        if hasattr(module, '__path__'):
            for _, submodule_name, _ in pkgutil.iter_modules(module.__path__):
                full_name = f"{module_name}.{submodule_name}"
                if not any(full_name.startswith(p.rstrip('*')) for p in self.config.exclude_patterns):
                    module_doc.submodules.append(full_name)

        self._modules[module_name] = module_doc
        return module_doc

    def _scan_class(self, cls: type, module_name: str) -> ClassDoc:
        doc = ClassDoc(
            name=cls.__name__,
            module=module_name,
            bases=[b.__name__ for b in cls.__bases__ if b is not object],
            abstract=inspect.isabstract(cls),
        )

        # Parse class docstring
        if cls.__doc__:
            doc.docstring = self.parser.parse(cls.__doc__)

        # Determine visibility
        if cls.__name__.startswith('__'):
            doc.visibility = DocVisibility.PRIVATE
        elif cls.__name__.startswith('_'):
            doc.visibility = DocVisibility.INTERNAL

        # Scan methods
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if name.startswith('__') and name != '__init__':
                continue

            method_doc = self._scan_method(cls, method)
            if method_doc.visibility != DocVisibility.PRIVATE:
                if method_doc.is_classmethod:
                    doc.classmethods.append(method_doc)
                elif method_doc.is_staticmethod:
                    doc.staticmethods.append(method_doc)
                elif method_doc.is_property:
                    doc.properties.append({
                        'name': method_doc.name,
                        'type': method_doc.return_type,
                        'description': method_doc.docstring.description,
                    })
                else:
                    doc.methods.append(method_doc)

        # Scan attributes
        for name, value in inspect.getmembers(cls):
            if (
                not name.startswith('_')
                and not inspect.isfunction(value)
                and not inspect.ismethod(value)
                and not isinstance(value, (classmethod, staticmethod, property))
            ):
                doc.attributes.append({
                        'name': name,
                        'type': type(value).__name__,
                        'value': repr(value)[:100],
                    })

        return doc

    def _scan_method(self, cls: type, method: Callable) -> FunctionDoc:
        doc = FunctionDoc(
            name=method.__name__,
            module=method.__module__,
            class_name=cls.__name__,
        )

        # Get signature
        sig = inspect.signature(method)
        doc.signature = str(sig)

        # Check decorators
        doc.decorators = getattr(method, '__wrapped__', [])
        doc.is_async = inspect.iscoroutinefunction(method)

        # Check for special decorators
        if isinstance(getattr(cls, method.__name__, None), classmethod):
            doc.is_classmethod = True
        elif isinstance(getattr(cls, method.__name__, None), staticmethod):
            doc.is_staticmethod = True
        elif isinstance(getattr(cls, method.__name__, None), property):
            doc.is_property = True

        # Parse docstring
        if method.__doc__:
            doc.docstring = self.parser.parse(method.__doc__)

        # Parse parameters
        sig = inspect.signature(method)
        for param_name, param in sig.parameters.items():
            if param_name == 'self' or param_name == 'cls':
                continue

            param_info = {
                'name': param_name,
                'type': str(param.annotation) if param.annotation != inspect.Parameter.empty else '',
                'default': str(param.default) if param.default != inspect.Parameter.empty else '',
                'required': param.default == inspect.Parameter.empty,
            }
            doc.parameters.append(param_info)

        # Return type
        if sig.return_annotation != inspect.Signature.empty:
            doc.return_type = str(sig.return_annotation)

        # Return description from docstring
        if doc.docstring.returns:
            doc.return_description = doc.docstring.returns.get('description', '')

        # Visibility
        if method.__name__.startswith('__'):
            doc.visibility = DocVisibility.PRIVATE
        elif method.__name__.startswith('_'):
            doc.visibility = DocVisibility.INTERNAL

        return doc

    def _scan_function(self, func: Callable, module_name: str) -> FunctionDoc:
        doc = FunctionDoc(
            name=func.__name__,
            module=module_name,
        )

        sig = inspect.signature(func)
        doc.signature = str(sig)
        doc.is_async = inspect.iscoroutinefunction(func)

        if func.__doc__:
            doc.docstring = self.parser.parse(func.__doc__)

        for param_name, param in sig.parameters.items():
            param_info = {
                'name': param_name,
                'type': str(param.annotation) if param.annotation != inspect.Parameter.empty else '',
                'default': str(param.default) if param.default != inspect.Parameter.empty else '',
                'required': param.default == inspect.Parameter.empty,
            }
            doc.parameters.append(param_info)

        if sig.return_annotation != inspect.Signature.empty:
            doc.return_type = str(sig.return_annotation)

        if func.__doc__:
            doc.docstring = self.parser.parse(func.__doc__)

        if func.__name__.startswith('_'):
            doc.visibility = DocVisibility.INTERNAL

        return doc

    def scan_endpoints(self, app: Any) -> list[EndpointDoc]:
        """Scan FastAPI/Starlette app for endpoints."""
        endpoints = []

        for route in app.routes:
            if hasattr(route, 'methods') and hasattr(route, 'path'):
                for method in route.methods:
                    if method == 'HEAD':
                        continue

                    endpoint = EndpointDoc(
                        path=route.path,
                        method=method,
                    )

                    # Get endpoint function
                    if hasattr(route, 'endpoint'):
                        func = route.endpoint
                        if func.__doc__:
                            parsed = self.parser.parse(func.__doc__)
                            endpoint.summary = parsed.summary
                            endpoint.description = parsed.description

                        # Parameters from path
                        import re
                        path_params = re.findall(r'{(\w+)}', route.path)
                        for param in path_params:
                            endpoint.parameters.append({
                                'name': param,
                                'in': 'path',
                                'required': True,
                                'schema': {'type': 'string'},
                            })

                        # Query parameters from signature
                        sig = inspect.signature(route.endpoint)
                        for name, param in sig.parameters.items():
                            if name in ['request', 'response', 'background_tasks']:
                                continue
                            if param.name in path_params:
                                continue

                            param_info = {
                                'name': param.name,
                                'in': 'query',
                                'required': param.default == inspect.Parameter.empty,
                                'schema': {'type': 'string'},  # Would need type mapping
                            }
                            if param.default != inspect.Parameter.empty:
                                param_info['default'] = param.default
                            endpoint.parameters.append(param_info)

                        # Responses
                        endpoint.responses = {
                            '200': {'description': 'Successful response'},
                            '422': {'description': 'Validation error'},
                        }

                        endpoints.append(endpoint)

        self._endpoints = endpoints
        return endpoints

    def generate_openapi(self, app: Any) -> dict[str, Any]:
        """Generate OpenAPI specification."""
        self.scan_endpoints(app)

        spec: dict[str, Any] = {
            "openapi": "3.0.3",
            "info": {
                "title": self.config.title,
                "version": self.config.version,
                "description": self.config.description,
            },
            "servers": [{"url": self.config.base_url}],
            "paths": {},
            "components": {
                "schemas": {},
                "securitySchemes": {},
            },
            "tags": [],
        }

        # Group endpoints by path
        paths: dict[str, dict[str, Any]] = defaultdict(dict)
        for endpoint in self._endpoints:
            if endpoint.path not in paths:
                paths[endpoint.path] = {}

            params = []
            for param in endpoint.parameters:
                params.append({
                    "name": param['name'],
                    "in": param['in'],
                    "required": param.get('required', False),
                    "schema": param.get('schema', {'type': 'string'}),
                    "description": param.get('description', ''),
                })

            responses = {}
            for status, resp in endpoint.responses.items():
                responses[status] = {
                    "description": resp.get('description', ''),
                    "content": resp.get('content', {}),
                }

            paths[endpoint.path][endpoint.method.lower()] = {
                "summary": endpoint.summary,
                "description": endpoint.description,
                "tags": endpoint.tags,
                "parameters": params,
                "responses": responses,
                "deprecated": endpoint.deprecated,
                "security": endpoint.security,
            }

            if endpoint.tags:
                for tag in endpoint.tags:
                    if tag not in [t['name'] for t in spec['tags']]:
                        spec['tags'].append({'name': tag, 'description': ''})

        spec['paths'] = dict(paths)
        return spec

    def generate_markdown(self) -> str:
        """Generate Markdown documentation."""
        lines = [
            f"# {self.config.title}",
            f"Version: {self.config.version}",
            f"{self.config.description}",
            "",
            "---",
            "",
        ]

        for module_name, module_doc in self._modules.items():
            lines.append(f"# Module: {module_name}")
            lines.append("")

            if module_doc.summary:
                lines.append(module_doc.summary)
            if module_doc.description:
                lines.append(module_doc.description)
            lines.append("")

            # Classes
            for class_doc in module_doc.classes:
                lines.append(f"## Class: {class_doc.name}")
                if class_doc.docstring.summary:
                    lines.append(class_doc.docstring.summary)
                if class_doc.docstring.description:
                    lines.append(class_doc.docstring.description)
                lines.append("")

                # Methods
                for method in class_doc.methods:
                    lines.append(f"### {method.name}{method.signature}")
                    if method.docstring.summary:
                        lines.append(method.docstring.summary)

                    if method.parameters:
                        lines.append("**Parameters:**")
                        for param in method.parameters:
                            req = " (required)" if param.get('required') else " (optional)"
                            default = f" = {param['default']}" if param.get('default') else ""
                            lines.append(f"- `{param['name']}`{req}{default}: {param.get('type', '')} - {method.docstring.params.get(param['name'], {}).get('description', '')}")

                    if method.docstring.returns:
                        lines.append(f"**Returns:** `{method.docstring.returns.get('type', '')}` - {method.docstring.returns.get('description', '')}")

                    lines.append("")

        return '\n'.join(lines)

    def write_output(self, output_dir: Optional[str] = None) -> None:
        """Write documentation to output directory."""
        out_dir = Path(output_dir or self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # Generate markdown
        if DocFormat.MARKDOWN in self.config.formats:
            md = self.generate_markdown()
            (out_dir / "API_REFERENCE.md").write_text(md)

        # Generate OpenAPI
        if DocFormat.OPENAPI_JSON in self.config.formats or DocFormat.OPENAPI_YAML in self.config.formats:
            # Would need app instance
            pass

        logger.info(f"Documentation written to {out_dir}")


class ADRManager:
    """Manages Architecture Decision Records."""

    def __init__(self, adr_dir: str = "./docs/adr"):
        self.adr_dir = Path(adr_dir)
        self.adr_dir.mkdir(parents=True, exist_ok=True)
        self._adrs: dict[str, ADR] = {}
        self._load_adrs()

    def _load_adrs(self) -> None:
        for file in self.adr_dir.glob("*.md"):
            try:
                content = file.read_text()
                # Parse ADR from markdown
                adr = self._parse_adr(content)
                if adr:
                    self._adrs[adr.id] = adr
            except Exception as e:
                logger.error(f"Failed to load ADR {file}: {e}")

    def _parse_adr(self, content: str) -> Optional[ADR]:
        lines = content.split('\n')

        # Extract ID from title
        id_match = re.match(r'#\s*ADR-(\d+):\s*(.*)', lines[0]) if lines else None
        if not id_match:
            return None

        adr_id, title = id_match.groups()

        # Simple parsing
        adr = ADR(
            id=adr_id,
            title=title,
        )

        current_section = ""
        section_content = defaultdict(list)

        for line in lines[1:]:
            if line.startswith('## '):
                current_section = line[3:].strip().lower()
            elif current_section:
                section_content[current_section].append(line)

        adr.context = '\n'.join(section_content.get('context', [])).strip()
        adr.decision = '\n'.join(section_content.get('decision', [])).strip()
        adr.consequences = '\n'.join(section_content.get('consequences', [])).strip()

        if 'alternatives considered' in section_content:
            for alt in section_content['alternatives considered']:
                if alt.strip().startswith('- '):
                    adr.alternatives.append(alt.strip()[2:])

        if 'related adrs' in section_content:
            for rel in section_content['related adrs']:
                if rel.strip().startswith('- '):
                    adr.related_adrs.append(rel.strip()[2:])

        return adr

    def create_adr(
        self,
        title: str,
        context: str,
        decision: str,
        consequences: str,
        alternatives: Optional[list[str]] = None,
        related_adrs: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        author: str = "",
    ) -> ADR:
        # Find next ID
        existing_ids = [int(a.id) for a in self._adrs.values() if a.id.isdigit()]
        next_id = str(max(existing_ids) + 1) if existing_ids else "1"

        adr = ADR(
            id=next_id,
            title=title,
            context=context,
            decision=decision,
            consequences=consequences,
            alternatives=alternatives or [],
            related_adrs=related_adrs or [],
            tags=tags or [],
            author=author,
        )

        self._adrs[adr.id] = adr
        self._save_adr(adr)
        return adr

    def _save_adr(self, adr: ADR) -> None:
        filename = f"ADR-{adr.id.zfill(4)}-{adr.title.lower().replace(' ', '-')}.md"
        filepath = self.adr_dir / filename
        filepath.write_text(adr.to_markdown())

    def get_adr(self, adr_id: str) -> Optional[ADR]:
        return self._adrs.get(adr_id)

    def list_adrs(self, status: Optional[str] = None) -> list[ADR]:
        adrs = list(self._adrs.values())
        if status:
            adrs = [a for a in adrs if a.status == status]
        return sorted(adrs, key=lambda a: int(a.id) if a.id.isdigit() else 0)

    def update_adr_status(self, adr_id: str, status: str) -> bool:
        if adr_id in self._adrs:
            self._adrs[adr_id].status = status
            self._adrs[adr_id].updated_at = utc_now()
            self._save_adr(self._adrs[adr_id])
            return True
        return False

    def get_adr_index(self) -> str:
        """Generate ADR index markdown."""
        lines = [
            "# Architecture Decision Records Index",
            "",
            "| ID | Title | Status | Date | Tags |",
            "|----|-------|--------|------|------|",
        ]

        for adr in self.list_adrs():
            tags = ', '.join(adr.tags) if adr.tags else ''
            lines.append(f"| {adr.id} | [{adr.title}](ADR-{adr.id.zfill(4)}-{adr.title.lower().replace(' ', '-')}.md) | {adr.status} | {adr.created_at.strftime('%Y-%m-%d')} | {tags} |")

        return '\n'.join(lines)


class ChangelogGenerator:
    """Generates changelog from git history or manual entries."""

    def __init__(self, changelog_path: str = "./CHANGELOG.md"):
        self.changelog_path = Path(changelog_path)
        self._entries: list[ChangelogEntry] = []
        self._load_changelog()

    def _load_changelog(self) -> None:
        if not self.changelog_path.exists():
            return

        _content = self.changelog_path.read_text()
        # Parse existing changelog (simplified)
        # Would need proper parsing for real use

    def add_entry(
        self,
        version: str,
        changes: Optional[dict[str, list[str]]] = None,
        breaking_changes: Optional[list[str]] = None,
        deprecated: Optional[list[str]] = None,
        removed: Optional[list[str]] = None,
        security_fixes: Optional[list[str]] = None,
        date: Optional[datetime] = None,
    ) -> ChangelogEntry:
        entry = ChangelogEntry(
            version=version,
            date=date or utc_now(),
            changes=changes or {},
            breaking_changes=breaking_changes or [],
            deprecated=deprecated or [],
            removed=removed or [],
            security_fixes=security_fixes or [],
        )

        self._entries.insert(0, entry)
        return entry

    def add_changes(self, version: str, category: str, changes: list[str]) -> None:
        # Find or create entry
        entry = next((e for e in self._entries if e.version == version), None)
        if not entry:
            entry = ChangelogEntry(version=version, date=utc_now())
            self._entries.insert(0, entry)

        if category not in entry.changes:
            entry.changes[category] = []
        entry.changes[category].extend(changes)

    def generate(self) -> str:
        lines = [
            "# Changelog",
            "",
            "All notable changes to this project will be documented in this file.",
            "",
            "The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),",
            "and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).",
            "",
        ]

        for entry in self._entries:
            lines.append(entry.to_markdown())

        return '\n'.join(lines)

    def save(self) -> None:
        content = self.generate()
        self.changelog_path.write_text(content)


class DocGenerator:
    """Main documentation generator orchestrating all generators."""

    def __init__(self, config: Optional[APIDocConfig] = None):
        self.config = config or APIDocConfig()
        self.api_generator = APIDocGenerator(config)
        self.adr_manager = ADRManager()
        self.changelog = ChangelogGenerator()

    def generate_all(
        self,
        modules: Optional[list[str]] = None,
        app: Any = None,
    ) -> dict[str, str]:
        """Generate all documentation."""
        results = {}

        # Scan modules
        if modules:
            for module in modules:
                self.api_generator.scan_module(module)

        # Generate API docs
        results['api_reference'] = self.api_generator.generate_markdown()

        # ADR index
        results['adr_index'] = self.adr_manager.get_adr_index()

        # Changelog
        results['changelog'] = self.changelog.generate()

        return results

    def write_all(self, output_dir: Optional[str] = None) -> None:
        out_dir = Path(output_dir or self.config.output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        # API Reference
        if DocFormat.MARKDOWN in self.config.formats:
            (out_dir / "API_REFERENCE.md").write_text(self.api_generator.generate_markdown())

        # ADR Index
        (out_dir / "adr" / "INDEX.md").write_text(self.adr_manager.get_adr_index())

        # Changelog
        (out_dir / "CHANGELOG.md").write_text(self.changelog.generate())

        logger.info(f"All documentation written to {out_dir}")


# Convenience functions
def generate_api_docs(
    modules: list[str],
    output_dir: str = "./docs/api",
    config: Optional[APIDocConfig] = None,
) -> dict[str, Any]:
    """Generate API documentation for modules."""
    config = config or APIDocConfig(output_dir=output_dir)
    generator = APIDocGenerator(config)

    for module in modules:
        generator.scan_module(module)

    return {
        "markdown": generator.generate_markdown(),
        "modules": list(generator._modules.keys()),
    }


def create_adr(
    title: str,
    context: str,
    decision: str,
    consequences: str,
    adr_dir: str = "./docs/adr",
    **kwargs: Any
) -> ADR:
    """Create a new ADR."""
    manager = ADRManager(adr_dir)
    return manager.create_adr(title, **{"context": context, "decision": decision, "consequences": consequences, **kwargs})


def init_changelog(path: str = "./CHANGELOG.md") -> ChangelogGenerator:
    """Initialize changelog."""
    return ChangelogGenerator(path)


__all__ = [
    "DocFormat",
    "DocVisibility",
    "APIDocConfig",
    "DocString",
    "EndpointDoc",
    "ModuleDoc",
    "ClassDoc",
    "FunctionDoc",
    "DocstringParser",
    "APIDocGenerator",
    "ADR",
    "ADRManager",
    "ChangelogEntry",
    "ChangelogGenerator",
    "DocGenerator",
    "generate_api_docs",
    "create_adr",
    "init_changelog",
]
