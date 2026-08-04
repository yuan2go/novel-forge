"""Typed conversion contracts for frozen Legacy assets.

The registry is deliberately closed: an unknown Legacy type is quarantined
instead of being wrapped in a generic candidate that can drift into production.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any


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
    references: tuple[str, ...]
    content: dict[str, Any]
    content_hash: str
    lifecycle: str
    eligibility: str
    governance: str
    qualification_policy: str
    activation_decision: str
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
    rebuildable: bool
    quarantine_rules: tuple[str, ...]
    reconciliation_rules: tuple[str, ...]

    @property
    def codec_name(self) -> str:
        return f"native:{self.source_type}->{self.target_asset_type}"

    @property
    def codec_version(self) -> str:
        return "2.0.0"

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
        approved = _explicitly_approved(original)
        activation_decision = (
            "ACTIVATE"
            if approved and self.activation_policy == "AUTO_IF_EXPLICITLY_APPROVED"
            else "NEEDS_REVIEW"
        )
        return NativeMigrationCandidate(
            source_type=self.source_type,
            target_asset_type=self.target_asset_type,
            schema_version=self.schema_version,
            stable_business_identity=self.stable_identity(record),
            project_id=str(record.project_id),
            workspace_id=str(record.workspace_id),
            references=tuple(record.references),
            content=native_content,
            content_hash=content_hash,
            lifecycle="ACTIVE" if activation_decision == "ACTIVATE" else "IMPORTED",
            eligibility="ELIGIBLE" if approved else "PENDING_EVALUATION",
            governance="CLEAR",
            qualification_policy=self.qualification_policy,
            activation_decision=activation_decision,
            reconciliation={
                "source_hash": str(record.source_hash),
                "target_content_hash": content_hash,
                "reference_count": len(record.references),
                "stable_business_identity": self.stable_identity(record),
                "activation_decision": activation_decision,
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
                "rebuildable": codec.rebuildable,
                "quarantine_rules": list(codec.quarantine_rules),
                "reconciliation_rules": list(codec.reconciliation_rules),
                "codec_name": codec.codec_name,
                "codec_version": codec.codec_version,
            }
            for codec in self.codecs
        ]


def _codec(source_type: str, target_asset_type: str | None = None) -> TypedMigrationCodec:
    target = target_asset_type or source_type
    return TypedMigrationCodec(
        source_type=source_type,
        target_asset_type=target,
        schema_version=f"{target}.authority.v1",
        scope_resolution="require_project_and_resolve_workspace_v1",
        reference_resolution="same_project_complete_reference_set_v1",
        conversion="native_content_without_local_paths_v1",
        validation=f"{target}.migration.schema.v1",
        qualification_policy=f"{target}.legacy-import-qualification.v1",
        activation_policy="AUTO_IF_EXPLICITLY_APPROVED",
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


# This set is derived from the current schema validators and PostgreSQL
# Authority modules.  Rebuildable runtime/cache types intentionally do not get
# codecs; the scanner marks them for rebuild instead.
_TYPE_TARGETS = {
    # Project / book / Story Design
    "project_workspace_state": "project_record",
    "book": "book_record",
    "book_record": "book_record",
    "book_design": "book_design",
    "book_design_candidate": "book_design",
    "story_design": "story_design",
    "story_design_candidate": "story_design",
    # Typed planning and design assets
    "book_plan": "book_plan",
    "volume_plan": "volume_plan",
    "arc_plan": "arc_plan",
    "chapter_plan": "chapter_plan",
    "chapter_plan_version": "chapter_plan",
    "outline_version": "book_plan",
    "topic_seed": "topic_seed",
    "world_bible": "world_bible",
    "character_card": "character_card",
    "faction_card": "faction_card",
    "location_card": "location_card",
    # Context, content and editorial state
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
    # Canon and story state
    "canon_database": "canon_snapshot",
    "canon_graph_snapshot": "canon_graph_snapshot",
    "story_state_snapshot": "story_state_snapshot",
    "continuity_bible": "continuity_bible",
    "fact_ledger": "fact_ledger",
    # Source, material and MKAOS
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
    # Durable business workflow definitions/checkpoints
    "workflow_definition": "workflow_definition",
    "workflow_run": "workflow_run_snapshot",
    "agent_contract": "agent_contract",
    "agent_run": "agent_run_snapshot",
    "agent_checkpoint": "agent_checkpoint",
    # Reader / feedback
    "feedback_import_batch": "feedback_import_batch",
    "feedback_insight": "feedback_insight",
    "reader_sentiment_report": "reader_sentiment_report",
    "reader_outcome": "reader_outcome",
    # Publishing evidence
    "publish_gate_report": "publish_gate_report",
    "release_package": "release_package",
    "publishing_plan": "publishing_plan",
    "publishing_log": "publishing_log",
    "publication_record": "publication_record",
}

DEFAULT_CODEC_REGISTRY = TypedMigrationCodecRegistry(
    tuple(_codec(source, target) for source, target in sorted(_TYPE_TARGETS.items()))
)


def _explicitly_approved(payload: dict[str, Any]) -> bool:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
    status = str(payload.get("status") or content.get("status") or "").upper()
    return bool(metadata.get("migration_approved")) and status in {
        "ACTIVE",
        "APPROVED",
        "ACCEPTED",
        "PUBLISHED",
    }


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
]
