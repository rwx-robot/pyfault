"""
OpenAPI Generator for PyFault framework - auto-generates from routes.
"""

import inspect
from typing import Any

from pyfault.common.openapi.decorators import get_openapi_doc, init_openapi
from pyfault.common.openapi.schema import (
    Components,
    OpenAPISchema,
    Operation,
    Parameter,
    PathItem,
    Response,
    SecurityScheme,
)
from pyfault.core.scanner import MetadataKeys, MetadataScanner


class OpenAPIGenerator:
    """Auto-generates OpenAPI documentation from PyFault routes."""

    def __init__(self, app_factory: Any = None):
        self.app_factory = app_factory
        self.scanner = MetadataScanner()

    def generate(self, title: str = "PyFault API", version: str = "1.0.0") -> OpenAPISchema:
        """Generate OpenAPI document from registered routes."""
        global _openapi_doc

        # Initialize OpenAPI document
        init_openapi(title, version)
        doc = get_openapi_doc()
        if doc is None:
            raise RuntimeError("OpenAPI document is not initialized")

        if self.app_factory and hasattr(self.app_factory, 'container'):
            # Generate from registered controllers
            self._generate_from_controllers(doc)
        else:
            # Generate from scanner metadata
            self._generate_from_scanner(doc)

        # Add security schemes
        self._add_security_schemes(doc)

        return doc

    def _generate_from_scanner(self, doc: OpenAPISchema) -> None:
        """Generate from metadata scanner."""
        # This would scan all modules for controllers and routes
        pass

    def _generate_from_controllers(self, doc: OpenAPISchema) -> None:
        """Generate from registered controllers in container."""
        # This would inspect the container for controllers
        pass

    def generate_from_module(self, module_class: type, title: str = "PyFault API", version: str = "1.0.0") -> OpenAPISchema:
        """Generate OpenAPI document from a module class."""
        global _openapi_doc

        init_openapi(title, version)
        doc = get_openapi_doc()
        if doc is None:
            raise RuntimeError("OpenAPI document is not initialized")

        # Get module config
        module_config = self.scanner.get_metadata(module_class, MetadataKeys.MODULE)
        if module_config:
            controllers = module_config.get('controllers', [])

            for controller_class in controllers:
                self._generate_from_controller(doc, controller_class)

            # Collect schemas from all classes in module
            self._collect_schemas(doc, module_class)

        self._add_security_schemes(doc)
        return doc

    def _generate_from_controller(self, doc: OpenAPISchema, controller_class: type) -> None:
        """Generate OpenAPI paths from a controller class."""
        # Get prefix
        prefix = self.scanner.get_metadata(controller_class, MetadataKeys.PREFIX) or ''

        # Get routes from scanner (includes method-level routes)
        routes = self.scanner.get_routes(controller_class)

        for route in routes:
            path = route.get('path', '')
            method = route.get('method', 'GET').lower()

            # Find the handler method
            handler = self._find_handler_method(controller_class, route)

            # Build full path with prefix
            full_path = prefix + path

            # Get OpenAPI metadata from handler
            openapi_meta = getattr(handler, '__openapi__', {}) if handler else {}

            # Create operation
            operation = Operation(
                tags=openapi_meta.get('tags', [controller_class.__name__]),
                summary=openapi_meta.get('summary', ''),
                description=openapi_meta.get('description', ''),
                operation_id=openapi_meta.get('operation_id', f"{controller_class.__name__}.{handler.__name__}" if handler else ""),
                parameters=self._extract_parameters(path, handler),
                request_body=openapi_meta.get('request_body'),
                responses=openapi_meta.get('responses', {
                    "200": Response(description="Successful response"),
                }),
                security=openapi_meta.get('security', []),
                deprecated=openapi_meta.get('deprecated', False),
            )

            # Add to path
            if full_path not in doc.paths:
                doc.paths[full_path] = PathItem()

            path_item = doc.paths[full_path]
            setattr(path_item, method, operation)

    def _find_handler_method(self, controller_class: type, route: dict) -> Any:
        """Find the handler method for a route."""
        method_name = route.get('method', 'GET').lower()
        path = route.get('path', '')

        for attr_name in dir(controller_class):
            attr = getattr(controller_class, attr_name)
            if callable(attr) and hasattr(attr, '__routes__'):
                method_routes = attr.__routes__
                for r in method_routes:
                    if r.get('path') == path and r.get('method', '').lower() == method_name:
                        return attr
        return None

    def _collect_schemas(self, doc: OpenAPISchema, module_class: type) -> None:
        """Collect schema definitions from classes in module."""
        if doc.components is None:
            doc.components = Components()

        # Get module config
        module_config = self.scanner.get_metadata(module_class, MetadataKeys.MODULE)
        if module_config:
            # Check controllers, providers for schema classes
            for cls_list in [module_config.get('controllers', []), module_config.get('providers', [])]:
                for cls in cls_list:
                    self._collect_class_schema(doc, cls)

            # Also check imports recursively
            for imported_module in module_config.get('imports', []):
                self._collect_schemas(doc, imported_module)

    def _collect_class_schema(self, doc: OpenAPISchema, cls: type) -> None:
        """Collect schema from a class if it has @schema decorator."""
        schema_name = getattr(cls, '__openapi_schema__', None)
        if schema_name:
            annotations = getattr(cls, '__annotations__', {})
            properties = {}
            required = []

            for field_name, field_type in annotations.items():
                prop_schema = self._param_type_to_schema(field_type)
                properties[field_name] = prop_schema

                # Check if required (no default value)
                if not hasattr(cls, field_name):
                    required.append(field_name)

            schema_dict = {
                "type": "object",
                "properties": properties,
            }

            if required:
                schema_dict["required"] = required

            if doc.components is None:
                doc.components = Components()
            doc.components.schemas[schema_name] = schema_dict

    def _extract_parameters(self, path: str, handler: Any) -> list[Parameter]:
        """Extract path and query parameters from route."""
        parameters: list[Parameter] = []

        if handler is None:
            return parameters

        sig = inspect.signature(handler)

        # Extract path parameters from path template
        path_params = self._extract_path_params(path)

        for param_name, param in sig.parameters.items():
            if param_name in ('self', 'request', 'body'):
                continue

            # Determine parameter location
            if param_name in path_params:
                param_in = "path"
                required = True
            else:
                param_in = "query"
                required = param.default == inspect.Parameter.empty

            # Convert type annotation to schema
            schema = self._param_type_to_schema(param.annotation)

            param_obj = Parameter(
                name=param_name,
                in_=param_in,
                required=required,
                schema=schema,
            )
            parameters.append(param_obj)

        return parameters

    def _extract_path_params(self, path: str) -> list[str]:
        """Extract parameter names from path template."""
        import re
        return re.findall(r'\{(\w+)\}', path)

    def _param_type_to_schema(self, annotation: Any) -> dict[str, Any]:
        """Convert Python type annotation to OpenAPI schema."""
        if annotation == inspect.Parameter.empty:
            return {"type": "string"}

        if annotation is str:
            return {"type": "string"}
        elif annotation is int:
            return {"type": "integer"}
        elif annotation is float:
            return {"type": "number"}
        elif annotation is bool:
            return {"type": "boolean"}
        elif annotation is list:
            return {"type": "array", "items": {"type": "string"}}

        # Handle Optional
        if hasattr(annotation, '__origin__'):
            from typing import Optional
            if annotation.__origin__ is Optional:
                args = annotation.__args__
                non_none = [a for a in args if a is not type(None)]
                if non_none:
                    return self._param_type_to_schema(non_none[0])
            elif annotation.__origin__ is list:
                args = annotation.__args__
                if args:
                    return {"type": "array", "items": self._param_type_to_schema(args[0])}

        return {"type": "string"}

    def _add_security_schemes(self, doc: OpenAPISchema) -> None:
        """Add default security schemes."""
        if doc.components is None:
            doc.components = Components()

        # Bearer token (JWT)
        doc.components.security_schemes["bearerAuth"] = SecurityScheme(
            type="http",
            scheme="bearer",
            bearer_format="JWT",
            description="JWT Authorization header"
        )

        # API Key
        doc.components.security_schemes["apiKeyAuth"] = SecurityScheme(
            type="apiKey",
            description="API Key in header"
        )

    def save_json(self, filepath: str) -> None:
        """Save OpenAPI document as JSON."""
        import json
        doc = get_openapi_doc()
        if doc:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(doc.to_dict(), f, indent=2, ensure_ascii=False)

    def save_yaml(self, filepath: str) -> None:
        """Save OpenAPI document as YAML."""
        try:
            import yaml
            doc = get_openapi_doc()
            if doc:
                with open(filepath, 'w', encoding='utf-8') as f:
                    yaml.dump(doc.to_dict(), f, allow_unicode=True, sort_keys=False)
        except ImportError:
            self.save_json(filepath.replace('.yaml', '.json').replace('.yml', '.json'))


_openapi_doc = None
