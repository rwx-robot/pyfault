"""
Database Migrations for PyFault framework - Alembic integration.
"""

import subprocess
from pathlib import Path
from typing import Optional


class MigrationManager:
    """Manages database migrations using Alembic."""

    def __init__(self, database_url: str, migrations_dir: str = "migrations"):
        self.database_url = database_url
        self.migrations_dir = Path(migrations_dir)
        self.alembic_ini = self.migrations_dir / "alembic.ini"

    def init(self, template_dir: Optional[str] = None) -> bool:
        """Initialize Alembic migrations directory."""
        if self.alembic_ini.exists():
            print(f"Migrations already initialized at {self.migrations_dir}")
            return False

        self.migrations_dir.mkdir(parents=True, exist_ok=True)

        # Run alembic init
        cmd = ["alembic", "init", str(self.migrations_dir)]
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
        # Replace sqlalchemy.url placeholder
        content = content.replace(
            "sqlalchemy.url = driver://user:pass@localhost/dbname",
            f"sqlalchemy.url = {self.database_url}"
        )
        self.alembic_ini.write_text(content)

    def create_migration(self, message: str, autogenerate: bool = True) -> Optional[str]:
        """Create a new migration."""
        cmd = ["alembic", "revision"]
        if autogenerate:
            cmd.append("--autogenerate")
        cmd.extend(["-m", message])

        result = subprocess.run(cmd, cwd=self.migrations_dir.parent, capture_output=True, text=True)
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
        cmd = ["alembic", "upgrade", revision]
        result = subprocess.run(cmd, cwd=self.migrations_dir.parent, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to upgrade: {result.stderr}")
            return False
        print(result.stdout)
        return True

    def downgrade(self, revision: str = "-1") -> bool:
        """Revert migrations."""
        cmd = ["alembic", "downgrade", revision]
        result = subprocess.run(cmd, cwd=self.migrations_dir.parent, capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to downgrade: {result.stderr}")
            return False
        print(result.stdout)
        return True

    def current(self) -> Optional[str]:
        """Get current revision."""
        cmd = ["alembic", "current"]
        result = subprocess.run(cmd, cwd=self.migrations_dir.parent, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return result.stdout.strip()

    def history(self) -> Optional[str]:
        """Get migration history."""
        cmd = ["alembic", "history"]
        result = subprocess.run(cmd, cwd=self.migrations_dir.parent, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return result.stdout

    def show(self, revision: str) -> Optional[str]:
        """Show migration details."""
        cmd = ["alembic", "show", revision]
        result = subprocess.run(cmd, cwd=self.migrations_dir.parent, capture_output=True, text=True)
        if result.returncode != 0:
            return None
        return result.stdout


def run_migrations(database_url: str, migrations_dir: str = "migrations") -> bool:
    """Convenience function to run all pending migrations."""
    manager = MigrationManager(database_url, migrations_dir)
    if not manager.alembic_ini.exists():
        manager.init()
    return manager.upgrade()
