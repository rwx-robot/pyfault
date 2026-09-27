"""
AI Plugin Marketplace for PyFault framework.
"""

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional, TypeVar

import aiofiles

logger = logging.getLogger(__name__)

T = TypeVar("T")


class PluginStatus(str, Enum):
    """Plugin status."""
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"
    DISABLED = "disabled"


class PluginCategory(str, Enum):
    """Plugin category."""
    INFERENCE = "inference"
    PREPROCESSING = "preprocessing"
    POSTPROCESSING = "postprocessing"
    ROUTING = "routing"
    MONITORING = "monitoring"
    SECURITY = "security"
    TRANSFORMATION = "transformation"
    INTEGRATION = "integration"
    CUSTOM = "custom"


@dataclass
class PluginManifest:
    """Plugin manifest metadata."""
    plugin_id: str
    name: str
    version: str
    description: str
    author: str
    category: PluginCategory
    tags: list[str] = field(default_factory=list)
    license: str = "MIT"
    homepage: str = ""
    repository: str = ""
    documentation: str = ""
    min_framework_version: str = "1.0.0"
    max_framework_version: Optional[str] = None
    dependencies: list[str] = field(default_factory=list)
    permissions: list[str] = field(default_factory=list)
    entry_point: str = "main"
    config_schema: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "category": self.category.value,
            "tags": self.tags,
            "license": self.license,
            "homepage": self.homepage,
            "repository": self.repository,
            "documentation": self.documentation,
            "min_framework_version": self.min_framework_version,
            "max_framework_version": self.max_framework_version,
            "dependencies": self.dependencies,
            "permissions": self.permissions,
            "entry_point": self.entry_point,
            "config_schema": self.config_schema,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }


@dataclass
class PluginPackage:
    """Plugin package with manifest and code."""
    manifest: PluginManifest
    code: str
    checksum: str
    size_bytes: int
    status: PluginStatus = PluginStatus.PENDING
    download_count: int = 0
    rating: float = 0.0
    review_count: int = 0
    reviews: list[dict[str, Any]] = field(default_factory=list)
    installed_at: Optional[datetime] = None
    last_updated: Optional[datetime] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.manifest.to_dict(),
            "checksum": self.checksum,
            "size_bytes": self.size_bytes,
            "status": self.status.value,
            "download_count": self.download_count,
            "rating": self.rating,
            "review_count": self.review_count,
            "reviews": self.reviews,
            "installed_at": self.installed_at.isoformat() if self.installed_at else None,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
        }


class PluginRegistry:
    """
    Plugin registry for managing AI plugins.
    """

    def __init__(self, storage_path: str = "./data/plugins"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._packages: dict[str, PluginPackage] = {}
        self._index: dict[str, dict[str, PluginPackage]] = defaultdict(dict)  # category -> name -> package
        self._loaded = False

    async def initialize(self) -> None:
        """Load plugins from storage."""
        await self._load_index()
        self._loaded = True

    @staticmethod
    def _manifest_from_dict(raw: dict[str, Any]) -> PluginManifest:
        """Build a manifest from serialized data (old nested format and
        current flat format both store category as a string and datetimes
        as ISO strings)."""
        fields = {k: v for k, v in raw.items()
                  if k in PluginManifest.__dataclass_fields__}
        if isinstance(fields.get("created_at"), str):
            fields["created_at"] = datetime.fromisoformat(
                fields["created_at"])
        if isinstance(fields.get("updated_at"), str):
            fields["updated_at"] = datetime.fromisoformat(
                fields["updated_at"])
        # JSON always stores the enum's value string (both formats)
        fields["category"] = PluginCategory(fields["category"])
        return PluginManifest(**fields)

    async def _load_index(self) -> None:
        """Load plugin index from disk."""
        index_file = self.storage_path / "index.json"
        if index_file.exists():
            async with aiofiles.open(index_file) as f:
                data = json.loads(await f.read())
                for pkg_data in data:
                    # Handle both old format (with "manifest" key) and new
                    # format (flat); both go through the same conversion so
                    # category/datetime strings are normalized either way
                    if "manifest" in pkg_data:
                        manifest = self._manifest_from_dict(
                            pkg_data["manifest"])
                    else:
                        manifest = self._manifest_from_dict(pkg_data)

                    pkg = PluginPackage(
                        manifest=manifest,
                        code=pkg_data.get("code", ""),
                        checksum=pkg_data["checksum"],
                        size_bytes=pkg_data["size_bytes"],
                        status=PluginStatus(pkg_data["status"]),
                        download_count=pkg_data.get("download_count", 0),
                        rating=pkg_data.get("rating", 0.0),
                        review_count=pkg_data.get("review_count", 0),
                        reviews=pkg_data.get("reviews", []),
                        installed_at=datetime.fromisoformat(pkg_data["installed_at"]) if pkg_data.get("installed_at") else None,
                        last_updated=datetime.fromisoformat(pkg_data["last_updated"]) if pkg_data.get("last_updated") else None,
                    )
                    self._packages[manifest.plugin_id] = pkg
                    self._index[manifest.category.value][manifest.name] = pkg

    async def _save_index(self) -> None:
        """Save plugin index to disk."""
        index_file = self.storage_path / "index.json"
        data = [pkg.to_dict() for pkg in self._packages.values()]
        async with aiofiles.open(index_file, 'w') as f:
            await f.write(json.dumps(data, indent=2, default=str))

    async def register_plugin(self, manifest: PluginManifest, code: str) -> PluginPackage:
        """Register a new plugin."""
        # Compute checksum
        checksum = hashlib.sha256(manifest.name.encode() + manifest.version.encode()).hexdigest()[:16]

        package = PluginPackage(
            manifest=manifest,
            code=code,
            checksum=checksum,
            size_bytes=len(code.encode()),
        )

        self._packages[manifest.plugin_id] = package
        self._index[manifest.category.value][manifest.name] = package

        await self._save_index()
        logger.info(f"Registered plugin: {manifest.name} v{manifest.version}")
        return package

    async def update_plugin(self, plugin_id: str, manifest: PluginManifest, code: str) -> PluginPackage:
        """Update an existing plugin."""
        if plugin_id not in self._packages:
            raise ValueError(f"Plugin not found: {plugin_id}")

        old_pkg = self._packages[plugin_id]
        old_name = old_pkg.manifest.name

        # Remove from old index
        old_cat = old_pkg.manifest.category.value
        if old_name in self._index[old_cat]:
            del self._index[old_cat][old_name]

        # Create new package
        new_manifest = manifest
        new_manifest.updated_at = datetime.utcnow()
        new_pkg = PluginPackage(
            manifest=new_manifest,
            code=code,
            checksum=hashlib.sha256(manifest.name.encode() + manifest.version.encode()).hexdigest()[:16],
            size_bytes=len(code.encode()),
            status=PluginStatus.PENDING,
            download_count=old_pkg.download_count,
            rating=old_pkg.rating,
            review_count=old_pkg.review_count,
            reviews=old_pkg.reviews,
            installed_at=old_pkg.installed_at,
            last_updated=datetime.utcnow(),
        )

        self._packages[plugin_id] = new_pkg
        self._index[manifest.category.value][manifest.name] = new_pkg

        await self._save_index()
        return new_pkg

    async def approve_plugin(self, plugin_id: str) -> bool:
        """Approve a plugin for public listing."""
        if plugin_id not in self._packages:
            return False
        pkg = self._packages[plugin_id]
        pkg.status = PluginStatus.APPROVED
        await self._save_index()
        return True

    async def reject_plugin(self, plugin_id: str, reason: str) -> bool:
        """Reject a plugin."""
        if plugin_id not in self._packages:
            return False
        pkg = self._packages[plugin_id]
        pkg.status = PluginStatus.REJECTED
        await self._save_index()
        return True

    async def uninstall_plugin(self, plugin_id: str) -> bool:
        """Uninstall a plugin."""
        if plugin_id not in self._packages:
            return False
        pkg = self._packages.pop(plugin_id)
        del self._index[pkg.manifest.category.value][pkg.manifest.name]
        await self._save_index()
        return True

    def get_plugin(self, plugin_id: str) -> Optional[PluginPackage]:
        """Get plugin by ID."""
        return self._packages.get(plugin_id)

    def get_plugin_by_name(self, name: str, category: Optional[PluginCategory] = None) -> Optional[PluginPackage]:
        """Get plugin by name and optional category."""
        if category:
            return self._index.get(category.value, {}).get(name)
        for cat_pkgs in self._index.values():
            if name in cat_pkgs:
                return cat_pkgs[name]
        return None

    def list_plugins(
        self,
        category: Optional[PluginCategory] = None,
        status: Optional[PluginStatus] = None,
        tag: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PluginPackage]:
        """List plugins with filters."""
        pkgs = list(self._packages.values())

        if category:
            pkgs = [p for p in pkgs if p.manifest.category == category]
        if status:
            pkgs = [p for p in pkgs if p.status == status]
        if tag:
            pkgs = [p for p in pkgs if tag in p.manifest.tags]

        pkgs.sort(key=lambda p: p.manifest.created_at, reverse=True)
        return pkgs[offset:offset + limit]

    def search(self, query: str, limit: int = 20) -> list[PluginPackage]:
        """Search plugins by query."""
        query = query.lower()
        results = []
        for pkg in self._packages.values():
            if (query in pkg.manifest.name.lower() or
                query in pkg.manifest.description.lower() or
                any(query in tag.lower() for tag in pkg.manifest.tags)):
                results.append(pkg)
        return results[:limit]

    async def add_review(self, plugin_id: str, user_id: str, rating: int, comment: str) -> bool:
        """Add a review to a plugin."""
        if plugin_id not in self._packages:
            return False
        pkg = self._packages[plugin_id]
        review = {
            "user_id": user_id,
            "rating": rating,
            "comment": comment,
            "timestamp": datetime.utcnow().isoformat(),
        }
        pkg.reviews.append(review)
        pkg.review_count = len(pkg.reviews)
        pkg.rating = sum(r["rating"] for r in pkg.reviews) / len(pkg.reviews)
        await self._save_index()
        return True

    async def record_download(self, plugin_id: str) -> bool:
        """Record a plugin download."""
        if plugin_id not in self._packages:
            return False
        pkg = self._packages[plugin_id]
        pkg.download_count += 1
        await self._save_index()
        return True


class PluginInstaller:
    """Handles plugin installation and management."""

    def __init__(self, registry: PluginRegistry, runtime_path: str = "./runtime"):
        self.registry = registry
        self.runtime_path = Path(runtime_path)
        self.runtime_path.mkdir(parents=True, exist_ok=True)
        self._installed: dict[str, PluginPackage] = {}

    async def install(self, plugin_id: str, config: Optional[dict[str, Any]] = None) -> bool:
        """Install a plugin."""
        pkg = self.registry.get_plugin(plugin_id)
        if not pkg or pkg.status != PluginStatus.APPROVED:
            return False

        # Save plugin code
        plugin_dir = self.runtime_path / pkg.manifest.plugin_id
        plugin_dir.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(plugin_dir / "main.py", 'w') as f:
            await f.write(pkg.code)

        # Write manifest
        async with aiofiles.open(plugin_dir / "manifest.json", 'w') as f:
            await f.write(json.dumps(pkg.manifest.to_dict(), indent=2))

        # Write config
        if config:
            async with aiofiles.open(plugin_dir / "config.json", 'w') as f:
                await f.write(json.dumps(config, indent=2))

        pkg.installed_at = datetime.utcnow()
        pkg.status = PluginStatus.APPROVED
        self._installed[pkg.manifest.plugin_id] = pkg

        await self.registry._save_index()
        return True

    async def uninstall(self, plugin_id: str) -> bool:
        """Uninstall a plugin."""
        if plugin_id not in self._installed:
            return False
        pkg = self._installed.pop(plugin_id)
        plugin_dir = self.runtime_path / plugin_id
        if plugin_dir.exists():
            import shutil
            shutil.rmtree(plugin_dir)
        pkg.status = PluginStatus.PENDING
        pkg.installed_at = None
        # persist the reset — without this the index still advertised the
        # plugin as installed after a restart (install() saves, uninstall
        # didn't)
        await self.registry._save_index()
        return True

    def is_installed(self, plugin_id: str) -> bool:
        return plugin_id in self._installed

    def list_installed(self) -> list[PluginPackage]:
        return list(self._installed.values())


class PluginManager:
    """
    High-level plugin management.
    """

    def __init__(
        self,
        storage_path: str = "./data/plugins",
        runtime_path: str = "./runtime",
    ):
        self.registry = PluginRegistry(storage_path)
        self.installer = PluginInstaller(self.registry, runtime_path)

    async def initialize(self) -> None:
        await self.registry.initialize()

    async def install_plugin(self, plugin_id: str, config: Optional[dict] = None) -> bool:
        return await self.installer.install(plugin_id, config)

    async def uninstall_plugin(self, plugin_id: str) -> bool:
        return await self.installer.uninstall(plugin_id)

    def list_available(
        self,
        category: Optional[PluginCategory] = None,
        status: PluginStatus = PluginStatus.APPROVED,
        limit: int = 50,
    ) -> list:
        return self.registry.list_plugins(category=category, status=status, limit=limit)

    def search(self, query: str, limit: int = 20) -> list:
        return self.registry.search(query, limit)

    async def install(self, plugin_id: str, config: Optional[dict] = None) -> bool:
        return await self.installer.install(plugin_id, config)

    async def uninstall(self, plugin_id: str) -> bool:
        return await self.installer.uninstall(plugin_id)

    def is_installed(self, plugin_id: str) -> bool:
        return self.installer.is_installed(plugin_id)

    def list_installed(self) -> list:
        return self.installer.list_installed()


# Global plugin manager
_plugin_manager: Optional["PluginManager"] = None


def get_plugin_manager(storage_path: str = "./data/plugins") -> "PluginManager":
    global _plugin_manager
    if _plugin_manager is None:
        _plugin_manager = PluginManager(storage_path)
    return _plugin_manager


def set_plugin_manager(manager: "PluginManager") -> None:
    global _plugin_manager
    _plugin_manager = manager
