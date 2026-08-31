"""COMPATIBILITY: unknown archival types are quarantined instead of becoming generic production candidates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from novel_forge.modules.legacy_migration.state_machine import (
    MigrationMaterializationLevel,
)


class MigrationCodecNotFound(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NativeMigrationCandidate:
    source_type: str
    target_asset_type: str
    schema_version: str
    stable_business_identity: str
    project_id: str
    workspace_id: str
    references: tuple[dict[str, Any], ...]
    content: dict[str, Any]
    content_hash: str
    lifecycle: str
    eligibility: str
    governance: str
    qualification_policy: str
    activation_decision: str
    materialization_level: MigrationMaterializationLevel
    legacy_approval_evidence: dict[str, Any]
    reconciliation: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TypedMigrationCodec:
    source_type: str
    target_asset_type: str
    schema_version: str
    scope_resolution: str
    reference_resolution: str
    conversion: str
    validation: str
    qualification_policy: str
    activation_policy: str
    materialization_level: MigrationMaterializationLevel
    domain_adapter: str
    domain_validator: str
    projection_strategy: str
    activation_strategy: str
    rebuildable: bool
    quarantine_rules: tuple[str, ...]
    reconciliation_rules: tuple[str, ...]

    @property
    def codec_name(self) -> str:
        return f"native:{self.source_type}->{self.target_asset_type}"

    @property
    def codec_version(self) -> str:
        return "3.0.0"

    def stable_identity(self, record: Any) -> str:
        return ":".join(
            (
                str(record.project_id),
                self.target_asset_type,
                str(record.stable_business_key),
            )
        )

    def convert_record(self, record: Any) -> NativeMigrationCandidate:
        if record.source_asset_type != self.source_type:
            raise ValueError("migration codec source type does not match the record")
        if not record.project_id:
            raise ValueError("native conversion requires project scope")
        if not isinstance(record.payload, dict):
            raise ValueError("native conversion requires an inline object payload")
        if not str(record.source_hash).startswith("sha256:"):
            raise ValueError("native conversion requires a SHA-256 record hash")

        original = record.payload
        payload_content = original.get("content")
        if payload_content is None:
            payload_content = {
                key: value
                for key, value in original.items()
                if key
                not in {
                    "id",
                    "type",
                    "version",
                    "created_at",
                    "updated_at",
                    "metadata",
                    "references",
                }
            }
        if not isinstance(payload_content, dict):
            raise ValueError("Legacy asset content must be an object")
        native_content = _strip_local_paths(payload_content)
        native_content.update(
            {
                "schema_version": self.schema_version,
                "project_id": str(record.project_id),
                "workspace_id": str(record.workspace_id),
                "legacy_migration": {
                    "source_ref": str(record.source_ref),
                    "source_hash": str(record.source_hash),
                    "source_type": self.source_type,
                    "stable_business_identity": self.stable_identity(record),
                    "codec": self.codec_name,
                    "codec_version": self.codec_version,
                },
            }
        )
        content_hash = _content_hash(native_content)
        legacy_approval_evidence = _legacy_approval_evidence(original)
        activation_decision = "NEEDS_REVIEW"
        validate_archival_candidate(
            content=native_content,
            content_hash=content_hash,
            project_id=str(record.project_id),
            workspace_id=str(record.workspace_id),
        )
        return NativeMigrationCandidate(
            source_type=self.source_type,
            target_asset_type=self.target_asset_type,
            schema_version=self.schema_version,
            stable_business_identity=self.stable_identity(record),
            project_id=str(record.project_id),
            workspace_id=str(record.workspace_id),
            references=tuple(
                reference.to_contract() for reference in record.references
            ),
            content=native_content,
            content_hash=content_hash,
            lifecycle="IMPORTED",
            eligibility="PENDING_EVALUATION",
            governance="CLEAR",
            qualification_policy=self.qualification_policy,
            activation_decision=activation_decision,
            materialization_level=MigrationMaterializationLevel.ARCHIVAL_NATIVE,
            legacy_approval_evidence=legacy_approval_evidence,
            reconciliation={
                "source_hash": str(record.source_hash),
                "target_content_hash": content_hash,
                "reference_count": len(record.references),
                "stable_business_identity": self.stable_identity(record),
                "activation_decision": activation_decision,
                "materialization_level": (
                    MigrationMaterializationLevel.ARCHIVAL_NATIVE.value
                ),
                "target_materialization_level": self.materialization_level.value,
                "legacy_approval_evidence": legacy_approval_evidence,
            },
        )


class TypedMigrationCodecRegistry:
    def __init__(self, codecs: tuple[TypedMigrationCodec, ...]) -> None:
        indexed = {codec.source_type: codec for codec in codecs}
        if len(indexed) != len(codecs):
            raise ValueError("duplicate Legacy migration source type")
        self._codecs = indexed

    @property
    def source_types(self) -> frozenset[str]:
        return frozenset(self._codecs)

    @property
    def codecs(self) -> tuple[TypedMigrationCodec, ...]:
        return tuple(self._codecs[key] for key in sorted(self._codecs))

    def resolve(self, source_type: str) -> TypedMigrationCodec:
        normalized = str(source_type).strip().lower()
        try:
            return self._codecs[normalized]
        except KeyError as exc:
            raise MigrationCodecNotFound(
                f"no native migration codec registered for Legacy type: {normalized or '<empty>'}"
            ) from exc

    def to_manifest(self) -> list[dict[str, Any]]:
        return [
            {
                "source_type": codec.source_type,
                "target_asset_type": codec.target_asset_type,
                "schema_version": codec.schema_version,
                "stable_business_identity": "project_id:target_asset_type:legacy_business_key",
                "scope_resolution": codec.scope_resolution,
                "reference_resolution": codec.reference_resolution,
                "conversion": codec.conversion,
                "validation": codec.validation,
                "qualification_policy": codec.qualification_policy,
                "activation_policy": codec.activation_policy,
                "materialization_level": codec.materialization_level.value,
                "domain_adapter": codec.domain_adapter,
                "domain_validator": codec.domain_validator,
                "projection_strategy": codec.projection_strategy,
                "activation_strategy": codec.activation_strategy,
                "rebuildable": codec.rebuildable,
                "quarantine_rules": list(codec.quarantine_rules),
                "reconciliation_rules": list(codec.reconciliation_rules),
                "codec_name": codec.codec_name,
                "codec_version": codec.codec_version,
            }
            for codec in self.codecs
        ]


def _codec(
    source_type: str,
    target_asset_type: str | None = None,
    *,
    domain: str = "",
) -> TypedMigrationCodec:
    target = target_asset_type or source_type
    return TypedMigrationCodec(
        source_type=source_type,
        target_asset_type=target,
        schema_version=f"{target}.authority.v1",
        scope_resolution="require_project_and_resolve_workspace_v1",
        reference_resolution="same_project_complete_reference_set_v1",
        conversion="native_content_without_local_paths_v1",
        validation="legacy_migration.validate_archival_candidate.v1",
        qualification_policy="legacy-archival-import-qualification-v1",
        activation_policy="EXPLICIT_AUTHORITY_APPROVAL_REQUIRED",
        materialization_level=(
            MigrationMaterializationLevel.DOMAIN_NATIVE
            if domain
            else MigrationMaterializationLevel.ARCHIVAL_NATIVE
        ),
        domain_adapter=(
            f"novel_forge.legacy_migration.{domain}.v1" if domain else ""
        ),
        domain_validator=(
            f"novel_forge.{domain}.domain_validator.v1"
            if domain
            else "legacy_migration.validate_archival_candidate.v1"
        ),
        projection_strategy=(
            f"{domain}.authority_projection.v1"
            if domain
            else "immutable_asset_version_only.v1"
        ),
        activation_strategy=(
            f"{domain}.explicit_command.v1"
            if domain
            else "NEEDS_REVIEW"
        ),
        rebuildable=False,
        quarantine_rules=(
            "PROJECT_ID_MISSING",
            "MISSING_REFERENCE",
            "CROSS_PROJECT_REFERENCE",
            "BUSINESS_IDENTITY_CONTENT_CONFLICT",
            "SOURCE_RIGHTS_UNVERIFIED",
            "OBJECT_STORE_REQUIRED",
        ),
        reconciliation_rules=(
            "snapshot_hash",
            "record_hash",
            "stable_business_identity",
            "reference_count",
            "target_content_hash",
            "qualification",
            "active_projection",
        ),
    )


# INVARIANT: only schema-backed Authority assets receive codecs; rebuildable
# runtime/cache records are marked for rebuild.
_TYPE_TARGETS = {
    "project_workspace_state": "project_record",
    "book": "book_record",
    "book_record": "book_record",
    "book_design": "book_design",
    "book_design_candidate": "book_design",
    "story_design": "story_design",
    "story_design_candidate": "story_design",
    "book_plan": "book_plan",
    "volume_plan": "volume_plan",
    "arc_plan": "arc_plan",
    "chapter_plan": "chapter_plan",
    "chapter_plan_version": "chapter_plan",
    "chapter_group_plan": "chapter_group_plan",
    "outline_version": "book_plan",
    "topic_seed": "topic_seed",
    "world_bible": "world_bible",
    "character_card": "character_card",
    "faction_card": "faction_card",
    "location_card": "location_card",
    "context_build_plan": "context_build_plan",
    "context_bundle": "context_bundle",
    "draft": "draft_chapter",
    "draft_chapter": "draft_chapter",
    "revised_draft": "revised_draft",
    "review_report": "review_report",
    "review_issue": "review_issue",
    "revision_plan": "revision_plan",
    "revision_task": "revision_task",
    "editor_patch": "editor_patch",
    "draft_diff_report": "draft_diff_report",
    "canon_database": "canon_snapshot",
    "canon_graph_snapshot": "canon_graph_snapshot",
    "story_state_snapshot": "story_state_snapshot",
    "continuity_bible": "continuity_bible",
    "fact_ledger": "fact_ledger",
    "source_document": "source_document",
    "source_chunk": "source_chunk",
    "cleaned_text": "cleaned_text",
    "material_card": "material_card",
    "analysis_report": "analysis_report",
    "knowledge_card_candidate": "knowledge_card_candidate",
    "knowledge_card": "knowledge_card",
    "rule_card": "rule_card",
    "template_card": "template_card",
    "knowledge_pack": "knowledge_pack",
    "workflow_definition": "workflow_definition",
    "workflow_run": "workflow_run_snapshot",
    "agent_contract": "agent_contract",
    "agent_run": "agent_run_snapshot",
    "agent_checkpoint": "agent_checkpoint",
    "feedback_import_batch": "feedback_import_batch",
    "feedback_insight": "feedback_insight",
    "reader_sentiment_report": "reader_sentiment_report",
    "reader_outcome": "reader_outcome",
    "publish_gate_report": "publish_gate_report",
    "release_package": "release_package",
    "publishing_plan": "publishing_plan",
    "publishing_log": "publishing_log",
    "publication_record": "publication_record",
}


_DOMAIN_ADAPTERS = {
    "project_workspace_state": "project_authority",
    "book": "book_design_authority",
    "book_record": "book_design_authority",
    "book_design": "book_design_authority",
    "book_design_candidate": "book_design_authority",
    "story_design": "story_design_authority",
    "story_design_candidate": "story_design_authority",
    "book_plan": "hierarchical_planning",
    "outline_version": "hierarchical_planning",
    "volume_plan": "hierarchical_planning",
    "arc_plan": "hierarchical_planning",
    "chapter_plan": "hierarchical_planning",
    "chapter_plan_version": "hierarchical_planning",
    "chapter_group_plan": "hierarchical_planning",
    "source_document": "source_authority",
    "knowledge_card_candidate": "mkaos_authority",
    "knowledge_card": "mkaos_authority",
    "knowledge_pack": "mkaos_authority",
}

CORE_DOMAIN_MIGRATION_SOURCE_TYPES = frozenset(_DOMAIN_ADAPTERS)
DOMAIN_MIGRATION_ALIAS_GROUPS = (
    ("book", "book_record"),
    ("book_design", "book_design_candidate"),
    ("story_design", "story_design_candidate"),
    ("book_plan", "outline_version"),
    ("chapter_plan", "chapter_plan_version"),
    ("knowledge_card_candidate", "knowledge_card"),
)

if len(CORE_DOMAIN_MIGRATION_SOURCE_TYPES) != 18:
    raise RuntimeError("core Domain migration source-type contract must contain 18 types")

DEFAULT_CODEC_REGISTRY = TypedMigrationCodecRegistry(
    tuple(
        _codec(source, target, domain=_DOMAIN_ADAPTERS.get(source, ""))
        for source, target in sorted(_TYPE_TARGETS.items())
    )
)


def _legacy_approval_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    status = str(payload.get("status") or content.get("status") or "").upper()
    return {
        "claimed_approved": bool(metadata.get("migration_approved")),
        "claimed_status": status,
        "trusted_for_activation": False,
        "policy": "LEGACY_STATE_IS_EVIDENCE_ONLY",
    }


def validate_archival_candidate(
    *,
    content: dict[str, Any],
    content_hash: str,
    project_id: str,
    workspace_id: str,
) -> None:
    if not project_id or not workspace_id:
        raise ValueError("archival native candidate requires Project/Workspace scope")
    if not content_hash.startswith("sha256:") or len(content_hash) != 71:
        raise ValueError("archival native candidate requires canonical SHA-256")
    migration = content.get("legacy_migration")
    if not isinstance(migration, dict):
        raise ValueError("archival native candidate requires migration lineage")
    required = {
        "source_ref",
        "source_hash",
        "source_type",
        "stable_business_identity",
        "codec",
        "codec_version",
    }
    if required - migration.keys():
        raise ValueError("archival native candidate migration lineage is incomplete")
    if not str(migration["source_hash"]).startswith("sha256:"):
        raise ValueError("archival native candidate source hash is invalid")


def _strip_local_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _strip_local_paths(child)
            for key, child in value.items()
            if not str(key).lower().endswith(("_path", "_file", "_directory"))
        }
    if isinstance(value, list):
        return [_strip_local_paths(child) for child in value]
    return value


def _content_hash(content: dict[str, Any]) -> str:
    encoded = json.dumps(
        content, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "DEFAULT_CODEC_REGISTRY",
    "MigrationCodecNotFound",
    "NativeMigrationCandidate",
    "TypedMigrationCodec",
    "TypedMigrationCodecRegistry",
    "validate_archival_candidate",
]
