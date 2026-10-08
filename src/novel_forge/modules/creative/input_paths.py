from __future__ import annotations

import hashlib
import json
from pathlib import Path


def resolve_historical_input_path(path: Path) -> Path:
    root = Path(__file__).resolve().parents[4]
    try:
        relative = path.absolute().relative_to(root).as_posix()
    except ValueError:
        return path
    manifest = root / "config/archive/creative-inputs-legacy/path-map.json"
    records = json.loads(manifest.read_bytes())["entries"]
    record = next((item for item in records if item["previous_path"] == relative), None)
    if record is None:
        return path
    archived = root / record["archive_path"]
    if archived.is_symlink() or not archived.resolve().is_relative_to(root) or hashlib.sha256(archived.read_bytes()).hexdigest() != record["sha256"]:
        raise ValueError("Historical input path must resolve to the original immutable bytes")
    return archived
