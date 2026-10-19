import gzip
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from novel_forge.modules.book_authority.manuscript import resolve_working_source
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from verify_dispatch import working_sources


def verify(path):
    data = json.load(gzip.open(path, "rt"))
    assert data["evidence_class"] == "REAL_PROVIDER_NATIVE_POSTGRESQL"
    assert len(data["books"]) == 1
    book = data["books"][0]
    assert book["current_chapter"] >= 2 and len(data["deliveries"]) >= 2
    assets = {a["version"]["asset_version_id"]: a["version"] for a in data["assets"]}
    receipts = {x["dispatch"]["external_effect_id"]: x for x in data["receipts"]}
    checks = []
    local_memos = []
    with AuthorityUnitOfWork(os.environ["NOVEL_FORGE_DATABASE_URL"]) as uow:
        uow.cursor.execute("SET TRANSACTION READ ONLY")
        uow.cursor.execute("SELECT to_jsonb(b) FROM authority_book_production b WHERE book_run_id=%s", [book["book_run_id"]])
        current = uow.cursor.fetchone()[0]
        assert set(current) == set(book)
        normalized_current, normalized_snapshot = dict(current), dict(book)
        timestamp_checks = []
        for field in ("created_at", "updated_at"):
            actual = datetime.fromisoformat(current[field])
            captured = datetime.fromisoformat(book[field])
            assert actual.tzinfo is not None and captured.tzinfo is not None
            assert actual == captured, field
            normalized_current[field] = actual.astimezone(timezone.utc).isoformat()
            normalized_snapshot[field] = captured.astimezone(timezone.utc).isoformat()
            timestamp_checks.append({"field": field, "native_utc": current[field],
                                     "snapshot": book[field], "same_instant": True})
        assert normalized_current == normalized_snapshot and current["accepted_through_chapter"] == 0

        def check(source, *, role, target, operation_id):
            assert source["chapter"] < target
            document, resolution = resolve_working_source(uow, book, source["chapter"], prefer_accepted=False)
            assert document.asset_version_id == source["asset_version_id"]
            assert document.content_hash == source["content_hash"]
            assert resolution == source["source_resolution"]
            assert source["status"] == "UNREVIEWED_WORKING_PROSE"
            assert source["character_knowledge"] == "NOT_VERIFIED"
            checks.append({"role": role, "operation_id": operation_id, "target_chapter": target,
                "source_chapter": source["chapter"], "source_asset_version_id": document.asset_version_id,
                "content_hash": document.content_hash, "source_resolution": resolution})

        for effect in data["effects"]:
            sources = list(working_sources(effect["request_payload"].get("input")))
            if not sources:
                continue
            receipt = receipts[effect["external_effect_id"]]
            evidence = (receipt["receipt"]["payload"]["evidence"] if receipt["receipt"] else receipt["dispatch"]["evidence"])
            scope = evidence["production_execution"]["execution_request"]["target_scope"]
            assert scope["book_id"] == book["book_id"] and scope["project_id"] == book["project_id"]
            target = scope.get("chapter_number")
            if target is None:
                target = int(re.search(r":(\d+)$", scope["scope_id"]).group(1))
            for source in sources:
                check(source, role="ACTUAL_PROVIDER_INPUT", target=target, operation_id=effect["operation_id"])

        for asset in data["assets"]:
            memo = asset["version"]
            if asset["asset_type"] != "chapter_memo" or memo["content"].get("execution_evidence", {}).get("model_call") != "NOT_RUN":
                continue
            uow.cursor.execute("""SELECT child.operation_id,root.command_payload->>'book_id'
                FROM authority_operation_output_asset output JOIN authority_operation child USING(operation_id)
                JOIN authority_operation root ON root.operation_id=child.root_operation_id
                WHERE output.asset_version_id=%s AND output.role='primary'
                  AND child.definition_name='chapter.memo.generate' AND child.status='SUCCEEDED'""", [memo["asset_version_id"]])
            owners = uow.cursor.fetchall()
            assert len(owners) == 1 and owners[0][1] == book["book_id"]
            local_memos.append(memo["asset_version_id"])
            intent = assets[memo["content"]["source_chapter_execution_intent_asset_version_id"]]
            for source in working_sources(intent["content"]):
                check(source, role="LOCAL_MEMO_FROZEN_INTENT", target=memo["content"]["chapter"], operation_id=owners[0][0])
    assert checks and len(local_memos) >= 2
    report = {"status": "PASS", "evidence_class": "READ_ONLY_BOOK_OWNER_SOURCE_RESOLUTION_AUDIT",
        "input": Path(path).name, "input_sha256": "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "book_run_id": book["book_run_id"], "book_id": book["book_id"], "book_version": book["version"],
        "accepted_through_chapter": 0, "local_memos": local_memos,
        "book_fields_compared": sorted(book), "timestamp_instants_checked": timestamp_checks,
        "working_source_occurrences": len(checks), "checks": checks}
    out = Path(path).with_name("actual-book-source-resolution.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(len(checks), "past-chapter same-Book source resolutions verified")


if __name__ == "__main__":
    verify(sys.argv[1])
