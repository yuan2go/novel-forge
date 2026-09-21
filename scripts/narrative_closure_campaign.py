"""INVARIANT: Campaign progress and spending remain native Book, Chapter and Kernel facts."""

from __future__ import annotations

import argparse
from dataclasses import asdict, fields
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any

from novel_forge.modules.book_authority.production import SubmitBookChapterCommand
from novel_forge.modules.command_kernel.creative_budget_contract import (
    PAIRED_SAMPLES_VERSION, validate_comparison_budget,
)
from novel_forge.modules.review.diagnostics import prose_hash
from scripts.creation_freeze import _json_bytes, _read_regular, _write_file


VERSION = "narrative-closure-campaign.v1"
CRAFT_OBSERVATIONS = (
    "ADOPTED", "ADAPTED", "REJECTED", "NOT_USED", "MISUSED", "OVERUSED", "FORCED", "SIDE_EFFECT",
)


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json_bytes(value)).hexdigest()


def validate_campaign(value: dict) -> dict:
    if value.get("contract_version") != VERSION or value.get("intervention") not in {"WP02_COMBINED", "CRAFT_POLICY"}:
        raise ValueError("Campaign requires a separate versioned WP02 or Craft intervention")
    for key in ("campaign_id", "implementation_sha", "implementation_identity", "migration_head", "route_contract_hash", "database_name"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"Campaign requires exact {key}")
    if len(value["implementation_sha"]) != 40 or not all(char in "0123456789abcdef" for char in value["implementation_sha"]):
        raise ValueError("Campaign implementation SHA must be complete")
    design = value.get("comparison_design") or {}
    if design != {"implementation_control": "SAME_FINAL_IMPLEMENTATION_NATIVE_PATHS",
                  "historical_defective_implementation": "NOT_RUN",
                  "attribution": "COMPLETE_DECLARED_INTERVENTION_ONLY"}:
        raise ValueError("Freeze native-path comparison scope; a shared final implementation cannot prove historical old-versus-new effects")
    budget = validate_comparison_budget(value["budget"], require_both_arms=True)
    if budget["contract_version"] != PAIRED_SAMPLES_VERSION or budget["experiment_id"] != value["campaign_id"]:
        raise ValueError("Campaign requires its exact native paired sample budget")
    pairs = value.get("samples")
    if not isinstance(pairs, list) or len(pairs) not in {2, 8}:
        raise ValueError("Freeze two pilot tasks, optionally followed by six exploration tasks")
    indexed = {(arm["sample_id"], arm["arm"]): arm for arm in budget["arms"]}
    seen, groups, native_ids = set(), set(), set()
    for sample in pairs:
        identity = sample["sample_id"]
        if not isinstance(identity, str) or re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,79}", identity) is None:
            raise ValueError("Sample identity must be a safe bounded filename")
        if identity in seen or sample.get("data_group") in groups:
            raise ValueError("Samples require distinct identities and independent data groups")
        seen.add(identity)
        groups.add(sample["data_group"])
        if sample["domain"] not in {"ACTION", "RELATIONSHIP"}:
            raise ValueError("Samples must declare action or relationship scope")
        if set(sample["arms"]) != {"A", "B"}:
            raise ValueError("Every sample requires exactly two independent arms")
        for name, arm in sample["arms"].items():
            allocation = indexed.get((identity, name))
            if allocation is None or any(arm[key] != allocation[key] for key in ("project_id", "book_id")) or sample["stage"] != allocation["stage"]:
                raise ValueError("Sample differs from its immutable native budget participant")
            for key in ("book_run_id", "chapter_group_run_id", "author_input_asset_version_id"):
                if not isinstance(arm.get(key), str) or not arm[key].strip() or arm[key] in native_ids:
                    raise ValueError("Each arm needs independent native Book Run and original-input versions")
                native_ids.add(arm[key])
            command = arm["chapter_command"]
            allowed = {field.name for field in fields(SubmitBookChapterCommand)} - {"book_run_id"}
            if not isinstance(command, dict) or set(command) - allowed:
                raise ValueError("Only native SubmitBookChapterCommand fields may be frozen")
            SubmitBookChapterCommand(book_run_id=arm["book_run_id"], **command)
            if set(arm.get("world_character_asset_version_ids") or {}) != {"world", "characters"}:
                raise ValueError("Each arm requires exact world and character source versions")
            adoption = (command.get("preparation_report") or {}).get("author_draft_adoption") or {}
            if not adoption.get("candidate_asset_version_id") or not adoption.get("decision_asset_version_id"):
                raise ValueError("Same-draft campaign requires a native accepted author candidate binding")
        if sample["arms"]["A"]["chapter_command"]["chapter_number"] != sample["arms"]["B"]["chapter_command"]["chapter_number"]:
            raise ValueError("Paired chapter positions differ")
        for key in ("source_text_hashes", "original_text_hash", "plan_semantics_hash", "world_character_contract_hash"):
            if key not in sample:
                raise ValueError(f"Sample must freeze {key}")
        if any(key in sample for key in ("expected_answer", "answer", "expected_diagnosis")):
            raise ValueError("Evaluation answers do not belong in runtime input manifests")
    if set(indexed) != {(sample, arm) for sample in seen for arm in ("A", "B")}:
        raise ValueError("Budget and sample populations differ")
    exploration = [sample for sample in pairs if sample["stage"] == "EXPLORATION"]
    if exploration and sorted(sample["domain"] for sample in exploration) != ["ACTION"] * 3 + ["RELATIONSHIP"] * 3:
        raise ValueError("Exploration must contain three action and three relationship tasks")
    return value


def plan_semantics(content: dict, *, intervention: str = "WP02_COMBINED") -> dict:
    excluded = {"project_id", "workspace_id", "book_id"}
    if intervention == "CRAFT_POLICY":
        excluded.add("craft_strategy")
    return {key: item for key, item in content.items() if key not in excluded}


def require_native_inputs(*, sample: dict, arm: dict, composition: Any, query: Any, intervention: str = "WP02_COMBINED") -> dict:
    book = composition.authority.require(arm["book_run_id"])
    if any(book[key] != arm[key] for key in ("project_id", "book_id")):
        raise ValueError("Frozen Book Run belongs to another arm")
    command = arm["chapter_command"]
    number = command["chapter_number"]
    group = composition.chapter_groups.require(arm["chapter_group_run_id"])
    if (any(group[key] != arm[key] for key in ("project_id", "book_id", "book_run_id"))
        or group["group_plan_version_id"] != command.get("parent_group_version_id")
        or group["chapter_end"] != number):
        raise ValueError("Target must close its exact native ChapterGroup so pilot reading is complete")
    if book["accepted_through_chapter"] not in {number - 1, number}:
        raise ValueError("Campaign Book cursor differs from its exact frozen target")
    plan = query.require(project_id=arm["project_id"], asset_version_id=command["chapter_plan_asset_version_id"])
    if plan.content_hash != command["chapter_plan_content_hash"] or digest(plan_semantics(plan.content, intervention=intervention)) != sample["plan_semantics_hash"]:
        raise ValueError("Native plan differs from the paired frozen plan")
    adoption = command["preparation_report"]["author_draft_adoption"]
    authored = query.require(project_id=arm["project_id"], asset_version_id=adoption["candidate_asset_version_id"])
    if prose_hash(authored.content["text"]) != sample["original_text_hash"]:
        raise ValueError("Native author candidate differs from the paired exact original")
    source = query.require(project_id=arm["project_id"], asset_version_id=arm["author_input_asset_version_id"])
    if (source.asset_type != "author_edit_candidate" or source.asset_version_id != authored.asset_version_id
        or source.content.get("rights_basis") not in {"ORIGINAL_AUTHOR_INPUT", "AUTHORIZED_INPUT"}):
        raise ValueError("The exact adopted original must carry its native author rights declaration")
    sources = []
    for chapter in range(1, number):
        reality = composition.query.narrative_reality(book_run_id=arm["book_run_id"], chapter_number=chapter)
        sources.append(reality)
    from scripts.creation_reading import load_accepted_reading
    reading = load_accepted_reading(composition=composition, book_run_id=arm["book_run_id"], through_chapter=number - 1) if number > 1 else {"chapters": []}
    actual = [item["text_hash"] for item in reading["chapters"]]
    if actual != sample["source_text_hashes"]:
        raise ValueError("Accepted history differs from the same-prose paired source window")
    world = arm["world_character_asset_version_ids"]
    world_documents = {
        key: plan_semantics(query.require(project_id=arm["project_id"], asset_version_id=version).content)
        for key, version in world.items() if version
    }
    if not world_documents or digest(world_documents) != sample["world_character_contract_hash"]:
        raise ValueError("World and character facts must be exact and comparable across arms")
    context_ids = {item.get("asset_version_id") for item in command["context_candidates"]}
    if not set(world.values()).issubset(context_ids):
        raise ValueError("Frozen world and character contracts must be actual native Context candidates")
    profile = query.require(project_id=arm["project_id"], asset_version_id=book["production_profile_version"])
    return {"original": authored.content, "plan": plan.content, "production_profile": profile.content,
            "source_reading": reading, "source_realities": sources}


def require_intervention(*, manifest: dict, pair: dict[str, dict]) -> None:
    profiles = [plan_semantics(pair[name]["production_profile"]) for name in ("A", "B")]
    if manifest["intervention"] == "WP02_COMBINED":
        windows = [profile.pop("cross_chapter_review_policy", None) for profile in profiles]
        if windows[0] is not None or not windows[1]:
            raise ValueError("WP02 A must retain the original path and B must enable the frozen prose window")
        if pair["A"]["plan"].get("craft_strategy") != pair["B"]["plan"].get("craft_strategy"):
            raise ValueError("WP02 comparison cannot also change the frozen Craft strategy")
    else:
        strategies = [pair[name]["plan"].get("craft_strategy") for name in ("A", "B")]
        if strategies[0] == strategies[1] or not strategies[1]:
            raise ValueError("Craft comparison must actually change the adopted strategy")
    if profiles[0] != profiles[1]:
        raise ValueError("Comparison changes production policy beyond its declared intervention")


def drive_chapter(*, composition: Any, chapter: Any, principal: Any, worker: Any,
                  arm: dict, deadline: float, max_ticks: int, record: Any) -> dict:
    command = SubmitBookChapterCommand(book_run_id=arm["book_run_id"], **arm["chapter_command"])
    book = composition.authority.require(arm["book_run_id"])
    group_id = arm.get("chapter_group_run_id")
    if group_id and book["accepted_through_chapter"] == command.chapter_number:
        group = composition.chapter_groups.require(group_id)
        if group["state"] == "CHAPTER_RUNNING":
            group = composition.chapter_groups.reconcile_and_accept(group_id, principal=principal)
        if group["state"] == "CLOSURE_PENDING":
            composition.chapter_groups.close(group_id, principal=principal)
    if book["accepted_through_chapter"] == command.chapter_number:
        request_id = composition.query.latest_accepted_chapter_request_id(book_run_id=arm["book_run_id"], project_id=arm["project_id"])
        existing = composition.authority.require_chapter_request(request_id)
        original_command = dict(existing["command_payload"])
        original_command.pop("accepted_prose_snapshot", None)
        if digest(original_command) != digest(asdict(command)):
            raise ValueError("Accepted replay differs from the frozen Chapter request")
        return {"status": "ACCEPTED_TARGET", "replayed": True, "acceptance": book, "chapter_request": existing}
    if group_id:
        group = composition.chapter_groups.require(group_id)
        if not group.get("active_chapter_request_id"):
            group = composition.chapter_groups.dispatch(group_id, command, principal=principal)
        dispatched = composition.authority.require_chapter_request(group["active_chapter_request_id"])
        original_command = dict(dispatched["command_payload"])
        original_command.pop("accepted_prose_snapshot", None)
        if digest(original_command) != digest(asdict(command)):
            raise ValueError("Resuming ChapterGroup contains a different frozen Chapter request")
    else:
        dispatched = composition.authority.submit_chapter(command, principal=principal)
    record({"kind": "NATIVE_CHAPTER_ADMISSION", "result": dispatched})
    scheduler = chapter.scheduler(principal=worker)
    for _ in range(max_ticks):
        if time.monotonic() >= deadline:
            return {"status": "BOUNDED_TIME_EXHAUSTED", "chapter_request": dispatched}
        tick = scheduler.tick(project_id=arm["project_id"], root_operation_id=dispatched["chapter_root_operation_id"])
        record({"kind": "CHAPTER_TICK", "result": asdict(tick)})
        if tick.saga_status == "SUCCEEDED":
            if group_id:
                group = composition.chapter_groups.reconcile_and_accept(group_id, principal=principal)
                if group["state"] == "CLOSURE_PENDING":
                    group = composition.chapter_groups.close(group_id, principal=principal)
                if group["state"] != "COMPLETED":
                    return {"status": "WAITING_ACCEPTED_GROUP_CLOSURE", "chapter_request": dispatched, "group": group}
                accepted = composition.authority.require(arm["book_run_id"])
            else:
                composition.authority.reconcile_chapter(dispatched["chapter_request_id"])
                accepted = composition.authority.accept_chapter(dispatched["chapter_request_id"], principal=principal)
            return {"status": "ACCEPTED_TARGET", "acceptance": accepted, "chapter_request": dispatched}
        if tick.saga_status in {"FAILED_TERMINAL", "CANCELLED", "WAITING_GATE"} or tick.operation_status in {"RECONCILIATION_REQUIRED", "WAITING_EXTERNAL_RESULT", "WAITING_APPROVAL", "WAITING_OPERATOR", "FAILED_TERMINAL"}:
            return {"status": "NATIVE_GATE_OR_RECOVERY_REQUIRED", "tick": asdict(tick), "chapter_request": dispatched}
    return {"status": "BOUNDED_TICKS_EXHAUSTED", "chapter_request": dispatched}


def execute_campaign(manifest: dict, *, root: Path, destination: Path, stage: str,
                     max_ticks: int, max_seconds: int) -> dict:
    from novel_forge.api.authority_dependencies import (
        build_book_production_composition, build_chapter_authority_application,
        build_production_execution_composition, build_trusted_principal_resolver,
    )
    from novel_forge.infrastructure.settings import IndustrialSettings
    from novel_forge.modules.command_kernel.creative_budget_runtime import get_creative_budget
    from novel_forge.modules.production_execution.security import redact_secret_text
    from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
    from scripts.creation_checkpoints import require_reading_decision
    from scripts.creation_pilot import freeze_routes
    from scripts.run_world_production_smoke import export, validate_configuration

    values = dict(os.environ)
    validate_configuration(values)
    settings = IndustrialSettings.from_env(values, root=root)
    import psycopg
    from novel_forge.storage.migrations import LATEST_MIGRATION_ID, MIGRATIONS
    from novel_forge.tools.backend_qualification_resources import require_disposable_database_name
    with psycopg.connect(settings.database_url, options="-c default_transaction_read_only=on") as connection:
        database = connection.execute("SELECT current_database()").fetchone()[0]
        applied = {row[0] for row in connection.execute("SELECT migration_id FROM nf_schema_migrations").fetchall()}
    require_disposable_database_name(database)
    if database != manifest["database_name"] or manifest["migration_head"] != LATEST_MIGRATION_ID or applied != {migration.migration_id for migration in MIGRATIONS}:
        raise ValueError("Campaign database or exact migration identity changed")
    resolver = build_trusted_principal_resolver(env=values)
    principal = resolver.resolve_api_principal()
    worker = resolver.resolve_worker_principal("narrative-closure-worker")
    execution = build_production_execution_composition(settings, env=values)
    report: dict[str, Any] = {"status": "RUNNING", "campaign_hash": digest(manifest), "arms": [], "human_editorial": "NOT_RUN", "creative_effect": "NOT_PROVEN"}
    try:
        if any(route.model_profile.model_provider == "scripted_provider_v2" for route in execution.gateway.routes.values()):
            raise ValueError("Real experiment rejects scripted routes")
        if digest(freeze_routes(execution.gateway.routes)) != manifest["route_contract_hash"]:
            raise ValueError("Frozen Provider/Prompt/Skill/token-accounting route changed")
        chapter = build_chapter_authority_application(settings, execution=execution, env=values)
        composition = build_book_production_composition(settings, principal=principal, execution=execution, chapter_application=chapter, env=values)
        query = AuthorityAssetQuery(settings.database_url)
        samples = sorted(manifest["samples"], key=lambda item: (item["stage"] != "PILOT", item["sample_id"]))
        frozen_inputs = {}
        for sample in samples:
            if sample["stage"] == "EXPLORATION" and stage == "PILOT":
                continue
            pair = {}
            for name, arm in sample["arms"].items():
                principal.require("book.authority.execute", arm["project_id"])
                native_budget = get_creative_budget(settings.database_url, arm["project_id"])
                if native_budget["comparison_budget"] != manifest["budget"]:
                    raise ValueError("All arm budgets must match before the first dispatch")
                pair[name] = require_native_inputs(sample=sample, arm=arm, composition=composition, query=query, intervention=manifest["intervention"])
            require_intervention(manifest=manifest, pair=pair)
            frozen_inputs[sample["sample_id"]] = pair
        for sample in samples:
            if sample["stage"] == "EXPLORATION" and stage == "PILOT":
                continue
            for name, arm in sample["arms"].items():
                principal.require("book.authority.execute", arm["project_id"])
                budget = get_creative_budget(settings.database_url, arm["project_id"])
                if budget["comparison_budget"] != manifest["budget"]:
                    raise ValueError("Native budget or authorization differs from the frozen campaign")
                inputs = frozen_inputs[sample["sample_id"]][name]
                if stage == "EXPLORATION" and sample["stage"] == "PILOT":
                    require_reading_decision(composition=composition, book_run_id=arm["book_run_id"], boundary=arm["chapter_command"]["chapter_number"])
                    continue
                directory = destination / sample["sample_id"] / name
                directory.mkdir(parents=True, exist_ok=False)
                _write_file(directory / "frozen-inputs.json", _json_bytes(inputs))
                def record(event, directory=directory):
                    with (directory / "events.jsonl").open("ab") as stream:
                        stream.write((json.dumps(event, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
                        stream.flush()
                        os.fsync(stream.fileno())
                result = {"status": "FAILED_BEFORE_ACCEPTANCE"}
                try:
                    result = drive_chapter(composition=composition, chapter=chapter, principal=principal, worker=worker, arm=arm,
                                           deadline=time.monotonic() + max_seconds, max_ticks=max_ticks, record=record)
                except Exception as exc:
                    result = {"status": "FAILED", "error": redact_secret_text(str(exc)), "error_code": getattr(exc, "code", type(exc).__name__)}
                finally:
                    try:
                        export(composition=composition, book_run_id=arm["book_run_id"], destination=directory)
                        from scripts.compare_creation_exports import chapter_results
                        manuscripts, errors = chapter_results(directory)
                        if errors:
                            raise ValueError("Native accepted manuscript export is incomplete")
                        original = inputs["original"]["text"]
                        _write_file(directory / "original.txt", original.encode("utf-8"))
                        target = manuscripts.get(arm["chapter_command"]["chapter_number"])
                        if target:
                            import difflib
                            selected = target["candidate"]["content"]["text"]
                            _write_file(directory / "selected.txt", selected.encode("utf-8"))
                            _write_file(directory / "changes.diff", "\n".join(difflib.unified_diff(original.splitlines(), selected.splitlines(), fromfile="original", tofile="selected", lineterm="")).encode("utf-8"))
                        result["budget"] = get_creative_budget(settings.database_url, arm["project_id"])
                    except Exception as exc:
                        result.update(status="EVIDENCE_EXPORT_FAILED", export_error=redact_secret_text(str(exc)))
                    _write_file(directory / "result.json", _json_bytes(result))
                    report["arms"].append({"sample_id": sample["sample_id"], "arm": name, **result})
                if result["status"] != "ACCEPTED_TARGET":
                    report["status"] = "STOPPED_AT_NATIVE_FAILURE_OR_GATE"
                    return report
                if sample["stage"] == "PILOT":
                    book = composition.authority.require(arm["book_run_id"])
                    if book["state"] != "PAUSED":
                        composition.authority.pause(arm["book_run_id"], principal=principal, reason="Frozen pilot requires source-bound reading decision before exploration")
        report["status"] = "PILOT_AWAITING_NATIVE_READING_DECISIONS" if stage == "PILOT" else "EXPLORATION_EXECUTED_NOT_QUALITY_PROVEN"
        return report
    finally:
        execution.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("freeze", "run", "resume"))
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--manifest-hash", default="")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--stage", choices=("PILOT", "EXPLORATION"), default="PILOT")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-ticks", type=int, default=80)
    parser.add_argument("--max-seconds", type=int, default=1800)
    args = parser.parse_args(argv)
    manifest = validate_campaign(json.loads(_read_regular(args.manifest)))
    identity = digest(manifest)
    if args.action == "freeze":
        _write_file(args.output, _json_bytes(manifest))
        print(json.dumps({"manifest_hash": identity, "real_provider": "NOT_RUN", "status": "FROZEN_NATIVE_BINDINGS_REQUIRE_LIVE_VERIFICATION"}))
        return 0
    if not args.execute or not args.root or args.manifest_hash != identity:
        parser.error("run/resume requires --execute, --root and the exact frozen --manifest-hash")
    if not 1 <= args.max_ticks <= 200 or not 1 <= args.max_seconds <= 7200:
        parser.error("bounded ticks/time must be 1..200 and 1..7200")
    repo = Path(__file__).resolve().parents[1]
    from novel_forge.tools.implementation_tree_identity import build_implementation_tree_identity
    from novel_forge.modules.production_execution.security import redact_secret_text
    if (subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() != manifest["implementation_sha"]
        or subprocess.check_output(["git", "status", "--porcelain"], cwd=repo, text=True).strip()
        or build_implementation_tree_identity(repo)["implementation_tree_sha"] != manifest["implementation_identity"]):
        parser.error("Execution requires the clean frozen implementation identity")
    args.output.mkdir(parents=True, exist_ok=False)
    try:
        report = execute_campaign(manifest, root=args.root, destination=args.output, stage=args.stage, max_ticks=args.max_ticks, max_seconds=args.max_seconds)
    except Exception as exc:
        report = {"status": "BLOCKED", "error": redact_secret_text(str(exc)), "campaign_hash": identity, "human_editorial": "NOT_RUN"}
    report["comparison_design"] = manifest["comparison_design"]
    if (subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip() != manifest["implementation_sha"]
        or build_implementation_tree_identity(repo)["implementation_tree_sha"] != manifest["implementation_identity"]):
        report.update(status="IMPLEMENTATION_DRIFT_EVIDENCE_INVALIDATED", creative_effect="NOT_PROVEN")
    _write_file(args.output / "campaign-result.json", _json_bytes(report))
    print(json.dumps(report, ensure_ascii=False, default=str))
    return 0 if report["status"] in {"PILOT_AWAITING_NATIVE_READING_DECISIONS", "EXPLORATION_EXECUTED_NOT_QUALITY_PROVEN"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
