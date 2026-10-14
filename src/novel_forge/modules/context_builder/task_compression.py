from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
import json
import re
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_contracts import ContextCandidate, ContextClass
from novel_forge.modules.narrative_state.reality import narrative_hash

from .task_context import (
    SYSTEM_CONTEXT_WINDOW_TOKENS,
    TASK_CONTEXT_POLICY_VERSION,
    serialized_token_upper_bound,
    task_references,
    fact_aliases,
)

_HISTORY = frozenset({"narrative_retrieval_document", "chapter_episodic_summary", "scene_episodic_summary", "character_timeline", "relationship_timeline", "source_chunk", "source_observation_excerpt"})
_EXACT = frozenset({"draft_chapter", "draft_version", "best_draft_candidate", "review_report", "review_issue"})
ModelCall = Callable[[str, dict[str, Any]], Mapping[str, Any]]


def _payload(candidate: ContextCandidate) -> dict[str, Any]:
    return {
        "safe_summary": candidate.safe_summary,
        "structured_facts": [fact for fact in candidate.structured_facts if fact.get("provider_visibility") != "INTERNAL_QUALITY_ONLY"],
    }


def _candidate_tokens(candidate: ContextCandidate) -> tuple[int, str]:
    payload = _payload(candidate)
    if candidate.asset_type == "chapter_execution_intent" and (candidate.provenance or {}).get("working_artifact"):
        try:
            intent = json.loads(candidate.safe_summary)
        except (ValueError, TypeError):
            intent = None
        working = intent.get("working_manuscript") if isinstance(intent, dict) else None
        if (isinstance(working, dict) and isinstance(working.get("projection_policy"), dict)
            and working["projection_policy"].get("version") in {"working-prose-projection.v2", "working-prose-projection.v3"}):
            from novel_forge.modules.chapter_authority.provider_views import compile_exact_context_references
            encoded, _ = compile_exact_context_references({**payload, 'safe_summary': intent}, structured_transport=True)
            return max(1, serialized_token_upper_bound(encoded) + 64), "STRUCTURED_WORKING_INTENT"
    return max(1, serialized_token_upper_bound(payload)), "SERIALIZED_SUMMARY"


def _protected_envelope_accounting(candidates, *, required_asset_types):
    from .domain import context_candidate_class
    from novel_forge.modules.chapter_authority.provider_views import compile_exact_context_references

    protected = [item for item in candidates if item.allowed_use != "evidence_only" and (
        context_candidate_class(item) is ContextClass.PROTECTED or item.required
        or item.asset_type in required_asset_types or item.asset_type in _EXACT)]
    source = {"context_segments": [{"asset_version_id": item.asset_version_id, **_payload(item)} for item in protected]}
    encoded, proof = compile_exact_context_references(source, structured_transport=True, short_literals=True)
    amounts = {item.asset_version_id: serialized_token_upper_bound(row) + 256
               for item, row in zip(protected, encoded["context_segments"])}
    result = [replace(item, estimated_tokens=amounts[item.asset_version_id])
              if item.asset_version_id in amounts else item for item in candidates]
    return result, {**proof, "contract_version": "protected-context-exact-accounting.v1",
                    "protected_asset_version_ids": [item.asset_version_id for item in protected],
                    "members": [{"asset_version_id": item.asset_version_id, "content_hash": item.content_digest,
                                 "payload_hash": narrative_hash(_payload(item)), "allocated_bytes": amounts[item.asset_version_id]}
                                for item in protected],
                    "framing_bytes_per_source": 256, "encoded_payload_bytes": serialized_token_upper_bound(encoded),
                    "final_provider_capacity_check": "REQUIRED"}


def _units(candidate: ContextCandidate, task: Mapping[str, Any]) -> list[dict[str, Any]]:
    units = []
    try:
        document = json.loads(candidate.safe_summary)
    except (ValueError, TypeError):
        document = None
    if isinstance(document, dict):
        engineering = {"provider_evidence", "context_bundle_id", "context_bundle_content_hash", "context_fingerprint", "retrieval_result_asset_version_id", "retrieval_result_fingerprint", "created_by_operation_id", "validation_evidence", "model_call_log", "cost_ledger"}
        for field, value in sorted(document.items()):
            if field in engineering:
                continue
            if field in {"scene_artifacts", "scenes", "scene_summaries"} and isinstance(value, list):
                for index, scene in enumerate(value):
                    units.append({"unit_id": f"json:{field}:{index}", "text": json.dumps(scene, ensure_ascii=False, sort_keys=True, separators=(",", ":")), "kind": "SOURCE_SCENE_OR_CAUSAL_UNIT", "field": "safe_summary", "source_path": [field, index]})
            elif field in {"text", "safe_summary", "summary"} and isinstance(value, str):
                for index, paragraph in enumerate(value.split("\n\n")):
                    if paragraph:
                        units.append({"unit_id": f"json:{field}:{index}", "text": paragraph, "kind": "SOURCE_PARAGRAPH", "field": "safe_summary", "source_path": [field], "index": index})
            else:
                units.append({"unit_id": f"json:{field}", "text": json.dumps({field: value}, ensure_ascii=False, sort_keys=True, separators=(",", ":")), "kind": "SOURCE_CAUSAL_FIELD", "field": "safe_summary", "source_path": [field], "required": task.get("writer_projection_version") != "accepted-writer-history.v2" or field in {"used_fact_ids", "scene_separators", "required_fact_ids", "cause_refs", "knowledge_boundaries"}})
    else:
        for index, text in enumerate(candidate.safe_summary.split("\n\n")):
            if text:
                units.append({"unit_id": f"text:{index}", "text": text, "kind": "SOURCE_PARAGRAPH", "field": "safe_summary", "index": index})
    for index, fact in enumerate(candidate.structured_facts):
        if fact.get("provider_visibility") == "INTERNAL_QUALITY_ONLY":
            continue
        units.append({"unit_id": f"fact:{index}", "text": json.dumps(fact, ensure_ascii=False, sort_keys=True, separators=(",", ":")), "kind": "STATE_OR_CAUSAL_UNIT", "field": "structured_facts", "index": index})
    quotes = tuple(task.get("preserve_quotes") or ())
    for unit in units:
        heading = task.get("stage") == "reference_analysis" and any(
            re.match(r"^第[0-9一二三四五六七八九十百千万零〇两]+[章回节卷](?:\s|$)", line.strip())
            for line in unit["text"].splitlines()
        )
        if heading:
            unit["kind"] = "SOURCE_LOCATION_HEADER"
        unit["required"] = bool(unit.get("required")) or heading or candidate.required or unit["field"] == "structured_facts" or any(quote in unit["text"] for quote in quotes)
    return units


def validate_task_dependencies(candidates: list[ContextCandidate], *, task: Mapping[str, Any]) -> dict[str, Any]:
    facts = [fact for candidate in candidates if candidate.allowed_use != "evidence_only" for fact in candidate.structured_facts if fact.get("provider_visibility") != "INTERNAL_QUALITY_ONLY"]
    available = set().union(*(fact_aliases(fact) for fact in facts)) if facts else set()
    foundation_types = {"creative_foundation", "world_bible", "character_cards", "character_cast"}
    foundation = {
        "foundation:" + str(identity)
        for candidate in candidates if candidate.asset_type in foundation_types
        for identity in (candidate.asset_version_id, (candidate.provenance or {}).get("authority_asset_version_id")) if identity
    }
    required = set((task.get("plan") or {}).get("required_long_distance_fact_ids") or ())
    required.update(ref for fact in facts for ref in (fact.get("state") or {}).get("world_transition", {}).get("cause_refs", ()))
    missing = required - available - foundation
    if missing:
        raise KernelError("TASK_CONTEXT_DEPENDENCY_UNAVAILABLE", "necessary explicit Context dependencies remain unavailable after governed directed retrieval: " + ", ".join(sorted(missing)))
    return {"required_refs": sorted(required), "available_refs": sorted(available), "verified_foundation_refs": sorted(foundation), "coverage": "COMPLETE"}


def compile_task_context(
    candidates: list[ContextCandidate], *, task: Mapping[str, Any], token_budget: int,
    required_asset_types: tuple[str, ...], model_call: ModelCall | None = None,
    compression_input_tokens: int = 0, maximum_chunks: int = 8,
    admitted_source_ids: frozenset[str] | None = None,
) -> tuple[list[ContextCandidate], dict[str, Any]]:
    from .domain import context_candidate_class, deduplicate_context_candidates, resolve_context_profile

    if not 0 < token_budget <= SYSTEM_CONTEXT_WINDOW_TOKENS:
        raise KernelError("TASK_CONTEXT_BUDGET_INVALID", "task target must fit the system context support ceiling")
    if task.get("writer_projection_version") == "accepted-writer-history.v2":
        from .story_projection import clean_context_candidates
        candidates = clean_context_candidates(list(candidates), stage=str(task.get("stage") or "draft"))
    reference = task.get("stage") == "reference_analysis"
    boundary_key = "observation_boundary" if reference else "accepted_boundary"
    boundary = dict(task.get(boundary_key) or {})
    if reference:
        from novel_forge.modules.source_authority.observation import observation_boundary
        observation_boundary(boundary)
        if task.get("accepted_boundary"):
            raise KernelError("TASK_CONTEXT_BOUNDARY_TYPE", "reference observation cannot claim accepted Canon")
    elif not boundary or "accepted_through_chapter" not in boundary:
        raise KernelError("TASK_CONTEXT_BOUNDARY_REQUIRED", "task Context must freeze an accepted source boundary")
    selectors = task_references(task)
    source_positions = {}
    if reference:
        for position, span in enumerate(boundary["spans"]):
            source_positions[(span["chunk_asset_version_id"], span["content_hash"])] = position
            source_positions.setdefault((span["chunk_asset_version_id"], ""), position)

    def source_position(candidate):
        identity = (candidate.provenance or {}).get("source_chunk_asset_version_id", candidate.asset_version_id)
        return source_positions.get((identity, candidate.content_digest), source_positions.get((identity, ""), len(source_positions)))

    working = []
    excluded = []
    auxiliary = []
    denied = []
    for candidate in sorted(candidates, key=source_position if reference else lambda item: item.asset_version_id):
        if admitted_source_ids is not None and candidate.asset_version_id not in admitted_source_ids:
            denied.append(candidate)
            continue
        if reference and (candidate.accepted_boundary or candidate.source_use_mode != "source_analysis" or candidate.allowed_use != "source_analysis" or candidate.asset_type not in resolve_context_profile("reference_analysis").allowed_asset_types):
            raise KernelError("TASK_CONTEXT_REFERENCE_SOURCE", "reference analysis requires exact analysis-only sources")
        if dict((candidate.observation_boundary if reference else candidate.accepted_boundary) or {}) != boundary:
            raise KernelError("TASK_CONTEXT_SOURCE_BOUNDARY_CHANGED", "Context source does not match its frozen task boundary")
        protected = context_candidate_class(candidate) is ContextClass.PROTECTED or candidate.asset_type in _EXACT
        required = protected or candidate.required or candidate.asset_type in required_asset_types
        selected = required or candidate.asset_type not in _HISTORY or bool(selectors & task_references(candidate.structured_facts)) or any(reason.startswith("required_") for reason in candidate.retrieval_reasons) or candidate.relevance_score > 0 or any(quote in candidate.safe_summary for quote in task.get("preserve_quotes") or ())
        if selected:
            working.append(candidate)
        else:
            auxiliary.append(candidate)
    auxiliary.sort(key=lambda item: (-item.relevance_score, item.asset_version_id))
    working.extend(auxiliary[:12])
    excluded.extend(auxiliary[12:])
    normalized = []
    candidate_accounting = []
    for candidate in working:
        amount, representation = (1, "EVIDENCE_ONLY") if candidate.allowed_use == "evidence_only" else _candidate_tokens(candidate)
        candidate_accounting.append({"asset_version_id": candidate.asset_version_id,
            "representation": representation, "provider_data_upper_bound": amount,
            "storage_payload_bytes": serialized_token_upper_bound(_payload(candidate))})
        normalized.append(replace(candidate, estimated_tokens=amount, truncation_strategy=""))
    normalized, deduplications = deduplicate_context_candidates(normalized, required_logical_kinds=set(required_asset_types) | resolve_context_profile("reference_analysis" if reference else "draft").required_asset_types)
    exact_accounting = None
    if task.get("protected_context_accounting_version") not in (None, "protected-context-exact-accounting.v1"):
        raise KernelError("TASK_CONTEXT_ACCOUNTING_INVALID", "Unknown protected Context accounting version")
    if task.get("protected_context_accounting_version") == "protected-context-exact-accounting.v1":
        if reference or task.get("writer_projection_version") != "accepted-writer-history.v2":
            raise KernelError("TASK_CONTEXT_ACCOUNTING_INVALID", "Protected exact accounting requires its Writer projection")
        normalized, exact_accounting = _protected_envelope_accounting(normalized, required_asset_types=required_asset_types)
        by_id = {item.asset_version_id: item for item in normalized}
        for row in candidate_accounting:
            if row["asset_version_id"] in exact_accounting["protected_asset_version_ids"]:
                row.update(representation="STRUCTURED_PROTECTED_ENVELOPE", provider_data_upper_bound=by_id[row["asset_version_id"]].estimated_tokens)
    duplicated_ids = {receipt["asset_version_id"] for receipt in deduplications}
    excluded.extend(item for item in working if item.asset_version_id in duplicated_ids)
    protected = [item for item in normalized if context_candidate_class(item) is ContextClass.PROTECTED or item.required or item.asset_type in required_asset_types or item.asset_type in _EXACT]
    optional_auxiliary_ids = {item.asset_version_id for item in auxiliary[:12]}
    needed_refs = set((task.get("plan") or {}).get("required_long_distance_fact_ids") or ())
    needed_refs.update(ref for item in normalized if item.asset_version_id not in optional_auxiliary_ids for fact in item.structured_facts for ref in (fact.get("state") or {}).get("world_transition", {}).get("cause_refs", ()))
    if sum(item.estimated_tokens for item in normalized) > token_budget:
        for item in sorted((item for item in normalized if item.asset_version_id in optional_auxiliary_ids), key=lambda item: (item.relevance_score, item.asset_version_id)):
            if needed_refs.intersection(set().union(*(fact_aliases(fact) for fact in item.structured_facts)) if item.structured_facts else set()):
                continue
            normalized.remove(item)
            excluded.append(item)
            if sum(value.estimated_tokens for value in normalized) <= token_budget:
                break
    dependencies = validate_task_dependencies(normalized, task=task)
    protected_tokens = sum(item.estimated_tokens for item in protected)
    if protected_tokens > token_budget:
        raise KernelError("TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED", f"necessary exact task content requires conservative {protected_tokens} tokens; target={token_budget}")
    before = sum(item.estimated_tokens for item in normalized)
    traces = []
    if before > token_budget:
        eligible = [item for item in normalized if item not in protected and item.asset_type in _HISTORY and not item.compression_trace]
        if not eligible or model_call is None or compression_input_tokens <= 0:
            raise KernelError("TASK_CONTEXT_COMPRESSION_NOT_AUTHORIZED", "overflow requires a qualified controlled compressor route or a revised authorized task budget")
        protected_ids = {item.asset_version_id for item in protected}
        untouched_tokens = sum(item.estimated_tokens for item in normalized if item not in eligible)
        if untouched_tokens >= token_budget:
            raise KernelError("TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED", "exact sources and non-recompressible evidence exceed the task target")
        eligible_units = {item.asset_version_id: _units(item, task) for item in eligible}
        minimum_tokens = untouched_tokens
        for item in eligible:
            mandatory = [unit for unit in eligible_units[item.asset_version_id] if unit["required"]]
            minimum_tokens += serialized_token_upper_bound({
                "safe_summary": "\n\n".join(unit["text"] for unit in mandatory if unit["field"] == "safe_summary"),
                "structured_facts": [item.structured_facts[unit["index"]] for unit in mandatory if unit["field"] == "structured_facts"],
            })
        if minimum_tokens > token_budget:
            raise KernelError("TASK_CONTEXT_REQUIRED_BUDGET_EXCEEDED", "mandatory source units exceed the task target before compression")
        remaining = token_budget - untouched_tokens
        replacements = {}
        call_count = 0
        for candidate in eligible:
            if sum(replacements.get(item.asset_version_id, item).estimated_tokens for item in normalized) <= token_budget:
                break
            units = eligible_units[candidate.asset_version_id]
            groups = []
            group = []
            for unit in units:
                visible = {key: unit[key] for key in ("unit_id", "text", "kind", "required")}
                if serialized_token_upper_bound(visible) > compression_input_tokens:
                    raise KernelError("TASK_CONTEXT_CAUSAL_UNIT_TOO_LARGE", "one complete source unit exceeds the compressor input allocation")
                if group and (len(group) >= 256 or serialized_token_upper_bound([*group, visible]) > compression_input_tokens):
                    groups.append(group)
                    group = []
                group.append(visible)
            if group:
                groups.append(group)
            for index, original in enumerate(tuple(groups)):
                neighbours = [*(groups[index - 1][-2:] if index else []), *(groups[index + 1][:2] if index + 1 < len(groups) else [])]
                expanded = list({unit["unit_id"]: unit for unit in [*original, *neighbours]}.values())
                if len(expanded) <= 256 and serialized_token_upper_bound(expanded) <= compression_input_tokens:
                    groups[index] = expanded
            if len(groups) + call_count > maximum_chunks:
                raise KernelError("TASK_CONTEXT_COMPRESSION_CALL_BOUND", "task compression exceeds its bounded chunk allowance")
            keep = set()
            restored = set()
            evidence = []
            assessments = []
            candidate_target = max(1, remaining * candidate.estimated_tokens // max(1, sum(item.estimated_tokens for item in eligible)))
            group_weights = [serialized_token_upper_bound(group) for group in groups]
            weight_total = max(1, sum(group_weights))
            group_targets = [candidate_target * weight // weight_total for weight in group_weights]
            if any(target <= 0 for target in group_targets):
                raise KernelError("TASK_CONTEXT_COMPRESSION_BUDGET_INFEASIBLE", "candidate target cannot allocate every complete source group")
            for group_index, group in enumerate(groups):
                chunk = {
                    "contract_version": "task-context-compression.v1", "policy_version": TASK_CONTEXT_POLICY_VERSION,
                    boundary_key: boundary, "memo_fingerprint": str(task.get("memo_fingerprint") or ""), "task": dict(task), "units": group,
                    "required_unit_ids": [unit["unit_id"] for unit in group if unit["required"]],
                    "target_tokens": group_targets[group_index],
                    "candidate_target_tokens": candidate_target,
                    "selection_policy": "source-attribution-and-shared-group-budget.v2",
                    "source_binding": {"asset_version_id": candidate.asset_version_id, "content_hash": candidate.content_digest, "source_revision": candidate.source_revision},
                    "chunk_index": group_index,
                }
                selected_result = dict(model_call("context_compress", chunk))
                selected = selected_result.get("selected_unit_ids")
                allowed = {unit["unit_id"] for unit in group}
                required = set(chunk["required_unit_ids"])
                if not isinstance(selected, list) or any(not isinstance(value, str) for value in selected) or len(set(selected)) != len(selected) or not set(selected).issubset(allowed):
                    raise KernelError("TASK_CONTEXT_COMPRESSOR_IDENTITY_INVALID", "compressor may select only distinct host-bound source unit identities")
                chosen = set(selected) | required
                restored.update(required - set(selected))
                verdict = dict(model_call("context_fidelity", {**chunk, "selected_unit_ids": sorted(chosen)}))
                missing = set(verdict.get("missing_unit_ids") or ())
                distorted = set(verdict.get("distorted_unit_ids") or ())
                if not (missing | distorted).issubset(allowed):
                    chosen = allowed
                    restored.update(allowed)
                elif missing or distorted or verdict.get("supported") is not True or verdict.get("coverage_complete") is not True:
                    if missing and not distorted and verdict.get("supported") is True:
                        chosen.update(missing)
                        check = dict(model_call("context_fidelity", {**chunk, "selected_unit_ids": sorted(chosen)}))
                        assessments.append({
                            "task": chunk, "selected_unit_ids": selected,
                            "fidelity_selected_unit_ids": sorted(chosen),
                            "fidelity": {key: value for key, value in check.items() if key != "_execution_evidence"},
                            "compressor_evidence": dict(selected_result.get("_execution_evidence") or {}),
                            "fidelity_evidence": dict(check.get("_execution_evidence") or {}),
                            "recheck": True,
                        })
                        evidence.append(dict(check.get("_execution_evidence") or {}))
                        if check.get("supported") is not True or check.get("coverage_complete") is not True or check.get("missing_unit_ids") or check.get("distorted_unit_ids"):
                            chosen = allowed
                    else:
                        chosen = allowed
                    restored.update(chosen - set(selected))
                assessments.append({
                    "task": chunk, "selected_unit_ids": selected,
                    "fidelity_selected_unit_ids": sorted(set(selected) | required),
                    "fidelity": {key: value for key, value in verdict.items() if key != "_execution_evidence"},
                    "compressor_evidence": dict(selected_result.get("_execution_evidence") or {}),
                    "fidelity_evidence": dict(verdict.get("_execution_evidence") or {}),
                    "extract_accepted": chosen == set(selected) | required and verdict.get("supported") is True
                        and verdict.get("coverage_complete") is True and not missing and not distorted,
                })
                keep.update(chosen)
                evidence.extend([dict(selected_result.get("_execution_evidence") or {}), dict(verdict.get("_execution_evidence") or {})])
                call_count += 1
            texts = [unit["text"] for unit in units if unit["unit_id"] in keep and unit["field"] == "safe_summary"]
            facts = tuple(candidate.structured_facts[unit["index"]] for unit in units if unit["unit_id"] in keep and unit["field"] == "structured_facts") + tuple(fact for fact in candidate.structured_facts if fact.get("provider_visibility") == "INTERNAL_QUALITY_ONLY" and task.get("writer_projection_version") != "accepted-writer-history.v2")
            from .writer_projection import WRITER_PROJECTION_VERSION
            writer_projection = (candidate.provenance or {}).get("writer_projection_version") in {WRITER_PROJECTION_VERSION, "accepted-writer-history.v2"}
            payload = {"safe_summary": "\n\n".join(texts).strip() if writer_projection else "\n\n".join(texts), "structured_facts": list(facts)}
            trace = {"source_asset_version_id": candidate.asset_version_id, "source_content_hash": candidate.content_digest, "source_revision": candidate.source_revision, "task_hash": narrative_hash(task), boundary_key: boundary, "policy_version": TASK_CONTEXT_POLICY_VERSION, "method": "host-bound-extractive-semantic.v2", "selected_unit_ids": sorted(keep), "source_units": [{"unit_id": unit["unit_id"], "source_path": unit.get("source_path", [unit["field"]]), "index": unit.get("index"), "unit_hash": narrative_hash(unit["text"]), "kind": unit["kind"]} for unit in units if unit["unit_id"] in keep], "restored_unit_ids": sorted(restored), "result_content_hash": narrative_hash(payload), "forward_check": "EXACT_HOST_SOURCE_UNITS", "reverse_check": "REQUIRED_UNITS_AND_INDEPENDENT_SEMANTIC_CHECK_OR_FULL_LOCAL_RESTORE", "model_execution_evidence": evidence, "routing_assessments": assessments}
            if writer_projection:
                trace["writer_projection_version"] = candidate.provenance["writer_projection_version"]
            replacements[candidate.asset_version_id] = replace(candidate, safe_summary=payload["safe_summary"], structured_facts=facts, estimated_tokens=max(1, serialized_token_upper_bound(payload)), context_class=ContextClass.COMPRESSIBLE, compression_method=trace["method"], compression_trace=(trace,))
            traces.append(trace)
        normalized = [replacements.get(item.asset_version_id, item) for item in normalized]
        if sum(item.estimated_tokens for item in normalized) > token_budget:
            raise KernelError("TASK_CONTEXT_FIDELITY_RESTORE_EXCEEDS_BUDGET", "faithful restored Context exceeds its authorized task target; no required source was silently discarded")
        assert not protected_ids.intersection(replacements)
    if reference:
        normalized.sort(key=source_position)
    result = [*normalized, *denied] + [replace(item, provenance={**dict(item.provenance or {}), "task_excluded": True}) for item in excluded]
    receipt = {"policy_version": TASK_CONTEXT_POLICY_VERSION, "task_hash": narrative_hash(task), boundary_key: boundary, "source_bindings": [{"asset_version_id": item.asset_version_id, "source_revision": item.source_revision, "content_hash": item.content_digest} for item in candidates], "system_context_window_tokens": SYSTEM_CONTEXT_WINDOW_TOKENS, "task_target_tokens": token_budget, "token_accounting": "utf8-byte-upper-bound.v1", "candidate_accounting": candidate_accounting, "before_estimated_tokens": before, "after_estimated_tokens": sum(item.estimated_tokens for item in normalized), "protected_estimated_tokens": protected_tokens, "dependency_coverage": dependencies, "deduplications": deduplications, "excluded_asset_version_ids": [item.asset_version_id for item in excluded], "compression_trace": traces, "fast_path": not traces, "compression_source": "ORIGINAL_FROZEN_PROJECTION_ONLY", "fact_mutation_allowed": False}
    if exact_accounting is not None:
        receipt["protected_exact_accounting"] = exact_accounting
    return result, {**receipt, "receipt_hash": narrative_hash(receipt)}
