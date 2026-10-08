from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import sys

REPO = Path("/Users/yuan/.codex/worktrees/work-adaptation-reader-prose-01/novel-forge")
ORIGINAL = Path("/Volumes/DevSSD/Development/Data/novel-runtime/wp-qidian-learning-prose-01-20261008")
PROJECT = "qid-learning-prose-01"
BOOK = "book:qinglan-wendao-20261008"
FORMATION = "story-formation:0a8aa0c2dc447a252fad800a5a31b0663fd6f167087d18bfeb5a980a8afe261d"
EFFECT = "30421df5-8e89-46ab-8aff-ebb9cf3077c7"
sys.path.insert(0, str(REPO / "src"))
env = json.loads((ORIGINAL / "env-final.private.json").read_text())
os.environ.update(env)
os.environ["NOVEL_FORGE_NO_MODEL_DISPATCH"] = "1"
os.environ["NOVEL_FORGE_ROOT"] = str(REPO)
from psycopg.conninfo import make_conninfo
os.environ["NOVEL_FORGE_DATABASE_URL"] = make_conninfo(env["NOVEL_FORGE_DATABASE_URL"], connect_timeout=5, options="-c default_transaction_read_only=on")
from novel_forge.modules.production_execution.process_supervisor import CodexProcessSupervisor, PersistentExecutionDirectory
from novel_forge.modules.production_execution.membership_identity import observe_membership_identity
from novel_forge.cli.runtime_inspection import inspect_runtime
from novel_forge.modules.book_authority.creation_runtime import creation_status
from novel_forge.api.authority_dependencies import build_trusted_principal_resolver
result = {"project_id": PROJECT, "book_id": BOOK, "external_effect_id": EFFECT, "provider_dispatches": 0, "snapshot_fallback": False}
identity = observe_membership_identity(env["NOVEL_FORGE_CODEX_HOME"])
result["membership_matches_original"] = identity["account_ref"] == env["NOVEL_FORGE_CODEX_ACCOUNT_IDENTITY_REF"]
folder = next((ORIGINAL / "executions").glob("*30421df5*"))
receipt = json.loads((folder / "process-receipt.json").read_text())
if receipt["status"] != "FAILED":
    result["local_recovery"] = "Changed receipt; inspect its original evidence before any mutation"
else:
    before = hashlib.sha256((folder / "process-receipt.json").read_bytes()).hexdigest()
    recovered = CodexProcessSupervisor(PersistentExecutionDirectory(ORIGINAL / "executions")).recover(receipt["execution_id"])
    after = hashlib.sha256((folder / "process-receipt.json").read_bytes()).hexdigest()
    result["local_recovery"] = {"execution_id": receipt["execution_id"], "result_recoverable": recovered.result_recoverable, "process_status": recovered.receipt.status.value, "receipt_unchanged": before == after, "remote_outcome": "UNKNOWN", "usage": "UNKNOWN"}
try:
    import psycopg
    with psycopg.connect(os.environ["NOVEL_FORGE_DATABASE_URL"]) as connection:
        connection.execute("SELECT current_database()")
    principal = build_trusted_principal_resolver().resolve_api_principal()
    principal.require("book.authority.query", PROJECT)
    native = inspect_runtime(os.environ["NOVEL_FORGE_DATABASE_URL"], project_id=PROJECT, expected_database="nf_qidian_learning_20261008_test")
    if BOOK not in native["books"]:
        raise ValueError("Original Book is absent; stop without replacement")
    result["original_ledger"] = native
    result["creation"] = creation_status(os.environ["NOVEL_FORGE_DATABASE_URL"], project_id=PROJECT, formation_run_id=FORMATION, principal=principal)
except Exception as exc:
    result["original_ledger"] = {"status": "UNVERIFIED", "error_class": type(exc).__name__, "code": getattr(exc, "code", None)}
print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
