from __future__ import annotations

from pathlib import Path

from novel_forge.modules.common import read_previous
from novel_forge.schemas import Outline
from novel_forge.storage.local import LocalStorage


def generate_outline(storage: LocalStorage, input_path: str | None = None) -> Path:
    character = read_previous(storage, "characters", input_path)
    asset = Outline(
        title="Echo Clock three-act outline",
        source=character.id,
        tags=["outline", "three-act"],
        content={
            "acts": [
                {"act": 1, "goal": "discover the clock signal pattern", "turn": "first clue implicates the archive"},
                {"act": 2, "goal": "trace the maintainer network", "turn": "ally is exposed as compromised"},
                {"act": 3, "goal": "force a public reveal", "turn": "protagonist must sacrifice neutrality"},
            ]
        },
        references=[character.id],
    )
    return storage.write_asset("outlines", asset)
