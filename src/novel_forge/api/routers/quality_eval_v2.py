from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from novel_forge.api.provider_adapters import adapter_from_provider_payload, ensure_model_route_from_payload
from novel_forge.api.routers.context import ProductRouterContext
from novel_forge.modules.chapter_economy import create_chapter_economy_report
from novel_forge.modules.character_pressure import create_character_pressure_reports
from novel_forge.modules.mobile_reading import create_mobile_reading_report
from novel_forge.modules.quality_eval import build_quality_calibration_readiness_report, build_quality_rubric_pack, run_provider_quality_judge, run_quality_gate, run_quality_suite
from novel_forge.storage.local import LocalStorage


def create_router(ctx: ProductRouterContext) -> APIRouter:
    app_settings = ctx.app_settings
    models = ctx.models
    globals().update(models)
    router = APIRouter(tags=["product-quality-eval-v2"])
    QualityRubricPackRequest = models["QualityRubricPackRequest"]
    QualitySuiteRunRequest = models["QualitySuiteRunRequest"]
    QualityGateRunRequest = models["QualityGateRunRequest"]
    ChapterEconomyRequest = models["ChapterEconomyRequest"]
    CharacterPressureRequest = models["CharacterPressureRequest"]
    MobileReadingRequest = models["MobileReadingRequest"]
    ProviderQualityJudgeRequest = models["ProviderQualityJudgeRequest"]

    @router.post("/product/quality/rubric-pack")
    def quality_rubric_pack_endpoint(request: QualityRubricPackRequest) -> dict:
        try:
            return build_quality_rubric_pack(
                LocalStorage(app_settings.root),
                genre_id=request.genre_id,
                platform_id=request.platform_id,
                style_profile_path=request.style_profile_path,
                scope=request.scope,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/quality/suite")
    def quality_suite_endpoint(request: QualitySuiteRunRequest) -> dict:
        try:
            return run_quality_suite(
                LocalStorage(app_settings.root),
                suite_type=request.suite_type,
                target_paths=request.target_paths,
                rubric_path=request.rubric_path,
                genre_strategy_pack_path=request.genre_strategy_pack_path,
                style_profile_path=request.style_profile_path,
                platform_id=request.platform_id,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/quality/gate")
    def quality_gate_endpoint(request: QualityGateRunRequest) -> dict:
        try:
            return run_quality_gate(
                LocalStorage(app_settings.root),
                quality_report_path=request.quality_report_path,
                environment=request.environment,
                envelope=request.envelope or None,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/quality/chapter-economy")
    def chapter_economy_endpoint(request: ChapterEconomyRequest) -> dict:
        try:
            return create_chapter_economy_report(
                LocalStorage(app_settings.root),
                request.draft_path,
                reward_ledger_path=request.reward_ledger_path or None,
                chapter_plan_path=request.chapter_plan_path or None,
                workspace_path=request.workspace_path,
                persist_issues=request.persist_issues,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/quality/character-pressure")
    def character_pressure_endpoint(request: CharacterPressureRequest) -> dict:
        try:
            return create_character_pressure_reports(
                LocalStorage(app_settings.root),
                request.draft_path,
                character_state_ledger_path=request.character_state_ledger_path or None,
                villain_operation_plan_path=request.villain_operation_plan_path or None,
                workspace_path=request.workspace_path,
                persist_issues=request.persist_issues,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/quality/mobile-reading")
    def mobile_reading_endpoint(request: MobileReadingRequest) -> dict:
        try:
            return create_mobile_reading_report(
                LocalStorage(app_settings.root),
                request.draft_path,
                platform_id=request.platform_id,
                workspace_path=request.workspace_path,
                persist_issues=request.persist_issues,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("/product/quality/provider-judge")
    def provider_quality_judge_endpoint(request: ProviderQualityJudgeRequest) -> dict:
        storage = LocalStorage(app_settings.root)
        payload = request.model_dump()
        try:
            route = ensure_model_route_from_payload(
                storage,
                task_type="quality_judge",
                payload=payload,
                project_id=str((request.envelope or {}).get("project_id") or ""),
                environment=request.environment,
            )
            adapter = adapter_from_provider_payload(
                {
                    **payload,
                    "fixture_response": request.fixture_judge_response or None,
                    "allow_mock_fixture": request.allow_mock_fixture,
                },
                default_operation="review",
            )
            result = run_provider_quality_judge(
                storage,
                suite_type=request.suite_type,
                target_paths=request.target_paths,
                rubric_path=request.rubric_path,
                adapter=adapter,
                genre_strategy_pack_path=request.genre_strategy_pack_path,
                style_profile_path=request.style_profile_path,
                platform_id=request.platform_id,
                environment=request.environment,
                envelope=request.envelope or None,
                provider_runtime_guard=request.provider_runtime_guard or None,
                allow_mock_fixture=request.allow_mock_fixture,
                require_external_provider_proof=request.require_external_provider_proof,
            )
            if route:
                result["model_route_path"] = route["path"]
            return result
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/product/quality/calibration-readiness")
    def quality_calibration_readiness_endpoint(project_id: str | None = None, persist: bool = True, limit: int = Query(default=1000, ge=1, le=5000)) -> dict:
        try:
            return build_quality_calibration_readiness_report(
                LocalStorage(app_settings.root),
                project_id=project_id or "",
                persist=persist,
                limit=limit,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return router
