from __future__ import annotations

from novel_forge.modules.book_authority.completion_domain import completion_digest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.mkaos_authority.craft import validate_craft_mechanism
from novel_forge.modules.mkaos_authority.craft_selection import build_craft_strategy, validate_craft_policy
from novel_forge.modules.mkaos_authority.domain import resolve_book_knowledge_access_policy
from novel_forge.modules.mkaos_authority.query import MkaosAuthorityQuery


def freeze_screenplay_craft(uow, *, source: dict) -> dict:
    uow.cursor.execute("SELECT production_profile_version FROM authority_book_production WHERE project_id=%s AND book_id=%s AND book_run_id=%s",
        [source["project_id"], source["book_id"], source["book_run_id"]])
    row = uow.cursor.fetchone()
    if not row:
        raise KernelError("SCREENPLAY_CRAFT_SOURCE_INVALID", "Adaptation Craft needs its source Book's production policy")
    profile = uow.repositories.asset_documents.require(project_id=source["project_id"], asset_version_id=row[0])
    access = resolve_book_knowledge_access_policy(production_profile=profile.content, project_id=source["project_id"], book_id=source["book_id"])
    query = MkaosAuthorityQuery(uow.database_url)
    selected, translations, decisions = {}, [], []
    fields = {"knowledge_card_asset_version_id", "content_hash", "role", "sequence", "adaptation_rationale", "prerequisite_resolution",
              "intended_reader_effect", "abandon_condition", "interference_risk", "required"}
    for index, scene in enumerate(source["scene_plan"]):
        requests = scene.get("craft_uses", [])
        if not isinstance(requests, list) or len(requests) > 3:
            raise KernelError("SCREENPLAY_CRAFT_SCOPE_INVALID", "Scene Craft requires at most three governed uses")
        for use in requests:
            if (not isinstance(use, dict) or set(use) != fields or type(use["required"]) is not bool
                or any(not isinstance(use[key], str) or not use[key].strip() or len(use[key]) > 2000 for key in fields - {"sequence", "required"})):
                raise KernelError("SCREENPLAY_CRAFT_SCOPE_INVALID", "Craft requires exact Card, adaptation, applicability, interference and abandonment decisions")
            card = query.require_planning_card_current(project_id=source["project_id"], asset_version_id=use["knowledge_card_asset_version_id"],
                content_hash=use["content_hash"], book_id=source["book_id"], knowledge_access_policy=access, cursor=uow.cursor)
            abstract = card["content"].get("abstract_content", {})
            mechanism = validate_craft_mechanism(abstract.get("craft_mechanism"))
            selected[card["asset_version_id"]] = {"knowledge_card_asset_version_id": card["asset_version_id"],
                "content_hash": card["content_hash"], "selected_content": abstract}
            translations.append({"knowledge_card_asset_version_id": card["asset_version_id"], "decision": "ADAPT",
                "rationale": use["adaptation_rationale"], "prerequisite_resolution": use["prerequisite_resolution"],
                "use_sites": [{"target_pointer": "/scene_plan/" + str(index) + "/dramatic_goal", "realization_excerpt": scene["dramatic_goal"],
                    "expected_application": use["adaptation_rationale"], "preservation_requirements": mechanism["preservation_constraints"],
                    "verification_checks": mechanism["review_checks"], "craft_role": use["role"], "craft_sequence": use["sequence"],
                    "intended_reader_effect": use["intended_reader_effect"]}]})
            decisions.append({"scene_id": scene["scene_id"], **use})
    selection = {"selected": list(selected.values()), "craft_policy": validate_craft_policy({"schema_version": "narrative-craft-budget.v1"}),
        "target_form": "SCENE_SCREENPLAY", "source_revision_id": source["source_revision_id"], "decisions": decisions}
    selection["selection_digest"] = completion_digest(selection)
    basis = "AUTHOR_ADAPTATION_WITH_DETERMINISTIC_COMPATIBILITY_CHECK"
    frozen = {item["judgment_basis"] for item in (source.get("screenplay_craft", {}).get("strategy") or {}).get("composition", [])}
    if frozen:
        if len(frozen) != 1 or not frozen <= {basis, "PROVIDER_PLANNING_TRANSLATION_WITH_DETERMINISTIC_COMPATIBILITY_CHECK"}:
            raise KernelError("SCREENPLAY_CRAFT_SOURCE_DRIFT", "Frozen adaptation judgment provenance is invalid")
        basis = next(iter(frozen))
    strategy = build_craft_strategy({"scene_plan": source["scene_plan"], "knowledge_translations": translations}, selection,
        judgment_basis=basis)
    return {"contract_version": "screenplay-craft-adaptation.v1", "production_profile_asset_version_id": profile.asset_version_id,
        "production_profile_content_hash": profile.content_hash, "knowledge_access_policy": access, "decisions": decisions,
        "strategy": strategy, "acceptance_owner": "SCREENPLAY_VERSION_ONLY", "novel_craft_history_mutation_allowed": False}


def validate_realizations(output: dict, source: dict) -> None:
    uses = {use["use_id"]: use for use in (source["screenplay_craft"].get("strategy") or {}).get("uses", [])}
    values = output["craft_realizations"]
    if len(values) != len(uses) or {item["use_id"] for item in values} != set(uses):
        raise KernelError("SCREENPLAY_CRAFT_REALIZATION_MISSING", "Every frozen Craft use needs an explicit located adoption or omission")
    scenes = {scene["scene_id"]: scene for scene in output["scenes"]}
    for item in values:
        use = uses[item["use_id"]]
        decisions = [decision for decision in source["screenplay_craft"]["decisions"] if decision["scene_id"] == use["scene_id"] and decision["knowledge_card_asset_version_id"] == use["knowledge_card_asset_version_id"]]
        if (item["scene_id"] != use["scene_id"] or set(item["beat_ids"]) - {beat["beat_id"] for beat in scenes[use["scene_id"]]["beats"]}
            or item["decision"] == "ADOPT" and not item["beat_ids"]
            or item["decision"] == "OMIT" and (item["beat_ids"] or decisions[0]["required"])):
            raise KernelError("SCREENPLAY_CRAFT_REALIZATION_INVALID", "Craft locations and required uses must retain the frozen exact scene decisions")


def validate_craft_checks(output: dict, source: dict, candidate: dict) -> None:
    uses = {use["use_id"]: use for use in (source["screenplay_craft"].get("strategy") or {}).get("uses", [])}
    checks = output["craft_checks"]
    if len(checks) != len(uses) or {item["use_id"] for item in checks} != set(uses):
        raise KernelError("SCREENPLAY_CRAFT_REVIEW_MISSING", "Review must assess every frozen Craft use and its scene interference")
    scenes = {scene["scene_id"]: scene for scene in candidate["scenes"]}
    realized = {item["use_id"]: item for item in candidate["craft_realizations"]}
    for check in checks:
        use = uses[check["use_id"]]
        if (check["scene_id"] != use["scene_id"] or set(check["beat_ids"]) - {beat["beat_id"] for beat in scenes[use["scene_id"]]["beats"]}
            or check["status"] == "ACHIEVED" and (not check["beat_ids"] or realized[use["use_id"]]["decision"] != "ADOPT")):
            raise KernelError("SCREENPLAY_CRAFT_REVIEW_LOCATION_INVALID", "Craft evaluation must bind actual scene beats and realization decisions")
        expected = "NOT_USED" if realized[use["use_id"]]["decision"] == "OMIT" else "ACHIEVED"
        if check["status"] == "NOT_USED" and (expected != "NOT_USED" or check["beat_ids"]):
            raise KernelError("SCREENPLAY_CRAFT_REVIEW_LOCATION_INVALID", "Only an approved optional omission may be reviewed as not used")
        if output["verdict"] == "APPROVE" and (check["status"] != expected or check["interference"] != "CLEAR"):
            raise KernelError("SCREENPLAY_CRAFT_REVIEW_UNRESOLVED", "Uncertain, rejected, failed or interfering Craft requires explicit revision or a new adaptation decision")
