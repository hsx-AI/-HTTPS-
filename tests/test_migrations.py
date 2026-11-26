import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from dashboard_api import catalog, migrations, pdf_catalog


class MigrationTests(unittest.TestCase):
    def test_existing_catalog_is_backed_up_and_upgraded_once(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / 'catalog.db'
            with sqlite3.connect(db) as conn:
                catalog.ensure_schema(conn)
                pdf_catalog.ensure_schema(conn)  # PDF import may already have created these tables.
                conn.execute("INSERT INTO document_notes VALUES ('A-001', '0007', '2026-11-24')")
                conn.execute("INSERT INTO pdf_catalog_batches VALUES (1, '旧清单.pdf', '2026-11-24', '[2]', 2, 1)")
                conn.execute("INSERT INTO pdf_catalog_rows VALUES (1, 1, 2, 2, '[\"001\"]')")
            first = migrations.migrate(db, root / 'backups')
            self.assertEqual([1], first['applied'])
            self.assertTrue(Path(first['backup']).exists())
            with sqlite3.connect(db) as conn:
                self.assertEqual('0007', conn.execute("SELECT internal_code FROM document_notes WHERE code='A-001'").fetchone()[0])
                self.assertEqual('旧清单.pdf', conn.execute('SELECT filename FROM pdf_catalog_batches WHERE id=1').fetchone()[0])
                self.assertEqual({'pdf_catalog_batches', 'pdf_catalog_rows', 'schema_migrations'} <= {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}, True)
            second = migrations.migrate(db, root / 'backups')
            self.assertEqual([], second['applied'])
            self.assertIsNone(second['backup'])
            self.assertEqual(1, len(list((root / 'backups').glob('*.db'))))

    def test_failed_migration_keeps_old_data_and_no_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = root / 'catalog.db'
            with sqlite3.connect(db) as conn:
                catalog.ensure_schema(conn)
                conn.execute("INSERT INTO document_notes VALUES ('A-001', '0007', '2026-11-24')")
            def fail(conn):
                conn.execute('CREATE TABLE temporary_migration_table (id INTEGER)')
                raise RuntimeError('test migration failure')
            with patch.object(migrations, 'MIGRATIONS', [(1, 'fails', fail)]):
                with self.assertRaisesRegex(RuntimeError, 'test migration failure'):
                    migrations.migrate(db, root / 'backups')
            with sqlite3.connect(db) as conn:
                self.assertEqual('0007', conn.execute("SELECT internal_code FROM document_notes WHERE code='A-001'").fetchone()[0])
                self.assertNotIn('temporary_migration_table', {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")})
                self.assertNotIn('schema_migrations', {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")})
            self.assertEqual(1, len(list((root / 'backups').glob('*.db'))))
