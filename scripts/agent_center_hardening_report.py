from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from novel_forge.modules.agent_scheduler import agent_center_snapshot
from novel_forge.storage.local import LocalStorage


ROOT = Path(".local/provider-hard-stop-proof").resolve()
REPORT_PATH = Path("docs/reports/agent-center-hardening-report.md")


def main() -> int:
    storage = LocalStorage(ROOT)
    storage.ensure_layout()
    snapshot = agent_center_snapshot(storage)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(_markdown(snapshot), encoding="utf-8")
    required = [
        "run_graph",
        "gate_timeline",
        "checkpoints",
        "budget_burn",
        "retry_controls",
        "dead_letter_queue",
        "rollback_preview",
        "sla_duration",
        "evidence_drawer",
        "operation_coverage",
    ]
    return 0 if all(key in snapshot for key in required) else 1


def _markdown(snapshot: dict) -> str:
    checks = snapshot.get("readiness_checks", []) if isinstance(snapshot.get("readiness_checks", []), list) else []
    summary = snapshot.get("summary", {}) if isinstance(snapshot.get("summary", {}), dict) else {}
    lines = [
        "# Agent Center Hardening Report",
        "",
        f"Status: `{snapshot.get('status')}`",
        f"Health score: `{snapshot.get('health_score', summary.get('health_score', 0))}`",
        "",
        "| Capability | Present | Evidence Count / Status |",
        "|---|---:|---|",
        f"| run graph | yes | {len(snapshot.get('run_graph', {}).get('nodes', []))} nodes |",
        f"| gate timeline | yes | {len(snapshot.get('gate_timeline', []))} rows |",
        f"| checkpoint list | yes | {len(snapshot.get('checkpoints', []))} rows |",
        f"| budget burn | yes | {json.dumps(snapshot.get('budget_burn', {}), ensure_ascii=False)} |",
        f"| retry controls | yes | {len(snapshot.get('retry_controls', []))} rows |",
        f"| dead-letter queue | yes | {len(snapshot.get('dead_letter_queue', []))} rows |",
        f"| rollback preview | yes | {len(snapshot.get('rollback_preview', []))} rows |",
        f"| SLA / duration tracking | yes | {len(snapshot.get('sla_duration', []))} rows |",
        f"| evidence drawer | yes | {len(snapshot.get('evidence_drawer', []))} rows |",
        f"| operation coverage | yes | {len(snapshot.get('operation_coverage', []))} contracts |",
        "",
        "## Readiness Checks",
        "",
    ]
    if checks:
        lines.extend(f"- {row.get('key')}: {row.get('status')} - {row.get('message') or row.get('recommendation')}" for row in checks)
    else:
        lines.append("- no checks available")
    lines.extend(
        [
            "",
            "## Recommendations",
            "",
        ]
    )
    recommendations = snapshot.get("recommendations", []) or snapshot.get("recommended_actions", [])
    if recommendations:
        lines.extend(f"- {item}" for item in recommendations)
    else:
        lines.append("- none")
    lines.extend(["", "## Snapshot Summary", "", "```json", json.dumps(summary, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
