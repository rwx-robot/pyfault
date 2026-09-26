"""
Database Migrations for PyFault framework - Alembic integration.
"""

import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


class MigrationManager:
    """Manages database migrations using Alembic."""

    def __init__(self, database_url: str, migrations_dir: str = "migrations"):
        self.database_url = database_url
        self.migrations_dir = Path(migrations_dir)
        self.alembic_ini = self.migrations_dir / "alembic.ini"

    def _alembic(self, *args: str) -> list[str]:
        """Build an alembic command bound to this project's config file.

        Runs via ``python -m alembic`` so it works regardless of whether
        the ``alembic`` console script is on PATH, and always passes
        ``-c`` so the config location is explicit (no cwd guessing).
        """
        return [sys.executable, "-m", "alembic", "-c", str(self.alembic_ini), *args]

    def init(self, template_dir: Optional[str] = None) -> bool:
        """Initialize Alembic migrations directory."""
        if self.alembic_ini.exists():
            print(f"Migrations already initialized at {self.migrations_dir}")
            return False

        self.migrations_dir.mkdir(parents=True, exist_ok=True)

        cmd = self._alembic("init", str(self.migrations_dir))
        if template_dir:
            cmd.extend(["-t", template_dir])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to initialize migrations: {result.stderr}")
            return False

        # Update alembic.ini with database URL
        self._update_alembic_ini()

        print(f"Migrations initialized at {self.migrations_dir}")
        return True

    def _update_alembic_ini(self) -> None:
        """Update alembic.ini with database URL."""
        if not self.alembic_ini.exists():
            return

        content = self.alembic_ini.read_text()
        # Replace whatever sqlalchemy.url line is present (default
        # template ships a placeholder driver:// URL).
        content = re.sub(
            r"(?m)^sqlalchemy\.url\s*=.*$",
            lambda _match: f"sqlalchemy.url = {self.database_url}",
            content,
        )
        self.alembic_ini.write_text(content)

    def create_migration(self, message: str, autogenerate: bool = True) -> Optional[str]:
        """Create a new migration."""
        cmd = self._alembic("revision")
        if autogenerate:
            cmd.append("--autogenerate")
        cmd.extend(["-m", message])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to create migration: {result.stderr}")
            return None

        # Extract revision from output
        for line in result.stdout.splitlines():
            if "Generating" in line or "revision" in line.lower():
                return line.strip()

        return "Migration created"

    def upgrade(self, revision: str = "head") -> bool:
        """Apply migrations up to revision."""
        cmd = self._alembic("upgrade", revision)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to upgrade: {result.stderr}")
            return False
        print(result.stdout)
        return True

    def downgrade(self, revision: str = "-1") -> bool:
        """Revert migrations."""
        cmd = self._alembic("downgrade", revision)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to downgrade: {result.stderr}")
            return False
        print(result.stdout)
        return True

    def current(self) -> Optional[str]:
        """Get current revision."""
        cmd = self._alembic("current")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def history(self) -> Optional[str]:
        """Get migration history."""
        cmd = self._alembic("history")
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return result.stdout

    def show(self, revision: str) -> Optional[str]:
        """Show migration details."""
        cmd = self._alembic("show", revision)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return result.stdout


def run_migrations(database_url: str, migrations_dir: str = "migrations") -> bool:
    """Convenience function to run all pending migrations."""
    manager = MigrationManager(database_url, migrations_dir)
    if not manager.alembic_ini.exists():
        manager.init()
    return manager.upgrade()
