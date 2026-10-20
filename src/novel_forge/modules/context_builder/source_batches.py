from copy import deepcopy
from dataclasses import replace

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.context_contracts import ContextClass, FROZEN_COMPRESSION_REQUEST_MAX_UNITS
from novel_forge.modules.narrative_state.reality import narrative_hash

from . import semantic_units

BATCH_VERSION = "source-bound-capacity-batching.v1"


def current_batching_version(data):
    task = data.get("input_manifest") or {}
    context = data.get("context_bundle") or {}
    packets = [context.get("working_manuscript"),
        (task.get("frozen_intent") or {}).get("working_manuscript"),
        (task.get("arc_working_set") or {}).get("working_manuscript"),
        (task.get("world_preparation") or {}).get("working_manuscript")]
    versions = {(packet.get("retrieval_task") or {}).get("contract_version")
                for packet in packets if isinstance(packet, dict)}
    return BATCH_VERSION if versions == {"working-retrieval-task.v6"} else ""


def compress_source_batches(*, eligible, normalized, catalogs, mandatory_amounts, token_budget,
                            task, boundary, model_call, chunk_fits, token_counter, external_refs):
    replacements, traces = {}, []
    pending = []

    def payload(members, *, selected=None):
        units, origins = [], {}
        for candidate in members:
            local = catalogs[candidate.asset_version_id]
            remap = {unit["unit_id"]: "batch:" + narrative_hash([candidate.asset_version_id, unit["unit_id"]]).split(":")[-1]
                     for unit in local}
            for unit in local:
                identity = remap[unit["unit_id"]]
                origins[identity] = (candidate.asset_version_id, unit["unit_id"])
                units.append({**deepcopy(unit), "unit_id": identity, "order": len(units),
                    "explicit_refs": [remap.get(ref, ref) for ref in unit.get("explicit_refs", ())],
                    "attribution": {**deepcopy(unit.get("attribution", {})),
                        "source_expression": deepcopy(candidate.provenance.get("source_expression") or {}),
                        "source_candidate": {"asset_version_id": candidate.asset_version_id,
                            "content_hash": candidate.content_digest, "original_unit_id": unit["unit_id"]}}})
        ids = {candidate.asset_version_id for candidate in members}
        others = sum(replacements.get(item.asset_version_id, item).estimated_tokens
                     for item in normalized if item.asset_version_id not in ids)
        target = max(1, sum(mandatory_amounts[identity] for identity in ids), token_budget - others)
        result = {"contract_version": "task-context-compression.v3",
            "semantic_contract": semantic_units.SEMANTIC_CONTRACT,
            "policy_version": "task-scoped-context.v1", "frozen_input_boundary": boundary,
            "task_fingerprint": task["source_projection_hash"], "task": task,
            "source_binding": members[0].provenance["source_binding"],
            "units": units, "required_unit_ids": [unit["unit_id"] for unit in units if unit["required"]],
            "target_tokens": min(512_000, target), "candidate_target_tokens": target,
            "selection_policy": BATCH_VERSION}
        if selected is not None:
            result["selected_unit_ids"] = sorted(selected)
        return result, origins

    def fits(members):
        if sum(len(catalogs[item.asset_version_id]) for item in members) > FROZEN_COMPRESSION_REQUEST_MAX_UNITS:
            return False
        chunk, _ = payload(members)
        return chunk_fits(chunk)

    def flush(members):
        if len(members) < 2 or sum(replacements.get(item.asset_version_id, item).estimated_tokens for item in normalized) <= token_budget:
            return
        chunk, origins = payload(members)
        result = dict(model_call("context_compress", chunk))
        selected = result.get("selected_unit_ids")
        allowed = set(origins)
        if (not isinstance(selected, list) or any(not isinstance(value, str) for value in selected)
                or len(selected) != len(set(selected)) or not set(selected) <= allowed):
            raise KernelError("TASK_CONTEXT_COMPRESSOR_IDENTITY_INVALID", "Batch selection requires distinct original host-bound unit identities")
        chosen = semantic_units.close_dependencies(chunk["units"], set(selected) | set(chunk["required_unit_ids"]), external_refs=external_refs)
        verdict = dict(model_call("context_fidelity", {**chunk, "selected_unit_ids": sorted(chosen)}))
        missing, distorted = verdict.get("missing_unit_ids"), verdict.get("distorted_unit_ids")
        valid = (isinstance(missing, list) and isinstance(distorted, list)
            and all(isinstance(value, str) for value in [*missing, *distorted])
            and set(missing) | set(distorted) <= allowed)
        evidence = [dict(result.get("_execution_evidence") or {}), dict(verdict.get("_execution_evidence") or {})]
        if valid and missing and not distorted and verdict.get("supported") is True:
            chosen = semantic_units.close_dependencies(chunk["units"], chosen | set(missing), external_refs=external_refs)
            verdict = dict(model_call("context_fidelity", {**chunk, "selected_unit_ids": sorted(chosen)}))
            evidence.append(dict(verdict.get("_execution_evidence") or {}))
            missing, distorted = verdict.get("missing_unit_ids"), verdict.get("distorted_unit_ids")
            valid = isinstance(missing, list) and isinstance(distorted, list) and not missing and not distorted
        restored = not valid or bool(missing or distorted) or verdict.get("supported") is not True or verdict.get("coverage_complete") is not True
        if restored:
            chosen = allowed
        shared = {"version": BATCH_VERSION, "batch_hash": narrative_hash(chunk),
            "source_candidate_ids": [item.asset_version_id for item in members],
            "selected_unit_ids": sorted(chosen), "original_selection": selected,
            "restoration": "EXACT_ORIGINAL_BATCH" if restored else "INDEPENDENT_FIDELITY_SUPPORTED",
            "provider_execution_scope": "SHARED_BATCH_NOT_PER_SOURCE_CALL"}
        for candidate in members:
            identity = candidate.asset_version_id
            units = catalogs[identity]
            keep = {original for batch_id, (source, original) in origins.items() if source == identity and batch_id in chosen}
            value = semantic_units.reconstruct(candidate, units, keep)
            local_task = {**chunk, "task": {**task, "source_expression": candidate.provenance.get("source_expression") or {}},
                "units": units, "required_unit_ids": [unit["unit_id"] for unit in units if unit["required"]]}
            trace = {"source_asset_version_id": identity, "source_content_hash": candidate.content_digest,
                "source_revision": candidate.source_revision, "source_binding": chunk["source_binding"],
                "source_binding_role": "FROZEN_PROVIDER_CONTEXT_CUSTODY", "task_hash": narrative_hash(task),
                "frozen_input_boundary": boundary, "policy_version": "task-scoped-context.v1",
                "method": "host-bound-extractive-semantic.v4", "semantic_contract": semantic_units.SEMANTIC_CONTRACT,
                "selected_unit_ids": sorted(keep), "restored_unit_ids": sorted(original for batch_id, (source, original) in origins.items()
                    if source == identity and batch_id in chosen - set(selected)),
                "source_units": semantic_units.source_audit(units, keep),
                "source_catalog": semantic_units.source_audit(units, {unit["unit_id"] for unit in units}),
                "result_content_hash": narrative_hash(value), "source_batch": shared,
                "forward_check": "EXACT_HOST_SOURCE_UNITS", "reverse_check": "SHARED_INDEPENDENT_FIDELITY_OR_EXACT_ORIGINAL_BATCH",
                "model_execution_evidence": evidence,
                "routing_assessments": [{"task": local_task, "execution_scope": "HOST_PROJECTION_OF_SHARED_BATCH",
                    "provider_task_hash": narrative_hash(chunk), "fidelity": {key: value for key, value in verdict.items() if key != "_execution_evidence"}}],
                "final_composition": {"status": "REQUIRES_FINAL_PROVIDER_COMPOSITION", "batch_hash": shared["batch_hash"]}}
            replacements[identity] = replace(candidate, safe_summary=value["safe_summary"], structured_facts=tuple(value["structured_facts"]),
                estimated_tokens=max(1, token_counter(value)), context_class=ContextClass.COMPRESSIBLE,
                compression_method=trace["method"], compression_trace=(trace,))
            traces.append(trace)

    for candidate in eligible:
        if candidate.asset_type != "historical_expression_projection" or not (candidate.provenance or {}).get("source_binding"):
            continue
        binding = candidate.provenance["source_binding"]
        if pending and (pending[0].provenance["source_binding"] != binding or not fits([*pending, candidate])):
            flush(pending)
            pending = []
        if not pending and not fits([candidate]):
            continue
        pending.append(candidate)
    flush(pending)
    return replacements, traces
