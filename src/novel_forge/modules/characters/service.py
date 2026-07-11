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
        project_id = str(world.metadata.get("project_id") or "")
        workspace_path = str(world.metadata.get("workspace_path") or "")
        world_content = world.content if isinstance(world.content, dict) else {}
        conflict_system = str(world_content.get("conflict_system") or world.title)
        setting = str(world_content.get("setting") or "当前世界规则")
        asset = CharacterCard(
            title=f"{world.title}：主角卡",
            source=world.id,
            tags=["character", "protagonist"],
            content={
                "role": "被世界规则直接压迫、必须主动选择的主角",
                "external_goal": f"改变或解决：{conflict_system}",
                "internal_need": "不再用回避风险来替代做出选择",
                "motivation_chain": [f"进入：{setting}", "遭遇规则造成的现实损失", "在更高代价前主动推进目标"],
                "risk": "每次推进都会失去资源、关系、身份或安全中的至少一项",
            },
            metadata={"project_id": project_id, "workspace_path": workspace_path},
            references=[world.id],
        )
        run.guard("write_character_card", "character_card")
        path = storage.write_asset("characters", asset)
        run.succeed(output_assets=[str(path.relative_to(storage.root))])
        return path
