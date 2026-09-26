"""
Plugin Marketplace for PyFault framework.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class PluginPackage:
    """Plugin package metadata."""
    name: str
    version: str
    description: str
    author: str
    license: str = "MIT"
    homepage: str = ""
    repository: str = ""
    keywords: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    min_pyfault_version: str = "1.0.0"
    downloads: int = 0
    rating: float = 0.0
    reviews: int = 0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    verified: bool = False
    official: bool = False
    download_url: str = ""
    checksum: str = ""
    size: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "license": self.license,
            "homepage": self.homepage,
            "repository": self.repository,
            "keywords": self.keywords,
            "dependencies": self.dependencies,
            "provides": self.provides,
            "min_pyfault_version": self.min_pyfault_version,
            "downloads": self.downloads,
            "rating": self.rating,
            "reviews": self.reviews,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "verified": self.verified,
            "official": self.official,
            "download_url": self.download_url,
            "checksum": self.checksum,
            "size": self.size,
        }


@dataclass
class MarketplaceConfig:
    """Marketplace configuration."""
    registry_url: str = "https://registry.pyfault.org"
    cache_ttl: int = 3600
    enable_official: bool = True
    enable_community: bool = True
    auto_update: bool = False


def _version_key(version: str) -> tuple[tuple[int, int, str], ...]:
    """Sort key that orders numeric segments numerically.

    Plain string sorting puts "9.0.0" above "10.0.0"; each segment is
    tagged so numeric segments compare as ints and the rest as strings.
    """
    parts: list[tuple[int, int, str]] = []
    for segment in version.split("."):
        if segment.isdigit():
            parts.append((1, int(segment), ""))
        else:
            parts.append((0, 0, segment))
    return tuple(parts)


class PluginMarketplace:
    """Plugin marketplace for discovering and installing plugins."""

    def __init__(self, config: Optional[MarketplaceConfig] = None):
        self.config = config or MarketplaceConfig()
        self._packages: dict[str, PluginPackage] = {}
        self._categories: dict[str, list[str]] = {}
        self._cache: dict[str, Any] = {}
        self._cache_expiry: dict[str, float] = {}

    def register_package(self, package: PluginPackage) -> None:
        """Register a plugin package."""
        key = f"{package.name}@{package.version}"
        self._packages[key] = package

        # Update categories
        for keyword in package.keywords:
            if keyword not in self._categories:
                self._categories[keyword] = []
            if package.name not in self._categories[keyword]:
                self._categories[keyword].append(package.name)

    def get_package(self, name: str, version: str = "latest") -> Optional[PluginPackage]:
        """Get a package by name and version."""
        if version == "latest":
            # Find latest version
            versions = [k for k in self._packages if k.startswith(f"{name}@")]
            if not versions:
                return None
            # Sort by semantic version (numeric segments compare as ints)
            versions.sort(key=lambda x: _version_key(x.split("@", 1)[1]), reverse=True)
            return self._packages[versions[0]]

        key = f"{name}@{version}"
        return self._packages.get(key)

    def search(self, query: str = "", category: Optional[str] = None,
               sort: str = "relevance", limit: int = 20) -> list[PluginPackage]:
        """Search for packages."""
        results = []

        for package in self._packages.values():
            # Filter by query
            if query:
                query_lower = query.lower()
                if (query_lower not in package.name.lower() and
                    query_lower not in package.description.lower() and
                    query_lower not in " ".join(package.keywords).lower()):
                    continue

            # Filter by category
            if category and category not in package.keywords:
                continue

            results.append(package)

        # Sort results
        if sort == "relevance":
            results.sort(key=lambda p: p.downloads, reverse=True)
        elif sort == "rating":
            results.sort(key=lambda p: p.rating, reverse=True)
        elif sort == "updated":
            results.sort(key=lambda p: p.updated_at, reverse=True)
        elif sort == "name":
            results.sort(key=lambda p: p.name)

        return results[:limit]

    def get_categories(self) -> list[str]:
        """Get all categories."""
        return list(self._categories.keys())

    def get_package_versions(self, name: str) -> list[str]:
        """Get all versions of a package."""
        versions = []
        for key in self._packages:
            if key.startswith(f"{name}@"):
                versions.append(key.split("@", 1)[1])
        return sorted(versions, key=_version_key, reverse=True)

    def install_package(self, name: str, version: str = "latest") -> dict[str, Any]:
        """Install a plugin package."""
        # This would integrate with the plugin manager
        package = self.get_package(name, version)
        if not package:
            return {"success": False, "error": "Package not found"}

        # Verify checksum if available
        if package.checksum:
            # Verify download
            pass

        return {
            "success": True,
            "package": package.to_dict(),
            "message": f"Package {name}@{package.version} ready for installation",
        }

    def publish_package(self, package: PluginPackage) -> dict[str, Any]:
        """Publish a package to the marketplace."""
        # Validate package
        if not package.name or not package.version:
            return {"success": False, "error": "Name and version required"}

        # Check if already exists
        key = f"{package.name}@{package.version}"
        if key in self._packages:
            return {"success": False, "error": "Package already exists"}

        # Register package
        self.register_package(package)

        return {
            "success": True,
            "package": package.to_dict(),
            "message": f"Package {package.name}@{package.version} published",
        }

    def get_popular(self, limit: int = 10) -> list[PluginPackage]:
        """Get most popular packages."""
        packages = list(self._packages.values())
        packages.sort(key=lambda p: p.downloads, reverse=True)
        return packages[:limit]

    def get_recent(self, limit: int = 10) -> list[PluginPackage]:
        """Get recently updated packages."""
        packages = list(self._packages.values())
        packages.sort(key=lambda p: p.updated_at, reverse=True)
        return packages[:limit]

    def get_featured(self, limit: int = 10) -> list[PluginPackage]:
        """Get featured (official/verified) packages."""
        packages = [p for p in self._packages.values() if p.official or p.verified]
        packages.sort(key=lambda p: p.downloads, reverse=True)
        return packages[:limit]

    def get_stats(self) -> dict[str, Any]:
        """Get marketplace statistics."""
        total_packages = len(self._packages)
        total_downloads = sum(p.downloads for p in self._packages.values())
        official_count = sum(1 for p in self._packages.values() if p.official)
        verified_count = sum(1 for p in self._packages.values() if p.verified)

        return {
            "total_packages": total_packages,
            "total_downloads": total_downloads,
            "official_packages": official_count,
            "verified_packages": verified_count,
            "categories": len(self._categories),
        }
