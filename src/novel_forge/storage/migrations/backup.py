from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any


def create_migration_backup(database_url: str, cursor: Any, *, applied: list[dict[str, str]], directory: str | None) -> dict[str, Any]:
    if not directory or not Path(directory).is_absolute():
        raise RuntimeError("MIGRATION_BACKUP_REQUIRED: provide an absolute backup directory before upgrading an existing ledger")
    dump, restore = shutil.which("pg_dump"), shutil.which("pg_restore")
    if not dump or not restore:
        raise RuntimeError("MIGRATION_BACKUP_REQUIRED: pg_dump and pg_restore must be installed")
    root = Path(directory)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    cursor.execute("SELECT current_database(), current_setting('server_version'), pg_export_snapshot()")
    database, version, snapshot = cursor.fetchone()
    descriptor, name = tempfile.mkstemp(prefix="migration-", suffix=".dump", dir=root)
    os.close(descriptor)
    path = Path(name)
    from psycopg.conninfo import conninfo_to_dict
    from psycopg.pq import Conninfo

    options = Conninfo.get_defaults()
    parameters = {option.keyword.decode(): option.val.decode() for option in options if option.val and option.envvar}
    parameters.update(conninfo_to_dict(database_url))
    parameters["dbname"] = database
    environment = {"PATH": os.environ.get("PATH", os.defpath)}
    for option in options:
        key = option.keyword.decode()
        if key in parameters:
            if not option.envvar:
                raise RuntimeError("MIGRATION_BACKUP_REQUIRED: connection option cannot be passed privately to pg_dump: " + key)
            environment[option.envvar.decode()] = parameters[key]
    try:
        subprocess.run([dump, "--format=custom", "--snapshot=" + snapshot, "--file=" + str(path)],
                       env=environment, check=True, capture_output=True, timeout=600)
        subprocess.run([restore, "--list", str(path)], env=environment, check=True, capture_output=True, timeout=60)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("MIGRATION_BACKUP_FAILED: no migration DDL was executed; retain and inspect the private backup") from error
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    evidence = {"path": str(path.resolve()), "sha256": digest, "bytes": path.stat().st_size,
                "database": database, "server_version": version, "snapshot": snapshot,
                "applied": applied, "archive_readable": True, "restore_qualification": "NOT_RUN",
                "scope": "DATABASE_ONLY; Blob and execution files require the deployment restore procedure"}
    metadata = path.with_suffix(".json")
    with open(metadata, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as stream:
        json.dump(evidence, stream, indent=2)
    return evidence
