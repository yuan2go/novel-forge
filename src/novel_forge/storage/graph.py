from __future__ import annotations

import json
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

    def sync_novel_kg(self, graph: dict[str, Any]) -> dict[str, int]:
        """Project a Novel KG snapshot into Neo4j without making Neo4j authoritative."""

        node_rows = _novel_kg_nodes(graph)
        relation_rows = _novel_kg_relations(graph)
        with self.driver.session() as session:
            session.run("CREATE CONSTRAINT nf_novel_kg_node_id IF NOT EXISTS FOR (n:NFNovelKGNode) REQUIRE n.id IS UNIQUE")
            for row in node_rows:
                session.run(
                    """
                    MERGE (n:NFNovelKGNode {id: $id})
                    SET n.kind = $kind,
                        n.entity_type = $entity_type,
                        n.name = $name,
                        n.source_asset_id = $source_asset_id,
                        n.source_asset_type = $source_asset_type,
                        n.source_path = $source_path,
                        n.project_id = $project_id,
                        n.workspace_path = $workspace_path,
                        n.ontology_version = $ontology_version,
                        n.kg_id = $kg_id,
                        n.attributes_json = $attributes_json,
                        n.evidence_json = $evidence_json
                    """,
                    **row,
                )
            for row in relation_rows:
                session.run(
                    """
                    MERGE (s:NFNovelKGNode {id: $source})
                    ON CREATE SET s.kind = 'external', s.name = $source
                    MERGE (t:NFNovelKGNode {id: $target})
                    ON CREATE SET t.kind = 'external', t.name = $target
                    MERGE (s)-[r:NF_KG_RELATION {id: $id}]->(t)
                    SET r.relation_type = $relation_type,
                        r.source_asset_id = $source_asset_id,
                        r.source_asset_type = $source_asset_type,
                        r.source_path = $source_path,
                        r.ontology_version = $ontology_version,
                        r.kg_id = $kg_id,
                        r.attributes_json = $attributes_json
                    """,
                    **row,
                )
        return {"nodes": len(node_rows), "relations": len(relation_rows)}


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


def _novel_kg_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for collection in _novel_kg_node_collections():
        items = graph.get(collection, [])
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or not str(item.get("id", "")).strip():
                continue
            rows.append(
                {
                    "id": str(item.get("id", "")),
                    "kind": str(item.get("kind", collection)),
                    "entity_type": str(item.get("entity_type", item.get("rule_type", item.get("template_type", "")))),
                    "name": str(item.get("name", item.get("id", ""))),
                    "source_asset_id": str(item.get("source_asset_id", "")),
                    "source_asset_type": str(item.get("source_asset_type", "")),
                    "source_path": str(item.get("source_path", "")),
                    "project_id": str(item.get("project_id", graph.get("project_id", ""))),
                    "workspace_path": str(item.get("workspace_path", graph.get("workspace_path", ""))),
                    "ontology_version": str(graph.get("ontology_version", "")),
                    "kg_id": str(graph.get("kg_id", "")),
                    "attributes_json": _json_dumps(item.get("attributes", {})),
                    "evidence_json": _json_dumps(item.get("evidence", {})),
                }
            )
    return rows


def _novel_kg_relations(graph: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    relations = graph.get("relations", [])
    if not isinstance(relations, list):
        return rows
    for item in relations:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip()
        target = str(item.get("target", "")).strip()
        if not source or not target:
            continue
        relation_id = str(item.get("id", "")).strip() or f"{source}:{item.get('relation_type', 'related_to')}:{target}"
        rows.append(
            {
                "id": relation_id,
                "source": source,
                "target": target,
                "relation_type": str(item.get("relation_type", "related_to")),
                "source_asset_id": str(item.get("source_asset_id", "")),
                "source_asset_type": str(item.get("source_asset_type", "")),
                "source_path": str(item.get("source_path", "")),
                "ontology_version": str(graph.get("ontology_version", "")),
                "kg_id": str(graph.get("kg_id", "")),
                "attributes_json": _json_dumps(item.get("attributes", {})),
            }
        )
    return rows


def _novel_kg_node_collections() -> list[str]:
    return ["entities", "events", "rules", "timelines", "foreshadowing", "factions", "locations", "props", "power_scales", "review_rules", "templates"]


def _json_dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)
