from __future__ import annotations
from dataclasses import asdict, dataclass
import hashlib
import json
from typing import Any, Mapping
from novel_forge.modules.command_kernel.errors import KernelError
from .foundation import FoundationRole, QualifiedFoundationSet
from dataclasses import field as dataclass_field

BOOK_SCHEMA_VERSION = "book-authority.v1"
LEGACY_BOOK_DESIGN_SCHEMA_VERSION = "book-design.v1"
COUPLED_BOOK_DESIGN_SCHEMA_VERSION = "book-design.v2"
BOOK_DESIGN_SCHEMA_VERSION = "book-design.v3"
EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION = "book-design.v4"
FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION = "book-design.v5"
WORK_BOOK_DESIGN_SCHEMA_VERSION = "book-design.v7"
LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION = "book-design.v6"


def _required_string(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise KernelError("BOOK_DESIGN_INVALID", f"{field} is required")
    return normalized


def _strict_keys(payload: Mapping[str, Any], allowed: set[str], contract: str) -> None:
    unexpected = sorted(set(payload) - allowed)
    if unexpected:
        raise KernelError(
            "BOOK_DESIGN_INVALID",
            f"{contract} contains unsupported fields: {', '.join(unexpected)}",
        )


@dataclass(frozen=True, slots=True)
class BookScope:
    project_id: str
    workspace_id: str
    book_id: str
    principal: str
    service_identity: str
    production_profile: dict[str, Any]
    runtime_policy: dict[str, Any]
    release_identity: str
    schema_version: str = BOOK_SCHEMA_VERSION

    @classmethod
    def from_mapping(
        cls,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        principal: str,
        service_identity: str,
        payload: Mapping[str, Any],
    ) -> "BookScope":
        _strict_keys(
            payload,
            {
                "schema_version",
                "title",
                "production_profile",
                "runtime_policy",
                "release_identity",
            },
            "Book",
        )
        schema_version = str(payload.get("schema_version") or BOOK_SCHEMA_VERSION)
        if schema_version != BOOK_SCHEMA_VERSION:
            raise KernelError(
                "BOOK_SCHEMA_UNSUPPORTED", f"unsupported Book schema: {schema_version}"
            )
        production_profile = payload.get("production_profile")
        runtime_policy = payload.get("runtime_policy")
        if not isinstance(production_profile, dict) or not isinstance(
            runtime_policy, dict
        ):
            raise KernelError(
                "BOOK_SCOPE_INVALID",
                "production_profile and runtime_policy must be objects",
            )
        for field, value in (
            ("project_id", project_id),
            ("workspace_id", workspace_id),
            ("book_id", book_id),
            ("principal", principal),
            ("service_identity", service_identity),
        ):
            _required_string(value, field)
        return cls(
            project_id=project_id,
            workspace_id=workspace_id,
            book_id=book_id,
            principal=principal,
            service_identity=service_identity,
            production_profile=dict(production_profile),
            runtime_policy=dict(runtime_policy),
            release_identity=_required_string(
                payload.get("release_identity"), "release_identity"
            ),
            schema_version=schema_version,
        )

    def content(self, *, title: str) -> dict[str, Any]:
        return {
            **asdict(self),
            "title": _required_string(title, "title"),
            "book_scope": {
                "project_id": self.project_id,
                "workspace_id": self.workspace_id,
                "book_id": self.book_id,
            },
        }


@dataclass(frozen=True, slots=True)
class ProtagonistDesign:
    name: str
    external_goal: str
    internal_need: str
    flaw: str
    arc: str

    @classmethod
    def from_mapping(cls, payload: Any) -> "ProtagonistDesign":
        if not isinstance(payload, Mapping):
            raise KernelError("BOOK_DESIGN_INVALID", "protagonist must be an object")
        allowed = {"name", "external_goal", "internal_need", "flaw", "arc"}
        _strict_keys(payload, allowed, "protagonist")
        return cls(
            **{
                field: _required_string(payload.get(field), f"protagonist.{field}")
                for field in allowed
            }
        )


@dataclass(frozen=True, slots=True)
class BookDesignPayload:
    title: str
    genre: str
    premise: str
    theme: str
    core_conflict: str
    reader_promise: str
    ending: str
    protagonist: ProtagonistDesign
    world_rules: tuple[str, ...]
    target_chapters: int
    core_characters: tuple[dict[str, str], ...]
    opposition_forces: tuple[dict[str, str], ...]
    narrative_dna: dict[str, str | None]
    creative_foundation: dict[str, str] = dataclass_field(default_factory=dict)
    world_system: tuple[dict[str, str], ...] = ()
    character_system: tuple[dict[str, str], ...] = ()
    foundation_set: QualifiedFoundationSet | None = None
    book_invariants: tuple[str, ...] = ()
    cross_layer_synthesis: tuple[dict[str, Any], ...] = ()
    schema_version: str = BOOK_DESIGN_SCHEMA_VERSION

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "BookDesignPayload":
        if not isinstance(payload, Mapping):
            raise KernelError(
                "BOOK_DESIGN_INVALID", "BookDesign payload must be an object"
            )
        base_fields = {
            "schema_version",
            "title",
            "genre",
            "premise",
            "theme",
            "core_conflict",
            "reader_promise",
            "ending",
            "protagonist",
            "world_rules",
            "target_chapters",
        }
        progressive_fields = {
            "core_characters",
            "opposition_forces",
            "narrative_dna",
        }
        evolution_fields = {
            "creative_foundation",
            "world_system",
            "character_system",
        }
        foundation_fields = {
            "schema_version",
            "title",
            "target_chapters",
            "foundation_set",
            "book_invariants",
            "cross_layer_synthesis",
            "narrative_dna",
        }
        schema_version = str(payload.get("schema_version") or "")
        if schema_version == COUPLED_BOOK_DESIGN_SCHEMA_VERSION:
            raise KernelError(
                "BOOK_DESIGN_COUPLED_QUALIFICATION_RETIRED",
                "new BookDesign candidates cannot carry generator-owned qualification",
            )
        allowed = (
            foundation_fields
            if schema_version
            in {FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION, WORK_BOOK_DESIGN_SCHEMA_VERSION, LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION}
            else (
                base_fields
                | progressive_fields
                | (
                    evolution_fields
                    if schema_version == EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION
                    else set()
                )
                if schema_version
                in {BOOK_DESIGN_SCHEMA_VERSION, EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION}
                else base_fields
            )
        )
        _strict_keys(payload, allowed, "BookDesign")
        if schema_version not in {
            BOOK_DESIGN_SCHEMA_VERSION,
            EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION,
            FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
            WORK_BOOK_DESIGN_SCHEMA_VERSION,
            LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
            LEGACY_BOOK_DESIGN_SCHEMA_VERSION,
        }:
            raise KernelError(
                "BOOK_DESIGN_SCHEMA_UNSUPPORTED",
                "BookDesign schema is not supported",
            )
        rules = payload.get("world_rules")
        normalized_rules: tuple[str, ...] = ()
        if schema_version not in {
            FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
            WORK_BOOK_DESIGN_SCHEMA_VERSION,
            LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
        }:
            if not isinstance(rules, list) or not rules:
                raise KernelError(
                    "BOOK_DESIGN_INVALID", "world_rules must be a non-empty list"
                )
            normalized_rules = tuple(
                _required_string(rule, "world_rules[]") for rule in rules
            )
            if len(set(normalized_rules)) != len(normalized_rules):
                raise KernelError("BOOK_DESIGN_INVALID", "world_rules must be unique")
        target_chapters = payload.get("target_chapters")
        if (
            not isinstance(target_chapters, int)
            or isinstance(target_chapters, bool)
            or not 1 <= target_chapters <= 10000
        ):
            raise KernelError(
                "BOOK_DESIGN_INVALID", "target_chapters must be an integer between 1 and 10000"
            )
        core_characters: tuple[dict[str, str], ...] = ()
        opposition_forces: tuple[dict[str, str], ...] = ()
        narrative_dna: dict[str, str | None] = {}
        creative_foundation: dict[str, str] = {}
        world_system: tuple[dict[str, str], ...] = ()
        character_system: tuple[dict[str, str], ...] = ()
        foundation_set: QualifiedFoundationSet | None = None
        book_invariants: tuple[str, ...] = ()
        cross_layer_synthesis: tuple[dict[str, Any], ...] = ()
        if schema_version in {
            BOOK_DESIGN_SCHEMA_VERSION,
            EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION,
            FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
            WORK_BOOK_DESIGN_SCHEMA_VERSION,
            LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
        }:
            if schema_version not in {
                FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                WORK_BOOK_DESIGN_SCHEMA_VERSION,
                LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
            }:
                core_characters = _typed_records(
                    payload.get("core_characters"),
                    "core_characters",
                    (
                        "character_id",
                        "role",
                        "long_term_goal",
                        "causal_arc",
                        "conflict_function",
                    ),
                )
                opposition_forces = _typed_records(
                    payload.get("opposition_forces"),
                    "opposition_forces",
                    (
                        "force_id",
                        "goal",
                        "leverage",
                        "escalation_pattern",
                        "limit",
                    ),
                )
            dna_value = payload.get("narrative_dna")
            dna_fields = {
                "core_question",
                "recurring_choice",
                "cost_logic",
                "distinctive_mechanism",
                "emotional_contract",
            }
            if not isinstance(dna_value, Mapping):
                raise KernelError(
                    "BOOK_DESIGN_INVALID", "narrative_dna must be an object"
                )
            _strict_keys(dna_value, dna_fields, "narrative_dna")
            narrative_dna = {
                field: (
                    None
                    if schema_version in {WORK_BOOK_DESIGN_SCHEMA_VERSION, LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION}
                    and field in {"recurring_choice", "cost_logic"}
                    and field in dna_value
                    and dna_value[field] is None
                    else _required_string(
                        dna_value.get(field), f"narrative_dna.{field}"
                    )
                )
                for field in sorted(dna_fields)
            }
        if schema_version in {
            FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
            WORK_BOOK_DESIGN_SCHEMA_VERSION,
            LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
        }:
            foundation_value = payload.get("foundation_set")
            if not isinstance(foundation_value, Mapping):
                raise KernelError(
                    "BOOK_DESIGN_INVALID",
                    "BookDesign v5 requires the exact qualified Foundation Set",
                )
            foundation_set = QualifiedFoundationSet.from_mapping(foundation_value)
            invariants = payload.get("book_invariants")
            if not isinstance(invariants, list) or (
                not invariants and schema_version not in {WORK_BOOK_DESIGN_SCHEMA_VERSION, LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION}
            ):
                raise KernelError(
                    "BOOK_DESIGN_INVALID", "book_invariants must be non-empty"
                )
            book_invariants = tuple(
                _required_string(item, "book_invariants[]") for item in invariants
            )
            if len(set(book_invariants)) != len(book_invariants):
                raise KernelError(
                    "BOOK_DESIGN_INVALID", "book_invariants must be unique"
                )
            cross_layer_synthesis = _synthesis_records(
                payload.get("cross_layer_synthesis")
            )
        if schema_version == EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION:
            foundation_value = payload.get("creative_foundation")
            foundation_fields = {
                "target_reader",
                "why_worth_writing",
                "subgenre",
                "core_desire",
                "core_fear",
                "narrative_engine",
                "differentiation",
                "emotional_contract",
                "serialization_potential",
                "thematic_question",
                "ending_direction",
            }
            if not isinstance(foundation_value, Mapping):
                raise KernelError(
                    "BOOK_DESIGN_INVALID", "creative_foundation must be an object"
                )
            _strict_keys(foundation_value, foundation_fields, "creative_foundation")
            creative_foundation = {
                name: _required_string(
                    foundation_value.get(name), f"creative_foundation.{name}"
                )
                for name in sorted(foundation_fields)
            }
            world_system = _typed_records(
                payload.get("world_system"),
                "world_system",
                (
                    "rule_id",
                    "rule",
                    "cost",
                    "exception",
                    "consequence",
                    "conflict_potential",
                    "narrative_function",
                ),
            )
            character_system = _typed_records(
                payload.get("character_system"),
                "character_system",
                (
                    "character_id",
                    "name",
                    "role",
                    "desire",
                    "need",
                    "fear",
                    "wound",
                    "false_belief",
                    "values",
                    "moral_boundary",
                    "agency",
                    "capability",
                    "weakness",
                    "voice",
                    "secret",
                    "relationship_function",
                    "arc_direction",
                ),
            )
        return cls(
            title=_required_string(payload.get("title"), "title"),
            genre=(
                ""
                if schema_version
                in {
                    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                    WORK_BOOK_DESIGN_SCHEMA_VERSION,
                    LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
                }
                else _required_string(payload.get("genre"), "genre")
            ),
            premise=(
                ""
                if schema_version
                in {
                    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                    WORK_BOOK_DESIGN_SCHEMA_VERSION,
                    LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
                }
                else _required_string(payload.get("premise"), "premise")
            ),
            theme=(
                ""
                if schema_version
                in {
                    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                    WORK_BOOK_DESIGN_SCHEMA_VERSION,
                    LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
                }
                else _required_string(payload.get("theme"), "theme")
            ),
            core_conflict=(
                ""
                if schema_version
                in {
                    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                    WORK_BOOK_DESIGN_SCHEMA_VERSION,
                    LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
                }
                else _required_string(payload.get("core_conflict"), "core_conflict")
            ),
            reader_promise=(
                ""
                if schema_version
                in {
                    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                    WORK_BOOK_DESIGN_SCHEMA_VERSION,
                    LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
                }
                else _required_string(payload.get("reader_promise"), "reader_promise")
            ),
            ending=(
                ""
                if schema_version
                in {
                    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                    WORK_BOOK_DESIGN_SCHEMA_VERSION,
                    LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
                }
                else _required_string(payload.get("ending"), "ending")
            ),
            protagonist=(
                ProtagonistDesign("", "", "", "", "")
                if schema_version
                in {
                    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                    WORK_BOOK_DESIGN_SCHEMA_VERSION,
                    LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
                }
                else ProtagonistDesign.from_mapping(payload.get("protagonist"))
            ),
            world_rules=normalized_rules,
            target_chapters=target_chapters,
            core_characters=core_characters,
            opposition_forces=opposition_forces,
            narrative_dna=narrative_dna,
            creative_foundation=creative_foundation,
            world_system=world_system,
            character_system=character_system,
            foundation_set=foundation_set,
            book_invariants=book_invariants,
            cross_layer_synthesis=cross_layer_synthesis,
            schema_version=schema_version,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["world_rules"] = list(self.world_rules)
        payload["core_characters"] = [dict(item) for item in self.core_characters]
        payload["opposition_forces"] = [dict(item) for item in self.opposition_forces]
        payload["world_system"] = [dict(item) for item in self.world_system]
        payload["character_system"] = [dict(item) for item in self.character_system]
        payload["foundation_set"] = (
            self.foundation_set.to_dict() if self.foundation_set is not None else None
        )
        payload["book_invariants"] = list(self.book_invariants)
        payload["cross_layer_synthesis"] = [
            dict(item) for item in self.cross_layer_synthesis
        ]
        if self.schema_version == LEGACY_BOOK_DESIGN_SCHEMA_VERSION:
            for field in (
                "core_characters",
                "opposition_forces",
                "narrative_dna",
                "creative_foundation",
                "world_system",
                "character_system",
            ):
                payload.pop(field, None)
        elif self.schema_version == BOOK_DESIGN_SCHEMA_VERSION:
            for field in (
                "creative_foundation",
                "world_system",
                "character_system",
                "foundation_set",
                "book_invariants",
                "cross_layer_synthesis",
            ):
                payload.pop(field, None)
        elif self.schema_version == EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION:
            for field in ("foundation_set", "book_invariants", "cross_layer_synthesis"):
                payload.pop(field, None)
        elif self.schema_version in {
            FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
            WORK_BOOK_DESIGN_SCHEMA_VERSION,
            LEGACY_WORK_BOOK_DESIGN_SCHEMA_VERSION,
        }:
            for field in (
                "genre",
                "premise",
                "theme",
                "core_conflict",
                "reader_promise",
                "ending",
                "protagonist",
                "world_rules",
                "core_characters",
                "opposition_forces",
                "creative_foundation",
                "world_system",
                "character_system",
            ):
                payload.pop(field, None)
        return payload

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(
            self.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


def evidence_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _typed_records(
    value: Any,
    field: str,
    required_fields: tuple[str, ...],
) -> tuple[dict[str, str], ...]:
    if not isinstance(value, list) or not value:
        raise KernelError("BOOK_DESIGN_INVALID", f"{field} must be a non-empty list")
    records: list[dict[str, str]] = []
    identities: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise KernelError("BOOK_DESIGN_INVALID", f"{field} entries must be objects")
        _strict_keys(item, set(required_fields), field)
        record = {
            name: _required_string(item.get(name), f"{field}[].{name}")
            for name in required_fields
        }
        identity = record[required_fields[0]]
        if identity in identities:
            raise KernelError(
                "BOOK_DESIGN_INVALID", f"{field} identities must be unique"
            )
        identities.add(identity)
        records.append(record)
    return tuple(records)


def _synthesis_records(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise KernelError(
            "BOOK_DESIGN_INVALID", "cross_layer_synthesis must be non-empty"
        )
    allowed = {
        "synthesis_id",
        "source_roles",
        "narrative_function",
        "constraint",
        "downstream_scope",
    }
    records: list[dict[str, Any]] = []
    identities: set[str] = set()
    for item in value:
        if not isinstance(item, Mapping):
            raise KernelError(
                "BOOK_DESIGN_INVALID", "cross_layer_synthesis entries must be objects"
            )
        _strict_keys(item, allowed, "cross_layer_synthesis")
        identity = _required_string(item.get("synthesis_id"), "synthesis_id")
        if identity in identities:
            raise KernelError(
                "BOOK_DESIGN_INVALID", "synthesis identities must be unique"
            )
        raw_roles = item.get("source_roles")
        if not isinstance(raw_roles, list) or len(raw_roles) < 2:
            raise KernelError(
                "BOOK_DESIGN_INVALID", "synthesis requires at least two source roles"
            )
        roles = tuple(FoundationRole(str(role)).value for role in raw_roles)
        if len(set(roles)) != len(roles):
            raise KernelError(
                "BOOK_DESIGN_INVALID", "synthesis source roles must be unique"
            )
        records.append(
            {
                "synthesis_id": identity,
                "source_roles": list(roles),
                "narrative_function": _required_string(
                    item.get("narrative_function"), "narrative_function"
                ),
                "constraint": _required_string(item.get("constraint"), "constraint"),
                "downstream_scope": _required_string(
                    item.get("downstream_scope"), "downstream_scope"
                ),
            }
        )
        identities.add(identity)
    return tuple(records)


__all__ = [
    "BOOK_DESIGN_SCHEMA_VERSION",
    "COUPLED_BOOK_DESIGN_SCHEMA_VERSION",
    "EVOLUTION_BOOK_DESIGN_SCHEMA_VERSION",
    "FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION",
    "LEGACY_BOOK_DESIGN_SCHEMA_VERSION",
    "BOOK_SCHEMA_VERSION",
    "BookDesignPayload",
    "BookScope",
    "ProtagonistDesign",
    "evidence_hash",
]
