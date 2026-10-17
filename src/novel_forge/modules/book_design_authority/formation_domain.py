from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Mapping
from types import MappingProxyType

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.authority_security import (
    FORMATION_AUTO_ACTIONS,
    Principal,
    PrincipalType,
    build_scoped_auto_decision_evidence,
    canonical_formation_auto_authorization,
    require_worker_scoped_auto_decision,
)
from .foundation import FoundationRole


STORY_FORMATION_POLICY_VERSION = "story-formation-policy.v1"


def deterministic_story_formation_run_id(
    *, project_id: str, book_id: str, stable_idempotency_key: str
) -> str:
    identity = "\x00".join(
        (project_id, book_id, stable_idempotency_key)
    ).encode("utf-8")
    return "story-formation:" + hashlib.sha256(identity).hexdigest()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class StoryFormationStage(StrEnum):
    CREATIVE_SEARCH = "CREATIVE_SEARCH"
    CREATIVE_FOUNDATION = "CREATIVE_FOUNDATION"
    THEME_CONTRACT = "THEME_CONTRACT"
    ENDING_INTENT = "ENDING_INTENT"
    READER_PROMISE = "READER_PROMISE"
    WORLD_BIBLE = "WORLD_BIBLE"
    CHARACTER_CAST = "CHARACTER_CAST"
    BOOK_DESIGN = "BOOK_DESIGN"
    COMPLETE = "COMPLETE"


FORMATION_SEQUENCE = tuple(StoryFormationStage)


@dataclass(frozen=True, slots=True)
class FormationLayerInput:
    role: FoundationRole
    asset_version_id: str
    content_hash: str
    schema_version: str
    generation_operation_id: str
    qualification_evidence_asset_version_id: str
    qualification_hash: str
    activation_operation_id: str
    candidate_asset_version_ids: tuple[str, ...]
    selection_reason: tuple[str, ...]
    selection_basis: str = "INDEPENDENT_COMPARISON"

    def __post_init__(self) -> None:
        object.__setattr__(self, "role", FoundationRole(self.role))
        required = (
            self.asset_version_id,
            self.content_hash,
            self.schema_version,
            self.generation_operation_id,
            self.qualification_evidence_asset_version_id,
            self.qualification_hash,
            self.activation_operation_id,
        )
        if any(not item.strip() for item in required):
            raise ValueError(f"{self.role.value} Formation input is incomplete")
        if any(
            len(value) != 71 or not value.startswith("sha256:")
            for value in (self.content_hash, self.qualification_hash)
        ):
            raise ValueError("Formation content and qualification must be hash-bound")
        if (
            not self.candidate_asset_version_ids
            or len(set(self.candidate_asset_version_ids))
            != len(self.candidate_asset_version_ids)
            or self.asset_version_id not in self.candidate_asset_version_ids
            or not self.selection_reason
        ):
            raise ValueError("Formation selection evidence is incomplete")
        if self.selection_basis not in {"INDEPENDENT_COMPARISON", "AUTHOR_COMPARISON", "AUTHOR_DIRECTION", "TEMPLATE_VALIDATION", "AUTHOR_AVAILABLE_ALTERNATIVE", "AUTO_COMPARISON"}:
            raise ValueError("Formation selection basis is undeclared")
        if self.role is FoundationRole.CREATIVE_FOUNDATION and self.selection_basis not in {"AUTHOR_DIRECTION", "AUTHOR_AVAILABLE_ALTERNATIVE"} and len(
            self.candidate_asset_version_ids
        ) < 2:
            raise ValueError("Creative Search requires at least two compared candidates")

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "FormationLayerInput":
        expected = {
            "role",
            "asset_version_id",
            "content_hash",
            "schema_version",
            "generation_operation_id",
            "qualification_evidence_asset_version_id",
            "qualification_hash",
            "activation_operation_id",
            "candidate_asset_version_ids",
            "selection_reason",
        }
        if set(value) not in (expected, expected | {"selection_basis"}):
            raise KernelError(
                "STORY_FORMATION_INPUT_INVALID",
                "Formation layer input fields must match exactly",
            )
        return cls(
            role=FoundationRole(str(value["role"])),
            asset_version_id=str(value["asset_version_id"]),
            content_hash=str(value["content_hash"]),
            schema_version=str(value["schema_version"]),
            generation_operation_id=str(value["generation_operation_id"]),
            qualification_evidence_asset_version_id=str(
                value["qualification_evidence_asset_version_id"]
            ),
            qualification_hash=str(value["qualification_hash"]),
            activation_operation_id=str(value["activation_operation_id"]),
            candidate_asset_version_ids=tuple(
                str(item) for item in value["candidate_asset_version_ids"]
            ),
            selection_reason=tuple(str(item) for item in value["selection_reason"]),
            selection_basis=str(value.get("selection_basis") or "INDEPENDENT_COMPARISON"),
        )

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["role"] = self.role.value
        value["candidate_asset_version_ids"] = list(
            self.candidate_asset_version_ids
        )
        value["selection_reason"] = list(self.selection_reason)
        if self.selection_basis == "INDEPENDENT_COMPARISON":
            value.pop("selection_basis")
        return value


@dataclass(frozen=True, slots=True)
class StoryFormationInput:
    layers: tuple[FormationLayerInput, ...] = ()
    book_design_asset_version_id: str = ""
    book_design_content_hash: str = ""
    creative_brief_asset_version_id: str = ""
    creative_brief_content_hash: str = ""
    generation_policy: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        by_role = {item.role: item for item in self.layers}
        if self.creative_brief_asset_version_id:
            policy = dict(self.generation_policy or {})
            if self.layers or self.book_design_asset_version_id or len(self.creative_brief_content_hash) != 71 or not self.creative_brief_content_hash.startswith("sha256:"):
                raise ValueError("Generated Formation requires one hash-bound brief and no prequalified layers")
            base_fields = {
                "contract_version",
                "approval_mode",
                "creative_candidates",
                "target_chapters",
                "title",
            }
            contract_version = str(policy.get("contract_version") or "")
            if contract_version in {"formation-generation.v4", "formation-generation.v5", "formation-generation.v7"}:
                creation = policy.get("creation_input_policy")
                if (not isinstance(creation, dict) or creation.get("contract_version") != "creation-input-policy.v1"
                        or not isinstance(creation.get("profiles"), dict)
                        or not creation["profiles"].get("production_profile", {}).get("content", {}).get("language_contract")):
                    raise ValueError("Creation requires frozen profiles and the current input language contract")
                if creation.get("codex_input_only_policy") not in {None, "codex-input-only.v2"}:
                    raise ValueError("Creation requires a supported frozen structured generation policy")
                base_fields.add("creation_input_policy")
            if contract_version == "formation-generation.v5":
                if policy.get("creative_selection") not in {"AUTHOR_COMPARISON", "AUTHOR_DIRECTION"} or policy.get("approval_mode") != "AUTO":
                    raise ValueError("Creation must freeze its author comparison boundary")
                base_fields.add("creative_selection")
            if contract_version == "formation-generation.v7":
                from novel_forge.modules.story_planning_runtime.narrative_search import validate_search_selection_policy
                if policy.get("creative_selection") != "AUTO_COMPARISON" or policy.get("approval_mode") != "AUTO":
                    raise ValueError("Automatic direction comparison requires explicit scoped preauthorization")
                validate_search_selection_policy(policy.get("selection_policy"))
                directives = policy.get("strategy_directives")
                if (not isinstance(directives, list) or len(directives) != policy.get("creative_candidates")
                        or any(not isinstance(value, str) or not value.strip() for value in directives) or len(set(directives)) != len(directives)):
                    raise ValueError("Automatic comparison requires exact distinct bounded strategies")
                base_fields.update({"creative_selection", "selection_policy", "strategy_directives"})
            author_direction = contract_version == "formation-generation.v5" and policy.get("creative_selection") == "AUTHOR_DIRECTION"
            if contract_version == "formation-generation.v3" or author_direction:
                selected = policy.get("author_creative_foundation")
                if (not isinstance(selected, dict) or set(selected) != {"asset_version_id", "content_hash"}
                        or not str(selected["asset_version_id"]).strip() or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(selected["content_hash"]))
                        or not author_direction and policy.get("approval_mode") != "REVIEW_PLAN" or policy.get("creative_candidates") != 1):
                    raise ValueError("Author-directed Formation requires one exact selected input and manual review")
                base_fields.add("author_creative_foundation")
            expected_fields = (
                base_fields | {"auto_authorization"}
                if contract_version in {"formation-generation.v2", "formation-generation.v4", "formation-generation.v5", "formation-generation.v7"}
                and policy.get("approval_mode") == "AUTO"
                else base_fields
            )
            if (
                set(policy) != expected_fields
                or contract_version
                not in {"formation-generation.v1", "formation-generation.v2", "formation-generation.v3", "formation-generation.v4", "formation-generation.v5", "formation-generation.v7"}
                or policy["approval_mode"] not in {"AUTO", "REVIEW_PLAN"}
                or not isinstance(policy["creative_candidates"], int)
                or isinstance(policy["creative_candidates"], bool)
                or not (1 if contract_version == "formation-generation.v3" or author_direction else 2) <= policy["creative_candidates"] <= 4
                or not isinstance(policy["target_chapters"], int)
                or isinstance(policy["target_chapters"], bool)
                or not 1 <= policy["target_chapters"] <= 10000
                or not str(policy["title"]).strip()
            ):
                raise ValueError("Formation generation policy requires bounded search, scope and explicit approval mode")
            if "auto_authorization" in policy:
                policy["auto_authorization"] = canonical_formation_auto_authorization(
                    policy["auto_authorization"]
                )
            object.__setattr__(self, "generation_policy", MappingProxyType(policy))
        elif self.creative_brief_content_hash or self.generation_policy:
            raise ValueError("Formation generation policy requires a frozen creative brief")
        elif len(by_role) != len(self.layers) or set(by_role) != set(FoundationRole):
            raise ValueError("Story Formation requires one input for every Foundation role")
        has_version = bool(self.book_design_asset_version_id.strip())
        has_hash = bool(self.book_design_content_hash.strip())
        if has_version != has_hash or (
            has_hash
            and (
                len(self.book_design_content_hash) != 71
                or not self.book_design_content_hash.startswith("sha256:")
            )
        ):
            raise ValueError(
                "Story Formation BookDesign input must be absent or exactly hash-bound"
            )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "StoryFormationInput":
        legacy = {
            "layers",
            "book_design_asset_version_id",
            "book_design_content_hash",
        }
        current = legacy | {"creative_brief_asset_version_id", "creative_brief_content_hash", "generation_policy"}
        if set(value) not in (legacy, current) or not isinstance(value.get("layers"), list):
            raise KernelError(
                "STORY_FORMATION_INPUT_INVALID",
                "Story Formation input fields must match exactly",
            )
        return cls(
            layers=tuple(FormationLayerInput.from_mapping(item) for item in value["layers"]),
            book_design_asset_version_id=str(value["book_design_asset_version_id"]),
            book_design_content_hash=str(value["book_design_content_hash"]),
            creative_brief_asset_version_id=str(value.get("creative_brief_asset_version_id") or ""),
            creative_brief_content_hash=str(value.get("creative_brief_content_hash") or ""),
            generation_policy=value.get("generation_policy"),
        )

    @property
    def by_role(self) -> dict[FoundationRole, FormationLayerInput]:
        return {item.role: item for item in self.layers}

    def to_dict(self) -> dict[str, Any]:
        return {
            "layers": [item.to_dict() for item in self.layers],
            "book_design_asset_version_id": self.book_design_asset_version_id,
            "book_design_content_hash": self.book_design_content_hash,
            **({"creative_brief_asset_version_id": self.creative_brief_asset_version_id, "creative_brief_content_hash": self.creative_brief_content_hash, "generation_policy": dict(self.generation_policy or {})} if self.creative_brief_asset_version_id else {}),
        }

    def require_admission_scope(
        self,
        *,
        project_id: str,
        workspace_id: str,
        book_id: str,
        formation_run_id: str,
        admitted_by_principal_id: str,
        admitted_by_principal_type: PrincipalType,
    ) -> None:
        policy = dict(self.generation_policy or {})
        if policy.get("approval_mode") != "AUTO":
            return
        if policy.get("contract_version") not in {"formation-generation.v2", "formation-generation.v4", "formation-generation.v5", "formation-generation.v7"}:
            raise ValueError(
                "AUTO Formation requires a frozen scoped authorization contract"
            )
        authorization = canonical_formation_auto_authorization(
            policy.get("auto_authorization")
        )
        expected_scope = (
            project_id,
            workspace_id,
            book_id,
            formation_run_id,
            admitted_by_principal_id,
        )
        actual_scope = (
            authorization["project_id"],
            authorization["workspace_id"],
            authorization["book_id"],
            authorization["formation_run_id"],
            authorization["authorized_by_principal_id"],
        )
        if actual_scope != expected_scope:
            raise ValueError("AUTO Formation authorization differs from Formation scope")
        if admitted_by_principal_type is not PrincipalType.LOCAL_OPERATOR:
            raise ValueError("AUTO Formation must be authorized by a trusted operator")

    @property
    def auto_authorization(self) -> dict[str, Any]:
        policy = dict(self.generation_policy or {})
        value = policy.get("auto_authorization")
        return canonical_formation_auto_authorization(value) if value else {}

    @property
    def digest(self) -> str:
        return _canonical_hash(self.to_dict())


def build_formation_auto_decision_evidence(
    *,
    frozen: StoryFormationInput,
    action: str,
    candidate_asset_version_id: str,
    candidate_content_hash: str,
    executed_by_principal_id: str,
) -> dict[str, Any]:
    return build_scoped_auto_decision_evidence(
        authorization=frozen.auto_authorization,
        formation_input_digest=frozen.digest,
        action=action,
        candidate_asset_version_id=candidate_asset_version_id,
        candidate_content_hash=candidate_content_hash,
        executed_by_principal_id=executed_by_principal_id,
    )


def require_worker_formation_auto_decision(
    *,
    principal: Principal,
    evidence: Mapping[str, Any] | None,
    project_id: str,
    workspace_id: str,
    book_id: str,
    action: str,
    candidate_asset_version_id: str,
    candidate_content_hash: str,
) -> None:
    require_worker_scoped_auto_decision(
        principal=principal,
        evidence=evidence,
        project_id=project_id,
        workspace_id=workspace_id,
        book_id=book_id,
        action=action,
        candidate_asset_version_id=candidate_asset_version_id,
        candidate_content_hash=candidate_content_hash,
    )


__all__ = [
    "FORMATION_SEQUENCE",
    "FORMATION_AUTO_ACTIONS",
    "FormationLayerInput",
    "STORY_FORMATION_POLICY_VERSION",
    "StoryFormationInput",
    "StoryFormationStage",
    "build_formation_auto_decision_evidence",
    "deterministic_story_formation_run_id",
    "require_worker_formation_auto_decision",
]
