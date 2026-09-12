from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import secrets
import shutil

from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy, validate_book_knowledge_access_policy
from novel_forge.modules.review.knowledge import knowledge_review_targets
from novel_forge.modules.reader_calibration.blind_export import (
    BlindComparisonSubject, BlindEvaluator, export_blind_evaluation_packs,
)
from novel_forge.modules.reader_calibration.domain import BlindScope, EvaluatorIdentityClass
from scripts.compare_creation_exports import chapter_results
from novel_forge.modules.story_planning_runtime.domain import canonical_hash


AXES = ("knowledge_accuracy", "natural_integration", "causality", "character", "pacing", "voice", "desire_to_continue")


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def prepare(destination: Path, approved_versions: list[str] | None = None, *, target_book_id: str = "", input_dir: Path | None = None) -> dict:
    source = (input_dir or Path(__file__).resolve().parents[1] / "config/production/knowledge-closure").resolve()
    if not source.is_dir() or any(not path.is_file() for path in source.iterdir()):
        raise ValueError("Freeze input directory must contain only explicit input files")
    destination.mkdir(parents=True, exist_ok=False)
    for path in sorted(source.iterdir()):
        shutil.copyfile(path, destination / path.name)
    for name, count in ((("professional", 3), ("fiction", 6)) if input_dir is None else ()):
        _write(destination / f"{name}-import.json", {
            "source": {"kind": "LOCAL", "location": str((destination / f"{name}.jsonl").resolve())},
            "parser": {"version": "corpus-parser.v3", "format": "jsonl", "layout": "CHAPTER_ROWS",
                       "normalization": {"version": "chinese-longform.v2", "segmentation": "EXPLICIT", "min_body_chars": 1},
                       "fields": {"work_id": "book", "text": "text", "chapter_id": "chapter", "order": "order"},
                       "completeness": "COMPLETE", "expected_units": count},
            "purpose": "PRODUCTION_REFERENCE", "analyze": False,
            "rights": {"dataset_license": "CC0-1.0", "scope": "ALL_WORKS_IN_SNAPSHOT",
                       "underlying_rights": "OWNED", "allowed_purposes": ["PRODUCTION_REFERENCE"],
                       "allowed_uses": ["LOCAL_PROCESSING", "SOURCE_ANALYSIS", "ABSTRACT_GENERATION"],
                       "evidence_refs": ["repository:original-synthetic-knowledge-closure-fixture"],
                       "copyright_boundary": "Original synthetic test material; abstract learning only; no real-world professional qualification"},
        })
    binding = "KNOWLEDGE_APPROVAL_AND_EXACT_VERSION_BINDING_REQUIRED"
    if approved_versions is not None:
        policy = {"policy_id": "knowledge-closure-treatment", "policy_version": 1,
                  "mode": "ALLOW_ONLY", "allowed_knowledge_card_asset_version_ids": approved_versions}
        resolve_book_knowledge_access_policy(production_profile={"knowledge_access_policy": policy},
                                             project_id="configuration-check", book_id="configuration-check")
        _write(destination / "allow-only.json", policy)
        binding = "EXACT_VERSIONS_BOUND_AUTHORITY_RECHECK_REQUIRED"
    review_form = {"status": "NOT_REVIEWED", "reviewer_id": None, "sample_token": None,
                   "scale": {"minimum": 1, "maximum": 5, "unknown": "CANNOT_JUDGE"},
                   "axes": {axis: {"score": None, "chapter": None, "quote": None, "reason": None} for axis in AXES},
                   "knowledge_accuracy_reference": "Use the same approved abstract mechanism reference sheet for both samples after prose-only evaluation; keep treatment identity hidden."}
    _write(destination / "review-form.json", review_form)
    frozen = {"contract_version": "knowledge-closure-freeze.v1", "status": "READY_FOR_AUTHORIZATION",
              "input_directory": str(source), "arm_a_binding": binding, "real_provider_execution": "NOT_RUN", "human_editorial": "NOT_RUN",
              "analysis_target": {"intended_use": "ABSTRACT_GENERATION", "target_book_id": target_book_id,
                                  "status": "PENDING_AUTHORITY_PREFLIGHT" if target_book_id else "TARGET_BOOK_ID_REQUIRED"},
              "source_production_qualification": {
                  "required_scope": "EXACT_SOURCE_CAPABILITY_D0",
                  "supported_accounting_bases": ["PRICED", "ACCOUNT_ENTITLEMENT"],
                  "account_entitlement": "EXACT_AUTHORIZATION_ACCOUNT_AND_ENTITLEMENT_SNAPSHOT_REQUIRED",
                  "card_approval": "SEPARATE_GOVERNANCE_REVIEW_AND_AUTHORITY_RECHECK_REQUIRED",
              },
              "model_binding": "REQUIRED_AUTHORIZED_EXACT_ROUTE_FOR_BOTH_ARMS",
              "required_authorization": ["provider/backend and exact model", "account identity and permitted purpose",
                                         "total calls, input/output tokens and priced cost or explicit accounting basis",
                                         "revision/retry allocation within the same total", "independent Books and upper plans; frozen project sublimits sum within the shared grant"],
              "files": {path.name: "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in sorted(destination.iterdir()) if path.is_file()}}
    _write(destination / "freeze.json", frozen)
    return frozen


def _executed_groups(directory: Path, chapters: dict, identity: dict) -> list[dict]:
    try:
        lineage = json.loads((directory / "chapter-groups.json").read_text())
        scope = {key: identity[key] for key in ("project_id", "book_id", "book_run_id")}
        if (
            lineage.get("contract_version") != "book-chapter-group-lineage.v1"
            or any(lineage.get(key) != value for key, value in scope.items())
            or not all(scope.values()) or lineage.get("has_more") is not False
            or lineage.get("offset") != 0 or lineage.get("accepted_through_chapter") != 6
        ):
            raise ValueError("ChapterGroup export has incomplete or foreign Book scope")
        selected, covered, identities = [], set(), set()
        for group in lineage["groups"]:
            if group["group_run_id"] in identities:
                raise ValueError("ChapterGroup export repeats a Run identity")
            identities.add(group["group_run_id"])
            if any(group.get(key) != value for key, value in scope.items()):
                raise ValueError("ChapterGroup belongs to another Book")
            start, end = group["chapter_range"]
            plan = group["plan"]
            if (
                type(start) is not int or type(end) is not int or not 1 <= start <= end
                or plan["asset_version_id"] != group["group_plan_version_id"]
                or plan["content"].get("chapter_range") != [start, end]
                or canonical_hash(plan["content"]) != plan["content_hash"]
            ):
                raise ValueError("ChapterGroup range differs from its exact immutable plan")
            accepted = [item for item in group["chapters"] if item["status"] == "ACCEPTED"]
            if not accepted:
                continue
            if (
                group["state"] != "COMPLETED" or group["accepted_through_chapter"] != end
                or [item["chapter_number"] for item in accepted] != list(range(start, end + 1))
                or len(accepted) != len(group["chapters"])
            ):
                raise ValueError("ChapterGroup accepted coverage is incomplete")
            for child in accepted:
                number = child["chapter_number"]
                workspace = chapters[number]["workspace"]
                acceptance = workspace["acceptance"]
                outcome = acceptance["outcome"]["content"]
                command = workspace["run"]["command"]
                plans = [item for values in workspace["artifacts"].values() if isinstance(values, list)
                         for item in values if isinstance(item, dict)
                         and item.get("asset_type") == "chapter_plan"
                         and item.get("asset_version_id") == outcome["chapter_plan_version_id"]]
                if not plans or any(
                    canonical_hash(plan["content"]) != plan["content_hash"]
                    or plan["content"].get("source_extensions", {}).get("source_planning_candidate_asset_version_id") != child["chapter_plan_version_id"]
                    or plan["content"].get("source_chapter_plan_asset_version_id") != command.get("chapter_plan_asset_version_id")
                    or plan["content"].get("source_chapter_plan_content_hash") != command.get("chapter_plan_content_hash")
                    for plan in plans
                ):
                    raise ValueError("ChapterGroup planning candidate differs from the frozen and normalized Chapter plan")
                if (
                    number in covered or child["acceptance_status"] != "COMMITTED"
                    or any(workspace.get(key) != value for key, value in scope.items())
                    or child["child_root_operation_id"] != workspace["root_operation_id"]
                    or child["acceptance_id"] != acceptance["acceptance_id"]
                    or child["chapter_outcome_version_id"] != acceptance["outcome_asset_version_id"]
                    or acceptance["outcome"]["content"].get("parent_group_version_id") != group["group_plan_version_id"]
                    or any(not child.get(key) or child[key] != acceptance.get(key) for key in ("story_state_asset_version_id", "canon_snapshot_asset_version_id"))
                    or not child.get("chapter_request_id") or not child.get("acceptance_operation_id")
                ):
                    raise ValueError("ChapterGroup child differs from the exact accepted manuscript and state")
                covered.add(number)
            selected.append(group)
        if covered != set(chapters):
            raise ValueError("ChapterGroup export does not cover all accepted manuscripts")
        if len(selected) < 2:
            raise ValueError("Comparison requires at least two independently executed chapter groups")
        return selected
    except (OSError, KeyError, TypeError) as exc:
        raise ValueError("ChapterGroup execution lineage is missing or incomplete") from exc



def _treatment_evidence(directory: Path, chapters: dict, identity: dict, allowed: set[str]) -> dict:
    from novel_forge.modules.mkaos_authority.trace import workspace_knowledge_trace
    from novel_forge.modules.review.diagnostics import validate_location
    result = {"treatment_status": "TREATMENT_NOT_ESTABLISHED", "treatment_delivery": "NOT_EXPORTED",
              "treatment_realization": "NOT_VERIFIED_IN_ACCEPTED_PROSE", "creative_benefit": "CREATIVE_BENEFIT_NOT_EVALUABLE",
              "independent_editorial": "NOT_PROVEN", "evidence_classes": [], "delivered": [], "realized": []}
    path = directory / "knowledge-runtime-usage.json"
    if not path.is_file():
        return result
    usage = json.loads(path.read_text())
    if any(usage.get(key) != identity[key] for key in ("project_id", "book_id", "book_run_id")):
        raise ValueError("Knowledge runtime export belongs to another Book Run")
    if (usage.get("contract_version") != "book-knowledge-runtime-export.v1"
        or usage.get("status") != "COMPLETE" or usage.get("bounded") is not False):
        return result
    result["treatment_delivery"] = "NOT_DELIVERED_TO_CREATIVE_REQUEST"
    for number, chapter in chapters.items():
        context = chapter["context"]
        delivered = [item for item in usage["records"]
                     if item.get("project_id") == identity["project_id"] and item.get("book_id") == identity["book_id"]
                     and item.get("knowledge_card_asset_version_id") in allowed
                     and item.get("context_bundle_asset_version_id") == context["asset_version_id"]
                     and item.get("context_bundle_content_hash") == context["content_hash"]
                     and item.get("consumer_definition_name") in {"chapter.draft.generate", "chapter.revision.apply"}
                     and item.get("external_effect_status") == "SUCCEEDED" and item.get("external_effect_id")
                     and item.get("external_receipt_ids") and item.get("provider_context_view_hash")]
        result["delivered"].extend({"chapter": number, **item} for item in delivered)
        delivered_ids = {item["knowledge_card_asset_version_id"] for item in delivered}
        for card in workspace_knowledge_trace(chapter["workspace"])["cards"]:
            accepted = card.get("accepted") or {}
            check = accepted.get("check") or {}
            if (card["knowledge_card_asset_version_id"] in delivered_ids
                and check.get("status") == "VERIFIED_IN_PROSE" and check.get("conditions_checked")):
                validate_location(dict(check.get("evidence") or {}), chapter["candidate"]["content"]["text"])
                result["realized"].append({"chapter": number, "knowledge_card_asset_version_id": card["knowledge_card_asset_version_id"], **accepted})
    if result["delivered"]:
        result["treatment_delivery"] = "VERIFIED_CREATIVE_REQUEST_RECEIPTS"
    if result["realized"]:
        result.update(treatment_status="TREATMENT_ESTABLISHED_BY_RECORDED_EVIDENCE",
                      treatment_realization="VERIFIED_IN_ACCEPTED_PROSE", creative_benefit="EVALUABLE_NOT_PROVEN")
    result["evidence_classes"] = sorted({item.get("delivery_evidence_class", "UNVERIFIED_PROVIDER_RECEIPT") for item in result["delivered"]}
                                       | {item["check"].get("evidence_class", "UNVERIFIED_REVIEW") for item in result["realized"]})
    return result


def blind_export(left: Path, right: Path, destination: Path) -> dict:
    results = [chapter_results(path) for path in (left, right)]
    if any(errors or set(chapters) != set(range(1, 7)) for chapters, errors in results):
        raise ValueError("Blind export requires six exact accepted chapters in each arm; preserve partial exports")
    arms = [item[0] for item in results]
    identities = [json.loads((path / "creation-run.json").read_text()) for path in (left, right)]
    for directory, identity in zip((left, right), identities, strict=True):
        try:
            statuses = [json.loads((directory / name).read_text()) for name in ("asset-export-status.json", "workspace-export-status.json")]
        except (OSError, ValueError) as exc:
            raise ValueError("Blind comparison requires complete native evidence export receipts") from exc
        if (
            identity.get("status") not in {"ACCEPTED_TARGET_REACHED", "PILOT_ACCEPTED_CURSOR_REACHED"}
            or identity.get("artifact_export_error") or identity.get("export_error")
            or any(status.get("status") != "COMPLETE" or status.get("errors") != [] for status in statuses)
        ):
            raise ValueError("Blind comparison requires complete native evidence exports and a successful accepted cursor")
    for field in ("implementation_identity", "brief_input_hash", "formation_policy"):
        if not identities[0].get(field) or identities[0][field] != identities[1].get(field):
            raise ValueError("Comparison frozen inputs differ: " + field)
    frozen = [item.get("frozen_configuration", {}) for item in identities]
    if not frozen[0].get("models") or frozen[0]["models"] != frozen[1].get("models"):
        raise ValueError("Comparison requires identical frozen model, Prompt and Skill routes")
    policies_without_knowledge = []
    for item in frozen:
        policy = deepcopy(item.get("creation_policy") or {})
        if not policy:
            raise ValueError("Comparison requires frozen creation and revision policies")
        policy["profiles"]["production_profile"]["content"].pop("knowledge_access_policy", None)
        policies_without_knowledge.append(policy)
    if policies_without_knowledge[0] != policies_without_knowledge[1]:
        raise ValueError("Comparison word targets, revision policy or future intervention differ")
    for field in ("runtime_settings", "cost_accounting"):
        values = [deepcopy(item.get(field)) for item in frozen]
        if field == "cost_accounting":
            for value in values:
                if isinstance(value, dict):
                    value.pop("authorization_ref", None)
        if any(value is None for value in values) or values[0] != values[1]:
            raise ValueError("Comparison frozen budgets or runtime settings differ: " + field)
    if identities[0]["book_id"] == identities[1]["book_id"]:
        raise ValueError("Comparison arms require independently created Books")
    arc_sets = []
    group_sets = []
    for i, identity in enumerate(identities):
        changed = identity.get("future_plan_change") or {}
        if changed.get("after_chapter") != 3 or not changed.get("result", {}).get("snapshot_id"):
            raise ValueError("Comparison requires the applied third-chapter future PlanChange receipt")
        arcs = {arc for chapter in arms[i].values()
                for arc in chapter["workspace"]["run"]["command"].get("context_version_refs", {}).get("arc_plan_versions", [])}
        groups = _executed_groups((left, right)[i], arms[i], identity)
        group_sets.append({item[key] for item in groups for key in ("group_plan_version_id", "volume_plan_version_id")})
        arc_sets.append(arcs)
    if arc_sets[0] & arc_sets[1] or group_sets[0] & group_sets[1]:
        raise ValueError("Comparison arms cannot share upper-level plans")
    for number in range(1, 7):
        if arms[0][number]["context"]["content"].get("chapter_execution", {}).get("source_chapter_plan_asset_version_id") == arms[1][number]["context"]["content"].get("chapter_execution", {}).get("source_chapter_plan_asset_version_id"):
            raise ValueError("Comparison arms cannot share absorbed plans")
    policies = [item["knowledge_access_policy"] for item in identities]
    if policies[0]["mode"] != "ALLOW_ONLY" or policies[1]["mode"] != "DENY_ALL":
        raise ValueError("Expected approved-only treatment and DENY_ALL control")
    for identity, chapters, policy in zip(identities, arms, policies, strict=True):
        scope = {key: identity[key] for key in ("project_id", "book_id")}
        validate_book_knowledge_access_policy(policy, **scope)
        allowed = set(policy["allowed_knowledge_card_asset_version_ids"])
        for chapter in chapters.values():
            context = chapter["context"]["content"]
            if validate_book_knowledge_access_policy(context.get("knowledge_access_policy") or {}, **scope) != policy:
                raise ValueError("Comparison accepted Context and declared Book knowledge policy differ")
            delivered = {item["knowledge_card_asset_version_id"] for item in knowledge_review_targets(context)}
            if delivered - allowed:
                raise ValueError("Comparison contains forbidden external knowledge in an accepted Context")
    treatment = _treatment_evidence(left, arms[0], identities[0], set(policies[0]["allowed_knowledge_card_asset_version_ids"]))
    subjects = []
    for start, end, scope in [(n, n, BlindScope.CHAPTER) for n in range(1, 7)] + [(1, 6, BlindScope.ARC)]:
        subjects.append(BlindComparisonSubject(
            subject_id=f"window:{start}:{end}", scope_type=scope, chapter_start=start, chapter_end=end,
            canonical_asset_version_id=arms[0][end]["candidate"]["asset_version_id"],
            baseline_asset_version_id=arms[1][end]["candidate"]["asset_version_id"],
            canonical_text="\n\n".join(arms[0][n]["candidate"]["content"]["text"] for n in range(start, end+1)),
            baseline_text="\n\n".join(arms[1][n]["candidate"]["content"]["text"] for n in range(start, end+1)),
            arc_plan_version_ids=tuple(sorted({
                arc for i in (0, 1) for n in range(start, end+1)
                for arc in arms[i][n]["workspace"]["run"]["command"].get("context_version_refs", {}).get("arc_plan_versions", [])
            })),
        ))
    bundle = export_blind_evaluation_packs(
        campaign_token="knowledge-closure", campaign_version=1, protocol_version="knowledge-closure-blind.v1",
        evaluation_version="knowledge-closure-seven-axes.v1", campaign_secret=secrets.token_hex(32),
        evaluators=[BlindEvaluator(f"unassigned-reader-{n}", EvaluatorIdentityClass.GENERAL_READER) for n in (1, 2)],
        subjects=subjects,
    )
    destination.mkdir(parents=True, exist_ok=False)
    private = destination / "private"
    private.mkdir(mode=0o700)
    for name, pack in bundle.packs.items():
        public = destination / name
        public.mkdir()
        _write(public / "prose.json", pack.public_payload)
        _write(public / "knowledge-review-form.json", {
            "status": "NOT_REVIEWED", "reviewer_id": None, "axes": list(AXES),
            "responses": [{"pair_token": item.pair_token, "scores": {axis: None for axis in AXES},
                           "evidence_locations": [], "choice": None} for item in pack.private_mapping],
        })
        _write(private / f"{name}.json", [asdict(item) for item in pack.private_mapping])
    _write(private / "treatment-status.json", treatment)
    status = {"status": "EXPORTED_NOT_REVIEWED", "human_approval": False,
              **{key: treatment[key] for key in ("treatment_status", "treatment_delivery", "treatment_realization", "creative_benefit")},
              "treatment_evidence_classes": treatment["evidence_classes"]}
    _write(destination / "status.json", status)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description="Freeze native six-chapter comparison inputs or export existing accepted manuscripts for blind review")
    modes = parser.add_subparsers(dest="action", required=True)
    frozen = modes.add_parser("prepare")
    frozen.add_argument("--output", type=Path, required=True)
    frozen.add_argument("--approved-card-versions", type=Path)
    frozen.add_argument("--target-book-id", default="")
    frozen.add_argument("--input-dir", type=Path)
    blind = modes.add_parser("blind")
    blind.add_argument("treatment", type=Path)
    blind.add_argument("control", type=Path)
    blind.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "prepare":
        result = prepare(args.output, json.loads(args.approved_card_versions.read_text()) if args.approved_card_versions else None, target_book_id=args.target_book_id, input_dir=args.input_dir)
    else:
        result = blind_export(args.treatment, args.control, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
