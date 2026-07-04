from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from novel_forge.modules.clickhouse_analytics import clickhouse_online_e2e_smoke
from novel_forge.modules.pgvector_store import pgvector_online_e2e_smoke
from novel_forge.storage.local import LocalStorage


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify optional pgvector and ClickHouse online backends.")
    parser.add_argument("--root", default=os.environ.get("NOVEL_FORGE_ROOT", ".local/workspace"))
    parser.add_argument("--project-id", default="")
    parser.add_argument("--require-online", action="store_true")
    args = parser.parse_args()

    storage = LocalStorage(args.root)
    storage.ensure_layout()
    results = {
        "pgvector": pgvector_online_e2e_smoke(storage, project_id=args.project_id, require_online=args.require_online),
        "clickhouse": clickhouse_online_e2e_smoke(storage, project_id=args.project_id, require_online=args.require_online),
    }
    print(json.dumps(_compact(results), ensure_ascii=False, indent=2, sort_keys=True))
    failed = any(str(result.get("status")) == "failed" for result in results.values())
    return 1 if failed else 0


def _compact(value):
    if isinstance(value, dict):
        return {key: _compact(child) for key, child in value.items() if key not in {"asset"}}
    if isinstance(value, list):
        return [_compact(child) for child in value]
    return value


if __name__ == "__main__":
    raise SystemExit(main())
