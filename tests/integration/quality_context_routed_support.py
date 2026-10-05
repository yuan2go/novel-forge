from dataclasses import replace
from datetime import datetime, timedelta, timezone

from novel_forge.modules.production_execution.cost_routing import (
    ModelCandidate,
    PricingSnapshot,
    task_policy,
)
from novel_forge.modules.production_execution.routing_runtime import (
    ProductionProviderRouter,
)
from tests.unit.test_cost_aware_routing import samples

SCENARIOS = {
    "observation": {
        "genre": "serious realist observation",
        "audience": "adult reflective readers",
        "tone": "克制、观察性、保留含混",
        "pov": "第三人称限知",
        "structure": "三章短篇、场景并置",
        "character": "制图学徒保留犹疑，不强制成长弧线",
        "world": "档案由普通机构管理，无超自然权力",
        "prohibition": "禁止救世结局和新能力解决问题",
        "optional": "允许环境观察；不采用奖励机制或悬念钩子",
    },
    "fantasy": {
        "genre": "light fantasy adventure",
        "audience": "young adult adventure readers",
        "tone": "轻松、温暖、具体动作",
        "pov": "第三人称限知",
        "structure": "三章短冒险、保留场景完整性",
        "character": "制图学徒好奇而谨慎，允许小幅变化",
        "world": "幻想港口有固定规则，不临时发明能力",
        "prohibition": "禁止血腥描写和万能救援",
        "optional": "允许幽默；不采用奖励机制或悬念钩子",
    },
    "science": {
        "genre": "restrained science fiction",
        "audience": "adult science fiction readers",
        "tone": "节制、清晰、避免技术说教",
        "pov": "第三人称限知",
        "structure": "三章短篇、有限技术解释",
        "character": "制图学徒必须承认知识边界",
        "world": "资料系统有可解释的信息边界",
        "prohibition": "禁止突然升级技术与全知叙述",
        "optional": "允许留白；不采用奖励机制或悬念钩子",
    },
}


def bind_mock_scenario(monkeypatch, scenario):
    from copy import deepcopy
    from novel_forge.modules.story_design_authority.author_input import (
        GENERATOR_TARGETS,
        text_hash,
    )
    from tests.integration import synthesis_author_input_support as authors
    from tests.integration import test_synthesis_formation_postgres as formation
    from novel_forge.modules.story_planning_runtime.foundation_generation import (
        FOUNDATION_GENERATORS,
    )
    from novel_forge.modules.book_design_authority.foundation import FoundationRole

    original_author = authors.author_fixture
    original_transport = authors.AuthorSynthesisTransport
    text = "\n".join(f"{key}: {value}" for key, value in scenario.items())

    def author(project, book):
        result = original_author(project, book)
        result["documents"].append(
            {
                "path": "fixture/work-intent.md",
                "content": text,
                "content_hash": text_hash(text),
            }
        )
        result["fragments"].append(
            {
                "fragment_id": "work-intent-scenario",
                "source_path": "fixture/work-intent.md",
                "start": 0,
                "end": len(text),
                "content_hash": text_hash(text),
                "targets": list(GENERATOR_TARGETS.values()),
                "chapter_range": [1, 3],
                "visibility": "SCENE_INTENT",
                "strength": "REQUIRED",
            }
        )
        return result

    def decline_methods(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {
                    "reward_action",
                    "ending_hook",
                    "reward_mode",
                    "chapter_hook",
                    "reward_setup",
                    "reward_payoff",
                }:
                    value[key] = None
                else:
                    decline_methods(item)
        elif isinstance(value, list):
            for item in value:
                decline_methods(item)

    class ScenarioTransport(original_transport):
        def planning(self, stage, inputs):
            result = super().planning(stage, inputs)
            if FOUNDATION_GENERATORS.get(stage) == FoundationRole.CREATIVE_FOUNDATION:
                result.update(
                    genre=scenario["genre"], target_reader=scenario["audience"]
                )
                result["style_profile"].update(
                    narrator=scenario["tone"],
                    pov=scenario["pov"],
                    constraints=[
                        scenario[key]
                        for key in (
                            "tone",
                            "pov",
                            "structure",
                            "character",
                            "world",
                            "prohibition",
                            "optional",
                        )
                    ],
                )
            elif stage not in FOUNDATION_GENERATORS:
                decline_methods(result)
            if FOUNDATION_GENERATORS.get(stage) == FoundationRole.CREATIVE_FOUNDATION:
                result["serialization_potential"] = None
                for declaration in result["applicability"]:
                    if declaration["field_path"] == "$.serialization_potential":
                        declaration.update(
                            status="NOT_APPLICABLE",
                            rationale="Author requested a bounded three-chapter work",
                        )
            return result

    execute = formation.ContentAuthorityApplication.execute

    def submit(application, request, **kwargs):
        if request.definition_name == "creative.brief.create":
            payload = deepcopy(request.payload)
            payload["brief"].update(
                genre=scenario["genre"],
                audience=scenario["audience"],
                constraints=[
                    scenario[key]
                    for key in (
                        "tone",
                        "pov",
                        "structure",
                        "character",
                        "world",
                        "prohibition",
                        "optional",
                    )
                ],
            )
            request = replace(request, payload=payload)
        return execute(application, request, **kwargs)

    from tests.integration.synthesis_production_support import SynthesisChapterTransport

    chapter_planning = SynthesisChapterTransport.planning

    def chapter_plan(transport, stage, inputs):
        result = chapter_planning(transport, stage, inputs)
        decline_methods(result)
        return result

    monkeypatch.setattr(SynthesisChapterTransport, "planning", chapter_plan)
    monkeypatch.setattr(authors, "author_fixture", author)
    monkeypatch.setattr(authors, "AuthorSynthesisTransport", ScenarioTransport)
    monkeypatch.setattr(formation.ContentAuthorityApplication, "execute", submit)
    return text


def attach_mock_qualified_router(execution, database_url):
    """Use the actual persisted Router with a controlled qualification data source.

    MOCK_E2E only: these observations are never persisted or exported as real
    qualification. Router selection, budget, admission, and frozen receipts run.
    """
    candidate = ModelCandidate(
        "mock-scripted",
        "scripted_provider_v2",
        "synthesis-scripted",
        "high",
        "mock-only",
        ("structured_output", "text_generation"),
        524288,
        32000,
        PricingSnapshot(
            "mock-price",
            "2026-01-01T00:00:00+00:00",
            "2027-01-01T00:00:00+00:00",
            "0",
            "0",
            "0",
            source="MOCK_E2E_ONLY",
        ),
        "mock-capability",
        model_revision="mock-v1",
    )
    router = ProductionProviderRouter(
        database_url,
        candidates=[candidate],
        task_money_limit="10",
        task_token_limit=100_000_000,
        execution_environment="test",
    )
    real_select = router.select
    requested = {}

    def select(base, **kwargs):
        requested.update(kwargs)
        return real_select(base, **kwargs)

    def observations(*, task_type, producer_contract_hash=None, **_):
        policy = task_policy(
            task_type, requested.get("risk", ""), requested.get("quality_floor", 0)
        )
        common = dict(
            occurred_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            producer_contract_hash=producer_contract_hash or "",
            experiment_partition="CALIBRATION",
        )
        rows = []
        for i, row in enumerate(samples(n=200)):
            values = dict(
                common,
                evidence_ref=f"MOCK_ONLY:{task_type}:{i}",
                sample_identity=f"MOCK_ONLY:{task_type}:{i}",
                independence_group=f"MOCK_ONLY:{i}",
            )
            if policy.quality_metric == "GENERATOR_SCORE":
                values.update(
                    quality_score=None,
                    accepted=None,
                    evidence_class="BENCHMARK_CHALLENGER",
                    production_eligible=False,
                    generator_quality_score=0.99,
                    generator_risk=policy.risk,
                    generator_context_tokens=requested["input_tokens"],
                    generator_protocol_hash="sha256:mock-generator",
                    outcome_refs=(f"MOCK_ONLY:adjudication:{i}",),
                )
            elif policy.quality_metric == "REFERENCE_AGREEMENT":
                values.update(
                    quality_score=None,
                    accepted=None,
                    evidence_class="REFERENCE_EVALUATION",
                    production_eligible=False,
                    reference_agreed=True,
                    reference_risk=policy.risk,
                    reference_context_tokens=requested["input_tokens"],
                    reference_protocol_hash="sha256:mock-reference",
                    reference_label_classes=("PASS" if i % 2 else "FAIL",),
                )
            elif policy.quality_metric == "DOMAIN_GATE_ACCEPTANCE":
                values.update(domain_gate_accepted=True)
            rows.append(replace(row, **values))
        return rows

    router.select = select
    router.registry.observations = observations
    execution.gateway.provider_router = router
    return router
