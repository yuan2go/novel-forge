from __future__ import annotations

from pathlib import Path

from novel_forge.modules.common import read_previous
from novel_forge.schemas import WorldBible
from novel_forge.storage.local import LocalStorage


def generate_world(storage: LocalStorage, input_path: str | None = None) -> Path:
    topic = read_previous(storage, "topics", input_path)
    asset = WorldBible(
        title="Echo Clock City World Bible",
        source=topic.id,
        tags=["world", "urban-suspense"],
        content={
            "setting": "A rain-heavy port city where public clocks archive civic announcements and rumors.",
            "rules": ["every public signal has a logged maintainer", "archives are incomplete after a reform year"],
            "conflict_system": "public memory vs private survival",
            "boundaries": "no imported settings or protected unique world elements",
        },
        references=[topic.id],
    )
    return storage.write_asset("worlds", asset)
