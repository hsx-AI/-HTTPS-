"""Versioned migrations for the server-owned catalog database."""
from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

from . import catalog, pdf_catalog


def _initial_catalog(conn: sqlite3.Connection) -> None:
    catalog.ensure_schema(conn)
    pdf_catalog.ensure_schema(conn)


# Append new numbered migrations here. Never edit a migration after deployment.
MIGRATIONS = [(1, 'catalog_and_pdf_tables', _initial_catalog)]


def migrate(path: Path | None = None, backup_dir: Path | None = None) -> dict:
    path = Path(path or catalog.catalog_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn:
        current = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        applied = {row[0] for row in conn.execute('SELECT version FROM schema_migrations')} if 'schema_migrations' in current else set()
        pending = [(version, name, action) for version, name, action in MIGRATIONS if version not in applied]
        if not pending:
            return {'applied': [], 'backup': None, 'path': str(path)}

        backup = None
        if path.exists() and path.stat().st_size and current:
            destination = Path(backup_dir) if backup_dir else path.parent / 'backups'
            destination.mkdir(parents=True, exist_ok=True)
            backup = destination / f'{path.stem}-{datetime.now().strftime("%Y%m%d-%H%M%S-%f")}.db'
            with closing(sqlite3.connect(backup)) as target:
                conn.backup(target)
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)')
            for version, name, action in pending:
                action(conn)
                conn.execute('INSERT INTO schema_migrations VALUES (?, ?, ?)', (version, name, datetime.now().astimezone().isoformat(timespec='seconds')))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return {'applied': [version for version, _, _ in pending], 'backup': str(backup) if backup else None, 'path': str(path)}


def main() -> None:
    result = migrate(backup_dir=Path(os.environ['NQD_BACKUP_DIR']) if os.environ.get('NQD_BACKUP_DIR') else None)
    print(f"数据库升级：{result['path']}；迁移 {result['applied'] or '无'}；备份 {result['backup'] or '无需'}", flush=True)


if __name__ == '__main__':
    main()
