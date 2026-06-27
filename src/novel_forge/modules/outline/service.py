from __future__ import annotations

from pathlib import Path

from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous
from novel_forge.modules.production_chain import create_outline_version
from novel_forge.schemas import Outline
from novel_forge.storage.local import LocalStorage


def generate_outline(storage: LocalStorage, input_path: str | None = None) -> Path:
    character = read_previous(storage, "characters", input_path)
    with AgentExecutionContext(
        storage,
        agent_key="outline",
        operation="generate-outline",
        input_assets=[input_path or character.id],
        output_types=["outline", "outline_version"],
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
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
        run.guard("write_outline", "outline")
        path = storage.write_asset("outlines", asset)
        run.guard("write_outline_version", "outline_version")
        version = create_outline_version(storage, path)
        run.succeed(output_assets=[str(path.relative_to(storage.root)), version["path"]])
        return path
