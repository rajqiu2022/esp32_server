"""Export a consistent, private deployment snapshot without stopping the local control panel."""
from contextlib import closing
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import sqlite3
import sys
import tarfile
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server.config import Config


def export_state(config):
    source = config.data / "control.db"
    key_file = config.data / "secrets.json"
    if not source.exists() or not key_file.exists():
        raise RuntimeError("No existing control-plane state to export")
    folder = config.data / "exports"
    folder.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = folder / ("esp32-state-" + timestamp + ".tar.gz")
    if target.exists():
        raise RuntimeError("An export with this timestamp already exists")
    with tempfile.TemporaryDirectory(prefix="state-", dir=folder) as temporary:
        database = Path(temporary) / "control.db"
        with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as original:
            with closing(sqlite3.connect(database)) as snapshot:
                original.backup(snapshot)
                # Browser login sessions and process liveness are machine-specific.
                snapshot.execute("DELETE FROM sessions")
                snapshot.execute("DELETE FROM settings WHERE key='runtime'")
                snapshot.commit()
                if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise RuntimeError("Exported database integrity check failed")
                if snapshot.execute("PRAGMA foreign_key_check").fetchone():
                    raise RuntimeError("Exported database foreign-key check failed")
        keys = Path(temporary) / "secrets.json"
        shutil.copyfile(key_file, keys)
        with tarfile.open(target, "x:gz") as archive:
            for file in (database, keys):
                info = archive.gettarinfo(str(file), arcname=file.name)
                info.mode = 0o600
                with file.open("rb") as stream:
                    archive.addfile(info, stream)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix(target.suffix + ".sha256").write_text(digest + "\n", encoding="ascii")
    return target


if __name__ == "__main__":
    print(export_state(Config()))
