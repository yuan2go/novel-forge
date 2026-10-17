import gzip, json, hashlib, sys, os
from pathlib import Path
import psycopg
from verify_dispatch import working_sources
from novel_forge.modules.chapter_authority.execution_artifacts import validate_chapter_memo

def sha(text):
    return "sha256:" + hashlib.sha256(text.encode()).hexdigest()

def verify(path):
    d = json.load(gzip.open(path, "rt"))
    assets = {a["version"]["asset_version_id"]: a["version"] for a in d["assets"]}
    memos = [a["version"] for a in d["assets"] if a["asset_type"] == "chapter_memo"
             and a["version"]["content"].get("execution_evidence", {}).get("model_call") == "NOT_RUN"]
    rows = []
    with psycopg.connect(os.environ["NOVEL_FORGE_DATABASE_URL"], options="-c default_transaction_read_only=on") as c:
        identity = c.execute("SELECT current_database(),(SELECT system_identifier::text FROM pg_control_system()),clock_timestamp()").fetchone()
        assert identity[0] == d.get("database", (d.get("identity") or [None])[0])
        for memo in memos:
            content = memo["content"]
            sid = content["source_chapter_execution_intent_asset_version_id"]
            intent = assets[sid]
            validate_chapter_memo(content, intent=intent["content"], intent_asset_version_id=sid)
            owners = c.execute("""SELECT o.operation_id,o.project_id,o.input_asset_snapshot
                FROM authority_operation_output_asset output JOIN authority_operation o USING(operation_id)
                WHERE output.asset_version_id=%s AND output.role='primary'
                  AND o.definition_name='chapter.memo.generate' AND o.status='SUCCEEDED'""", [memo["asset_version_id"]]).fetchall()
            assert len(owners) == 1
            op, project, snapshot = owners[0]
            assert any(x["asset_version_id"] == sid and x["content_hash"] == intent["content_hash"] for x in snapshot)
            assert intent["content"]["project_id"] == project
            sources = []
            for source in working_sources(intent["content"]):
                body = assets[source["asset_version_id"]]
                assert body["content_hash"] == source["content_hash"]
                text = body["content"]["text"]
                assert sha(text) == source["text_hash"]
                assert source["status"] == "UNREVIEWED_WORKING_PROSE" and source["character_knowledge"] == "NOT_VERIFIED"
                assert source["chapter"] < content["chapter"]
                owner = c.execute("SELECT a.project_id FROM authority_asset_version v JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s", [source["asset_version_id"]]).fetchone()
                assert owner == (project,)
                for passage in source["passages"]:
                    assert text[passage["start"]:passage["end"]] == passage["text"]
                    assert sha(passage["text"]) == passage["text_hash"]
                sources.append({k: source[k] for k in ["asset_version_id", "content_hash", "chapter", "text_hash", "status", "character_knowledge"]})
            rows.append({"chapter": content["chapter"], "operation_id": op, "memo_asset_version_id": memo["asset_version_id"], "memo_content_hash": memo["content_hash"], "source_intent_asset_version_id": sid, "source_intent_content_hash": intent["content_hash"], "model_call": "NOT_RUN", "enhancement_status": content["enhancement_status"], "working_sources": sources})
    report = {"status": "PASS", "evidence_class": "LOCAL_MEMO_FROZEN_INPUT_CONSUMPTION_READBACK", "input": Path(path).name, "input_file_sha256": "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest(), "source_sha": d["source_sha"], "identity": identity, "local_memos": len(rows), "working_source_occurrences": sum(len(x["working_sources"]) for x in rows), "rows": rows}
    out = Path(path).with_name(Path(path).name.removesuffix(".json.gz") + "-local-memo.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(out.name, len(rows), report["working_source_occurrences"])

if __name__ == "__main__":
    for path in sys.argv[1:]:
        verify(path)
