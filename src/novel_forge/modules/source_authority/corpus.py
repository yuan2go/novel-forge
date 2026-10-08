from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    model_serializer,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    model_validator,
)

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.source_authority.domain import decide_source_governance
from novel_forge.modules.source_authority.market import UseScope, DefineMarketRank, ObserveMarketRank, LinkMarketEdition


class CorpusPurpose(StrEnum):
    RESEARCH = "RESEARCH"
    BENCHMARK = "BENCHMARK"
    MARKET_INTELLIGENCE = "MARKET_INTELLIGENCE"
    PRODUCTION_REFERENCE = "PRODUCTION_REFERENCE"


class UnderlyingRights(StrEnum):
    OWNED = "OWNED"
    LICENSED = "LICENSED"
    PUBLIC_DOMAIN = "PUBLIC_DOMAIN"
    PERMISSION_GRANTED = "PERMISSION_GRANTED"
    UNKNOWN = "UNKNOWN"
    CONFLICTING = "CONFLICTING"
    RESTRICTED = "RESTRICTED"


Text = Annotated[str, Field(min_length=1, max_length=2048, pattern=r"\S")]
Identity = Annotated[str, Field(min_length=1, max_length=512, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class CorpusContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorpusUse(StrEnum):
    LOCAL_PROCESSING = "LOCAL_PROCESSING"
    SOURCE_ANALYSIS = "SOURCE_ANALYSIS"
    ABSTRACT_GENERATION = "ABSTRACT_GENERATION"


class WorkRights(CorpusContract):
    underlying_rights: UnderlyingRights
    underlying_license: str = Field(default="", max_length=2048)
    allowed_purposes: tuple[CorpusPurpose, ...] = Field(max_length=4)
    denied_purposes: tuple[CorpusPurpose, ...] = Field(default=(), max_length=4)
    allowed_uses: tuple[CorpusUse, ...] = Field(default=(), max_length=3)
    restrictions: tuple[Text, ...] = Field(default=(), max_length=30)
    evidence_refs: tuple[Text, ...] = Field(min_length=1, max_length=30)
    use_scope: UseScope | None = None

    @model_serializer(mode="wrap")
    def serialize_compatibility(self, handler):
        value = handler(self)
        if self.use_scope is None:
            value.pop("use_scope", None)
        return value

    @model_validator(mode="after")
    def independent_license(self) -> WorkRights:
        if (
            self.underlying_rights == UnderlyingRights.LICENSED
            and not self.underlying_license.strip()
        ):
            raise ValueError(
                "work-scoped licensing requires independent underlying license evidence"
            )
        return self


class RegisterCorpusSource(CorpusContract):
    action: Literal["register_source"]
    source_kind: Identity
    external_identity: Identity
    purpose: CorpusPurpose


class RightsDeclaration(CorpusContract):
    action: Literal["declare_rights"]
    source_id: Text
    previous_rights_id: str | None = None
    dataset_license: Text
    underlying_rights: UnderlyingRights
    underlying_license: str = Field(default="", max_length=2048)
    allowed_purposes: tuple[CorpusPurpose, ...] = Field(max_length=4)
    denied_purposes: tuple[CorpusPurpose, ...] = Field(default=(), max_length=4)
    restrictions: tuple[Text, ...] = Field(default=(), max_length=30)
    evidence_refs: tuple[Text, ...] = Field(min_length=1, max_length=30)
    copyright_boundary: Text
    scope: Literal["ALL_WORKS_IN_SNAPSHOT", "SELECTED_WORKS"]
    allowed_uses: tuple[CorpusUse, ...] = Field(default=(), max_length=3)
    work_grants: dict[str, WorkRights] = Field(default_factory=dict, max_length=1000)
    use_scope: UseScope | None = None

    @model_serializer(mode="wrap")
    def serialize_compatibility(self, handler):
        value = handler(self)
        if self.use_scope is None:
            value.pop("use_scope", None)
        return value

    @model_validator(mode="after")
    def explicit_underlying_license(self) -> RightsDeclaration:
        if (
            self.underlying_rights == UnderlyingRights.LICENSED
            and not self.underlying_license.strip()
        ):
            raise ValueError(
                "underlying-work license evidence is required independently of dataset license"
            )
        if len(set(self.allowed_purposes)) != len(self.allowed_purposes):
            raise ValueError("allowed purposes must be unique")
        if (self.scope == "SELECTED_WORKS") != bool(self.work_grants):
            raise ValueError("selected-work rights require explicit work-keyed grants")
        if any(not key.strip() or len(key) > 512 for key in self.work_grants):
            raise ValueError(
                "work rights require exact bounded external work identities"
            )
        return self


class DatasetManifest(CorpusContract):
    schema_version: Literal["corpus-dataset-manifest.v1"] = "corpus-dataset-manifest.v1"
    origin_uri: Text
    external_version: Text
    format: Text
    checksum: Digest
    adapter_profile: Text
    adapter_contract_version: Text
    metadata: dict[str, Any] = Field(default_factory=dict)


class AcquisitionIdentity(CorpusContract):
    locator: Text
    acquired_at: Text
    receipt_ref: Text
    checksum: Digest
    repository_snapshot_asset_version_id: str | None = None


class FreezeCorpusSnapshot(CorpusContract):
    action: Literal["freeze_snapshot"]
    source_id: Text
    previous_snapshot_id: str | None = None
    rights_id: Text
    manifest: DatasetManifest
    acquisition: AcquisitionIdentity

    @model_validator(mode="after")
    def acquisition_matches(self) -> FreezeCorpusSnapshot:
        from datetime import datetime

        moment = datetime.fromisoformat(
            self.acquisition.acquired_at.replace("Z", "+00:00")
        )
        if moment.tzinfo is None:
            raise ValueError("acquisition timestamp requires an explicit timezone")
        if self.manifest.checksum != self.acquisition.checksum:
            raise ValueError("manifest and acquisition checksums must match")
        return self


class BookEditionInput(CorpusContract):
    external_work_id: Identity
    external_edition_id: Identity
    title: Text
    checksum: Digest
    locator: Text
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportCorpusBatch(CorpusContract):
    action: Literal["import_batch"]
    snapshot_id: Text
    batch_key: Text
    entries: tuple[BookEditionInput, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_entries(self) -> ImportCorpusBatch:
        keys = {
            (entry.external_work_id, entry.external_edition_id)
            for entry in self.entries
        }
        if len(keys) != len(self.entries):
            raise ValueError("a batch cannot contain duplicate edition identities")
        return self


class EvaluateCorpusAdmission(CorpusContract):
    action: Literal["evaluate_admission"]
    edition_id: Text
    purpose: CorpusPurpose


class RetireCorpusSource(CorpusContract):
    action: Literal["retire_source"]
    source_id: Text
    reason: Text


class ControlCorpusImport(CorpusContract):
    action: Literal["control_import"]
    import_job_id: Text
    control: Literal["PAUSE", "RESUME", "CANCEL"]
    expected_status: Text
    reason: Text


class IntegrityResolution(CorpusContract):
    issue_id: Text
    resolution: Literal[
        "CONFIRM_EXCERPT",
        "MARK_NON_BODY",
        "CONFIRM_BOUNDARY",
        "REJECT_CORRUPT",
        "CONFIRM_LEGITIMATE_REPETITION",
        "CONFIRM_TOC_VARIANT",
        "ANNOTATE_TOC_DIFFERENCE",
    ]
    reason: Text

    evidence_refs: tuple[Text, ...] = Field(default=(), max_length=16)
    classification: (
        Literal[
            "DISPLAY",
            "TRANSCRIPTION_SUSPECTED",
            "VERSION_WORDING",
            "PARSER_ERROR",
            "INSUFFICIENT",
            "LEGITIMATE_REPETITION",
        ]
        | None
    ) = None

    @model_serializer(mode="wrap")
    def frozen_resolution(self, handler: Any) -> dict[str, Any]:
        value = handler(self)
        if not self.evidence_refs:
            value.pop("evidence_refs", None)
        if self.classification is None:
            value.pop("classification", None)
        return value


class ReviewCorpusProcessing(CorpusContract):
    action: Literal["review_processing"]
    processing_id: Text
    previous_id: Text | None = None
    decisions: tuple[IntegrityResolution, ...] = Field(min_length=1, max_length=32)
    reason: Text


class DecideCorpusEquivalence(CorpusContract):
    action: Literal["decide_equivalence"]
    left_id: Text
    right_id: Text
    previous_id: Text | None = None
    decision: Literal["ACCEPT", "REJECT", "REVOKE"]
    evidence_refs: tuple[Text, ...] = Field(min_length=1, max_length=16)
    reason: Text


CorpusRelation = Literal[
    "SAME_WORK",
    "SAME_EDITION_COPY",
    "REVISION",
    "ABRIDGED",
    "EXPANDED",
    "EXCERPT",
    "SIMILAR_ONLY",
    "DIFFERENT_WORK",
    "UNCERTAIN",
]


class DeclareCorpusRelation(CorpusContract):
    action: Literal["declare_relation"]
    left_id: Text
    right_id: Text
    previous_id: Text | None = None
    relation: CorpusRelation
    evidence_refs: tuple[Text, ...] = Field(min_length=1, max_length=16)
    reason: Text


class CanonicalMember(CorpusContract):
    processing_id: Text
    relation: Literal[
        "SAME_WORK", "SAME_EDITION_COPY", "REVISION", "ABRIDGED", "EXPANDED", "EXCERPT"
    ]
    evidence_refs: tuple[Text, ...] = Field(min_length=1, max_length=16)


class CanonicalWorkRevision(CorpusContract):
    work_key: Identity
    previous_id: Text | None = None
    title: Text
    aliases: tuple[Text, ...] = Field(default=(), max_length=32)
    external_ids: dict[str, str] = Field(default_factory=dict, max_length=16)
    language: str = Field(default="und", min_length=2, max_length=16)
    genre_tags: tuple[Text, ...] = Field(default=(), max_length=16)
    metadata_evidence: tuple[Text, ...] = Field(min_length=1, max_length=16)
    members: tuple[CanonicalMember, ...] = Field(default=(), max_length=100)
    state: Literal["ACTIVE", "RETIRED"] = "ACTIVE"


class ResolveCanonicalWorks(CorpusContract):
    action: Literal["resolve_canonical_works"]
    changes: tuple[CanonicalWorkRevision, ...] = Field(min_length=1, max_length=8)
    reason: Text


class CuratedFilter(CorpusContract):
    language: str = Field(default="", max_length=16)
    source_ids: tuple[Text, ...] = Field(default=(), max_length=32)
    work_ids: tuple[Text, ...] = Field(default=(), max_length=32)
    genre_tags: tuple[Text, ...] = Field(default=(), max_length=16)
    min_characters: int = Field(default=0, ge=0)
    max_characters: int = Field(default=64000000, ge=1, le=64000000)
    coverages: tuple[
        Literal["COMPLETE", "EXCERPT", "UNKNOWN", "REVIEW_REQUIRED", "CORRUPT"], ...
    ] = ()
    structure_usable: bool | None = None


class CuratedChoice(CorpusContract):
    processing_id: Text
    selected: bool
    reason: Text
    evidence_refs: tuple[Text, ...] = Field(min_length=1, max_length=16)


class ReviseCuratedCorpus(CorpusContract):
    action: Literal["revise_curated_corpus"]
    corpus_key: Identity
    previous_id: Text | None = None
    title: Text
    purpose: CorpusPurpose
    state: Literal["CANDIDATE", "FROZEN", "RETIRED"] = "CANDIDATE"
    filters: CuratedFilter = Field(default_factory=CuratedFilter)
    candidate_limit: int = Field(default=20, ge=1, le=100)
    choices: tuple[CuratedChoice, ...] = Field(default=(), max_length=100)
    reason: Text




CorpusAction = Annotated[
    RegisterCorpusSource
    | RightsDeclaration
    | FreezeCorpusSnapshot
    | ImportCorpusBatch
    | EvaluateCorpusAdmission
    | RetireCorpusSource
    | ControlCorpusImport
    | ReviewCorpusProcessing
    | DecideCorpusEquivalence
    | DeclareCorpusRelation
    | ResolveCanonicalWorks
    | ReviseCuratedCorpus
    | DefineMarketRank
    | ObserveMarketRank
    | LinkMarketEdition,
    Field(discriminator="action"),
]
CORPUS_ACTION = TypeAdapter(CorpusAction)
CORPUS_POLICY_VERSION = "source-corpus-admission.v1"


def validate_corpus_action(payload: dict[str, Any]) -> CorpusAction:
    try:
        if (
            len(json.dumps(payload, ensure_ascii=False, allow_nan=False).encode())
            > 262144
        ):
            raise ValueError("Corpus metadata command exceeds its 256 KiB policy")
        return CORPUS_ACTION.validate_python(payload)
    except ValueError as exc:
        raise KernelError("CORPUS_COMMAND_INVALID", str(exc)) from exc


def corpus_hash(value: Any) -> str:
    return (
        "sha256:"
        + hashlib.sha256(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
    )


def corpus_identity(kind: str, *parts: Any) -> str:
    return f"corpus-{kind}:" + corpus_hash(parts).removeprefix("sha256:")


def corpus_admission(
    *,
    rights: RightsDeclaration,
    source_purpose: CorpusPurpose,
    requested_purpose: CorpusPurpose,
    retired: bool = False,
    rights_current: bool = True,
    external_work_id: str = "",
) -> dict[str, Any]:
    rights = effective_work_rights(rights, external_work_id)
    reasons: list[str] = []
    if retired:
        reasons.append("SOURCE_RETIRED")
    if not rights_current:
        reasons.append("RIGHTS_REVIEW_REQUIRED")
    if source_purpose != requested_purpose:
        reasons.append("CORPUS_PURPOSE_ISOLATION")
    if (
        source_purpose == CorpusPurpose.BENCHMARK
        and requested_purpose == CorpusPurpose.PRODUCTION_REFERENCE
    ):
        reasons.append("BENCHMARK_PRODUCTION_FORBIDDEN")
    if requested_purpose not in rights.allowed_purposes:
        reasons.append("PURPOSE_NOT_GRANTED")
    if requested_purpose in rights.denied_purposes:
        reasons.append("PURPOSE_EXPLICITLY_DENIED")
    if requested_purpose == CorpusPurpose.PRODUCTION_REFERENCE:
        if rights.underlying_rights in {
            UnderlyingRights.UNKNOWN,
            UnderlyingRights.CONFLICTING,
            UnderlyingRights.RESTRICTED,
        }:
            reasons.append("UNDERLYING_WORK_RIGHTS_NOT_CLEARED")
        else:
            governed = decide_source_governance(
                authorization=rights.underlying_rights.lower(),
                license_name=rights.underlying_license,
                copyright_boundary=rights.copyright_boundary,
            )
            if not governed.analysis_allowed:
                reasons.append("SOURCE_GOVERNANCE_DENIED")
        if rights.restrictions:
            reasons.append("RESTRICTIONS_REQUIRE_REVIEW")
    return {
        "policy_version": CORPUS_POLICY_VERSION,
        "purpose": requested_purpose.value,
        "decision": "DENY" if reasons else "ALLOW",
        "reasons": reasons or ["EXPLICIT_PURPOSE_DECLARATION"],
        "generation_context_allowed": False,
        "requires_source_mkaos_governance": True,
    }


def effective_work_rights(
    rights: RightsDeclaration, external_work_id: str
) -> RightsDeclaration:
    if rights.scope == "ALL_WORKS_IN_SNAPSHOT":
        return rights
    grant = rights.work_grants.get(external_work_id)
    if grant is None:
        return rights.model_copy(
            update={
                "underlying_rights": UnderlyingRights.UNKNOWN,
                "allowed_purposes": (),
                "allowed_uses": (),
            }
        )
    return rights.model_copy(
        update={
            **grant.model_dump(),
            "use_scope": grant.use_scope or rights.use_scope,
            "restrictions": rights.restrictions + grant.restrictions,
            "denied_purposes": tuple(
                sorted(set(rights.denied_purposes) | set(grant.denied_purposes))
            ),
            "allowed_purposes": tuple(
                item
                for item in grant.allowed_purposes
                if item in rights.allowed_purposes
            ),
            "evidence_refs": rights.evidence_refs + grant.evidence_refs,
        }
    )


def corpus_use_admission(
    *,
    rights: RightsDeclaration,
    source_purpose: CorpusPurpose,
    use: CorpusUse,
    external_work_id: str,
    retired: bool,
    rights_current: bool,
    restricted_research: bool = False,
) -> dict[str, Any]:
    effective = effective_work_rights(rights, external_work_id)
    decision = corpus_admission(
        rights=rights,
        source_purpose=source_purpose,
        requested_purpose=source_purpose,
        retired=retired,
        rights_current=rights_current,
        external_work_id=external_work_id,
    )
    reasons = [] if decision["decision"] == "ALLOW" else list(decision["reasons"])
    if effective.use_scope is not None:
        from datetime import datetime, timezone

        try:
            effective.use_scope.require_use(use.value, datetime.now(timezone.utc))
        except ValueError:
            reasons.append("CORPUS_PURPOSE_SCOPE_NOT_GRANTED")
    if use not in effective.allowed_uses:
        reasons.append("CORPUS_USE_NOT_GRANTED")
    private_analysis = (restricted_research and use == CorpusUse.SOURCE_ANALYSIS
        and source_purpose == CorpusPurpose.RESEARCH
        and effective.underlying_rights != UnderlyingRights.CONFLICTING
        and effective.underlying_rights != UnderlyingRights.RESTRICTED
        and set(effective.restrictions).issubset({"PRIVATE_ANALYSIS_ONLY", "NO_RAW_WRITER_INPUT", "NO_PUBLIC_DISTRIBUTION"}))
    if use != CorpusUse.LOCAL_PROCESSING:
        if not private_analysis and (
            effective.underlying_rights
            in {
                UnderlyingRights.UNKNOWN,
                UnderlyingRights.CONFLICTING,
                UnderlyingRights.RESTRICTED,
            }
            or effective.restrictions
        ):
            reasons.append("UNDERLYING_USE_RIGHTS_NOT_CLEARED")
        if source_purpose == CorpusPurpose.BENCHMARK:
            reasons.append("BENCHMARK_PRODUCTION_PIPELINE_FORBIDDEN")
    if (
        use == CorpusUse.ABSTRACT_GENERATION
        and source_purpose != CorpusPurpose.PRODUCTION_REFERENCE
    ):
        reasons.append("PRODUCTION_PURPOSE_NOT_GRANTED")
    return {
        **decision,
        "use": use.value,
        "decision": "DENY" if reasons else "ALLOW",
        "reasons": reasons or ["EXPLICIT_USE_AND_PURPOSE_GRANTED"],
        "policy_version": "corpus-use-policy.v1",
    }
