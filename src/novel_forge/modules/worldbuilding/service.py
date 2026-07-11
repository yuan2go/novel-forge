from __future__ import annotations

from pathlib import Path

from novel_forge.modules.agent_runs import AgentExecutionContext
from novel_forge.modules.common import read_previous
from novel_forge.schemas import WorldBible
from novel_forge.storage.local import LocalStorage


def generate_world(storage: LocalStorage, input_path: str | None = None) -> Path:
    topic = read_previous(storage, "topics", input_path)
    with AgentExecutionContext(
        storage,
        agent_key="worldbuilding",
        operation="generate-world",
        input_assets=[input_path or topic.id],
        output_types=["world_bible"],
        sla_seconds=300,
    ) as run:
        run.guard("read_asset")
        project_id = str(topic.metadata.get("project_id") or "")
        workspace_path = str(topic.metadata.get("workspace_path") or "")
        topic_content = topic.content if isinstance(topic.content, dict) else {}
        logline = str(topic_content.get("logline") or topic.title)
        mechanism = str((topic_content.get("trope_variation") or {}).get("base_mechanism") or "核心冲突") if isinstance(topic_content.get("trope_variation"), dict) else "核心冲突"
        asset = WorldBible(
            title=f"{topic.title}：世界观",
            source=topic.id,
            tags=["world", "project-derived"],
            content={
                "setting": f"围绕“{mechanism}”展开的原创社会与行动空间；{logline}",
                "rules": [f"{mechanism}必须通过可见资源、制度或关系影响角色选择", "每次规则调用都要产生可追踪的代价或后果"],
                "conflict_system": f"主角目标与“{mechanism}”所代表的阻力持续碰撞",
                "boundaries": "no imported settings or protected unique world elements",
            },
            metadata={"project_id": project_id, "workspace_path": workspace_path},
            references=[topic.id],
        )
        run.guard("write_world_bible", "world_bible")
        path = storage.write_asset("worlds", asset)
        run.succeed(output_assets=[str(path.relative_to(storage.root))])
        return path
