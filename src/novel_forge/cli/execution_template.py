from __future__ import annotations

from pathlib import Path
from typing import Any


def add_execution_template_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-execution-template", help="bind a configured execution template to new Book work")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--book-id", required=True)
    parser.add_argument("--policy-version", required=True)
    parser.add_argument("--idempotency-key", required=True)
    parser.add_argument("--template-file", type=Path, default=Path("config/execution_templates/creative_validation.json"))


def run_execution_template_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.modules.production_execution.execution_template import configure_execution_template
    return configure_execution_template(settings, args)
