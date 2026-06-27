from __future__ import annotations

from pathlib import Path

from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous
from novel_forge.schemas import CharacterCard
from novel_forge.storage.local import LocalStorage


def generate_characters(storage: LocalStorage, input_path: str | None = None) -> Path:
    world = read_previous(storage, "worlds", input_path)
    with AgentExecutionContext(
        storage,
        agent_key="character",
        operation="generate-characters",
        input_assets=[input_path or world.id],
        output_types=["character_card"],
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
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
        run.guard("write_character_card", "character_card")
        path = storage.write_asset("characters", asset)
        run.succeed(output_assets=[str(path.relative_to(storage.root))])
        return path
