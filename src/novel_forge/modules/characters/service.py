from __future__ import annotations

from pathlib import Path

from novel_forge.modules.common import read_previous
from novel_forge.schemas import CharacterCard
from novel_forge.storage.local import LocalStorage


def generate_characters(storage: LocalStorage, input_path: str | None = None) -> Path:
    world = read_previous(storage, "worlds", input_path)
    asset = CharacterCard(
        title="Lin Qiao character card",
        source=world.id,
        tags=["character", "protagonist"],
        content={
            "role": "novice archive investigator",
            "external_goal": "identify who is manipulating the clock signals",
            "internal_need": "stop treating neutrality as safety",
            "motivation_chain": ["mentor's disgrace", "public accusation", "deadline before archive purge"],
            "risk": "may protect evidence at the cost of personal future",
        },
        references=[world.id],
    )
    return storage.write_asset("characters", asset)
