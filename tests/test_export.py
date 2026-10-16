from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest

from scripts.export_state import export_state
from server.config import Config
from server.store import Store


class ExportTests(unittest.TestCase):
    def test_online_export_preserves_private_config_and_excludes_local_sessions(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Config(folder)
            store = Store(config.data / "control.db")
            store.execute("INSERT INTO users VALUES(?,?,?)", (1, "owner", "hashed-password"))
            store.execute("INSERT INTO sessions VALUES(?,?,?)", ("old-browser-session", 1, 9999999999))
            store.save_setting("runtime", {"time": 1, "devices": ["aa:bb:cc:dd:ee:ff"]})
            store.save_setting("model", {"api_key": "test-model-secret", "model": "test-model"})
            (config.data / "first-login.txt").write_text("Do not migrate the plaintext password file")
            original_agent = store.one("SELECT * FROM agents")
            archive_path = export_state(config)
            self.assertTrue(archive_path.with_suffix(".gz.sha256").exists())
            with tarfile.open(archive_path) as archive:
                self.assertEqual(set(archive.getnames()), {"control.db", "secrets.json"})
                self.assertTrue(all(member.mode == 0o600 for member in archive.getmembers()))
                restored = Path(folder) / "restored.db"
                restored.write_bytes(archive.extractfile("control.db").read())
                self.assertEqual(json.load(archive.extractfile("secrets.json")), config.secrets)
            with closing(sqlite3.connect(restored)) as database:
                database.row_factory = sqlite3.Row
                self.assertEqual(database.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(database.execute("SELECT count(*) FROM sessions").fetchone()[0], 0)
                self.assertIsNone(database.execute("SELECT * FROM settings WHERE key='runtime'").fetchone())
                self.assertEqual(dict(database.execute("SELECT * FROM agents").fetchone()), original_agent)
                model = database.execute("SELECT value FROM settings WHERE key='model'").fetchone()[0]
                self.assertEqual(json.loads(model)["api_key"], "test-model-secret")
                self.assertEqual(database.execute("SELECT username FROM users").fetchone()[0], "owner")
            self.assertEqual(store.one("SELECT count(*) AS n FROM sessions")["n"], 1)
            self.assertIsNotNone(store.setting("runtime"))


if __name__ == "__main__":
    unittest.main()
