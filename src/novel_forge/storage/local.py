from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from novel_forge.core.constants import ASSET_DIR_BY_TYPE, DATA_DIRS
from novel_forge.schemas import BaseAsset, asset_from_dict


class LocalStorage:
    def __init__(self, root: str | Path = ".") -> None:
        self.root = Path(root).resolve()
        self.data_root = self.root / "data"

    def ensure_layout(self) -> None:
        for rel in DATA_DIRS:
            (self.data_root / rel).mkdir(parents=True, exist_ok=True)
        for rel in ["examples/sample_inputs", "examples/sample_outputs", "examples/sample_project"]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

    def data_dir(self, category: str) -> Path:
        return self.data_root / category

    def write_json(self, path: str | Path, data: Any) -> Path:
        resolved = self.root / path if not Path(path).is_absolute() else Path(path)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        resolved.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return resolved

    def read_json(self, path: str | Path) -> Any:
        resolved = self.root / path if not Path(path).is_absolute() else Path(path)
        return json.loads(resolved.read_text(encoding="utf-8"))

    def write_asset(self, category: str, asset: BaseAsset) -> Path:
        self.ensure_layout()
        path = self.data_dir(category) / f"{asset.id}.json"
        path.write_text(json.dumps(asset.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return path

    def write_asset_auto(self, asset: BaseAsset) -> Path:
        category = ASSET_DIR_BY_TYPE.get(asset.type)
        if not category:
            raise ValueError(f"no data directory mapping for asset type: {asset.type}")
        return self.write_asset(category, asset)

    def list_json(self, category: str) -> list[Path]:
        folder = self.data_dir(category)
        if not folder.exists():
            return []
        return sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime)

    def latest(self, category: str) -> Path:
        files = self.list_json(category)
        if not files:
            raise FileNotFoundError(f"no JSON assets found in data/{category}")
        return files[-1]

    def read_asset(self, path: str | Path) -> BaseAsset:
        data = self.read_json(path)
        if not isinstance(data, dict):
            raise ValueError(f"asset JSON must be an object: {path}")
        return asset_from_dict(data)

    def counts(self) -> dict[str, int]:
        return {category: len(self.list_json(category)) for category in DATA_DIRS}
