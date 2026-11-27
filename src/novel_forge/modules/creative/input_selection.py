from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Mapping

from novel_forge.modules.command_kernel.errors import KernelError


INPUT_SELECTION_VERSION = "creative-input-selection.v1"
INPUT_SOURCES = frozenset({"CURRENT_AUTHOR_INPUT", "TASK_GENERATED", "HISTORICAL_TEST_SAMPLE", "REFERENCE_MATERIAL"})
INPUT_PURPOSES = frozenset({"WORK_PRODUCTION", "CREATIVE_EVALUATION", "ENGINEERING_REGRESSION", "HISTORICAL_REPLAY"})


def validate_input_selection(value: Any) -> dict[str, Any]:
    fields = {"contract_version", "book_id", "source_kind", "purpose", "intent_ref"}
    parent = {"asset_version_id", "content_hash"}
    if (not isinstance(value, Mapping) or set(value) not in (fields, fields | {"parent_input"})
            or value.get("contract_version") != INPUT_SELECTION_VERSION
            or value.get("source_kind") not in INPUT_SOURCES or value.get("purpose") not in INPUT_PURPOSES
            or any(not isinstance(value.get(key), str) or not value[key].strip() for key in ("book_id", "intent_ref"))):
        raise KernelError("CREATIVE_INPUT_SELECTION_REQUIRED", "Select the current Book, input source, intended use and current intent reference explicitly")
    derived = value["source_kind"] == "TASK_GENERATED"
    source = value.get("parent_input")
    if derived != (source is not None) or source is not None and (
            not isinstance(source, Mapping) or set(source) != parent
            or not isinstance(source["asset_version_id"], str) or not source["asset_version_id"].strip()
            or not isinstance(source["content_hash"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", source["content_hash"])):
        raise KernelError("CREATIVE_INPUT_PARENT_REQUIRED", "A task-generated input must retain its exact selected current input")
    if value["purpose"] == "WORK_PRODUCTION" and value["source_kind"] not in {"CURRENT_AUTHOR_INPUT", "TASK_GENERATED"}:
        raise KernelError("CREATIVE_INPUT_USE_FORBIDDEN", "Historical samples and reference materials cannot supply current author intent")
    if value["source_kind"] == "REFERENCE_MATERIAL":
        raise KernelError("CREATIVE_INPUT_USE_FORBIDDEN", "Reference materials require the existing governed Source and Knowledge path")
    return deepcopy(dict(value))


def bind_input_selection(value: Any, *, project_id: str, workspace_id: str, actor_id: str,
                         operation_id: str, inputs: tuple[Any, ...] = ()) -> dict[str, Any]:
    selected = validate_input_selection(value)
    if selected["source_kind"] == "TASK_GENERATED":
        parent = selected["parent_input"]
        matches = [item for item in inputs if item.asset_version_id == parent["asset_version_id"]
                   and item.content_hash == parent["content_hash"] and item.asset_type == "creative_brief"]
        if len(matches) != 1:
            raise KernelError("CREATIVE_INPUT_PARENT_REQUIRED", "Derived input must freeze its selected current Brief")
        binding = require_input_scope(matches[0].content, project_id=project_id, workspace_id=workspace_id,
                                      book_id=selected["book_id"])
        if binding["purpose"] != selected["purpose"] or binding["intent_ref"] != selected["intent_ref"]:
            raise KernelError("CREATIVE_INPUT_PARENT_DRIFT", "Derived input cannot change its selected purpose or current intent")
    return {**selected, "project_id": project_id, "workspace_id": workspace_id,
            "selected_by_actor_id": actor_id, "selection_operation_id": operation_id}


def require_input_scope(content: Mapping[str, Any], *, project_id: str, workspace_id: str,
                        book_id: str) -> dict[str, Any]:
    binding = content.get("creative_input_selection")
    provenance = {"project_id", "workspace_id", "selected_by_actor_id", "selection_operation_id"}
    if not isinstance(binding, Mapping) or not provenance <= binding.keys():
        raise KernelError("CREATIVE_INPUT_SELECTION_REQUIRED", "New creation requires an explicitly selected Book-bound input; legacy input is readable only through its original frozen run")
    selected = validate_input_selection({key: value for key, value in binding.items() if key not in provenance})
    if (binding["project_id"], binding["workspace_id"], selected["book_id"]) != (project_id, workspace_id, book_id):
        raise KernelError("CREATIVE_INPUT_BOOK_MISMATCH", "Creative input belongs to another Project, Workspace or Book")
    if any(not isinstance(binding[key], str) or not binding[key].strip() for key in provenance):
        raise KernelError("CREATIVE_INPUT_PROVENANCE_REQUIRED", "Creative input requires its native selection Operation and actor")
    return dict(binding)


def narrative_brief(content: Mapping[str, Any]) -> dict[str, Any]:
    version = content.get("creative_brief_contract_version")
    from .domain import BRIEF_FIELDS
    fields = set(BRIEF_FIELDS) if version == "creative-brief-v1" else {"idea", "genre", "audience", "constraints", "source_boundaries"}
    return {key: deepcopy(content[key]) for key in ("creative_brief_contract_version", *sorted(fields)) if key in content}


def brief_input_assets(brief: Mapping[str, Any], selection: Mapping[str, Any] | None) -> tuple[dict[str, str], ...]:
    references = []
    if selection and selection.get("parent_input"):
        references.append(dict(selection["parent_input"]))
    if brief.get("editorial_learning"):
        from .editorial_learning import validate_editorial_learning
        learning = validate_editorial_learning(brief["editorial_learning"])
        for decision in learning["decisions"]:
            for card in decision["knowledge_cards"]:
                if card not in references:
                    references.append(dict(card))
    return tuple(references)


def require_selected_brief(cursor: Any, *, asset_version_id: str, content_hash: str,
                           project_id: str, workspace_id: str, book_id: str,
                           allow_legacy_frozen: bool = False) -> dict[str, Any]:
    cursor.execute("""SELECT v.content, v.content_hash, v.lifecycle, v.eligibility, v.governance
        FROM authority_asset_version v JOIN authority_asset a USING(asset_id)
        WHERE a.project_id=%s AND a.asset_type='creative_brief' AND v.asset_version_id=%s""",
        [project_id, asset_version_id])
    row = cursor.fetchone()
    if row is None or row[1] != content_hash or tuple(row[2:]) != ("ACTIVE", "ELIGIBLE", "CLEAR"):
        raise KernelError("CREATIVE_INPUT_IDENTITY_INVALID", "Selected input is missing, ineligible or differs from its frozen identity")
    content = dict(row[0])
    if not content.get("creative_input_selection") and allow_legacy_frozen:
        return content
    binding = require_input_scope(content, project_id=project_id, workspace_id=workspace_id, book_id=book_id)
    cursor.execute("""SELECT 1 FROM authority_operation o JOIN authority_asset_qualification q
        ON q.evidence->>'operation_id'=o.operation_id
        WHERE o.operation_id=%s AND o.project_id=%s AND o.workspace_id=%s
        AND o.actor_id=%s AND o.definition_name='creative.brief.create' AND o.status='SUCCEEDED'
        AND q.asset_version_id=%s AND o.command_payload #> '{payload,input_selection}'=%s::jsonb""",
        [binding["selection_operation_id"], project_id, workspace_id, binding["selected_by_actor_id"],
         asset_version_id, json.dumps({key: value for key, value in binding.items()
            if key not in {"project_id", "workspace_id", "selected_by_actor_id", "selection_operation_id"}})])
    if cursor.fetchone() is None:
        raise KernelError("CREATIVE_INPUT_PROVENANCE_REQUIRED", "Input labels cannot substitute for a successful native selection command")
    return content
