"""Structured Legacy migration references and dependency ordering."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Mapping


class MigrationRelationType(StrEnum):
    BOOK_DESIGN_OF_BOOK = "BOOK_DESIGN_OF_BOOK"
    PARENT_PLAN = "PARENT_PLAN"
    ARC_OVERLAY = "ARC_OVERLAY"
    KNOWLEDGE_PACK_ITEM = "KNOWLEDGE_PACK_ITEM"
    KNOWLEDGE_PACK_TARGET = "KNOWLEDGE_PACK_TARGET"
    SOURCE_EVIDENCE = "SOURCE_EVIDENCE"
    CANON_DEPENDENCY = "CANON_DEPENDENCY"
    CONTEXT_INPUT = "CONTEXT_INPUT"
    RELATED_ASSET = "RELATED_ASSET"
    OPTIONAL_REFERENCE = "OPTIONAL_REFERENCE"


@dataclass(frozen=True, slots=True)
class StructuredMigrationReference:
    business_key: str
    relation_type: MigrationRelationType
    optional: bool
    expected_source_type: str
    expected_target_asset_type: str
    expected_content_hash: str
    cardinality: str
    ordinal: int
    compatibility_mode: str

    def __post_init__(self) -> None:
        if not self.business_key:
            raise ValueError("reference business_key is required")
        if self.ordinal < 0:
            raise ValueError("reference ordinal cannot be negative")
        if self.cardinality not in {"ONE", "MANY"}:
            raise ValueError("reference cardinality must be ONE or MANY")
        if self.expected_content_hash and not self.expected_content_hash.startswith(
            "sha256:"
        ):
            raise ValueError("expected_content_hash must be canonical SHA-256")
        if (
            self.relation_type is MigrationRelationType.OPTIONAL_REFERENCE
            and not self.optional
        ):
            raise ValueError("OPTIONAL_REFERENCE must set optional=true")

    @property
    def compatibility_evidence(self) -> dict[str, Any]:
        return {
            "input_format": self.compatibility_mode,
            "normalized_relation_type": self.relation_type.value,
            "legacy_string_compatibility": (
                self.compatibility_mode == "LEGACY_STRING_V1"
            ),
        }

    def to_contract(self) -> dict[str, Any]:
        return {
            "business_key": self.business_key,
            "relation_type": self.relation_type.value,
            "optional": self.optional,
            "expected_source_type": self.expected_source_type,
            "expected_target_asset_type": self.expected_target_asset_type,
            "expected_content_hash": self.expected_content_hash,
            "cardinality": self.cardinality,
            "ordinal": self.ordinal,
            "compatibility_mode": self.compatibility_mode,
        }


_SOURCE_RELATIONS: dict[str, frozenset[MigrationRelationType]] = {
    "book_design": frozenset({MigrationRelationType.BOOK_DESIGN_OF_BOOK}),
    "book_design_candidate": frozenset({MigrationRelationType.BOOK_DESIGN_OF_BOOK}),
    "book_plan": frozenset(
        {MigrationRelationType.CANON_DEPENDENCY, MigrationRelationType.CONTEXT_INPUT}
    ),
    "outline_version": frozenset(
        {MigrationRelationType.CANON_DEPENDENCY, MigrationRelationType.CONTEXT_INPUT}
    ),
    "volume_plan": frozenset({MigrationRelationType.PARENT_PLAN}),
    "arc_plan": frozenset(
        {MigrationRelationType.PARENT_PLAN, MigrationRelationType.ARC_OVERLAY}
    ),
    "chapter_group_plan": frozenset({MigrationRelationType.PARENT_PLAN}),
    "chapter_plan": frozenset(
        {MigrationRelationType.PARENT_PLAN, MigrationRelationType.ARC_OVERLAY}
    ),
    "chapter_plan_version": frozenset(
        {MigrationRelationType.PARENT_PLAN, MigrationRelationType.ARC_OVERLAY}
    ),
    "knowledge_card": frozenset({MigrationRelationType.SOURCE_EVIDENCE}),
    "knowledge_card_candidate": frozenset(
        {MigrationRelationType.SOURCE_EVIDENCE}
    ),
    "knowledge_pack": frozenset(
        {
            MigrationRelationType.KNOWLEDGE_PACK_ITEM,
            MigrationRelationType.KNOWLEDGE_PACK_TARGET,
        }
    ),
}


def relation_supported(
    source_type: str, relation: MigrationRelationType | str
) -> bool:
    relation = MigrationRelationType(relation)
    if relation in {
        MigrationRelationType.RELATED_ASSET,
        MigrationRelationType.OPTIONAL_REFERENCE,
    }:
        return True
    return relation in _SOURCE_RELATIONS.get(source_type, frozenset())


def parse_migration_reference(
    value: str | Mapping[str, Any], *, ordinal: int
) -> StructuredMigrationReference:
    if isinstance(value, str):
        return StructuredMigrationReference(
            business_key=value.strip(),
            relation_type=MigrationRelationType.RELATED_ASSET,
            optional=False,
            expected_source_type="",
            expected_target_asset_type="",
            expected_content_hash="",
            cardinality="MANY",
            ordinal=ordinal,
            compatibility_mode="LEGACY_STRING_V1",
        )
    if not isinstance(value, Mapping):
        raise ValueError("reference must be a string or structured object")
    relation_value = str(value.get("relation_type") or "RELATED_ASSET")
    try:
        relation = MigrationRelationType(relation_value)
    except ValueError as exc:
        raise ValueError(f"unsupported reference relation_type: {relation_value}") from exc
    optional = bool(value.get("optional", False))
    if relation is MigrationRelationType.OPTIONAL_REFERENCE:
        optional = True
    return StructuredMigrationReference(
        business_key=str(value.get("business_key") or "").strip(),
        relation_type=relation,
        optional=optional,
        expected_source_type=str(value.get("expected_source_type") or "").strip(),
        expected_target_asset_type=str(
            value.get("expected_target_asset_type") or ""
        ).strip(),
        expected_content_hash=str(value.get("expected_content_hash") or "").strip(),
        cardinality=str(value.get("cardinality") or "MANY").strip().upper(),
        ordinal=int(value.get("ordinal", ordinal)),
        compatibility_mode="STRUCTURED_V1",
    )


def topological_activation_order(
    *,
    nodes: Iterable[str],
    dependencies: Mapping[str, Iterable[str]],
) -> list[str]:
    ordered_nodes = tuple(dict.fromkeys(str(node) for node in nodes))
    node_set = set(ordered_nodes)
    prerequisites = {
        node: {
            str(dependency)
            for dependency in dependencies.get(node, ())
            if str(dependency) in node_set
        }
        for node in ordered_nodes
    }
    output: list[str] = []
    ready = [node for node in ordered_nodes if not prerequisites[node]]
    while ready:
        current = ready.pop(0)
        output.append(current)
        for node in ordered_nodes:
            if current not in prerequisites[node]:
                continue
            prerequisites[node].remove(current)
            if not prerequisites[node] and node not in output and node not in ready:
                ready.append(node)
    if len(output) != len(ordered_nodes):
        cycle_nodes = sorted(node for node in ordered_nodes if node not in output)
        raise ValueError(
            "Legacy migration dependency cycle: " + ", ".join(cycle_nodes)
        )
    return output


def cyclic_dependency_nodes(
    *, nodes: Iterable[str], dependencies: Mapping[str, Iterable[str]]
) -> frozenset[str]:
    node_set = {str(node) for node in nodes}
    graph = {
        node: tuple(
            str(dependency)
            for dependency in dependencies.get(node, ())
            if str(dependency) in node_set
        )
        for node in node_set
    }
    cycle_nodes: set[str] = set()

    def visit(node: str, path: list[str], active: set[str]) -> None:
        if node in active:
            cycle_nodes.update(path[path.index(node) :])
            return
        active.add(node)
        path.append(node)
        for dependency in graph[node]:
            visit(dependency, path, active)
        path.pop()
        active.remove(node)

    for node in sorted(node_set):
        visit(node, [], set())
    return frozenset(cycle_nodes)


__all__ = [
    "MigrationRelationType",
    "StructuredMigrationReference",
    "cyclic_dependency_nodes",
    "parse_migration_reference",
    "relation_supported",
    "topological_activation_order",
]
