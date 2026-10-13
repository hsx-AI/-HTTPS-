import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import lan_sync_client


class LanSyncClientTests(unittest.TestCase):
    def test_snapshot_contains_committed_rows_and_can_be_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            source_path = Path(directory) / "source.db"
            with closing(sqlite3.connect(source_path)) as source:
                source.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY)")
                source.execute("INSERT INTO documents (id) VALUES (165)")
                source.commit()

            snapshot_path = lan_sync_client.make_consistent_snapshot(source_path)
            with closing(sqlite3.connect(snapshot_path)) as snapshot:
                row = snapshot.execute("SELECT id FROM documents").fetchone()
            self.assertEqual((165,), row)
            snapshot_path.unlink()

    def test_successful_upload_stays_successful_when_snapshot_cleanup_is_locked(self):
        snapshot = MagicMock()
        snapshot.read_bytes.return_value = b"SQLite snapshot"
        snapshot.unlink.side_effect = PermissionError(32, "file is in use")
        response = MagicMock()
        result = {"ok": True, "documentCount": 165, "receivedAt": "2026-10-13T17:58:29+08:00"}
        response.__enter__.return_value.read.return_value = json.dumps(result).encode("utf-8")
        output = io.StringIO()

        with (
            patch.object(lan_sync_client, "load_config", return_value={"url": "http://localhost:8787", "token": "test"}),
            patch.object(lan_sync_client, "make_consistent_snapshot", return_value=snapshot),
            patch.object(lan_sync_client, "urlopen", return_value=response),
            patch.object(lan_sync_client.time, "sleep"),
            redirect_stdout(output),
        ):
            actual = lan_sync_client.push_database(Path("unused.db"))

        self.assertEqual(result, actual)
        self.assertEqual(3, snapshot.unlink.call_count)
        self.assertIn("数据库已推送：165 条", output.getvalue())
        self.assertIn("临时快照清理失败", output.getvalue())


if __name__ == "__main__":
    unittest.main()
