from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.storage.local import LocalStorage


@dataclass(frozen=True)
class GraphStatus:
    enabled: bool
    configured: bool
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "configured": self.configured, "reason": self.reason}


class Neo4jGraphStore:
    """Optional graph projection for relationship-heavy story assets.

    Neo4j is deliberately gated. The project should keep using schema-backed JSON
    and PostgreSQL until relationship queries become a clear bottleneck.
    """

    def __init__(self, settings: IndustrialSettings) -> None:
        if not settings.neo4j_enabled:
            raise ValueError("Neo4j is disabled; set NOVEL_FORGE_ENABLE_NEO4J=true to opt in")
        if not settings.neo4j_uri or not settings.neo4j_password:
            raise ValueError("Neo4j requires NOVEL_FORGE_NEO4J_URI and NOVEL_FORGE_NEO4J_PASSWORD")
        self.settings = settings
        self.driver = _neo4j_driver(settings)

    def close(self) -> None:
        self.driver.close()

    def sync_story_graph(self, storage: LocalStorage) -> dict[str, int]:
        characters = [storage.read_json(path) for path in storage.list_json("characters")]
        worlds = [storage.read_json(path) for path in storage.list_json("worlds")]
        outlines = [storage.read_json(path) for path in storage.list_json("outlines")]
        with self.driver.session() as session:
            session.run("CREATE CONSTRAINT nf_asset_id IF NOT EXISTS FOR (a:NFAsset) REQUIRE a.id IS UNIQUE")
            for asset in [*characters, *worlds, *outlines]:
                if isinstance(asset, dict):
                    session.run(
                        """
                        MERGE (a:NFAsset {id: $id})
                        SET a.type = $type,
                            a.title = $title,
                            a.source = $source,
                            a.updated_at = $updated_at
                        """,
                        id=asset.get("id", ""),
                        type=asset.get("type", ""),
                        title=asset.get("title") or asset.get("name", ""),
                        source=asset.get("source", ""),
                        updated_at=asset.get("updated_at", ""),
                    )
        return {"characters": len(characters), "worlds": len(worlds), "outlines": len(outlines)}


def neo4j_status(settings: IndustrialSettings) -> dict[str, Any]:
    configured = bool(settings.neo4j_uri and settings.neo4j_password)
    if not settings.neo4j_enabled:
        return GraphStatus(False, configured, "disabled until relationship-query complexity justifies Neo4j").to_dict()
    if not configured:
        return GraphStatus(False, False, "missing Neo4j URI or password").to_dict()
    return GraphStatus(True, True, "enabled by NOVEL_FORGE_ENABLE_NEO4J").to_dict()


def _neo4j_driver(settings: IndustrialSettings):
    try:
        from neo4j import GraphDatabase
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency-gated path
        raise RuntimeError("Neo4j support requires the optional dependency: neo4j") from exc
    return GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
