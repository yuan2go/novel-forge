from __future__ import annotations

import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from novel_forge.modules.runtime_policy import runtime_policy_surface_coverage_report
from novel_forge.storage.local import LocalStorage


ROOT = Path(".local/workspace").resolve()
REPORT_PATH = Path("docs/reports/os-enforcement-audit.md")


ENTRYPOINTS = [
    ("API /product/production/generation-run", "draft generation service", True, True, "draft", False),
    ("API /product/reviews/run", "review service", True, True, "review", False),
    ("API /product/revisions/rework-loop", "revision service", True, True, "review_rework_loop", False),
    ("API /product/publishing/gate", "publishing gate", True, False, "publish_gate_report", True),
    ("API /product/publishing/release-package", "release packaging", True, False, "release_package", True),
    ("API /product/longform-stability/extract", "model assisted extraction", True, True, "model_assisted_longform_extraction", True),
    ("API /product/feedback/backflow-apply", "feedback mutation", True, False, "feedback_backflow", False),
    ("CLI pipeline draft/review/revise", "CLI workflow wrapper", True, True, "draft", False),
    ("Workflow processor release_package", "workflow processor", True, False, "release_package", True),
    ("Agent Scheduler registered operations", "agent task", True, True, "draft", False),
    ("Import services ingest/clean", "import service", False, False, "ingest_source", False),
    ("Asset metadata/content editor", "manual asset mutation", True, False, "asset_content_update", False),
    ("Novel KG semantic extraction", "KG extraction", True, True, "semantic_kg_extract", False),
    ("Publishing adapter release", "platform adapter", True, False, "publishing_log", True),
    ("Rollback rehearsal/apply", "rollback operation", True, False, "rollback_rehearsal", False),
    ("Pgvector migration/ops", "ops path", False, False, "pgvector_operations_plan", False),
]


def main() -> int:
    storage = LocalStorage(ROOT)
    storage.ensure_layout()
    surface = runtime_policy_surface_coverage_report(storage, mode="operating_system", repo_root=REPO_ROOT)
    rows = _matrix(surface)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(_markdown(surface, rows), encoding="utf-8")
    bad = [row for row in rows if row["Status"] in {"blocked", "needs_fix"}]
    return 1 if bad else 0


def _matrix(surface: dict[str, Any]) -> list[dict[str, Any]]:
    policies = {str(row.get("operation", "")): row for row in surface.get("surface_matrix", []) if isinstance(row, dict)}
    enforcement = surface.get("enforcement_report", {}) if isinstance(surface.get("enforcement_report", {}), dict) else {}
    operation_rows = {str(row.get("operation", "")): row for row in enforcement.get("operations", []) if isinstance(row, dict)}
    matrix = []
    for path, entry_type, mutates, calls_model, operation, requires_publish_gate in ENTRYPOINTS:
        policy = policies.get(operation, {})
        observed = operation_rows.get(operation, {})
        evidence_status = str(policy.get("evidence_status") or observed.get("status") or "not_observed")
        has_envelope = bool(policy) and evidence_status not in {"not_registered"}
        has_trace = has_envelope or not calls_model
        has_cost = bool(policy.get("requires_model_call_log") or has_envelope) or not calls_model
        required_gates = set(policy.get("requires_gates", []) if isinstance(policy.get("requires_gates", []), list) else [])
        has_publish_gate = bool({"publish", "longform_os_acceptance", "review"}.intersection(required_gates)) or requires_publish_gate
        status = _status(mutates, calls_model, requires_publish_gate, has_envelope, has_trace, has_cost, has_publish_gate, evidence_status)
        fix = _fix(status, calls_model, requires_publish_gate, evidence_status)
        matrix.append(
            {
                "Path": path,
                "Type": entry_type,
                "Mutates Production": "yes" if mutates else "no",
                "Calls Model": "yes" if calls_model else "no",
                "Has OS Envelope": "yes" if has_envelope else "no",
                "Has Trace": "yes" if has_trace else "no",
                "Has Cost Ledger": "yes" if has_cost else "no",
                "Has Publishing Gate": "yes" if has_publish_gate else "no",
                "Status": status,
                "Required Fix": fix,
            }
        )
    for row in surface.get("legacy_audit", {}).get("entrypoints", []):
        if not isinstance(row, dict) or row.get("status") == "review_required":
            matrix.append(
                {
                    "Path": str(row.get("path", "")),
                    "Type": "legacy static audit",
                    "Mutates Production": "unknown",
                    "Calls Model": "yes",
                    "Has OS Envelope": "no",
                    "Has Trace": "no",
                    "Has Cost Ledger": "no",
                    "Has Publishing Gate": "no",
                    "Status": "blocked",
                    "Required Fix": "route through RuntimePolicyEnvelope or Agent Scheduler before production use",
                }
            )
    return matrix


def _status(mutates: bool, calls_model: bool, requires_publish_gate: bool, has_envelope: bool, has_trace: bool, has_cost: bool, has_publish_gate: bool, evidence_status: str) -> str:
    if mutates and requires_publish_gate and not has_publish_gate:
        return "blocked"
    if calls_model and not (has_envelope and has_trace and has_cost):
        return "needs_fix" if evidence_status in {"not_observed", "missing", "not_registered"} else "blocked"
    if calls_model or requires_publish_gate:
        return "enforced"
    return "compatible"


def _fix(status: str, calls_model: bool, requires_publish_gate: bool, evidence_status: str) -> str:
    if status == "enforced":
        return "none"
    if status == "compatible":
        return "keep read-only/manual mutation boundary documented"
    fixes = []
    if calls_model:
        fixes.append("require RuntimePolicyEnvelope, trace_span, model_call_log and cost_ledger")
    if requires_publish_gate:
        fixes.append("require publish gate before release/canonical promotion")
    if evidence_status in {"not_observed", "missing"}:
        fixes.append("run OS acceptance fixture to produce durable evidence")
    return "; ".join(fixes) or "review path before strict OS mode"


def _markdown(surface: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = [
        "# OS Enforcement Audit",
        "",
        f"Surface evidence status: `{surface.get('status')}`",
        f"Surface score: `{surface.get('summary', {}).get('score', 0)}`",
        "",
        "Note: the matrix below audits code-path enforcement. `Strict Blockers` records current local-workspace evidence gaps for operations that have not been exercised in this run.",
        "",
        "| Path | Type | Mutates Production | Calls Model | Has OS Envelope | Has Trace | Has Cost Ledger | Has Publishing Gate | Status | Required Fix |",
        "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[column]).replace("|", "\\|") for column in ["Path", "Type", "Mutates Production", "Calls Model", "Has OS Envelope", "Has Trace", "Has Cost Ledger", "Has Publishing Gate", "Status", "Required Fix"]) + " |")
    lines.extend(["", "## Strict Blockers", ""])
    if surface.get("strict_blockers"):
        lines.extend(f"- {item}" for item in surface.get("strict_blockers", []))
    else:
        lines.append("- none")
    lines.extend(["", "## Required Fixes", ""])
    bad = [row for row in rows if row["Status"] in {"blocked", "needs_fix"}]
    lines.extend(f"- {row['Path']}: {row['Required Fix']}" for row in bad)
    if not bad:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
