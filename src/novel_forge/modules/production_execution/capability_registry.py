from __future__ import annotations

from collections.abc import Iterable

from novel_forge.infrastructure.environment import RuntimeEnvironment

from .capabilities import (
    CapabilityDefinition,
    CapabilityId,
    ExecutionDomain,
    RiskClass,
)
from .contracts import ExecutionCapabilityProfile, ExecutionRuntimeClass


CONTROLLED_ENVIRONMENTS = frozenset(
    item.value for item in RuntimeEnvironment if item.controlled
)
PLANNING_TIMEOUT_POLICY_VERSION = "v3"
_PLANNING_CAPABILITIES = frozenset(
    {
        CapabilityId.CREATIVE_PROPOSAL_GENERATE,
        CapabilityId.THEME_QUESTION_GENERATE,
        CapabilityId.ENDING_INTENT_GENERATE,
        CapabilityId.READER_PROMISE_GENERATE,
        CapabilityId.WORLD_DESIGN_GENERATE,
        CapabilityId.CHARACTER_CAST_GENERATE,
        CapabilityId.PLANNING_BOOK_GENERATE,
        CapabilityId.PLANNING_VOLUME_GENERATE,
        CapabilityId.PLANNING_ARC_GENERATE,
        CapabilityId.PLANNING_CHAPTER_GROUP_GENERATE,
        CapabilityId.PLANNING_STORY_CHAPTER_GENERATE,
    }
)
_PROVIDER_RUNTIME_V2_CAPABILITIES = frozenset(
    {
        CapabilityId.AGENT_WORKSPACE_EXECUTE,
        CapabilityId.RETRIEVAL_EMBED,
        CapabilityId.RETRIEVAL_QUERY_EXPAND,
    }
)

_MODEL_RUNTIMES = (
    ExecutionRuntimeClass.REMOTE_PROVIDER_API,
    ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    ExecutionRuntimeClass.SCRIPTED_FIXTURE,
)
_MODEL_BACKENDS = (
    "remote-provider",
    "remote-provider-*",
    "codex-cli",
    "scripted-fixture",
)
_EXTERNAL_RUNTIMES = (
    ExecutionRuntimeClass.REMOTE_EXTERNAL_ACTION,
    ExecutionRuntimeClass.SCRIPTED_FIXTURE,
)
_EXTERNAL_BACKENDS = ("remote-external-action", "scripted-fixture")
_AGENT_RUNTIMES = (
    ExecutionRuntimeClass.AGENT_WORKSPACE_TRANSACTION,
    ExecutionRuntimeClass.REMOTE_PROVIDER_API,
    ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
    ExecutionRuntimeClass.SCRIPTED_FIXTURE,
)
_AGENT_BACKENDS = (
    "agent-workspace",
    "remote-provider",
    "remote-provider-*",
    "codex-cli",
    "scripted-fixture",
)


class CapabilityRegistry:
    def __init__(self, definitions: Iterable[CapabilityDefinition] = ()) -> None:
        self._definitions: dict[CapabilityId, CapabilityDefinition] = {}
        for definition in definitions:
            self.register(definition)

    def register(self, definition: CapabilityDefinition) -> CapabilityDefinition:
        existing = self._definitions.get(definition.capability_id)
        if existing is not None:
            if existing.contract_hash != definition.contract_hash:
                raise ValueError(
                    f"capability {definition.capability_id.value} has a different contract"
                )
            return existing
        self._definitions[definition.capability_id] = definition
        return definition

    def resolve(self, capability_id: CapabilityId | str) -> CapabilityDefinition:
        try:
            identity = (
                capability_id
                if isinstance(capability_id, CapabilityId)
                else CapabilityId(str(capability_id))
            )
        except ValueError as exc:
            raise ValueError(f"capability is not governed: {capability_id}") from exc
        try:
            return self._definitions[identity]
        except KeyError as exc:
            raise ValueError(f"capability is not registered: {identity.value}") from exc

    def definitions(self) -> tuple[CapabilityDefinition, ...]:
        return tuple(
            self._definitions[key]
            for key in sorted(self._definitions, key=lambda item: item.value)
        )

    def capability_ids(self) -> tuple[str, ...]:
        return tuple(item.capability_id.value for item in self.definitions())

    def require_backend(
        self,
        capability_id: CapabilityId | str,
        backend: ExecutionCapabilityProfile,
        *,
        environment: str,
    ) -> CapabilityDefinition:
        definition = self.resolve(capability_id)
        normalized_environment = RuntimeEnvironment.parse(environment)
        controlled = normalized_environment.controlled
        fixture = backend.runtime_class is ExecutionRuntimeClass.SCRIPTED_FIXTURE
        if controlled and fixture:
            raise ValueError(
                "fixture backend is prohibited in a controlled environment"
            )
        if controlled and not definition.production_allowed:
            raise ValueError("capability is not allowed in production")
        if fixture and not definition.fixture_allowed:
            raise ValueError("capability does not allow fixture execution")
        if backend.runtime_class not in definition.allowed_runtime_classes:
            raise ValueError("backend runtime is not allowed by the capability")
        if not any(
            _backend_matches(backend.backend_id, allowed)
            for allowed in definition.allowed_backend_ids
        ):
            raise ValueError("backend is not allowed by the capability")
        if (
            definition.requires_provider_idempotency
            and not backend.supports_provider_idempotency
        ):
            raise ValueError("capability requires Provider idempotency")
        return definition


def _backend_matches(actual: str, allowed: str) -> bool:
    actual = actual.strip().lower()
    allowed = allowed.strip().lower()
    if allowed.endswith("*"):
        return actual.startswith(allowed[:-1])
    return actual == allowed


def capability_contract_version(capability_id: CapabilityId | str) -> int:
    identity = (
        capability_id
        if isinstance(capability_id, CapabilityId)
        else CapabilityId(str(capability_id))
    )
    return (
        2
        if identity in _PLANNING_CAPABILITIES
        or identity in _PROVIDER_RUNTIME_V2_CAPABILITIES
        else 1
    )


def _definition(
    capability_id: CapabilityId,
    domain: ExecutionDomain,
    *,
    runtimes: tuple[ExecutionRuntimeClass, ...] = _MODEL_RUNTIMES,
    backends: tuple[str, ...] = _MODEL_BACKENDS,
    prompt_bundle_type: str = "DOMAIN_PROMPT_BUNDLE",
    skill_bundle_type: str = "DOMAIN_SKILL_BUNDLE",
    provider_idempotency: bool = False,
    query: bool = True,
    cancel: bool = True,
    callback: bool = True,
    risk: RiskClass = RiskClass.HIGH,
    timeout_policy_version: str = "v1",
) -> CapabilityDefinition:
    policy_key = capability_id.value.replace(".", "-")
    return CapabilityDefinition(
        capability_id=capability_id,
        domain=domain,
        input_schema_ref=f"schema:execution-input:{policy_key}:v1",
        output_schema_ref=f"schema:execution-output:{policy_key}:v1",
        allowed_runtime_classes=runtimes,
        allowed_backend_ids=backends,
        prompt_bundle_type=prompt_bundle_type,
        skill_bundle_type=skill_bundle_type,
        timeout_policy_ref=f"timeout:{policy_key}:{timeout_policy_version}",
        budget_policy_ref=f"budget:{policy_key}:v1",
        permission_policy_ref=f"permission:{policy_key}:v1",
        source_policy_ref=f"source:{policy_key}:v1",
        validation_policy_ref=f"validation:{policy_key}:v1",
        commit_policy_ref=f"commit:{policy_key}:v1",
        requires_provider_idempotency=provider_idempotency,
        supports_query=query,
        supports_cancel=cancel,
        supports_callback=callback,
        fixture_allowed=True,
        production_allowed=True,
        risk_class=risk,
    )


def default_capability_registry() -> CapabilityRegistry:
    model_domains = {
        CapabilityId.CREATIVE_TOPIC_GENERATE: ExecutionDomain.CREATIVE,
        CapabilityId.CREATIVE_PROPOSAL_GENERATE: ExecutionDomain.CREATIVE,
        CapabilityId.THEME_QUESTION_GENERATE: ExecutionDomain.THEME,
        CapabilityId.ENDING_INTENT_GENERATE: ExecutionDomain.ENDING,
        CapabilityId.READER_PROMISE_GENERATE: ExecutionDomain.CREATIVE,
        CapabilityId.WORLD_DESIGN_GENERATE: ExecutionDomain.WORLD,
        CapabilityId.CHARACTER_CAST_GENERATE: ExecutionDomain.CHARACTER,
        CapabilityId.PLANNING_BOOK_GENERATE: ExecutionDomain.PLANNING,
        CapabilityId.PLANNING_VOLUME_GENERATE: ExecutionDomain.PLANNING,
        CapabilityId.PLANNING_ARC_GENERATE: ExecutionDomain.PLANNING,
        CapabilityId.PLANNING_CHAPTER_GROUP_GENERATE: ExecutionDomain.PLANNING,
        CapabilityId.PLANNING_CHAPTER_GENERATE: ExecutionDomain.PLANNING,
        CapabilityId.PLANNING_CHAPTER_MEMO: ExecutionDomain.PLANNING,
        CapabilityId.PLANNING_STORY_CHAPTER_GENERATE: ExecutionDomain.PLANNING,
        CapabilityId.PROSE_CHAPTER_DRAFT: ExecutionDomain.PROSE,
        CapabilityId.REVIEW_CHAPTER_EVALUATE: ExecutionDomain.REVIEW,
        CapabilityId.REVISION_CHAPTER_REVISE: ExecutionDomain.REVISION,
        CapabilityId.CANON_EXTRACT: ExecutionDomain.CANON,
        CapabilityId.SOURCE_CONTENT_CLASSIFY: ExecutionDomain.SOURCE,
        CapabilityId.DECONSTRUCTION_OBSERVE: ExecutionDomain.DECONSTRUCTION,
        CapabilityId.QUALITY_INTRINSIC_JUDGE: ExecutionDomain.QUALITY,
        CapabilityId.QUALITY_ORIGINALITY_JUDGE: ExecutionDomain.QUALITY,
        CapabilityId.QUALITY_PLATFORM_JUDGE: ExecutionDomain.QUALITY,
        CapabilityId.QUALITY_READER_OUTCOME_JUDGE: ExecutionDomain.QUALITY,
        CapabilityId.QUALITY_PAIRWISE_JUDGE: ExecutionDomain.QUALITY,
        CapabilityId.MKAOS_KNOWLEDGE_EXTRACT: ExecutionDomain.MKAOS,
        CapabilityId.MKAOS_RULE_EXTRACT: ExecutionDomain.MKAOS,
        CapabilityId.MKAOS_TEMPLATE_EXTRACT: ExecutionDomain.MKAOS,
        CapabilityId.LONGFORM_RECAP_ANALYZE: ExecutionDomain.LONGFORM,
        CapabilityId.LONGFORM_PLAN_VS_ACTUAL_JUDGE: ExecutionDomain.LONGFORM,
        CapabilityId.LONGFORM_ARC_CLOSURE_JUDGE: ExecutionDomain.LONGFORM,
        CapabilityId.LONGFORM_PLAN_CHANGE_GENERATE: ExecutionDomain.LONGFORM,
    }
    definitions = [
        _definition(
            capability_id,
            domain,
            timeout_policy_version=(
                PLANNING_TIMEOUT_POLICY_VERSION
                if capability_id in _PLANNING_CAPABILITIES
                else "v1"
            ),
        )
        for capability_id, domain in model_domains.items()
    ]
    definitions.append(
        _definition(
            CapabilityId.WORLD_CONSEQUENCE_ANALYZE,
            ExecutionDomain.WORLD,
            skill_bundle_type="WORLD_CONSEQUENCE_MODELING_SKILL",
        )
    )
    definitions.append(
        _definition(
            CapabilityId.QUALITY_AGGREGATE,
            ExecutionDomain.QUALITY,
            runtimes=(ExecutionRuntimeClass.AUTHORITY_IN_PROCESS,),
            backends=("chapter-authority",),
            prompt_bundle_type="NO_PROMPT_BUNDLE",
            skill_bundle_type="NO_SKILL_BUNDLE",
            query=False,
            cancel=False,
            callback=False,
            risk=RiskClass.LOW,
        )
    )
    for capability_id, domain, backend, skill_bundle, query, risk in (
        (
            CapabilityId.TEMPORAL_QUERY,
            ExecutionDomain.CANON,
            "temporal-query-authority",
            "LONGFORM_TEMPORAL_QUERY_SKILL",
            True,
            RiskClass.MEDIUM,
        ),
        (
            CapabilityId.CANON_VALIDATE,
            ExecutionDomain.CANON,
            "chapter-authority",
            "CANON_CONTINUITY_GRAPH_SKILL",
            False,
            RiskClass.HIGH,
        ),
        (
            CapabilityId.CONTINUITY_VALIDATE,
            ExecutionDomain.CANON,
            "chapter-authority",
            "CANON_CONTINUITY_GRAPH_SKILL",
            False,
            RiskClass.HIGH,
        ),
        (
            CapabilityId.HOOK_ANALYZE,
            ExecutionDomain.QUALITY,
            "chapter-authority",
            "NARRATIVE_BEAT_DESIGN_SKILL",
            False,
            RiskClass.MEDIUM,
        ),
        (
            CapabilityId.PACING_ANALYZE,
            ExecutionDomain.LONGFORM,
            "chapter-authority",
            "MULTI_SCALE_PACING_SKILL",
            False,
            RiskClass.MEDIUM,
        ),
        (
            CapabilityId.PACING_AGGREGATE,
            ExecutionDomain.LONGFORM,
            "content-intelligence-authority",
            "MULTI_SCALE_PACING_SKILL",
            True,
            RiskClass.MEDIUM,
        ),
        (
            CapabilityId.FACT_VERIFY,
            ExecutionDomain.MKAOS,
            "content-authority",
            "EVIDENCE_FACT_VERIFICATION_SKILL",
            False,
            RiskClass.HIGH,
        ),
    ):
        definitions.append(
            _definition(
                capability_id,
                domain,
                runtimes=(ExecutionRuntimeClass.AUTHORITY_IN_PROCESS,),
                backends=(backend,),
                prompt_bundle_type="NO_PROMPT_BUNDLE",
                skill_bundle_type=skill_bundle,
                query=query,
                cancel=False,
                callback=False,
                risk=risk,
            )
        )
    definitions.extend(
        (
            _definition(
                CapabilityId.RETRIEVAL_EMBED,
                ExecutionDomain.RETRIEVAL,
                runtimes=(
                    ExecutionRuntimeClass.REMOTE_PROVIDER_API,
                    ExecutionRuntimeClass.LOCAL_CLI_REMOTE_INFERENCE,
                    ExecutionRuntimeClass.REMOTE_EXTERNAL_ACTION,
                    ExecutionRuntimeClass.SCRIPTED_FIXTURE,
                ),
                backends=(
                    "remote-provider-*",
                    "codex-cli",
                    "remote-external-action",
                    "scripted-fixture",
                ),
                prompt_bundle_type="RETRIEVAL_INPUT_BUNDLE",
                skill_bundle_type="NO_SKILL_BUNDLE",
                risk=RiskClass.MEDIUM,
            ),
            _definition(
                CapabilityId.RETRIEVAL_RERANK,
                ExecutionDomain.RETRIEVAL,
                prompt_bundle_type="RETRIEVAL_INPUT_BUNDLE",
                skill_bundle_type="NO_SKILL_BUNDLE",
                risk=RiskClass.MEDIUM,
            ),
            _definition(
                CapabilityId.RETRIEVAL_QUERY_EXPAND,
                ExecutionDomain.RETRIEVAL,
                runtimes=_AGENT_RUNTIMES,
                backends=_AGENT_BACKENDS,
                prompt_bundle_type="RETRIEVAL_INPUT_BUNDLE",
                skill_bundle_type="DOMAIN_SKILL_BUNDLE",
                provider_idempotency=False,
                risk=RiskClass.HIGH,
            ),
            _definition(
                CapabilityId.AGENT_WORKSPACE_EXECUTE,
                ExecutionDomain.AGENT,
                runtimes=_AGENT_RUNTIMES,
                backends=_AGENT_BACKENDS,
                prompt_bundle_type="AGENT_INSTRUCTION_BUNDLE",
                skill_bundle_type="AGENT_SKILL_BUNDLE",
                provider_idempotency=False,
                risk=RiskClass.CRITICAL,
            ),
        )
    )
    for capability_id, domain, risk in (
        (
            CapabilityId.PUBLISHING_RELEASE_SUBMIT,
            ExecutionDomain.PUBLISHING,
            RiskClass.CRITICAL,
        ),
        (
            CapabilityId.PUBLISHING_RELEASE_QUERY,
            ExecutionDomain.PUBLISHING,
            RiskClass.HIGH,
        ),
        (
            CapabilityId.PUBLISHING_RELEASE_WITHDRAW,
            ExecutionDomain.PUBLISHING,
            RiskClass.CRITICAL,
        ),
        (
            CapabilityId.FEEDBACK_PLATFORM_FETCH,
            ExecutionDomain.FEEDBACK,
            RiskClass.HIGH,
        ),
        (
            CapabilityId.SOURCE_REMOTE_FETCH,
            ExecutionDomain.SOURCE,
            RiskClass.HIGH,
        ),
        (
            CapabilityId.NOTIFICATION_SEND,
            ExecutionDomain.NOTIFICATION,
            RiskClass.HIGH,
        ),
        (
            CapabilityId.STORAGE_OBJECT_PUT,
            ExecutionDomain.STORAGE,
            RiskClass.HIGH,
        ),
        (
            CapabilityId.TOOL_REMOTE_INVOKE,
            ExecutionDomain.TOOL,
            RiskClass.CRITICAL,
        ),
        (
            CapabilityId.ANALYTICS_QUERY_EXECUTE,
            ExecutionDomain.ANALYTICS,
            RiskClass.HIGH,
        ),
        (
            CapabilityId.RETRIEVAL_INDEX_UPSERT,
            ExecutionDomain.RETRIEVAL,
            RiskClass.HIGH,
        ),
        (
            CapabilityId.RETRIEVAL_INDEX_QUERY,
            ExecutionDomain.RETRIEVAL,
            RiskClass.HIGH,
        ),
    ):
        definitions.append(
            _definition(
                capability_id,
                domain,
                runtimes=_EXTERNAL_RUNTIMES,
                backends=_EXTERNAL_BACKENDS,
                prompt_bundle_type="NO_PROMPT_BUNDLE",
                skill_bundle_type="NO_SKILL_BUNDLE",
                provider_idempotency=capability_id
                not in {
                    CapabilityId.PUBLISHING_RELEASE_QUERY,
                    CapabilityId.FEEDBACK_PLATFORM_FETCH,
                    CapabilityId.SOURCE_REMOTE_FETCH,
                    CapabilityId.RETRIEVAL_INDEX_QUERY,
                },
                risk=risk,
            )
        )
    definitions.append(
        _definition(
            CapabilityId.CONTEXT_TASK_COMPILE, ExecutionDomain.RETRIEVAL,
            runtimes=(ExecutionRuntimeClass.AUTHORITY_IN_PROCESS,),
            backends=("chapter-authority",),
            prompt_bundle_type="NO_PROMPT_BUNDLE", skill_bundle_type="NO_SKILL_BUNDLE",
            query=False, cancel=False, callback=False, risk=RiskClass.HIGH,
        )
    )
    return CapabilityRegistry(definitions)


__all__ = [
    "CONTROLLED_ENVIRONMENTS",
    "PLANNING_TIMEOUT_POLICY_VERSION",
    "CapabilityRegistry",
    "capability_contract_version",
    "default_capability_registry",
]
