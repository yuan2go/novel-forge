from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError
from .diagnostics import open_diagnoses, prose_hash, validate_location


CRAFT_REVIEW_CONTRACT = "narrative-craft-review.v1"
SIDE_EFFECTS = (
    "MISUSE",
    "OVERUSE",
    "ARTIFICIALITY",
    "PACING_DAMAGE",
    "VOICE_CONFLICT",
    "POV_VIOLATION",
    "NEARBY_REPETITION",
    "UNINTENDED_EXPOSITION",
    "PRESERVATION_DAMAGE",
)
PRESERVATION_DIMENSIONS = (
    "CANON",
    "CHARACTER_VOICE",
    "CHARACTER_KNOWLEDGE",
    "POV",
    "SCENE_CAUSALITY",
    "ACTIVE_PLAN",
    "SATISFIED_CRAFT",
)


def craft_review_targets(draft: Mapping[str, Any]) -> list[dict[str, Any]]:
    strategy = (draft.get("realization_contract") or {}).get("craft_strategy")
    if not strategy:
        return []
    from novel_forge.modules.mkaos_authority.craft_selection import (
        validate_craft_strategy,
    )

    strategy = validate_craft_strategy(strategy)
    scene_ranges = _scene_ranges(draft)
    uses = strategy.get("uses")
    if not isinstance(uses, list):
        raise KernelError(
            "CRAFT_REVIEW_TARGET_INVALID", "frozen Craft uses are required"
        )
    seen, targets = set(), []
    for use in uses:
        fields = (
            "use_id",
            "knowledge_card_asset_version_id",
            "content_hash",
            "mechanism_id",
            "mechanism_version",
            "scene_id",
            "intended_reader_effect",
        )
        if (
            not isinstance(use, dict)
            or any(not use.get(key) for key in fields)
            or use["use_id"] in seen
            or use.get("decision") not in {"ADOPT", "ADAPT"}
            or not isinstance(use.get("mechanism"), dict)
        ):
            raise KernelError(
                "CRAFT_REVIEW_TARGET_INVALID",
                "review requires unique adopted frozen Craft use identities",
            )
        seen.add(use["use_id"])
        if use["scene_id"] not in scene_ranges:
            raise KernelError(
                "CRAFT_REVIEW_TARGET_INVALID",
                "Craft use requires exact realized scene prose",
            )
        targets.append(
            {
                **deepcopy(use),
                "selection_digest": strategy["selection_digest"],
                "scene_ranges": scene_ranges[use["scene_id"]],
            }
        )
    return targets


def _scene_ranges(draft: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    slots = (draft.get("realization_contract") or {}).get("slots") or []
    artifacts = draft.get("scene_artifacts") or []
    if len(slots) != len(artifacts) or not slots:
        raise KernelError(
            "CRAFT_REVIEW_TARGET_INVALID",
            "Craft review requires frozen scene slots and realized prose",
        )
    text = str(draft.get("text") or "")
    if any(
        not isinstance(item.get("text"), str) or not item["text"].strip()
        for item in artifacts
    ):
        raise KernelError("CRAFT_REVIEW_TARGET_INVALID", "scene prose cannot be empty")
    from novel_forge.modules.chapter_authority.realization_composition import realization_separators, serialize_realization
    separators = realization_separators(artifacts, draft.get("scene_separators"))
    if serialize_realization(artifacts, separators) != text:
        raise KernelError(
            "CRAFT_REVIEW_TARGET_INVALID",
            "scene realization no longer matches candidate prose",
        )
    ranges: dict[str, list[dict[str, Any]]] = {}
    offset = 0
    previous_scene = None
    for index, (slot, artifact) in enumerate(zip(slots, artifacts, strict=True)):
        if slot["slot_id"] != artifact.get("slot_id"):
            raise KernelError("CRAFT_REVIEW_TARGET_INVALID", "scene slot order changed")
        end = offset + len(artifact["text"])
        scene_id = slot["scene_id"]
        if previous_scene == scene_id:
            ranges[scene_id][-1]["end"] = end
        else:
            ranges.setdefault(scene_id, []).append({"start": offset, "end": end})
        offset, previous_scene = end + (len(separators[index]) if index < len(separators) else 0), scene_id
    return ranges


def same_frozen_targets(
    left: list[dict[str, Any]], right: list[dict[str, Any]]
) -> bool:
    return [
        {key: value for key, value in item.items() if key != "scene_ranges"}
        for item in left
    ] == [
        {key: value for key, value in item.items() if key != "scene_ranges"}
        for item in right
    ]


def craft_provider_task(
    draft: Mapping[str, Any], prior: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    targets = craft_review_targets(draft)
    if not targets:
        return {}
    task = {
        "craft_review_targets": targets,
        "craft_review_contract": "narrative-craft-review.v2" if any(item.get("usage", {}).get("type_policy", {}).get("transition_policy") for item in targets) else CRAFT_REVIEW_CONTRACT,
        "craft_side_effect_dimensions": list(SIDE_EFFECTS),
        "craft_review_instruction": (
            "Assess each frozen use at its specific scene and intended reader effect. Technique names are not evidence. "
            "Return one craft_check per use with ACHIEVED, UNCERTAIN or FAILED, literal Unicode code-point evidence, "
            "signals_checked and reason. Check every side-effect dimension as CLEAR, PRESENT or UNCERTAIN with "
            "located evidence. Failed effects or present side effects need linked actionable issue_codes. "
            "Aesthetic and uncertain judgments cannot be blockers. Model judgments are not actual reader evidence. "
            "Do not modify Canon, character knowledge, voice or the accepted plan to make a technique work."
        ),
    }
    if any(item.get("usage", {}).get("type_policy", {}).get("transition_policy") for item in targets):
        task["craft_review_instruction"] += " Separately evaluate the exact proposed phase_transition action, phase, condition and progress at a literal location. Return SUPPORTED, FAILED or UNCERTAIN. A achieved stylistic effect does not itself establish phase advancement. DEFER must preserve the phase and justify delay; END must have located closure evidence. Do not infer success from the plan."
    if prior is not None:
        task.update(
            {
                "prior_craft_checks": deepcopy(prior.get("craft_checks") or []),
                "craft_preservation_dimensions": list(PRESERVATION_DIMENSIONS),
                "craft_rereview_instruction": (
                    "Recheck every frozen use including previously achieved uses; disposition every prior diagnosis. "
                    "Return craft_preservation_checks for all dimensions with located evidence and a reason. "
                    "A claimed resolution cannot override regressed or uncertain preservation."
                ),
            }
        )
    return task


def validate_craft_checks(
    *,
    checks: Any,
    targets: list[dict[str, Any]],
    issues: list[dict[str, Any]],
    text: str,
    target_asset_version_id: str,
    real_model_call: bool,
) -> list[dict[str, Any]]:
    expected = {item["use_id"]: item for item in targets}
    if not isinstance(checks, list):
        raise KernelError(
            "CRAFT_REVIEW_CHECK_REQUIRED", "explicit Craft checks are required"
        )
    by_code = {issue["code"]: issue for issue in issues}
    seen, result = set(), []
    for check in checks:
        if not isinstance(check, dict):
            raise KernelError(
                "CRAFT_REVIEW_CHECK_INVALID", "Craft check must be an object"
            )
        use_id = check.get("use_id")
        if (
            use_id not in expected
            or use_id in seen
            or check.get("effect_status") not in {"ACHIEVED", "UNCERTAIN", "FAILED"}
        ):
            raise KernelError(
                "CRAFT_REVIEW_CHECK_INVALID",
                "Craft check must identify one delivered use and effect judgment",
            )
        seen.add(use_id)
        target = expected[use_id]
        if not str(check.get("reason") or "").strip():
            raise KernelError(
                "CRAFT_REVIEW_CHECK_INVALID", "Craft judgment requires an explanation"
            )
        signals = check.get("signals_checked")
        if (
            not isinstance(signals, list)
            or not signals
            or any(not isinstance(x, str) or not x.strip() for x in signals)
        ):
            raise KernelError(
                "CRAFT_REVIEW_CHECK_INVALID",
                "Craft judgment requires observed mechanism signals",
            )
        evidence = validate_location(dict(check.get("evidence") or {}), text)
        if not any(
            span["start"] <= evidence["start"] < evidence["end"] <= span["end"]
            for span in target["scene_ranges"]
        ):
            raise KernelError(
                "CRAFT_REVIEW_SCENE_MISMATCH",
                "intended effect evidence must be located inside its frozen use scene",
            )
        linked = check.get("issue_codes")
        if (
            not isinstance(linked, list)
            or any(not isinstance(code, str) for code in linked)
            or set(linked) - set(by_code)
        ):
            raise KernelError(
                "CRAFT_REVIEW_CHECK_INVALID",
                "Craft issue links must resolve to actual diagnoses",
            )
        for code in linked:
            issue = by_code[code]
            if issue.get("severity") == "blocking" and (
                issue.get("judgment_kind") in {"AESTHETIC_SUGGESTION", "UNCERTAIN"}
                or issue.get("category") == "CRAFT_EFFECT"
            ):
                raise KernelError(
                    "REVIEW_JUDGMENT_INVALID",
                    "subjective Craft reader-effect judgment cannot be a deterministic blocker",
                )
        if check["effect_status"] == "FAILED" and not linked:
            raise KernelError(
                "CRAFT_REVIEW_DIAGNOSIS_REQUIRED",
                "failed Craft effect needs an actionable located repair diagnosis",
            )
        sides = check.get("side_effects")
        if (
            not isinstance(sides, list)
            or len(sides) != len(SIDE_EFFECTS)
            or any(not isinstance(side, dict) for side in sides)
            or {side.get("kind") for side in sides} != set(SIDE_EFFECTS)
        ):
            raise KernelError(
                "CRAFT_REVIEW_CHECK_INVALID",
                "all Craft side-effect dimensions require explicit assessment",
            )
        normalized_sides = []
        for side in sides:
            if (
                side.get("status") not in {"CLEAR", "PRESENT", "UNCERTAIN"}
                or not str(side.get("reason") or "").strip()
            ):
                raise KernelError(
                    "CRAFT_REVIEW_CHECK_INVALID",
                    "Craft side effects require an explicit status and reason",
                )
            side_codes = side.get("issue_codes")
            if (
                not isinstance(side_codes, list)
                or any(not isinstance(code, str) for code in side_codes)
                or set(side_codes) - set(linked)
                or (side["status"] == "PRESENT" and not side_codes)
            ):
                raise KernelError(
                    "CRAFT_REVIEW_DIAGNOSIS_REQUIRED",
                    "present side effects need linked actionable diagnoses",
                )
            normalized_sides.append(
                {
                    **side,
                    "evidence": validate_location(
                        dict(side.get("evidence") or {}), text
                    ),
                }
            )
        phase_observation = {}
        usage = target.get("usage") or {}
        if usage.get("type_policy", {}).get("transition_policy"):
            observation = check.get("phase_transition")
            if (not isinstance(observation, Mapping) or set(observation) != {"action", "phase", "status", "progress", "evidence", "reason"}
                or observation["action"] != usage["transition"]["action"] or observation["phase"] != usage["phase"]
                or observation["status"] not in {"SUPPORTED", "FAILED", "UNCERTAIN"}
                or any(not isinstance(observation[key], str) or not observation[key].strip() or len(observation[key]) > 512 for key in ("progress", "reason"))):
                raise KernelError("CRAFT_PHASE_REVIEW_REQUIRED", "Explicit phase progress needs a separate located judgment matching the proposed transition")
            location = validate_location(dict(observation["evidence"]), text)
            if not any(span["start"] <= location["start"] < location["end"] <= span["end"] for span in target["scene_ranges"]):
                raise KernelError("CRAFT_PHASE_REVIEW_LOCATION_INVALID", "Phase evidence must occur in the exact use scene")
            phase_observation = {"phase_transition": {**deepcopy(observation), "evidence": location}}
        result.append(
            {
                **deepcopy(check),
                **phase_observation,
                "evidence": evidence,
                "side_effects": normalized_sides,
                **{
                    key: deepcopy(target[key])
                    for key in (
                        "knowledge_card_asset_version_id",
                        "content_hash",
                        "mechanism_id",
                        "mechanism_version",
                        "scene_id",
                        "intended_reader_effect",
                        "selection_digest",
                    )
                },
                "target_asset_version_id": target_asset_version_id,
                "target_text_hash": prose_hash(text),
                "evidence_class": "MODEL_SEMANTIC_REVIEW"
                if real_model_call
                else "FIXTURE_SEMANTIC_REVIEW",
                "reader_effect_proven": False,
                "formal_proof": False,
                "human_approved": False,
            }
        )
    if seen != set(expected):
        raise KernelError(
            "CRAFT_REVIEW_CHECK_REQUIRED", "review cannot omit any frozen Craft use"
        )
    return result


def craft_revision_contract(
    draft: Mapping[str, Any], review: Mapping[str, Any], *, compact_contract: bool = False,
    targeted_edits_only: bool = False,
) -> dict[str, Any]:
    targets = craft_review_targets(draft)
    if not targets:
        return {}
    if targets != review.get("craft_targets") or review.get(
        "target_text_hash"
    ) != prose_hash(str(draft.get("text") or "")):
        raise KernelError(
            "CRAFT_REVISION_SELECTION_CHANGED",
            "revision must retain the originally reviewed frozen Craft strategy",
        )
    if targeted_edits_only:
        instructions = (
            "Return only ordered non-overlapping edits inside diagnosed spans with exact old quotes, replacement prose "
            "and issue codes. The host derives Slot and chapter prose, preserving unaffected text exactly. "
            "Keep Canon, POV, voice, character knowledge, causal sequence, accepted planning and previously achieved Craft. "
            "Do not force optional aesthetic suggestions or add facts. ReReview decides resolution."
        )
    elif compact_contract:
        instructions = (
            "Return ordered non-overlapping edits inside existing diagnosed Unicode spans with the exact old quote, replacement and issue_codes. The host verifies the joined Scene Slot prose equals applying those edits; preserve all other prose exactly. Keep Canon, POV, voice, character knowledge, causal sequence, accepted planning and previously achieved Craft. Do not force optional aesthetic suggestions or add new story facts. ReReview decides resolution."
        )
    else:
        instructions = (
            "Return ordered non-overlapping edits inside existing diagnosed Unicode spans with the exact old quote, "
            "replacement and issue_codes. Returned text must equal applying those edits; preserve all other prose exactly. "
            "Keep Canon, POV, voice, character knowledge, causal sequence, accepted planning and previously achieved Craft. "
            "Do not force optional aesthetic suggestions or add new story facts. ReReview decides resolution."
        )
    return {
        "contract_version": "narrative-craft-targeted-repair.v2" if targeted_edits_only else "narrative-craft-targeted-repair.v1",
        "selection_digest": targets[0]["selection_digest"],
        "source_text_hash": review["target_text_hash"],
        "preservation_dimensions": list(PRESERVATION_DIMENSIONS),
        "satisfied_use_ids": [
            item["use_id"]
            for item in review.get("craft_checks", [])
            if item["effect_status"] == "ACHIEVED"
        ],
        "use_preservation_requirements": [
            {
                "use_id": item["use_id"],
                "requirements": deepcopy(item.get("preservation_requirements", [])),
                "repair_strategies": deepcopy(
                    item["mechanism"].get("repair_strategies", [])
                ),
            }
            for item in targets
        ],
        "instructions": instructions,
    }


def craft_rereview_preservation(
    result: dict[str, Any], initial: dict[str, Any], reviewed: dict[str, Any], text: str
) -> dict[str, Any]:
    if not initial.get("craft_targets"):
        return {}
    issues = open_diagnoses(initial)
    resolutions = result.get("resolution_checks")
    if (
        not isinstance(resolutions, list)
        or len(resolutions) != len(issues)
        or {item.get("code") for item in resolutions}
        != {item["code"] for item in issues}
    ):
        raise KernelError(
            "CRAFT_REREVIEW_RESOLUTION_REQUIRED",
            "Craft rereview must disposition every original diagnosis",
        )
    checks = result.get("craft_preservation_checks")
    if (
        not isinstance(checks, list)
        or len(checks) != len(PRESERVATION_DIMENSIONS)
        or any(not isinstance(check, dict) for check in checks)
        or {check.get("dimension") for check in checks} != set(PRESERVATION_DIMENSIONS)
    ):
        raise KernelError(
            "CRAFT_PRESERVATION_REQUIRED",
            "Craft rereview requires every preservation dimension",
        )
    normalized = []
    for check in checks:
        if (
            check.get("status") not in {"PRESERVED", "REGRESSED", "UNCERTAIN"}
            or not str(check.get("reason") or "").strip()
        ):
            raise KernelError(
                "CRAFT_PRESERVATION_REQUIRED",
                "Craft preservation requires explicit status and reason",
            )
        normalized.append(
            {
                **deepcopy(check),
                "evidence": validate_location(dict(check.get("evidence") or {}), text),
            }
        )
    current = {item["use_id"]: item for item in reviewed["craft_checks"]}
    lost = [
        item["use_id"]
        for item in initial["craft_checks"]
        if item["effect_status"] == "ACHIEVED"
        and current[item["use_id"]]["effect_status"] != "ACHIEVED"
    ]
    if (
        lost
        and next(item for item in normalized if item["dimension"] == "SATISFIED_CRAFT")[
            "status"
        ]
        == "PRESERVED"
    ):
        raise KernelError(
            "CRAFT_PRESERVATION_CONFLICT",
            "a previously achieved Craft is no longer achieved",
        )
    state = (
        "REGRESSED"
        if any(item["status"] == "REGRESSED" for item in normalized)
        else "UNCERTAIN"
        if any(item["status"] == "UNCERTAIN" for item in normalized)
        else "PRESERVED"
    )
    return {
        "craft_preservation_checks": normalized,
        "craft_preservation_status": state,
        "craft_regressed_use_ids": lost,
    }


def extend_craft_provider_schema(schema: dict[str, Any], stage: str, *, phase_transitions: bool = False, legacy_contract: bool = False) -> dict[str, Any]:
    result = deepcopy(schema)
    if stage == "revision":
        from .cross_chapter import extend_provider_schema

        return (
            result
            if "edits" in result["properties"]
            else extend_provider_schema(result, stage, legacy_contract=legacy_contract)
        )
    text = {"type": "string", "minLength": 1}

    def obj(fields: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": fields,
            "required": list(fields),
            "additionalProperties": False,
        }

    strings = {"type": "array", "items": text}
    location = obj(
        {**({"start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1}} if legacy_contract else {}), "quote": text}
    )
    side = obj(
        {
            "kind": {"enum": list(SIDE_EFFECTS)},
            "status": {"enum": ["CLEAR", "PRESENT", "UNCERTAIN"]},
            "evidence": location,
            "reason": text,
            "issue_codes": strings,
        }
    )
    check = obj(
        {
            "use_id": text,
            "effect_status": {"enum": ["ACHIEVED", "UNCERTAIN", "FAILED"]},
            "evidence": location,
            "reason": text,
            "signals_checked": {**strings, "minItems": 1},
            "side_effects": {
                "type": "array",
                "minItems": len(SIDE_EFFECTS),
                "maxItems": len(SIDE_EFFECTS),
                "items": side,
            },
            "issue_codes": strings,
        }
    )
    if phase_transitions:
        check["properties"]["phase_transition"] = obj({
            "action": {"type": "string", "enum": ["START", "CONTINUE", "ADVANCE", "DEFER", "END"]},
            "phase": text, "status": {"type": "string", "enum": ["SUPPORTED", "FAILED", "UNCERTAIN"]},
            "progress": {"type": "string", "minLength": 1, "maxLength": 512}, "evidence": location,
            "reason": {"type": "string", "minLength": 1, "maxLength": 512},
        })
        check["required"].append("phase_transition")
    result["properties"]["craft_checks"] = {"type": "array", "items": check}
    result["required"].append("craft_checks")
    if stage == "rereview":
        result["properties"]["craft_preservation_checks"] = {
            "type": "array",
            "minItems": len(PRESERVATION_DIMENSIONS),
            "maxItems": len(PRESERVATION_DIMENSIONS),
            "items": obj(
                {
                    "dimension": {"enum": list(PRESERVATION_DIMENSIONS)},
                    "status": {"enum": ["PRESERVED", "REGRESSED", "UNCERTAIN"]},
                    "evidence": location,
                    "reason": text,
                }
            ),
        }
        result["required"].append("craft_preservation_checks")
    return result


def craft_trace_projection(workspace: Mapping[str, Any]) -> dict[str, Any]:
    stages = workspace.get("artifacts") or {}
    selections, candidates, reviews, comparisons = [], [], [], []
    documents = {
        asset["asset_version_id"]: asset
        for assets in stages.values()
        for asset in assets
    }
    accepted = None
    if (workspace.get("acceptance") or {}).get("status") == "COMMITTED":
        from novel_forge.modules.chapter_outcome.acceptance_contract import (
            resolve_accepted_manuscript,
        )

        accepted = resolve_accepted_manuscript(workspace)
    for stage, assets in stages.items():
        for asset in assets:
            content = asset.get("content") or {}
            identity = {
                key: asset[key]
                for key in (
                    "asset_version_id",
                    "asset_type",
                    "content_hash",
                    "operation_id",
                )
                if key in asset
            }
            strategy = content.get("craft_strategy") or (
                content.get("realization_contract") or {}
            ).get("craft_strategy")
            if strategy:
                selections.append(
                    {**identity, "stage": stage, "craft_strategy": deepcopy(strategy)}
                )
            if strategy and content.get("text") is not None:
                candidates.append(
                    {
                        **identity,
                        "text_hash": prose_hash(content["text"]),
                        "selected_use_ids": [
                            item["use_id"] for item in strategy["uses"]
                        ],
                        "selection_digest": strategy["selection_digest"],
                        "provider_evidence": deepcopy(
                            content.get("provider_evidence") or {}
                        ),
                        "targeted_edits": deepcopy(content.get("targeted_edits") or []),
                        "craft_revision_contract": deepcopy(
                            content.get("craft_revision_contract") or {}
                        ),
                    }
                )
            if content.get("craft_checks"):
                reviews.append(
                    {
                        **identity,
                        **{
                            key: deepcopy(content[key])
                            for key in (
                                "target_asset_version_id",
                                "revision_version_id",
                                "target_text_hash",
                                "craft_targets",
                                "craft_checks",
                                "craft_preservation_checks",
                                "craft_preservation_status",
                                "craft_regressed_use_ids",
                                "issues",
                                "issue_lineage",
                                "resolution_checks",
                                "resolved_issue_codes",
                                "remaining_issue_codes",
                                "provider_evidence",
                            )
                            if key in content
                        },
                    }
                )
            comparison = content.get("candidate_comparison")
            if comparison or asset.get("asset_type") == "candidate_comparison":
                comparisons.append(
                    {**identity, "comparison": deepcopy(comparison or content)}
                )
    observations = []
    for review in reviews:
        for check in review["craft_checks"]:
            candidate_id = check["target_asset_version_id"]
            candidate = documents.get(candidate_id, {}).get("content") or {}
            plan_id = (candidate.get("realization_contract") or {}).get(
                "plan_version_id"
            )
            plan = documents.get(plan_id, {}).get("content") or {}
            scene = next(
                (
                    scene
                    for scene in plan.get("scene_plan", [])
                    if scene.get("scene_id") == check["scene_id"]
                ),
                {},
            )
            use = next(
                item
                for item in review["craft_targets"]
                if item["use_id"] == check["use_id"]
            )
            accepted_observation = None
            if (
                accepted
                and candidate_id
                == accepted["candidate"]["content"].get(
                    "selected_source_asset_version_id"
                )
                and check["target_text_hash"]
                == prose_hash(accepted["candidate"]["content"]["text"])
            ):
                accepted_review = accepted["review"]
                source_review_id = accepted_review["content"].get(
                    "selection_review_source_asset_version_id",
                    accepted_review["asset_version_id"],
                )
                if review["asset_version_id"] in {
                    source_review_id,
                    accepted_review["asset_version_id"],
                }:
                    accepted_observation = {
                        "acceptance_id": workspace["acceptance"]["acceptance_id"],
                        "candidate_asset_version_id": accepted["candidate"][
                            "asset_version_id"
                        ],
                        "review_asset_version_id": accepted_review["asset_version_id"],
                        "outcome_asset_version_id": accepted["outcome"][
                            "asset_version_id"
                        ],
                    }
            observations.append(
                {
                    **{
                        key: deepcopy(check[key])
                        for key in (
                            "use_id",
                            "knowledge_card_asset_version_id",
                            "content_hash",
                            "mechanism_id",
                            "mechanism_version",
                            "scene_id",
                            "intended_reader_effect",
                            "effect_status",
                            "evidence",
                            "side_effects",
                            "target_asset_version_id",
                            "target_text_hash",
                            "selection_digest",
                            "evidence_class",
                        )
                    },
                    **({"usage": deepcopy(use["usage"])} if "usage" in use else {}),
                    **({"phase_transition": deepcopy(check["phase_transition"])} if "phase_transition" in check else {}),
                    "review_asset_version_id": review["asset_version_id"],
                    "revision_version_id": review.get("revision_version_id"),
                    "provider_evidence": deepcopy(
                        review.get("provider_evidence") or {}
                    ),
                    "review_provider_id": (review.get("provider_evidence") or {}).get(
                        "provider_id"
                    ),
                    "review_model_id": (review.get("provider_evidence") or {}).get(
                        "model_id"
                    ),
                    "realization_provider_id": (
                        candidate.get("provider_evidence") or {}
                    ).get("provider_id"),
                    "realization_model_id": (
                        candidate.get("provider_evidence") or {}
                    ).get("model_id"),
                    "declared_mechanism_affinity": deepcopy(
                        use["mechanism"]["affinity"]
                    ),
                    "actual_scene_context": {
                        key: deepcopy(scene[key])
                        for key in (
                            "goal",
                            "scene_type",
                            "function",
                            "pov_character_id",
                            "focalization",
                            "pacing",
                        )
                        if key in scene
                    },
                    "actual_genre": deepcopy(plan.get("genre")),
                    "comparison_observations": [
                        {
                            "comparison_asset_version_id": item.get("asset_version_id"),
                            "selected": item["comparison"].get(
                                "selected_asset_version_id"
                            )
                            == candidate_id,
                        }
                        for item in comparisons
                        if candidate_id
                        in {
                            item["comparison"]
                            .get("previous", {})
                            .get("asset_version_id"),
                            item["comparison"]
                            .get("challenger", {})
                            .get("asset_version_id"),
                        }
                    ],
                    "accepted_lineage": accepted_observation,
                    "reader_effect_proven": False,
                }
            )
    return {
        "contract_version": "narrative-craft-trace.v1",
        "authority": "READ_ONLY_PROJECTION",
        "status": "FROZEN_CRAFT_EVIDENCE" if selections else "NO_CRAFT_STRATEGY",
        "selections": selections,
        "candidates": candidates,
        "reviews": reviews,
        "candidate_comparisons": comparisons,
        "effect_observations": observations,
        "reader_human_evidence": {
            "availability": "NOT_RECORDED",
            "scope": "CHAPTER_WORKSPACE",
            "followup_join_keys": {
                "project_id": workspace.get("project_id"),
                "book_id": workspace.get("book_id"),
                "book_run_id": workspace.get("book_run_id"),
                "chapter_root_operation_id": workspace.get("root_operation_id"),
                "acceptance_id": (workspace.get("acceptance") or {}).get(
                    "acceptance_id"
                ),
                "chapter_outcome_asset_version_id": (
                    workspace.get("acceptance") or {}
                ).get("outcome_asset_version_id"),
                "accepted_candidate_asset_version_id": accepted["candidate"][
                    "asset_version_id"
                ]
                if accepted
                else None,
                "accepted_text_hash": prose_hash(
                    accepted["candidate"]["content"]["text"]
                )
                if accepted
                else None,
            },
            "followup_authority": "BOOK_FOLLOWUP",
            "reader_proxy_is_human_evidence": False,
        },
        "acceptance": deepcopy(workspace.get("acceptance")),
        "accepted_manuscript": deepcopy(workspace.get("accepted_manuscript")),
        "reader_effect_proven": False,
        "evidence_ceiling": "OBSERVATIONS_ONLY; MODEL_OR_FIXTURE_REVIEW_IS_NOT_READER_EFFECT_PROOF",
    }


def fixture_craft_checks(inputs: Mapping[str, Any]) -> list[dict[str, Any]]:
    draft = inputs.get("revision") or inputs.get("draft") or {}
    text = str(draft.get("text") or "")

    def located(target: dict[str, Any]) -> dict[str, Any]:
        span = target["scene_ranges"][0]
        return {**span, "quote": text[span["start"] : span["end"]]}

    return [
        {
            "use_id": target["use_id"],
            "effect_status": "UNCERTAIN",
            **({"phase_transition": {"action": target["usage"]["transition"]["action"], "phase": target["usage"]["phase"], "status": "UNCERTAIN",
                "progress": "Fixture cannot establish accepted phase progress.", "evidence": located(target), "reason": "No semantic qualification in scripted transport."}}
                if target.get("usage", {}).get("type_policy", {}).get("transition_policy") else {}),
            "evidence": located(target),
            "reason": "Scripted transport cannot establish a Craft reader effect.",
            "signals_checked": ["Fixture checks delivery and immutable identity only."],
            "issue_codes": [],
            "side_effects": [
                {
                    "kind": kind,
                    "status": "UNCERTAIN",
                    "evidence": located(target),
                    "reason": "No semantic qualification in scripted transport.",
                    "issue_codes": [],
                }
                for kind in SIDE_EFFECTS
            ],
        }
        for target in craft_review_targets(draft)
    ]
