from __future__ import annotations

from copy import deepcopy
from base64 import urlsafe_b64encode

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.production_execution.cost_routing import snapshot_hash
from novel_forge.modules.review.diagnostics import prose_hash

CONTRACT = "canon-paragraph-references.v1"
SUCCESSOR = "chapter-canon-reference-contract-repair.v1"


def build_references(text, *, target_asset_version_id):
    identity = snapshot_hash(
        {"target": target_asset_version_id, "text_hash": prose_hash(text)}
    )
    token = urlsafe_b64encode(bytes.fromhex(identity.removeprefix("sha256:"))[:8]).decode().rstrip("=")
    rows, rendered, position = [], [], 0
    for line in text.splitlines(keepends=True):
        body = line.rstrip("\r\n")
        if body.strip():
            reference = (
                f"r:{token}:{len(rows) + 1}"
            )
            rows.append(
                {
                    "reference_id": reference,
                    "start": position,
                    "end": position + len(body),
                }
            )
            rendered.append(f"[{reference}] {line}")
        else:
            rendered.append(line)
        position += len(line)
    if not rows or position != len(text):
        raise KernelError(
            "CANON_REFERENCE_SOURCE_INVALID",
            "Require one complete nonempty exact prose source",
        )
    rendering = "".join(rendered)
    return {
        "contract_version": CONTRACT,
        "target_asset_version_id": target_asset_version_id,
        "source_text_hash": prose_hash(text),
        "offset_unit": "UNICODE_CODE_POINT",
        "references": rows,
        "rendered_text": rendering,
        "rendered_hash": snapshot_hash(rendering),
    }


def bind_reference_schema(schema, corpus):
    result = deepcopy(schema)
    ids = [row["reference_id"] for row in corpus["references"]]
    result.setdefault("$defs", {})["host_canon_paragraph_reference"] = {
        "type": "string",
        "enum": ids,
    }
    reference_schema = {"$ref": "#/$defs/host_canon_paragraph_reference"}

    def walk(value):
        if isinstance(value, dict):
            properties = value.get("properties", {})
            for key in ("evidence_quote", "quote"):
                if key in properties:
                    original = properties[key]
                    nullable = any(
                        item.get("type") == "null" for item in original.get("anyOf", [])
                    )
                    properties[key] = (
                        {"anyOf": [deepcopy(reference_schema), {"type": "null"}]}
                        if nullable
                        else deepcopy(reference_schema)
                    )
            if "resolution_evidence" in properties:
                properties["resolution_evidence"]["items"] = deepcopy(reference_schema)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(result)
    return result


def resolve_references(document, *, text, target_asset_version_id, corpus):
    expected = build_references(text, target_asset_version_id=target_asset_version_id)
    if expected != corpus:
        raise KernelError(
            "CANON_REFERENCE_SOURCE_DRIFT",
            "Require the exact original candidate reference corpus",
        )
    spans = {row["reference_id"]: row for row in corpus["references"]}
    resolved, mappings = deepcopy(document), []

    def resolve(reference, path, start=None, end=None):
        if reference is None:
            return None
        if not isinstance(reference, str) or reference not in spans:
            raise KernelError(
                "CANON_REFERENCE_INVALID",
                "Evidence must select a current host reference ID",
            )
        span = spans[reference]
        if (start is not None or end is not None) and (start, end) != (
            span["start"],
            span["end"],
        ):
            raise KernelError(
                "CANON_REFERENCE_OFFSET_INVALID",
                "Explicit intervals cannot contradict the selected reference",
            )
        quote = text[span["start"] : span["end"]]
        mappings.append(
            {
                "path": path,
                **span,
                "source_text_hash": corpus["source_text_hash"],
                "literal_resolution": "EXACT_FROZEN_INTERVAL",
                "semantic_support": "NOT_RUN",
            }
        )
        return quote

    def walk(value, path):
        if isinstance(value, dict):
            for key in ("evidence_quote", "quote"):
                if key in value:
                    prefix = "evidence_" if key == "evidence_quote" else ""
                    reference = value[key]
                    value[key] = resolve(
                        reference,
                        path + "." + key,
                        value.get(prefix + "start"),
                        value.get(prefix + "end"),
                    )
                    if reference is not None:
                        value[prefix + "start"] = spans[reference]["start"]
                        value[prefix + "end"] = spans[reference]["end"]
            if isinstance(value.get("resolution_evidence"), list):
                value["resolution_evidence"] = [
                    f"chars:{spans[reference]['start']}-{spans[reference]['end']}:"
                    + resolve(reference, path + f".resolution_evidence[{index}]")
                    for index, reference in enumerate(value["resolution_evidence"])
                ]
            for key, child in value.items():
                walk(child, path + "." + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, path + f"[{index}]")

    walk(resolved, "$")
    return resolved, {
        "contract_version": CONTRACT,
        "target_asset_version_id": target_asset_version_id,
        "source_text_hash": corpus["source_text_hash"],
        "reference_corpus_hash": snapshot_hash(corpus),
        "provider_output_hash": snapshot_hash(document),
        "mappings": mappings,
        "semantic_support": "NOT_RUN",
        "strict_certification_eligible": False,
    }


def require_successor_send(request):
    proof = (
        (request.command.get("preparation_report") or {}).get(
            "retained_graph_continuation"
        )
        or {}
    ).get("retained_result") or {}
    if proof.get("contract_version") != SUCCESSOR:
        return None
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    from .current_quote_recovery import repair_feedback

    with AuthorityUnitOfWork(request.database_url) as uow:
        uow.cursor.execute(
            "SELECT attempt_number FROM authority_attempt WHERE attempt_id=%s AND operation_id=%s",
            [request.attempt_id, request.operation_id],
        )
        if uow.cursor.fetchone() != (1,):
            raise KernelError(
                "CANON_REFERENCE_REPAIR_CONTROL_EXHAUSTED",
                "A changed-contract successor cannot reset the original calls or dispatch another repair send",
            )
    return repair_feedback(request, stage="canon_extraction")
