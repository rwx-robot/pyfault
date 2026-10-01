"""
Plugin Dependency Resolution for PyFault AI framework.

Provides dependency management for AI plugins:
- Dependency graph construction
- Version constraint solving
- Circular dependency detection
- Installation order calculation
- Conflict resolution
- Lock file generation
"""

import asyncio
import hashlib
import json
import logging
import uuid
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional, cast

from pyfault.common.time import utc_now

logger = logging.getLogger(__name__)


class DependencyType(str, Enum):
    """Dependency types."""
    REQUIRED = "required"
    OPTIONAL = "optional"
    DEVELOPMENT = "development"
    PEER = "peer"  # Must be provided by host
    BUNDLED = "bundled"  # Included with plugin


class VersionConstraint(str, Enum):
    """Version constraint operators."""
    EXACT = "=="
    MINIMUM = ">="
    MAXIMUM = "<="
    COMPATIBLE = "~="  # Compatible release (PEP 440)
    ANY = "*"


@dataclass
class VersionSpec:
    """Version specification with constraint."""
    constraint: VersionConstraint = VersionConstraint.ANY
    version: str = ""

    def __str__(self) -> str:
        if self.constraint == VersionConstraint.ANY:
            return "*"
        return f"{self.constraint.value}{self.version}"

    @classmethod
    def parse(cls, spec: str) -> "VersionSpec":
        """Parse version spec string (e.g., '>=1.0.0', '~=2.0', '*')."""
        spec = spec.strip()

        if spec == "*" or spec == "":
            return cls(VersionConstraint.ANY, "")

        for constraint in VersionConstraint:
            if spec.startswith(constraint.value):
                version = spec[len(constraint.value):].strip()
                return cls(constraint, version)

        # Default to exact
        return cls(VersionConstraint.EXACT, spec)

    def matches(self, version: str) -> bool:
        """Check if a version satisfies this constraint."""
        if self.constraint == VersionConstraint.ANY:
            return True

        try:
            from packaging import version as pkg_version
            v = pkg_version.parse(version)
            constraint_version = pkg_version.parse(self.version)
        except ImportError:
            # Fallback to string comparison
            return self._string_matches(version)
        except Exception:
            return False

        if self.constraint == VersionConstraint.EXACT:
            return v == constraint_version
        elif self.constraint == VersionConstraint.MINIMUM:
            return v >= constraint_version
        elif self.constraint == VersionConstraint.MAXIMUM:
            return v <= constraint_version
        else:  # COMPATIBLE
            # PEP 440 compatible release: ~=X.Y(.Z) -> >=X.Y(.Z), ==X.Y.*
            # (major-only comparison wrongly allowed ~=2.1.3 to match
            # 2.5.0; packaging's SpecifierSet rejects that pair).
            prefix = constraint_version.release[:-1]
            if not prefix:  # degenerate ~=2 form; PEP 440 forbids it
                return v >= constraint_version
            return (
                v >= constraint_version
                and tuple(v.release[:len(prefix)]) == prefix
            )

    def _string_matches(self, version: str) -> bool:
        """Simple string-based version matching."""
        if self.constraint == VersionConstraint.EXACT:
            return version == self.version
        elif self.constraint == VersionConstraint.MINIMUM:
            return version >= self.version
        elif self.constraint == VersionConstraint.MAXIMUM:
            return version <= self.version
        return True


@dataclass
class PluginDependency:
    """Plugin dependency declaration."""
    plugin_id: str
    name: str = ""
    version_spec: VersionSpec = field(default_factory=VersionSpec)
    dep_type: DependencyType = DependencyType.REQUIRED
    extras: list[str] = field(default_factory=list)
    conditions: dict[str, Any] = field(default_factory=dict)  # e.g., {"python_version": ">=3.8"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version_spec": str(self.version_spec),
            "dep_type": self.dep_type.value,
            "extras": self.extras,
            "conditions": self.conditions,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginDependency":
        return cls(
            plugin_id=data["plugin_id"],
            name=data.get("name", ""),
            version_spec=VersionSpec.parse(data.get("version_spec", "*")),
            dep_type=DependencyType(data.get("dep_type", "required")),
            extras=data.get("extras", []),
            conditions=data.get("conditions", {}),
        )


@dataclass
class PluginManifest:
    """Plugin manifest with dependencies."""
    plugin_id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    license: str = "MIT"
    homepage: str = ""
    repository: str = ""
    documentation: str = ""
    entry_point: str = "main"

    dependencies: list[PluginDependency] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)  # Capabilities provided
    requires: list[str] = field(default_factory=list)  # Capabilities required

    python_requires: str = ">=3.8"
    platform: list[str] = field(default_factory=list)

    config_schema: dict[str, Any] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)

    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "homepage": self.homepage,
            "repository": self.repository,
            "documentation": self.documentation,
            "entry_point": self.entry_point,
            "dependencies": [d.to_dict() for d in self.dependencies],
            "provides": self.provides,
            "requires": self.requires,
            "python_requires": self.python_requires,
            "platform": self.platform,
            "config_schema": self.config_schema,
            "permissions": self.permissions,
        }


class DependencyGraph:
    """
    Dependency graph for plugins.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, PluginManifest] = {}
        self._edges: dict[str, set[str]] = defaultdict(set)  # plugin_id -> set of dependency plugin_ids
        self._reverse_edges: dict[str, set[str]] = defaultdict(set)  # plugin_id -> set of dependents

    def add_plugin(self, manifest: PluginManifest) -> None:
        self._nodes[manifest.plugin_id] = manifest

        # Rebuild outgoing edges: re-adding a manifest (e.g. an updated
        # version of the same plugin) must drop edges left behind by the
        # previous one — otherwise removed dependencies linger forever.
        for dep_id in self._edges.pop(manifest.plugin_id, set()):
            self._reverse_edges[dep_id].discard(manifest.plugin_id)
        self._edges[manifest.plugin_id] = set()
        self._reverse_edges.setdefault(manifest.plugin_id, set())

        # Add dependency edges
        for dep in manifest.dependencies:
            if dep.dep_type in (DependencyType.REQUIRED, DependencyType.OPTIONAL):
                self._edges[manifest.plugin_id].add(dep.plugin_id)
                self._reverse_edges[dep.plugin_id].add(manifest.plugin_id)

    def remove_plugin(self, plugin_id: str) -> bool:
        if plugin_id not in self._nodes:
            return False

        # Remove edges
        for dep_id in self._edges.get(plugin_id, set()):
            self._reverse_edges[dep_id].discard(plugin_id)
        for dependent_id in self._reverse_edges.get(plugin_id, set()):
            self._edges[dependent_id].discard(plugin_id)

        del self._nodes[plugin_id]
        del self._edges[plugin_id]
        del self._reverse_edges[plugin_id]

        return True

    def get_dependencies(self, plugin_id: str) -> set[str]:
        return self._edges.get(plugin_id, set())

    def get_dependents(self, plugin_id: str) -> set[str]:
        return self._reverse_edges.get(plugin_id, set())

    def get_all_plugins(self) -> list[PluginManifest]:
        return list(self._nodes.values())

    def has_plugin(self, plugin_id: str) -> bool:
        return plugin_id in self._nodes

    def get_plugin(self, plugin_id: str) -> Optional[PluginManifest]:
        return self._nodes.get(plugin_id)


class DependencyResolver:
    """
    Resolves plugin dependencies and determines installation order.
    """

    def __init__(self, graph: DependencyGraph):
        self.graph = graph
        self._available_versions: dict[str, list[str]] = defaultdict(list)

    def register_available_version(self, plugin_id: str, version: str) -> None:
        """Register an available version for a plugin."""
        if version not in self._available_versions[plugin_id]:
            self._available_versions[plugin_id].append(version)
            # Sort versions (newest first)
            try:
                from packaging import version as pkg_version
                self._available_versions[plugin_id].sort(
                    key=lambda v: pkg_version.parse(v), reverse=True
                )
            except ImportError:
                self._available_versions[plugin_id].sort(reverse=True)

    def resolve(
        self,
        root_plugin_id: str,
        target_version: Optional[str] = None,
        include_optional: bool = True,
        include_dev: bool = False,
    ) -> "ResolutionResult":
        """Resolve all dependencies for a plugin."""
        errors = []
        warnings: list[str] = []
        resolved: dict[str, PluginManifest] = {}
        install_order: list[str] = []

        # Check if root plugin exists
        root = self.graph.get_plugin(root_plugin_id)
        if not root:
            errors.append(f"Root plugin not found: {root_plugin_id}")
            return ResolutionResult(
                success=False,
                errors=errors,
                warnings=warnings,
            )

        # Check version if specified
        if target_version and root.version != target_version:
            # Would need version registry - simplified
            pass

        # Perform DFS resolution
        visited = set()
        visiting = set()

        def visit(plugin_id: str, path: list[str]) -> bool:
            if plugin_id in visited:
                return True

            if plugin_id in visiting:
                # Circular dependency
                cycle = path[path.index(plugin_id):] + [plugin_id]
                errors.append(f"Circular dependency detected: {' -> '.join(cycle)}")
                return False

            visiting.add(plugin_id)
            path.append(plugin_id)

            plugin = self.graph.get_plugin(plugin_id)
            if not plugin:
                errors.append(f"Plugin not found: {plugin_id}")
                visiting.remove(plugin_id)
                path.pop()
                return False

            # Check version constraints for dependencies
            for dep in plugin.dependencies:
                if dep.dep_type == DependencyType.REQUIRED:
                    if not self._check_dependency(dep):
                        errors.append(f"Unmet dependency: {plugin.plugin_id} -> {dep.plugin_id} {dep.version_spec}")
                        visiting.remove(plugin_id)
                        path.pop()
                        return False
                elif dep.dep_type == DependencyType.OPTIONAL and include_optional and not self._check_dependency(dep):
                    warnings.append(f"Optional dependency not met: {plugin.plugin_id} -> {dep.plugin_id}")
                elif dep.dep_type == DependencyType.DEVELOPMENT and include_dev and not self._check_dependency(dep):
                    warnings.append(f"Dev dependency not met: {plugin.plugin_id} -> {dep.plugin_id}")

            # Visit dependencies. Type-aware traversal (graph edges cannot
            # express the include_optional / include_dev flags):
            # - optional deps that failed the version check above only warn;
            #   visiting them anyway used to hard-fail resolve() with
            #   "Plugin not found" despite the warning-only contract
            # - include_optional=False now actually excludes them
            # - include_dev=True now actually installs dev dependencies
            #   (they were only ever warned about before)
            # - PEER/BUNDLED are host-provided / shipped, never visited
            for dep in plugin.dependencies:
                if dep.dep_type == DependencyType.REQUIRED:
                    included = True  # already version-checked above
                elif dep.dep_type == DependencyType.OPTIONAL:
                    included = (include_optional
                                and self._check_dependency(dep))
                elif dep.dep_type == DependencyType.DEVELOPMENT:
                    included = include_dev and self._check_dependency(dep)
                else:
                    included = False  # PEER / BUNDLED

                if not included:
                    continue
                if not visit(dep.plugin_id, path):
                    visiting.remove(plugin_id)
                    path.pop()
                    return False

            visiting.remove(plugin_id)
            path.pop()
            visited.add(plugin_id)

            # Add to install order (post-order for dependencies first).
            # Unconditional: the visited-guard above guarantees each
            # plugin reaches this point at most once.
            install_order.append(plugin_id)

            resolved[plugin_id] = plugin
            return True

        success = visit(root_plugin_id, [])

        return ResolutionResult(
            success=success and len(errors) == 0,
            resolved_plugins=resolved,
            install_order=install_order,
            errors=errors,
            warnings=warnings,
        )

    def _check_dependency(self, dep: PluginDependency) -> bool:
        """Check if a dependency can be satisfied."""
        # Check if plugin exists
        if not self.graph.has_plugin(dep.plugin_id):
            return False

        # Check version availability
        available = self._available_versions.get(dep.plugin_id, [])
        if not available:
            return False

        # Check if any available version satisfies constraint
        return any(dep.version_spec.matches(version) for version in available)

    def get_install_plan(self, plugin_id: str) -> list[str]:
        """Get installation order for a plugin and its dependencies."""
        result = self.resolve(plugin_id)
        if result.success:
            return result.install_order
        return []


@dataclass
class ResolutionResult:
    """Result of dependency resolution."""
    success: bool
    resolved_plugins: dict[str, PluginManifest] = field(default_factory=dict)
    install_order: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "resolved_count": len(self.resolved_plugins),
            "install_order": self.install_order,
            "errors": self.errors,
            "warnings": self.warnings,
        }


class LockFileManager:
    """
    Manages lock files for reproducible installations.
    """

    def __init__(self, lock_file_path: str = "plugin-lock.json"):
        self.lock_file_path = Path(lock_file_path)

    def generate_lock_file(
        self,
        resolution: ResolutionResult,
        resolver: DependencyResolver,
    ) -> dict[str, Any]:
        """Generate lock file from resolution."""
        lock_data: dict[str, Any] = {
            "version": 1,
            "generated_at": utc_now().isoformat(),
            "plugins": {},
        }

        for plugin_id in resolution.install_order:
            plugin = resolution.resolved_plugins.get(plugin_id)
            if plugin:
                lock_data["plugins"][plugin_id] = {
                    "name": plugin.name,
                    "version": plugin.version,
                    "dependencies": [
                        {
                            "plugin_id": dep.plugin_id,
                            "version_spec": str(dep.version_spec),
                            "dep_type": dep.dep_type.value,
                        }
                        for dep in plugin.dependencies
                    ],
                }

        return lock_data

    def save_lock_file(self, lock_data: dict[str, Any]) -> bool:
        """Save lock file."""
        try:
            with open(self.lock_file_path, 'w') as f:
                json.dump(lock_data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Failed to save lock file: {e}")
            return False

    def load_lock_file(self) -> Optional[dict[str, Any]]:
        """Load lock file."""
        if not self.lock_file_path.exists():
            return None

        try:
            with open(self.lock_file_path) as f:
                return cast(dict[str, Any], json.load(f))
        except Exception as e:
            logger.error(f"Failed to load lock file: {e}")
            return None

    def verify_lock_file(
        self,
        lock_data: dict[str, Any],
        resolver: DependencyResolver,
    ) -> tuple[bool, list[str]]:
        """Verify lock file against current registry."""
        errors = []

        for plugin_id, info in lock_data.get("plugins", {}).items():
            # Check if plugin exists
            plugin = resolver.graph.get_plugin(plugin_id)
            if not plugin:
                errors.append(f"Plugin not found: {plugin_id}")
                continue

            # Check version match
            if plugin.version != info.get("version"):
                errors.append(f"Version mismatch for {plugin_id}: locked={info.get('version')}, current={plugin.version}")

            # Check dependencies
            for dep_info in info.get("dependencies", []):
                dep_id = dep_info.get("plugin_id")
                dep_plugin = resolver.graph.get_plugin(dep_id)
                if not dep_plugin:
                    errors.append(f"Dependency not found: {plugin_id} -> {dep_id}")

        return len(errors) == 0, errors


class ConflictResolver:
    """
    Resolves version conflicts between plugin dependencies.
    """

    def __init__(self, graph: DependencyGraph):
        self.graph = graph

    def detect_conflicts(
        self,
        plugin_ids: list[str],
    ) -> list["VersionConflict"]:
        """Detect version conflicts in a set of plugins."""
        conflicts = []
        requirements: dict[str, list[VersionSpec]] = defaultdict(list)

        # Collect all version requirements
        for plugin_id in plugin_ids:
            plugin = self.graph.get_plugin(plugin_id)
            if not plugin:
                continue

            for dep in plugin.dependencies:
                if dep.dep_type in (DependencyType.REQUIRED, DependencyType.OPTIONAL):
                    requirements[dep.plugin_id].append(dep.version_spec)

        # Check for conflicts
        for plugin_id, specs in requirements.items():
            if len(specs) <= 1:
                continue

            # Check if all specs can be satisfied by same version
            available_versions = self._get_available_versions(plugin_id)
            compatible = []

            for version in available_versions:
                if all(spec.matches(version) for spec in specs):
                    compatible.append(version)

            if not compatible:
                conflicts.append(VersionConflict(
                    plugin_id=plugin_id,
                    conflicting_specs=specs,
                    available_versions=available_versions,
                ))

        return conflicts

    def _get_available_versions(self, plugin_id: str) -> list[str]:
        # Would query registry in practice
        plugin = self.graph.get_plugin(plugin_id)
        return [plugin.version] if plugin else []

    def suggest_resolution(
        self,
        conflict: "VersionConflict",
    ) -> list["ResolutionOption"]:
        """Suggest resolution options for a conflict."""
        options: list[ResolutionOption] = []

        # Option 1: Upgrade/downgrade one plugin
        for _spec in conflict.conflicting_specs:
            # Find versions satisfying this spec
            pass  # Would need version registry

        # Option 2: Use compatible release ranges
        # Option 3: Fork/modify plugin
        # Option 4: Exclude optional dependency

        return options


@dataclass
class VersionConflict:
    """Version conflict between dependencies."""
    plugin_id: str
    conflicting_specs: list[VersionSpec]
    available_versions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "conflicting_specs": [str(s) for s in self.conflicting_specs],
            "available_versions": self.available_versions,
        }


@dataclass
class ResolutionOption:
    """Option for resolving a conflict."""
    option_id: str
    description: str
    actions: list[dict[str, Any]]
    risk_level: str = "low"  # low, medium, high


class DependencyManager:
    """
    High-level dependency management.
    """

    def __init__(self) -> None:
        self.graph = DependencyGraph()
        self.resolver = DependencyResolver(self.graph)
        self.lock_manager = LockFileManager()
        self.conflict_resolver = ConflictResolver(self.graph)

    def add_plugin(self, manifest: PluginManifest) -> None:
        self.graph.add_plugin(manifest)
        # Register available version
        self.resolver.register_available_version(manifest.plugin_id, manifest.version)

    def remove_plugin(self, plugin_id: str) -> bool:
        return self.graph.remove_plugin(plugin_id)

    def resolve_dependencies(
        self,
        plugin_id: str,
        version: Optional[str] = None,
        **kwargs: Any
    ) -> ResolutionResult:
        return self.resolver.resolve(plugin_id, version, **kwargs)

    def get_install_plan(self, plugin_id: str) -> list[str]:
        return self.resolver.get_install_plan(plugin_id)

    def check_conflicts(self, plugin_ids: list[str]) -> list[VersionConflict]:
        return self.conflict_resolver.detect_conflicts(plugin_ids)

    def generate_lock_file(
        self,
        plugin_id: str,
        output_path: Optional[str] = None,
    ) -> bool:
        result = self.resolve_dependencies(plugin_id)
        if not result.success:
            return False

        lock_data = self.lock_manager.generate_lock_file(result, self.resolver)

        if output_path:
            self.lock_manager.lock_file_path = Path(output_path)

        return self.lock_manager.save_lock_file(lock_data)

    def verify_installation(
        self,
        lock_file_path: Optional[str] = None,
    ) -> tuple[bool, list[str]]:
        if lock_file_path:
            self.lock_manager.lock_file_path = Path(lock_file_path)

        lock_data = self.lock_manager.load_lock_file()
        if not lock_data:
            return False, ["No lock file found"]

        return self.lock_manager.verify_lock_file(lock_data, self.resolver)

    def list_all_plugins(self) -> list[PluginManifest]:
        return self.graph.get_all_plugins()

    def get_plugin_info(self, plugin_id: str) -> Optional[PluginManifest]:
        return self.graph.get_plugin(plugin_id)

    def get_dependency_tree(self, plugin_id: str) -> dict[str, Any]:
        """Get full dependency tree for a plugin."""
        def build_tree(pid: str, visited: Optional[set[str]] = None) -> dict[str, Any]:
            if visited is None:
                visited = set()

            if pid in visited:
                return {"plugin_id": pid, "circular": True}

            visited.add(pid)
            plugin = self.graph.get_plugin(pid)
            if not plugin:
                return {"plugin_id": pid, "error": "Not found"}

            deps = []
            for dep in plugin.dependencies:
                if dep.dep_type in (DependencyType.REQUIRED, DependencyType.OPTIONAL):
                    deps.append(build_tree(dep.plugin_id, visited.copy()))

            return {
                "plugin_id": plugin.plugin_id,
                "name": plugin.name,
                "version": plugin.version,
                "dependencies": deps,
            }

        return build_tree(plugin_id)


# Global dependency manager
_dependency_manager: Optional[DependencyManager] = None


def get_dependency_manager() -> DependencyManager:
    global _dependency_manager
    if _dependency_manager is None:
        _dependency_manager = DependencyManager()
    return _dependency_manager


# Alias for backward compatibility
get_dependency_manager = get_dependency_manager
