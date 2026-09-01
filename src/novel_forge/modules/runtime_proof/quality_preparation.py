from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from novel_forge.api.authority_dependencies import (
    build_book_design_authority_application,
    build_book_production_composition,
    build_chapter_authority_application,
    build_production_execution_composition,
)
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.authority_security import Principal, PrincipalType
from novel_forge.modules.book_authority import (
    OpenBookProductionRequest,
    StartBookProductionCommand,
)
from novel_forge.modules.book_design_authority import (
    FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
    BookDesignAuthorityApplication,
    BookDesignAuthorityCommand,
    BookDesignAuthorityQuery,
    FormationLayerInput,
    FoundationRole,
    StartStoryFormationCommand,
    StoryFormationApplication,
    StoryFormationInput,
)
from novel_forge.modules.capability_packs.validation_deployment import (
    VALIDATION_PACK_PERMISSIONS,
    install_chapter_validation_pack,
    install_longform_validation_pack,
    register_validation_runtime_definitions,
)
from novel_forge.modules.capability_packs.longform_profiles import (
    build_narrative_evaluation_pack_profile,
    build_reader_outcome_pack_profile,
    build_story_planning_pack_profile,
)
from novel_forge.modules.content_authority import (
    CONTENT_CODECS,
    ContentAuthorityApplication,
    ContentOperationRequest,
)
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.chapter_quality_authority import QUALITY_DIMENSIONS
from novel_forge.modules.project_authority import (
    ProjectAuthorityApplication,
    ProjectAuthorityCommand,
)
from novel_forge.modules.production_preparation.foundation_context import (
    project_character_foundation_context,
)
from novel_forge.modules.runtime_job import RuntimeJobAuthority
from novel_forge.modules.story_design_authority import (
    NARRATIVE_QUALIFICATION_SCHEMA_VERSION,
    DesignTransition,
    NarrativeSemanticEvaluationApplication,
    NarrativeSemanticEvaluationCommand,
    PlanningScope,
    PostgresStoryDesignAssetAuthority,
    StoryDesignTransitionCommand,
    required_qualification_profiles,
)
from novel_forge.modules.story_design_authority.validators import (
    validate_story_design_candidate,
)
from novel_forge.modules.story_planning_runtime import GENERATOR_INPUT_ROLES
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.foundation_repositories import (
    require_current_foundation_set,
)
from novel_forge.workers.book_authority import (
    execute_book_opening_claim,
    execute_story_formation_claim,
)

from .quality_campaign import (
    BoundedQualityCampaignProfile,
    bounded_quality_chapter_fixture_response,
    bounded_quality_planning_fixture_response,
)


QUALITY_BOOK_CONTRACT_SCHEMA = "novel-forge.bounded-quality-book-contract.v1"
_FOUNDATION_AUTHORING = {
    FoundationRole.CREATIVE_FOUNDATION: (
        "story_design.creative_foundation.author",
        "creative.candidates.generate",
        "creative_foundation",
    ),
    FoundationRole.THEME_CONTRACT: (
        "story_design.theme_contract.author",
        "theme.candidates.generate",
        "theme_contract",
    ),
    FoundationRole.ENDING_INTENT: (
        "story_design.ending_intent.author",
        "ending.intent.generate",
        "ending_intent",
    ),
    FoundationRole.READER_PROMISE: (
        "story_design.reader_promise.author",
        "reader.promise.generate",
        "reader_promise",
    ),
    FoundationRole.WORLD_BIBLE: (
        "story_design.world_bible.author",
        "world.design.generate",
        "world_bible",
    ),
    FoundationRole.CHARACTER_CAST: (
        "story_design.character_cast.author",
        "character.cast.generate",
        "character_cast",
    ),
}
_BOOTSTRAP_OPERATIONS = frozenset(
    {
        "book.production_profile.author",
        "book.previous_volume_outcome.author",
        "book.previous_chapter_group_outcome.author",
        "book.previous_chapter_outcome.author",
        "book.arc_portfolio.author",
        "book.ending_reachability.author",
        "book.character_arc_portfolio.author",
        "book.conflict_state.author",
        "book.foreshadowing_ledger.author",
        "book.reader_segment.author",
        "book.reader_contract.author",
        "book.reader_state.author",
        "book.character_state.author",
        "book.foreshadowing_state.author",
        "book.quality_trend.author",
        "book.reward_ledger.author",
        "book.promise_ledger.author",
    }
)
_CHAPTER_PROFILE_OPERATIONS = frozenset(
    {
        "chapter.style_policy.author",
        "chapter.quality_rubric.author",
        "chapter.platform_profile.author",
        "chapter.operator_checklist.author",
    }
)
_OPENING_ROLES = frozenset(
    role
    for generator in (
        "book_plan.generate",
        "volume_plan.generate",
        "arc_plan.generate",
    )
    for role in GENERATOR_INPUT_ROLES[generator]
    if role not in {"book_plan", "volume_plan"}
)
_FORBIDDEN_EVIDENCE_KEYS = frozenset(
    {
        "human_verified",
        "ground_truth_claimed",
        "provider_generated",
        "real_provider_proven",
        "production_verified",
        "accepted_actual",
    }
)


def _canonical(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{field} must be a non-empty object")
    return {str(key): item for key, item in value.items()}


def _required(value: Any, field: str) -> str:
    result = str(value or "").strip()
    if not result:
        raise ValueError(f"{field} is required")
    return result


def _contains_forbidden_claim(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(
            (str(key) in _FORBIDDEN_EVIDENCE_KEYS and item is True)
            or _contains_forbidden_claim(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_claim(item) for item in value)
    return False


@dataclass(frozen=True, slots=True)
class BoundedQualityBookContract:
    _canonical_payload: str

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        *,
        campaign_profile: BoundedQualityCampaignProfile,
    ) -> "BoundedQualityBookContract":
        if not isinstance(raw, Mapping):
            raise ValueError("bounded Quality Book contract must be an object")
        expected_root = {
            "schema_version",
            "contract_version",
            "book",
            "foundation",
            "book_design",
            "bootstrap_inputs",
            "chapter_profiles",
        }
        if set(raw) != expected_root:
            raise ValueError("bounded Quality Book contract fields must match exactly")
        payload = json.loads(_canonical(dict(raw)))
        if payload["schema_version"] != QUALITY_BOOK_CONTRACT_SCHEMA:
            raise ValueError("bounded Quality Book contract schema is unsupported")
        if int(payload["contract_version"] or 0) != 1:
            raise ValueError("bounded Quality Book contract version must equal one")
        book = _mapping(payload["book"], "book")
        if set(book) != {
            "title",
            "language",
            "target_chapters",
            "production_profile_id",
            "arc_logical_keys",
        }:
            raise ValueError("bounded Quality Book identity fields differ")
        profile_book = campaign_profile.to_dict()["book"]
        if (
            book["title"] != profile_book["title"]
            or book["language"] != profile_book["language"]
            or int(book["target_chapters"] or 0) != 8
            or int(book["target_chapters"]) != int(profile_book["target_chapters"])
            or not _required(book["production_profile_id"], "production_profile_id")
            or not isinstance(book["arc_logical_keys"], list)
            or len(book["arc_logical_keys"]) not in {1, 2}
            or len(set(str(item) for item in book["arc_logical_keys"]))
            != len(book["arc_logical_keys"])
            or any(not str(item).strip() for item in book["arc_logical_keys"])
        ):
            raise ValueError("Book contract differs from the bounded campaign profile")
        foundation = _mapping(payload["foundation"], "foundation")
        if set(foundation) != {
            "selection_policy",
            "layers",
            "creative_alternate",
        } or not _required(foundation["selection_policy"], "selection_policy"):
            raise ValueError("Foundation contract fields differ")
        layers = foundation["layers"]
        if not isinstance(layers, list) or len(layers) != len(FoundationRole):
            raise ValueError("Foundation contract requires six selected layers")
        observed_roles: list[FoundationRole] = []
        for index, item in enumerate(layers):
            layer = _mapping(item, f"foundation.layers[{index}]")
            role = FoundationRole(str(layer.get("role") or ""))
            observed_roles.append(role)
            cls._validate_foundation_candidate(layer, role=role)
        if observed_roles != list(FoundationRole):
            raise ValueError("Foundation selected layers must follow canonical order")
        alternate = _mapping(
            foundation["creative_alternate"], "foundation.creative_alternate"
        )
        if (
            FoundationRole(str(alternate.get("role") or ""))
            is not FoundationRole.CREATIVE_FOUNDATION
        ):
            raise ValueError("Creative Search alternate must be a Creative Foundation")
        cls._validate_foundation_candidate(
            alternate,
            role=FoundationRole.CREATIVE_FOUNDATION,
        )
        if alternate["logical_key"] == layers[0]["logical_key"]:
            raise ValueError("Creative Search candidates require distinct identities")
        book_design = _mapping(payload["book_design"], "book_design")
        if set(book_design) != {
            "book_invariants",
            "cross_layer_synthesis",
            "narrative_dna",
        } or any(
            not isinstance(book_design[field], (list, dict)) for field in book_design
        ):
            raise ValueError("BookDesign synthesis contract is incomplete")
        bootstrap = _mapping(payload["bootstrap_inputs"], "bootstrap_inputs")
        profiles = _mapping(payload["chapter_profiles"], "chapter_profiles")
        if set(bootstrap) != _BOOTSTRAP_OPERATIONS:
            raise ValueError("Book bootstrap operations are incomplete")
        if set(profiles) != _CHAPTER_PROFILE_OPERATIONS:
            raise ValueError("Chapter profile operations are incomplete")
        for operation, raw_content in {**bootstrap, **profiles}.items():
            content = _mapping(raw_content, operation)
            if (
                not _required(content.get("type"), f"{operation}.type")
                or not _required(
                    content.get("safe_summary"), f"{operation}.safe_summary"
                )
                or not isinstance(content.get("structured_facts"), list)
                or _contains_forbidden_claim(content)
                or content.get("raw_source") is True
                or content.get("source_expression_included") is True
            ):
                raise ValueError(f"{operation} violates the source/evidence boundary")
        if (
            bootstrap["book.production_profile.author"].get("profile_id")
            != book["production_profile_id"]
            or bootstrap["book.production_profile.author"].get("target_chapter_count")
            != 8
            or dict(
                bootstrap["book.production_profile.author"].get("language_contract")
                or {}
            ).get("language")
            != book["language"]
        ):
            raise ValueError("production profile differs from the Book contract")
        return cls(_canonical_payload=_canonical(payload))

    @staticmethod
    def _validate_foundation_candidate(
        layer: Mapping[str, Any],
        *,
        role: FoundationRole,
    ) -> None:
        if set(layer) != {
            "role",
            "logical_key",
            "selection_reason",
            "candidate_payload",
            "review_assertions",
        }:
            raise ValueError(f"{role.value} contract fields must match exactly")
        logical_key = _required(layer["logical_key"], f"{role.value}.logical_key")
        if any(character.isspace() for character in logical_key):
            raise ValueError("Foundation logical keys cannot contain whitespace")
        _required(layer["selection_reason"], f"{role.value}.selection_reason")
        candidate = _mapping(
            layer["candidate_payload"], f"{role.value}.candidate_payload"
        )
        if role is FoundationRole.CHARACTER_CAST:
            try:
                project_character_foundation_context(
                    asset_type="character_cast",
                    content=candidate,
                    source_asset_version_id="bounded-quality-book-contract",
                )
            except KernelError as exc:
                raise ValueError(
                    "CHARACTER_CAST requires executable canonical names, aliases, and pronouns"
                ) from exc
        if _contains_forbidden_claim(candidate):
            raise ValueError("Foundation candidate cannot claim external evidence")
        generator = _FOUNDATION_AUTHORING[role][1]
        criteria = {
            criterion
            for profile in required_qualification_profiles(generator)
            for criterion in profile.criteria
        }
        assertions = _mapping(
            layer["review_assertions"], f"{role.value}.review_assertions"
        )
        if set(assertions) != criteria or any(
            len(str(rationale).strip()) < 20 for rationale in assertions.values()
        ):
            raise ValueError(
                f"{role.value} requires one substantive assertion per criterion"
            )

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical_payload)


def load_quality_book_contract(
    path: str | Path,
    *,
    campaign_profile: BoundedQualityCampaignProfile,
) -> BoundedQualityBookContract:
    payload = json.loads(Path(path).expanduser().resolve().read_text(encoding="utf-8"))
    return BoundedQualityBookContract.from_mapping(
        payload,
        campaign_profile=campaign_profile,
    )


@dataclass(frozen=True, slots=True)
class BoundedQualityPreparationResult:
    campaign_id: str
    project_id: str
    workspace_id: str
    book_id: str
    book_run_id: str
    opening_run_id: str
    exact_release_sha: str
    book_contract_digest: str
    capability_pack_manifest: dict[str, dict[str, str]]
    foundation_lineage: dict[str, Any]
    planning_lineage: dict[str, Any]
    initial_state_lineage: dict[str, str]
    runtime_env: dict[str, str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "novel-forge.bounded-quality-preparation-result.v1",
            "campaign_id": self.campaign_id,
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "book_id": self.book_id,
            "book_run_id": self.book_run_id,
            "opening_run_id": self.opening_run_id,
            "exact_release_sha": self.exact_release_sha,
            "book_contract_digest": self.book_contract_digest,
            "capability_pack_manifest": self.capability_pack_manifest,
            "foundation_lineage": self.foundation_lineage,
            "planning_lineage": self.planning_lineage,
            "initial_state_lineage": self.initial_state_lineage,
            "runtime_env": self.runtime_env,
        }


def build_quality_preparation_environment(
    *,
    base_env: Mapping[str, str],
    profile: BoundedQualityCampaignProfile,
    mode: str,
    project_id: str,
    commit_sha: str,
    application_build_id: str = "bounded-quality-preparation",
) -> dict[str, str]:
    if mode not in {"scripted", "real"}:
        raise ValueError("Quality preparation mode must be scripted or real")
    values = {str(key): str(value) for key, value in base_env.items()}
    routes = profile.provider_routes[mode]
    planning = routes["planning"]
    generator = routes["generator"]
    reviewer = routes["reviewer"]
    judge = routes["judge"]
    reader = routes["reader_proxy"]
    pack_scope = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:12]
    values.update(
        {
            "NOVEL_FORGE_APPLICATION_BUILD_ID": application_build_id,
            "NOVEL_FORGE_COMMIT_SHA": commit_sha,
            "NOVEL_FORGE_AUTHORITY_PROJECT_SCOPE": project_id,
            "NOVEL_FORGE_LOCAL_OPERATOR_PRINCIPAL_ID": (
                f"quality-operator:{project_id}"
            ),
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_PRINCIPAL_ID": (
                f"quality-provider-evaluator:{project_id}"
            ),
            "NOVEL_FORGE_MODEL_PROVIDER": str(generator["provider"]),
            "NOVEL_FORGE_PLANNING_PROVIDER": str(planning["provider"]),
            "NOVEL_FORGE_PLANNING_MODEL": str(planning["model"]),
            "NOVEL_FORGE_PLANNING_REASONING_EFFORT": str(planning["reasoning_effort"]),
            "NOVEL_FORGE_DRAFT_PROVIDER": str(generator["provider"]),
            "NOVEL_FORGE_DRAFT_MODEL": str(generator["model"]),
            "NOVEL_FORGE_REVISION_PROVIDER": str(generator["provider"]),
            "NOVEL_FORGE_REVISION_MODEL": str(generator["model"]),
            "NOVEL_FORGE_REVIEW_PROVIDER": str(reviewer["provider"]),
            "NOVEL_FORGE_REVIEW_MODEL": str(reviewer["model"]),
            "NOVEL_FORGE_REREVIEW_PROVIDER": str(reviewer["provider"]),
            "NOVEL_FORGE_REREVIEW_MODEL": str(reviewer["model"]),
            "NOVEL_FORGE_CANON_EXTRACTION_PROVIDER": str(reviewer["provider"]),
            "NOVEL_FORGE_CANON_EXTRACTION_MODEL": str(reviewer["model"]),
            "NOVEL_FORGE_QUALITY_PROVIDER": str(judge["provider"]),
            "NOVEL_FORGE_QUALITY_MODEL": str(judge["model"]),
            "NOVEL_FORGE_READER_OUTCOME_PROVIDER": str(reader["provider"]),
            "NOVEL_FORGE_READER_OUTCOME_MODEL": str(reader["model"]),
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_PROVIDER": str(reviewer["provider"]),
            "NOVEL_FORGE_NARRATIVE_EVALUATOR_MODEL": str(reviewer["model"]),
            "NOVEL_FORGE_REASONING_EFFORT": str(generator["reasoning_effort"]),
            "NOVEL_FORGE_NARRATIVE_SEMANTIC_EVALUATION_REASONING_EFFORT": str(
                reviewer["reasoning_effort"]
            ),
            "NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID": (
                f"quality_{pack_scope}_story_planning"
            ),
            "NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID": (
                f"quality_{pack_scope}_chapter_generation"
            ),
            "NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID": (
                f"quality_{pack_scope}_reader_outcome"
            ),
            "NOVEL_FORGE_NARRATIVE_EVALUATION_CAPABILITY_PACK_ID": (
                f"quality_{pack_scope}_narrative_evaluation"
            ),
        }
    )
    budget = profile.to_dict()["budget_policy"]
    values.update(
        {
            "NOVEL_FORGE_PROVIDER_MAX_COST_PER_CALL": str(
                budget["cost_limit_per_call_usd"]
            ),
            "NOVEL_FORGE_OPERATION_PROVIDER_CAP": str(
                budget["cost_limit_per_operation_usd"]
            ),
            "NOVEL_FORGE_CHAPTER_PROVIDER_CAP": str(
                budget["cost_limit_per_chapter_usd"]
            ),
            "NOVEL_FORGE_PROJECT_DAILY_PROVIDER_CAP": str(budget["cost_limit_usd"]),
            "NOVEL_FORGE_PROVIDER_DAILY_CAP": str(budget["cost_limit_usd"]),
        }
    )
    if mode == "scripted":
        values["NOVEL_FORGE_ENVIRONMENT"] = "test"
        values["NOVEL_FORGE_TEST_ALLOW_SCRIPTED_NARRATIVE_EVALUATION_FIXTURE"] = "true"
    elif values.get("NOVEL_FORGE_ENVIRONMENT") != "validation":
        raise ValueError("real Quality preparation requires validation environment")
    return values


class BoundedQualityCampaignPreparer:
    def __init__(
        self,
        *,
        database_url: str,
        repository_root: str | Path,
        settings: IndustrialSettings,
        runtime_env: Mapping[str, str],
        profile: BoundedQualityCampaignProfile,
        book_contract: BoundedQualityBookContract,
        campaign_id: str,
        exact_release_sha: str,
        mode: str,
    ) -> None:
        if (
            not database_url
            or not campaign_id.strip()
            or len(exact_release_sha) != 40
            or mode not in {"scripted", "real"}
        ):
            raise ValueError("bounded Quality preparation identity is incomplete")
        self.database_url = database_url
        self.repository_root = Path(repository_root).resolve()
        self.settings = settings
        self.profile = profile
        self.book_contract = book_contract
        self.campaign_id = campaign_id
        self.exact_release_sha = exact_release_sha
        self.mode = mode
        identity = hashlib.sha256(
            f"{campaign_id}\x00{exact_release_sha}".encode("utf-8")
        ).hexdigest()[:16]
        self.project_id = f"quality-proof:{identity}"
        self.workspace_id = f"workspace:{self.project_id}"
        self.book_id = f"book:{self.project_id}"
        self.runtime_env = build_quality_preparation_environment(
            base_env=runtime_env,
            profile=profile,
            mode=mode,
            project_id=self.project_id,
            commit_sha=exact_release_sha,
        )
        self.build_id = self.runtime_env["NOVEL_FORGE_APPLICATION_BUILD_ID"]
        self.operator = self._principal(
            f"quality-operator:{self.project_id}",
            "project.authority.execute",
            "book_design.authority.execute",
            "book_design.authority.query",
            "book.authority.execute",
            "book.authority.approve_replan",
            "book.followup:*",
            "chapter.authority.execute",
            "story_design.authority.execute",
            "story_planning.authority.execute",
            "story_planning.authority.approve",
            "story_planning.authority.activate",
            "content.authority.execute",
            "content.operation:*",
            "external_effect.execute",
            "narrative_design.evaluate",
        )
        self.foundation_reviewer = self._principal(
            f"quality-foundation-reviewer:{self.project_id}",
            "content.authority.execute",
            "content.operation:story_design.review.author",
            "narrative_design.evaluate",
            "story_design.authority.execute",
        )
        self.compiler = self._principal(
            f"quality-pack-compiler:{self.project_id}",
            *sorted(VALIDATION_PACK_PERMISSIONS),
        )
        self.approver = self._principal(
            f"quality-pack-approver:{self.project_id}",
            *sorted(VALIDATION_PACK_PERMISSIONS),
        )
        self.agent_admin = self._principal(
            f"quality-agent-admin:{self.project_id}", "agent.authority.admin"
        )

    def _principal(self, principal_id: str, *permissions: str) -> Principal:
        return Principal(
            principal_id=principal_id,
            principal_type=PrincipalType.LOCAL_OPERATOR,
            permissions=frozenset(permissions),
            project_scope=frozenset({self.project_id}),
            authentication_source="bounded-quality-preparation",
        )

    def prepare(self) -> BoundedQualityPreparationResult:
        self._require_runtime_boundary()
        self._create_project_and_book()
        packs = self._install_packs()
        selected, creative_alternate = self._prepare_foundation_candidates()
        formation, waiting = self._run_story_formation(
            selected=selected,
            creative_alternate=creative_alternate,
        )
        authored_inputs = self._author_book_inputs()
        execution = build_production_execution_composition(
            self.settings,
            env=self.runtime_env,
            planning_fixture_factory=(
                bounded_quality_planning_fixture_response
                if self.mode == "scripted"
                else None
            ),
            chapter_fixture_factory=(
                bounded_quality_chapter_fixture_response
                if self.mode == "scripted"
                else None
            ),
        )
        try:
            design = self._activate_book_design(
                execution=execution,
                formation=formation,
                waiting=waiting,
            )
            chapter = build_chapter_authority_application(
                self.settings,
                execution=execution,
                env=self.runtime_env,
            )
            composition = build_book_production_composition(
                self.settings,
                principal=self.operator,
                execution=execution,
                env=self.runtime_env,
                chapter_application=chapter,
            )
            opened = self._open_book(
                composition=composition,
                selected=selected,
                design=design,
                authored_inputs=authored_inputs,
            )
            book_run_id = self._start_book_run(
                composition=composition,
                snapshot_id=str(opened["input_snapshot_id"]),
            )
        finally:
            execution.close()
        pack_manifest = {
            role: {
                "pack_id": str(item["pack_id"]),
                "deployment_id": str(item["deployment_id"]),
                "hash": str(item["manifest_hash"]),
            }
            for role, item in packs.items()
        }
        foundation_lineage = {
            "book_contract_digest": self.book_contract.digest,
            "formation_run_id": formation.require(self._formation_run_id())[
                "formation_run_id"
            ],
            "foundation_set_digest": design["foundation_set_digest"],
            "book_design_asset_version_id": design["asset_version_id"],
            "book_design_content_hash": design["content_hash"],
            "book_version": design["book_version"],
            "selected_layers": {
                role.value: {
                    key: value
                    for key, value in selected[role].items()
                    if key
                    in {
                        "asset_version_id",
                        "content_hash",
                        "qualification_evidence_asset_version_id",
                        "qualification_hash",
                        "activation_operation_id",
                    }
                }
                for role in FoundationRole
            },
            "creative_alternate_asset_version_id": creative_alternate[
                "asset_version_id"
            ],
        }
        planning_lineage = {
            "input_snapshot_id": opened["input_snapshot_id"],
            "book_plan_asset_version_id": opened["book_plan_version"],
            "volume_plan_asset_version_id": str(
                opened.get("current_volume_plan_version")
                or opened.get("volume_plan_version")
                or ""
            ),
            "volume_portfolio_plan_version_ids": list(
                opened.get("volume_portfolio_plan_versions") or ()
            ),
            "arc_plan_asset_version_ids": list(
                opened.get("current_relevant_arc_plan_versions")
                or opened.get("arc_plan_versions")
                or ()
            ),
            "arc_portfolio_plan_version_ids": list(
                opened.get("arc_portfolio_plan_versions") or ()
            ),
            "opening_search_ids": list(opened["search_ids"]),
        }
        return BoundedQualityPreparationResult(
            campaign_id=self.campaign_id,
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            book_id=self.book_id,
            book_run_id=book_run_id,
            opening_run_id=self._opening_run_id(),
            exact_release_sha=self.exact_release_sha,
            book_contract_digest=self.book_contract.digest,
            capability_pack_manifest=pack_manifest,
            foundation_lineage=foundation_lineage,
            planning_lineage=planning_lineage,
            initial_state_lineage={
                "story_state_asset_version_id": authored_inputs["story_state"],
                "canon_snapshot_asset_version_id": authored_inputs["canon_snapshot"],
                "campaign_contract_identity": authored_inputs[
                    "campaign_contract_identity"
                ],
            },
            runtime_env={
                key: value
                for key, value in self.runtime_env.items()
                if key.startswith("NOVEL_FORGE_")
                and not any(
                    marker in key
                    for marker in (
                        "SECRET",
                        "TOKEN",
                        "PASSWORD",
                        "API_KEY",
                        "CREDENTIAL",
                    )
                )
            },
        )

    def _require_runtime_boundary(self) -> None:
        if self.settings.database_url != self.database_url:
            raise ValueError("Quality preparer settings differ from PostgreSQL scope")
        provider = self.runtime_env.get("NOVEL_FORGE_MODEL_PROVIDER")
        if self.mode == "real" and (
            provider == "scripted_provider_v2"
            or self.runtime_env.get("NOVEL_FORGE_ENVIRONMENT") != "validation"
        ):
            raise ValueError(
                "real Quality preparation has no controlled Provider route"
            )
        if self.mode == "scripted" and provider != "scripted_provider_v2":
            raise ValueError("scripted Quality preparation requires the fixture route")

    def _create_project_and_book(self) -> None:
        book = self.book_contract.to_dict()["book"]
        ProjectAuthorityApplication(
            self.database_url,
            application_build_id=self.build_id,
            commit_sha=self.exact_release_sha,
        ).execute(
            ProjectAuthorityCommand(
                definition_name="project_lifecycle.create",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id=self.operator.principal_id,
                idempotency_key=f"{self.campaign_id}:project:create",
                trace_id=f"trace:{self.campaign_id}:project:create",
                correlation_id=self.campaign_id,
                payload={
                    "title": book["title"],
                    "stage": "PRODUCTION",
                    "config": {
                        "quality_campaign_id": self.campaign_id,
                        "book_contract_digest": self.book_contract.digest,
                        "bounded_target_chapters": 8,
                    },
                },
            ),
            principal=self.operator,
        )
        BookDesignAuthorityApplication(
            self.database_url,
            application_build_id=self.build_id,
            commit_sha=self.exact_release_sha,
        ).execute(
            BookDesignAuthorityCommand(
                definition_name="book.create",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                book_id=self.book_id,
                actor_id=self.operator.principal_id,
                service_identity="bounded-quality-preparation",
                idempotency_key=f"{self.campaign_id}:book:create",
                trace_id=f"trace:{self.campaign_id}:book:create",
                correlation_id=self.campaign_id,
                payload={
                    "schema_version": "book-authority.v1",
                    "title": book["title"],
                    "production_profile": {
                        "environment": (
                            "validation" if self.mode == "real" else "test"
                        ),
                        "campaign_id": self.campaign_id,
                        "target_chapters": 8,
                    },
                    "runtime_policy": {
                        "legacy_write": False,
                        "silent_fallback": False,
                        "background_continuation": False,
                    },
                    "release_identity": f"{self.build_id}@{self.exact_release_sha}",
                },
            ),
            principal=self.operator,
        )

    def _install_packs(self) -> dict[str, dict[str, Any]]:
        hashes = register_validation_runtime_definitions(
            self.database_url,
            application_build_id=self.build_id,
            commit_sha=self.exact_release_sha,
        )
        common = {
            "project_id": self.project_id,
            "workspace_id": self.workspace_id,
            "book_id": self.book_id,
            "application_build_id": self.build_id,
            "commit_sha": self.exact_release_sha,
            "compiler": self.compiler,
            "approver": self.approver,
            "agent_admin": self.agent_admin,
            "runtime_environment": self.runtime_env["NOVEL_FORGE_ENVIRONMENT"],
        }
        planning_id = self.runtime_env["NOVEL_FORGE_PLANNING_CAPABILITY_PACK_ID"]
        reader_id = self.runtime_env["NOVEL_FORGE_READER_OUTCOME_CAPABILITY_PACK_ID"]
        evaluator_id = self.runtime_env[
            "NOVEL_FORGE_NARRATIVE_EVALUATION_CAPABILITY_PACK_ID"
        ]
        chapter_id = self.runtime_env["NOVEL_FORGE_CHAPTER_CAPABILITY_PACK_ID"]
        return {
            "narrative_evaluation": install_longform_validation_pack(
                self.database_url,
                profile=build_narrative_evaluation_pack_profile(
                    self.repository_root,
                    operation_definition_hash=hashes["narrative_evaluation"],
                    pack_id=evaluator_id,
                ),
                pack_version="1.0.0",
                agent_generation=1,
                expected_activation_version=0,
                agent_domain="story_design",
                agent_scope_type="BOOK",
                **common,
            ),
            "planning": install_longform_validation_pack(
                self.database_url,
                profile=build_story_planning_pack_profile(
                    self.repository_root,
                    operation_definition_hash=hashes["planning"],
                    pack_id=planning_id,
                ),
                pack_version="1.5.0",
                agent_generation=1,
                expected_activation_version=0,
                agent_domain="story_planning",
                agent_scope_type="BOOK",
                **common,
            ),
            "reader_proxy": install_longform_validation_pack(
                self.database_url,
                profile=build_reader_outcome_pack_profile(
                    self.repository_root,
                    operation_definition_hash=hashes["reader_proxy"],
                    pack_id=reader_id,
                ),
                pack_version="1.1.0",
                agent_generation=1,
                expected_activation_version=0,
                agent_domain="reader_outcome",
                agent_scope_type="CHAPTER",
                **common,
            ),
            "chapter": install_chapter_validation_pack(
                self.database_url,
                repository_root=self.repository_root,
                pack_id_override=chapter_id,
                **common,
            ),
        }

    def _content_application(self) -> ContentAuthorityApplication:
        return ContentAuthorityApplication(
            self.database_url,
            application_build_id=self.build_id,
            commit_sha=self.exact_release_sha,
            integration_proven=CONTENT_CODECS,
            trusted_only=True,
        )

    def _prepare_foundation_candidates(
        self,
    ) -> tuple[
        dict[FoundationRole, dict[str, Any]],
        dict[str, Any],
    ]:
        foundation = self.book_contract.to_dict()["foundation"]
        selected: dict[FoundationRole, dict[str, Any]] = {}
        for layer in foundation["layers"]:
            role = FoundationRole(layer["role"])
            selected[role] = self._prepare_foundation_candidate(
                layer,
                role=role,
                parents={parent: selected[parent] for parent in role.required_parents},
                activate=True,
            )
        alternate = self._prepare_foundation_candidate(
            foundation["creative_alternate"],
            role=FoundationRole.CREATIVE_FOUNDATION,
            parents={},
            activate=False,
        )
        return selected, alternate

    def _prepare_foundation_candidate(
        self,
        layer: Mapping[str, Any],
        *,
        role: FoundationRole,
        parents: Mapping[FoundationRole, Mapping[str, Any]],
        activate: bool,
    ) -> dict[str, Any]:
        operation_name, generator, asset_type = _FOUNDATION_AUTHORING[role]
        parent_bindings = {
            parent.value: {
                "asset_version_id": str(item["asset_version_id"]),
                "content_hash": str(item["content_hash"]),
            }
            for parent, item in parents.items()
        }
        candidate_payload = {
            **dict(layer["candidate_payload"]),
            **(
                {"foundation_parent_bindings": parent_bindings}
                if parent_bindings
                else {}
            ),
        }
        content = {
            "schema_version": "story_design.authority.v1",
            "project_id": self.project_id,
            "generator_operation_name": generator,
            "planning_scope": PlanningScope.NOT_APPLICABLE.value,
            "logical_key": str(layer["logical_key"]),
            "operator_authored": True,
            "provider_generated": False,
            "candidate_payload": candidate_payload,
        }
        validation = validate_story_design_candidate(
            content=content,
            project_id=self.project_id,
            generator_operation_name=generator,
            planning_scope=PlanningScope.NOT_APPLICABLE,
            logical_key=str(layer["logical_key"]),
        )
        authored = self._content_application().execute(
            ContentOperationRequest(
                definition_name=operation_name,
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id=self.operator.principal_id,
                trace_id=f"trace:{self.campaign_id}:{layer['logical_key']}:author",
                correlation_id=self.campaign_id,
                idempotency_key=f"{self.campaign_id}:{layer['logical_key']}:author",
                payload={"content": content},
                input_assets=tuple(
                    {
                        "asset_version_id": str(item["asset_version_id"]),
                        "content_hash": str(item["content_hash"]),
                    }
                    for item in parents.values()
                ),
            ),
            principal=self.operator,
        )
        authority = PostgresStoryDesignAssetAuthority(
            self.database_url,
            application_build_id=self.build_id,
            commit_sha=self.exact_release_sha,
        )
        try:
            state: dict[str, Any] = authority.require(
                project_id=self.project_id,
                asset_version_id=authored.asset_version_id,
            )
        except KernelError as exc:
            if exc.code != "STORY_DESIGN_CANDIDATE_NOT_FOUND":
                raise
            state = {"version": 0}

        def transition(
            step: DesignTransition,
            evidence: Mapping[str, Any],
        ) -> dict[str, Any]:
            return authority.transition(
                StoryDesignTransitionCommand(
                    project_id=self.project_id,
                    workspace_id=self.workspace_id,
                    actor_id=self.operator.principal_id,
                    trace_id=f"trace:{self.campaign_id}:{layer['logical_key']}",
                    correlation_id=self.campaign_id,
                    idempotency_key=(
                        f"{self.campaign_id}:{layer['logical_key']}:{step.value}"
                    ),
                    asset_version_id=authored.asset_version_id,
                    content_hash=authored.content_hash,
                    logical_key=str(layer["logical_key"]),
                    generator_operation_name=generator,
                    transition=step,
                    planning_scope=PlanningScope.NOT_APPLICABLE,
                    expected_version=int(state["version"]),
                    source_kind="OPERATOR_AUTHORED",
                    evidence=dict(evidence),
                ),
                principal=self.operator,
            )

        if "lifecycle" not in state:
            state = transition(
                DesignTransition.ENROLL,
                {
                    "operation_id": authored.operation_id,
                    "authoring_operation_id": authored.operation_id,
                    "operator_authored": True,
                    "provider_generated": False,
                    "book_contract_digest": self.book_contract.digest,
                },
            )
        if state["lifecycle"] == "CANDIDATE":
            state = transition(
                DesignTransition.MATERIALIZE,
                {"passed": True, "validation": validation.to_evidence()},
            )
        if state["qualification"] == "PENDING":
            state = transition(
                DesignTransition.STRUCTURAL_VALIDATE,
                {"passed": True, "validation": validation.to_evidence()},
            )
        evaluation = self._operator_evaluation(layer, generator=generator)
        review = self._content_application().execute(
            ContentOperationRequest(
                definition_name="story_design.review.author",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id=self.foundation_reviewer.principal_id,
                trace_id=f"trace:{self.campaign_id}:{layer['logical_key']}:review",
                correlation_id=self.campaign_id,
                idempotency_key=f"{self.campaign_id}:{layer['logical_key']}:review",
                payload={
                    "candidate_asset_version_id": authored.asset_version_id,
                    "candidate_content_hash": authored.content_hash,
                    "evaluation": evaluation,
                    "review_rationale": (
                        "Independent operator design review of every frozen criterion; "
                        "this is not human preference, Ground Truth, or Provider evidence."
                    ),
                },
                input_assets=(
                    {
                        "asset_version_id": authored.asset_version_id,
                        "content_hash": authored.content_hash,
                    },
                ),
            ),
            principal=self.foundation_reviewer,
        )
        semantic = NarrativeSemanticEvaluationApplication(
            self.database_url,
            application_build_id=self.build_id,
            commit_sha=self.exact_release_sha,
            allow_scripted_fixture=False,
        ).execute(
            NarrativeSemanticEvaluationCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                book_id=self.book_id,
                actor_id=self.foundation_reviewer.principal_id,
                candidate_asset_version_id=authored.asset_version_id,
                generation_operation_id=authored.operation_id,
                generator_operation_name=generator,
                candidate_content_hash=authored.content_hash,
                evaluator_execution_class="OPERATOR_REVIEW",
                evaluation=evaluation,
                evidence_asset_version_ids=(review.asset_version_id,),
                idempotency_key=(
                    f"{self.campaign_id}:{layer['logical_key']}:semantic-evaluation"
                ),
                trace_id=(f"trace:{self.campaign_id}:{layer['logical_key']}:semantic"),
                correlation_id=self.campaign_id,
            ),
            principal=self.foundation_reviewer,
            caller_permission="story_design.authority.execute",
        )
        if state["qualification"] == "STRUCTURALLY_VALID":
            state = transition(
                DesignTransition.SEMANTIC_VALIDATE,
                {
                    "passed": True,
                    "evaluation_asset_version_id": (
                        semantic.lineage.evaluation_asset_version_id
                    ),
                    "qualification_hash": semantic.qualification.qualification_hash,
                },
            )
        if state["qualification"] == "SEMANTICALLY_VALID":
            state = transition(DesignTransition.QUALIFY, {"passed": True})
        if activate:
            if state["approval"] == "NOT_REQUESTED":
                state = transition(
                    DesignTransition.SUBMIT_APPROVAL,
                    {"passed": True},
                )
            if state["approval"] == "PENDING":
                state = transition(DesignTransition.APPROVE, {"passed": True})
            if state["lifecycle"] == "MATERIALIZED":
                state = transition(DesignTransition.ACTIVATE, {"passed": True})
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT candidate.schema_version, evaluation.content_hash
                FROM authority_asset_version AS candidate
                JOIN authority_asset_version AS evaluation
                  ON evaluation.asset_version_id=%s
                WHERE candidate.asset_version_id=%s
                """,
                [
                    semantic.lineage.evaluation_asset_version_id,
                    authored.asset_version_id,
                ],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise RuntimeError("operator-authored Foundation AssetVersion disappeared")
        if activate and (
            state["lifecycle"] != "ACTIVE"
            or state["qualification"] != "QUALIFIED"
            or state["approval"] != "APPROVED"
        ):
            raise RuntimeError("selected Foundation candidate did not activate")
        if not activate and state["qualification"] != "QUALIFIED":
            raise RuntimeError("Creative Search alternate did not qualify")
        return {
            "role": role.value,
            "asset_type": asset_type,
            "asset_version_id": authored.asset_version_id,
            "content_hash": authored.content_hash,
            "schema_version": str(row[0]),
            "generation_operation_id": authored.operation_id,
            "qualification_evidence_asset_version_id": (
                semantic.lineage.evaluation_asset_version_id
            ),
            # WHY: Story Design's qualification_hash summarizes the semantic
            # receipts. Formation binds the complete immutable evaluation
            # AssetVersion and therefore requires its distinct content hash.
            "qualification_hash": str(row[1]),
            "activation_operation_id": (
                str(state["updated_by_operation_id"]) if activate else ""
            ),
            "logical_key": str(layer["logical_key"]),
            "selection_reason": str(layer["selection_reason"]),
        }

    def _operator_evaluation(
        self,
        layer: Mapping[str, Any],
        *,
        generator: str,
    ) -> dict[str, Any]:
        assertions = dict(layer["review_assertions"])
        return {
            "schema_version": NARRATIVE_QUALIFICATION_SCHEMA_VERSION,
            "evaluations": [
                {
                    "layer": profile.layer.value,
                    "profile_id": profile.profile_id,
                    "profile_version": profile.profile_version,
                    "profile_hash": profile.profile_hash,
                    "capability_id": profile.capability_id,
                    "skill_ref": profile.skill_ref,
                    "criteria": [
                        {
                            "criterion": criterion,
                            "verdict": "PASS",
                            "rationale": str(assertions[criterion]),
                            "evidence_refs": [
                                (
                                    f"book-contract:{self.book_contract.digest}:"
                                    f"{layer['logical_key']}:{criterion}"
                                )
                            ],
                            "repair_directive": "",
                        }
                        for criterion in profile.criteria
                    ],
                }
                for profile in required_qualification_profiles(generator)
            ],
        }

    def _run_story_formation(
        self,
        *,
        selected: Mapping[FoundationRole, Mapping[str, Any]],
        creative_alternate: Mapping[str, Any],
    ) -> tuple[StoryFormationApplication, dict[str, Any]]:
        formation = StoryFormationApplication(
            self.database_url,
            application_build_id=self.build_id,
            commit_sha=self.exact_release_sha,
        )
        formation_run_id = ""
        try:
            existing_run = formation.require(self._formation_run_id())
        except KernelError as exc:
            if exc.code != "STORY_FORMATION_NOT_FOUND":
                raise
        else:
            formation_run_id = str(existing_run["formation_run_id"])
            if existing_run["lifecycle"] in {"WAITING_APPROVAL", "READY"}:
                return formation, existing_run
            if existing_run["lifecycle"] in {"FAILED", "ABORTED"}:
                raise RuntimeError(
                    "Story Formation cannot replay a terminal failed run: "
                    + _canonical(existing_run)
                )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                "SELECT version FROM authority_book WHERE project_id=%s AND book_id=%s",
                [self.project_id, self.book_id],
            )
            row = uow.cursor.fetchone()
        if row is None:
            raise RuntimeError("Book Authority root is missing before Formation")
        layers = tuple(
            FormationLayerInput(
                role=role,
                asset_version_id=str(selected[role]["asset_version_id"]),
                content_hash=str(selected[role]["content_hash"]),
                schema_version=str(selected[role]["schema_version"]),
                generation_operation_id=str(selected[role]["generation_operation_id"]),
                qualification_evidence_asset_version_id=str(
                    selected[role]["qualification_evidence_asset_version_id"]
                ),
                qualification_hash=str(selected[role]["qualification_hash"]),
                activation_operation_id=str(selected[role]["activation_operation_id"]),
                candidate_asset_version_ids=(
                    (
                        str(selected[role]["asset_version_id"]),
                        str(creative_alternate["asset_version_id"]),
                    )
                    if role is FoundationRole.CREATIVE_FOUNDATION
                    else (str(selected[role]["asset_version_id"]),)
                ),
                selection_reason=(str(selected[role]["selection_reason"]),),
            )
            for role in FoundationRole
        )
        if not formation_run_id:
            admission = formation.admit(
                StartStoryFormationCommand(
                    project_id=self.project_id,
                    workspace_id=self.workspace_id,
                    book_id=self.book_id,
                    actor_id=self.operator.principal_id,
                    expected_book_version=int(row[0]),
                    stable_idempotency_key=self._formation_key(),
                    trace_id=f"trace:{self.campaign_id}:formation",
                    correlation_id=self.campaign_id,
                    frozen_input=StoryFormationInput(layers=layers),
                ),
                principal=self.operator,
            )
            formation_run_id = admission.formation_run_id
        jobs = RuntimeJobAuthority(self.database_url)
        for _step in range(12):
            run = formation.require(formation_run_id)
            if run["lifecycle"] in {"WAITING_APPROVAL", "READY"}:
                return formation, run
            if run["lifecycle"] in {"FAILED", "ABORTED"}:
                raise RuntimeError(
                    "Story Formation failed closed: "
                    + _canonical(
                        {
                            "failure": run["failure"],
                            "recovery_instruction": run["recovery_instruction"],
                        }
                    )
                )
            formation.schedule_candidates(limit=1)
            claim = jobs.claim(
                runtime_group="story_formation",
                worker_id=f"quality-formation-worker:{self.project_id}",
                lease_seconds=60,
                job_kinds=("STORY_FORMATION_ADVANCE",),
                project_id=self.project_id,
            )
            if claim is None:
                raise RuntimeError("Story Formation has no claimable bounded job")
            execute_story_formation_claim(
                jobs,
                formation,
                self.operator,
                claim,
                lease_seconds=60,
            )
        raise RuntimeError("Story Formation exceeded its bounded stage count")

    def _activate_book_design(
        self,
        *,
        execution: Any,
        formation: StoryFormationApplication,
        waiting: Mapping[str, Any],
    ) -> dict[str, Any]:
        query = BookDesignAuthorityQuery(self.database_url)
        if waiting["lifecycle"] == "READY":
            book = query.require_book(project_id=self.project_id, book_id=self.book_id)
            asset_version_id = str(book["active_book_design_version_id"])
            with AuthorityUnitOfWork(self.database_url) as uow:
                foundation = require_current_foundation_set(
                    uow.cursor,
                    project_id=self.project_id,
                    book_id=self.book_id,
                    require_ready=True,
                )
                uow.cursor.execute(
                    "SELECT content_hash FROM authority_asset_version WHERE asset_version_id=%s",
                    [asset_version_id],
                )
                row = uow.cursor.fetchone()
            if not asset_version_id or row is None:
                raise RuntimeError("READY Formation has no active BookDesign")
            return {
                "asset_version_id": asset_version_id,
                "content_hash": str(row[0]),
                "foundation_set_digest": foundation.set_digest,
                "book_version": int(book["version"]),
            }
        with AuthorityUnitOfWork(self.database_url) as uow:
            foundation = require_current_foundation_set(
                uow.cursor,
                project_id=self.project_id,
                book_id=self.book_id,
            )
        application = build_book_design_authority_application(
            self.settings,
            execution=execution,
            env=self.runtime_env,
        )
        book = query.require_book(project_id=self.project_id, book_id=self.book_id)
        contract = self.book_contract.to_dict()
        proposed = application.execute(
            BookDesignAuthorityCommand(
                definition_name="book_design.propose",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                book_id=self.book_id,
                actor_id=self.operator.principal_id,
                service_identity="bounded-quality-preparation",
                idempotency_key=f"{self.campaign_id}:book-design:propose",
                trace_id=f"trace:{self.campaign_id}:book-design:propose",
                correlation_id=self.campaign_id,
                payload={
                    "schema_version": FOUNDATION_BOOK_DESIGN_SCHEMA_VERSION,
                    "title": contract["book"]["title"],
                    "target_chapters": 8,
                    "foundation_set": foundation.to_dict(),
                    "book_invariants": contract["book_design"]["book_invariants"],
                    "cross_layer_synthesis": contract["book_design"][
                        "cross_layer_synthesis"
                    ],
                    "narrative_dna": contract["book_design"]["narrative_dna"],
                },
                expected_book_version=int(book["version"]),
                expected_current_design_asset_version_id=str(
                    book["active_book_design_version_id"]
                ),
            ),
            principal=self.operator,
        )
        candidate = next(
            item
            for item in query.list_design_versions(
                project_id=self.project_id,
                book_id=self.book_id,
            )
            if item["asset_version_id"] == str(proposed["asset_version_id"])
        )
        if candidate["status"] != "VALIDATED":
            raise RuntimeError(
                "BookDesign independent semantic evaluation did not validate: "
                + _canonical(candidate)
            )
        for definition_name, payload in (
            (
                "book_design.decide",
                {
                    "decision": "APPROVE",
                    "reason": "qualified exact Foundation synthesis for bounded validation",
                },
            ),
            (
                "book_design.activate",
                {"reason": "activate exact bounded Quality Foundation synthesis"},
            ),
        ):
            current = query.require_book(
                project_id=self.project_id,
                book_id=self.book_id,
            )
            application.execute(
                BookDesignAuthorityCommand(
                    definition_name=definition_name,
                    project_id=self.project_id,
                    workspace_id=self.workspace_id,
                    book_id=self.book_id,
                    actor_id=self.operator.principal_id,
                    service_identity="bounded-quality-preparation",
                    idempotency_key=(
                        f"{self.campaign_id}:book-design:{definition_name}"
                    ),
                    trace_id=(
                        f"trace:{self.campaign_id}:book-design:{definition_name}"
                    ),
                    correlation_id=self.campaign_id,
                    payload=payload,
                    expected_book_version=int(current["version"]),
                    expected_current_design_asset_version_id=str(
                        current["active_book_design_version_id"]
                    ),
                    target_asset_version_id=str(proposed["asset_version_id"]),
                ),
                principal=self.operator,
            )
        ready = formation.approve_book_design(
            str(waiting["formation_run_id"]),
            expected_version=int(waiting["version"]),
            asset_version_id=str(proposed["asset_version_id"]),
            content_hash=str(proposed["content_hash"]),
            principal=self.operator,
        )
        if ready["lifecycle"] != "READY":
            raise RuntimeError("BookDesign activation did not complete Formation")
        final_book = query.require_book(
            project_id=self.project_id,
            book_id=self.book_id,
        )
        return {
            "asset_version_id": str(proposed["asset_version_id"]),
            "content_hash": str(proposed["content_hash"]),
            "foundation_set_digest": foundation.set_digest,
            "book_version": int(final_book["version"]),
        }

    def _author_book_inputs(self) -> dict[str, str]:
        payload = self.book_contract.to_dict()
        result: dict[str, str] = {}
        app = self._content_application()
        for operation, content in {
            **payload["bootstrap_inputs"],
            **payload["chapter_profiles"],
        }.items():
            authored = app.execute(
                ContentOperationRequest(
                    definition_name=operation,
                    project_id=self.project_id,
                    workspace_id=self.workspace_id,
                    actor_id=self.operator.principal_id,
                    trace_id=f"trace:{self.campaign_id}:{operation}",
                    correlation_id=self.campaign_id,
                    idempotency_key=f"{self.campaign_id}:{operation}",
                    payload={"content": {**dict(content), "book_id": self.book_id}},
                ),
                principal=self.operator,
            )
            result[CONTENT_CODECS[operation].output_asset_type] = (
                authored.asset_version_id
            )
        if self.mode == "scripted":
            fixture_checklist = app.execute(
                ContentOperationRequest(
                    definition_name="chapter.operator_checklist.author",
                    project_id=self.project_id,
                    workspace_id=self.workspace_id,
                    actor_id=self.operator.principal_id,
                    trace_id=f"trace:{self.campaign_id}:fixture-waiver-checklist",
                    correlation_id=self.campaign_id,
                    idempotency_key=(f"{self.campaign_id}:fixture-waiver-checklist"),
                    payload={
                        "content": {
                            "type": "operator_checklist",
                            "book_id": self.book_id,
                            "chapter": 1,
                            "completed": True,
                            "contract_version": "fixture-waiver-checklist-v1",
                            "safe_summary": (
                                "Internal scripted-protocol waiver checklist; "
                                "not human preference or production evidence."
                            ),
                            "structured_facts": [
                                {
                                    "key": "human_preference_evidence",
                                    "value": False,
                                },
                                {
                                    "key": "production_verified",
                                    "value": False,
                                },
                            ],
                        }
                    },
                ),
                principal=self.operator,
            )
            fixture_approval = app.execute(
                ContentOperationRequest(
                    definition_name="chapter.fixture_waiver_approval.author",
                    project_id=self.project_id,
                    workspace_id=self.workspace_id,
                    actor_id=self.operator.principal_id,
                    trace_id=f"trace:{self.campaign_id}:fixture-waiver-approval",
                    correlation_id=self.campaign_id,
                    idempotency_key=f"{self.campaign_id}:fixture-waiver-approval",
                    payload={
                        "content": {
                            "type": "operator_approval",
                            "book_id": self.book_id,
                            "decision": "APPROVED",
                            "contract_version": "fixture-waiver-approval-v1",
                            "fixture_protocol_only": True,
                            "production_verified": False,
                            "waiver_reason": (
                                "Exercise the bounded scripted Chapter release "
                                "and recovery protocol without quality claims."
                            ),
                            "waived_dimensions": list(QUALITY_DIMENSIONS),
                            "scope": {
                                "project_id": self.project_id,
                                "scope_type": "PROJECT_FIXTURE",
                                "release_readiness": "INTERNAL_REVIEW_RELEASE",
                            },
                            "expiry": "2099-01-01T00:00:00Z",
                            "safe_summary": (
                                "Project-scoped fixture-only release waiver; "
                                "not human preference or production evidence."
                            ),
                            "structured_facts": [],
                        }
                    },
                ),
                principal=self.operator,
            )
            result["operator_checklist"] = fixture_checklist.asset_version_id
            result["operator_approval"] = fixture_approval.asset_version_id
        campaign_identity = _digest(
            {
                "campaign_id": self.campaign_id,
                "profile_digest": self.profile.digest,
                "book_contract_digest": self.book_contract.digest,
                "exact_release_sha": self.exact_release_sha,
                "book_id": self.book_id,
            }
        )
        story = app.execute(
            ContentOperationRequest(
                definition_name="book.initial_story_state.author",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id=self.operator.principal_id,
                trace_id=f"trace:{self.campaign_id}:story-genesis",
                correlation_id=self.campaign_id,
                idempotency_key=f"{self.campaign_id}:story-genesis",
                payload={
                    "book_id": self.book_id,
                    "campaign_contract_identity": campaign_identity,
                },
            ),
            principal=self.operator,
        )
        canon = app.execute(
            ContentOperationRequest(
                definition_name="book.initial_canon.author",
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                actor_id=self.operator.principal_id,
                trace_id=f"trace:{self.campaign_id}:canon-genesis",
                correlation_id=self.campaign_id,
                idempotency_key=f"{self.campaign_id}:canon-genesis",
                payload={
                    "book_id": self.book_id,
                    "campaign_contract_identity": campaign_identity,
                },
                input_assets=(
                    {
                        "asset_version_id": story.asset_version_id,
                        "content_hash": story.content_hash,
                    },
                ),
            ),
            principal=self.operator,
        )
        result.update(
            {
                "story_state": story.asset_version_id,
                "canon_snapshot": canon.asset_version_id,
                "campaign_contract_identity": campaign_identity,
            }
        )
        return result

    def _open_book(
        self,
        *,
        composition: Any,
        selected: Mapping[FoundationRole, Mapping[str, Any]],
        design: Mapping[str, Any],
        authored_inputs: Mapping[str, str],
    ) -> dict[str, Any]:
        book = BookDesignAuthorityQuery(self.database_url).require_book(
            project_id=self.project_id,
            book_id=self.book_id,
        )
        planning_inputs = {
            "creative_foundation": str(
                selected[FoundationRole.CREATIVE_FOUNDATION]["asset_version_id"]
            ),
            "book_design": str(design["asset_version_id"]),
            "world_bible": str(
                selected[FoundationRole.WORLD_BIBLE]["asset_version_id"]
            ),
            "character_cast": str(
                selected[FoundationRole.CHARACTER_CAST]["asset_version_id"]
            ),
            "theme_contract": str(
                selected[FoundationRole.THEME_CONTRACT]["asset_version_id"]
            ),
            "ending_intent": str(
                selected[FoundationRole.ENDING_INTENT]["asset_version_id"]
            ),
            "reader_promise": str(
                selected[FoundationRole.READER_PROMISE]["asset_version_id"]
            ),
            "platform_profile": authored_inputs["platform_profile"],
            "production_profile": authored_inputs["production_profile"],
            "previous_volume_outcome": authored_inputs["previous_volume_outcome"],
            "story_state": authored_inputs["story_state"],
            "canon_snapshot": authored_inputs["canon_snapshot"],
            "arc_portfolio": authored_inputs["arc_portfolio"],
            "ending_reachability": authored_inputs["ending_reachability"],
            "character_arc_portfolio": authored_inputs["character_arc_portfolio"],
            "conflict_state": authored_inputs["conflict_state"],
            "promise_ledger": authored_inputs["promise_ledger_snapshot"],
            "foreshadowing_ledger": authored_inputs["foreshadowing_ledger"],
        }
        if set(planning_inputs) != _OPENING_ROLES:
            raise RuntimeError("governed opening inputs differ from Planning roles")
        request = OpenBookProductionRequest(
            project_id=self.project_id,
            workspace_id=self.workspace_id,
            book_id=self.book_id,
            actor_id=self.operator.principal_id,
            expected_book_version=int(book["version"]),
            production_profile=authored_inputs["production_profile"],
            planning_input_versions=planning_inputs,
            arc_logical_keys=tuple(
                str(item)
                for item in self.book_contract.to_dict()["book"]["arc_logical_keys"]
            ),
            idempotency_key=self._opening_key(),
            trace_id=f"trace:{self.campaign_id}:book-opening",
            correlation_id=self.campaign_id,
            initial_story_state_version=authored_inputs["story_state"],
            initial_canon_snapshot_version=authored_inputs["canon_snapshot"],
        )
        admission = composition.open_book(request)
        if composition.opening is None:
            raise RuntimeError("canonical Book opening composition is missing")
        run = composition.opening.require(admission.opening_run_id)
        if run["lifecycle"] == "COMPLETE":
            return {
                **dict(run["result"]),
                "opening_run_id": admission.opening_run_id,
            }
        if run["lifecycle"] not in {"ADMITTED", "RUNNING"}:
            raise RuntimeError(
                "Book opening is not safely executable: " + _canonical(run)
            )
        jobs = composition.opening.runtime_jobs
        claim = composition.opening.claim_next_execution(
            worker_id=f"quality-opening-worker:{self.project_id}",
            lease_seconds=120,
            project_id=self.project_id,
            expected_opening_run_id=admission.opening_run_id,
            expected_runtime_job_id=admission.runtime_job_id,
        )
        if claim is None:
            raise RuntimeError("Book opening has no claimable bounded job")
        opened = execute_book_opening_claim(
            jobs,
            composition.opening,
            self.operator,
            claim,
            lease_seconds=120,
        )
        return {**opened, "opening_run_id": admission.opening_run_id}

    def _start_book_run(self, *, composition: Any, snapshot_id: str) -> str:
        snapshot = composition.input_resolver.require(snapshot_id)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT book_run_id,input_snapshot_id,target_chapter_count,
                       accepted_through_chapter,light_recap_cadence,
                       formal_recap_cadence,input_mode
                FROM authority_book_production
                WHERE project_id=%s AND workspace_id=%s AND book_id=%s
                  AND state NOT IN ('COMPLETED','ABORTED')
                """,
                [self.project_id, self.workspace_id, self.book_id],
            )
            existing = uow.cursor.fetchall()
        if existing:
            if len(existing) != 1 or (
                str(existing[0][1]) != snapshot_id
                or int(existing[0][2]) != 8
                or int(existing[0][3]) != 0
                or int(existing[0][4]) != 4
                or int(existing[0][5]) != 8
                or str(existing[0][6]) != "RESOLVED_AUTHORITY_INPUT"
            ):
                raise RuntimeError(
                    "Book has an incompatible non-terminal production run"
                )
            return str(existing[0][0])
        admission = composition.authority.start(
            StartBookProductionCommand(
                project_id=self.project_id,
                workspace_id=self.workspace_id,
                book_id=self.book_id,
                actor_id=self.operator.principal_id,
                trace_id=f"trace:{self.campaign_id}:book-run",
                correlation_id=self.campaign_id,
                stable_idempotency_key=f"{self.campaign_id}:book-run",
                book_design_version=snapshot.book_design_version,
                book_plan_version=snapshot.book_plan_version,
                production_profile_version=snapshot.production_profile_version,
                longform_context_versions={
                    "volume_plan_version": snapshot.current_volume_plan_version,
                    "arc_plan_versions": list(
                        snapshot.current_relevant_arc_plan_versions
                    ),
                    "character_state_version": snapshot.character_state_version,
                    "foreshadowing_state_version": (
                        snapshot.foreshadowing_state_version
                    ),
                    "quality_trend_version": snapshot.quality_trend_version,
                    "reward_ledger_version": snapshot.reward_ledger_version,
                    "promise_ledger_version": snapshot.promise_ledger_version,
                    "reader_segment_version": snapshot.reader_segment_version,
                    "reader_contract_version": snapshot.reader_contract_version,
                    "platform_profile_version": snapshot.platform_profile_version,
                },
                target_chapter_count=8,
                input_mode="RESOLVED_AUTHORITY_INPUT",
                input_snapshot_id=snapshot.snapshot_id,
                light_recap_cadence=4,
                formal_recap_cadence=8,
            ),
            principal=self.operator,
        )
        return admission.book_run_id

    def _formation_key(self) -> str:
        return f"{self.campaign_id}:story-formation"

    def _formation_run_id(self) -> str:
        identity = "\x00".join(
            (self.project_id, self.book_id, self._formation_key())
        ).encode("utf-8")
        return "story-formation:" + hashlib.sha256(identity).hexdigest()

    def _opening_key(self) -> str:
        return f"{self.campaign_id}:book-opening"

    def _opening_run_id(self) -> str:
        identity = "\x00".join(
            (self.project_id, self.book_id, self._opening_key())
        ).encode("utf-8")
        return "book-opening:" + hashlib.sha256(identity).hexdigest()


__all__ = [
    "BoundedQualityBookContract",
    "BoundedQualityCampaignPreparer",
    "BoundedQualityPreparationResult",
    "QUALITY_BOOK_CONTRACT_SCHEMA",
    "build_quality_preparation_environment",
    "load_quality_book_contract",
]
