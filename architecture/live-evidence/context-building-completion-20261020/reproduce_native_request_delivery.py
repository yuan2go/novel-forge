"""CONSTRAINT: Read-only verification requires retained private native inputs and authorization."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
from novel_forge.modules.book_authority.memory_readback import request_memory
from novel_forge.modules.chapter_authority.author_editor import source_draft_content
from novel_forge.modules.chapter_authority.provider_views import expand_exact_context_references
from novel_forge.modules.chapter_authority.request_snapshot import validate_provider_request_snapshot
from novel_forge.modules.story_planning_runtime.domain import canonical_hash
from novel_forge.storage.authority_uow import AuthorityUnitOfWork


def exact_passage_runs(sources, source_id, original):
    for source in sources:
        if source.get("asset_version_id") != source_id:
            continue
        run, last = "", None
        for part in sorted(source.get("passages", []), key=lambda row: row["start"]):
            start, end, text = part["start"], part["end"], part["text"]
            if text != original[start:end] or end - start != len(text):
                run, last = "", None
                continue
            run = (run if last == start else "") + text
            last = end
            yield run


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--book-run-id", required=True)
    parser.add_argument("--chapter-request-id", required=True)
    parser.add_argument("--external-effect-id", required=True)
    parser.add_argument("--critical-evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    env = json.loads(args.runtime_config.read_text())
    os.environ.update(env)
    principal = build_trusted_principal_resolver(env=env).resolve_api_principal()
    readback = request_memory(
        env["NOVEL_FORGE_DATABASE_URL"], project_id=args.project_id,
        book_run_id=args.book_run_id, chapter_request_id=args.chapter_request_id,
        principal=principal,
    )
    effect = next(row for row in readback["writer_effects"]
                  if row["external_effect_id"] == args.external_effect_id)
    if effect["input_snapshot_status"] != "FROZEN_APPLICATION_REQUEST":
        raise ValueError("Legacy hash-only input cannot be replaced by a current preview")
    admission = effect["provider_admission"]["content"]
    envelope = validate_provider_request_snapshot(
        admission["provider_request_snapshot"], identity=admission["provider_request_identity"],
        envelope_hash=admission["provider_request_snapshot"]["envelope_hash"],
    )
    frozen_view = admission["prompt_materialization"].get("provider_view", {})
    references = frozen_view.get("exact_context_references")
    if not references:
        raise ValueError("This verifier requires a frozen exact-reference application data frame")
    template = envelope.input_text.split("<prompt_template>\n", 1)[1].split("\n</prompt_template>", 1)[0]
    start = template.index('{"context_bundle":')
    encoded = json.JSONDecoder().raw_decode(template[start:])[0]
    actual = expand_exact_context_references(
        encoded, prose_comparison=references.get("transport_version") == "provider-structured-exact-reference.v5",
    )["context_bundle"]["working_manuscript"]
    checklist = json.loads(args.critical_evidence.read_text())
    snapshot = readback["working_manuscript"]
    originals = {}
    with AuthorityUnitOfWork(env["NOVEL_FORGE_DATABASE_URL"]) as uow:
        for source in snapshot["source_history"]["sources"]:
            document = uow.repositories.asset_documents.require(
                project_id=args.project_id, asset_version_id=source["asset_version_id"],
            )
            if document.content_hash != source["content_hash"] or canonical_hash(document.content) != document.content_hash:
                raise ValueError("Frozen original source failed its digest")
            originals[document.asset_version_id] = source_draft_content(document)["text"]
    cases = []
    for case in checklist["cases"]:
        alternatives = []
        for item in case["alternatives"]:
            source_id, quote = item["asset_version_id"], item["quote"]
            original = originals[source_id]
            if hashlib.sha256(quote.encode()).hexdigest() != item["quote_sha256"] or quote not in original:
                raise ValueError("Evidence quote differs from its original source")
            passage = any(quote in run for run in exact_passage_runs(actual["sources"], source_id, original))
            memory = any(
                row["source"]["asset_version_id"] == source_id and quote in row["quote"]
                and row["quote"] == original[row["location"]["start"]:row["location"]["end"]]
                for row in actual.get("working_memory", {}).get("entries", [])
            )
            alternatives.append(dict(
                asset_version_id=source_id, quote_sha256=item["quote_sha256"],
                source_bound_exact_passage=passage, source_bound_exact_memory_quote=memory,
            ))
        cases.append(dict(id=case["id"], alternatives=alternatives))
    result = dict(
        record_type="READ_ONLY_SOURCE_BOUND_ACTUAL_APPLICATION_INPUT_VERIFICATION",
        chapter_request_id=args.chapter_request_id, external_effect_id=args.external_effect_id,
        effect_status=effect["status"], envelope_hash=envelope.envelope_hash,
        application_input_sha256=hashlib.sha256(envelope.input_text.encode()).hexdigest(),
        application_input_utf8_bytes=len(envelope.input_text.encode()),
        protocol_schema_utf8_bytes=len(envelope.protocol_schema_json.encode()),
        critical_evidence_sha256=hashlib.sha256(args.critical_evidence.read_bytes()).hexdigest(),
        cases=cases, provider_calls=0,
        boundary="Presence facts only: apply the preregistered conditional rules separately. No model comprehension, prose success, acceptance or literary qualification is inferred.",
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(dict(cases=len(cases), provider_calls=0, effect_status=effect["status"])))


if __name__ == "__main__":
    try:
        main()
    except KernelError as error:
        raise SystemExit(str(error)) from error
