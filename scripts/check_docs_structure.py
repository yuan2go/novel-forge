#!/usr/bin/env python3
"""Check NovelForge V1 repository structure.

This script intentionally uses only the Python standard library.
It validates that required docs, templates, and top-level files exist.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_FILES = [
    "README.md",
    "AGENTS.md",
    "ROADMAP.md",
    "CHANGELOG.md",
    ".env.example",
    ".gitignore",
    "pyproject.toml",
    "Makefile",
]

DOC_FILES = [
    "00_overview.md",
    "01_architecture.md",
    "02_global_assets.md",
    "03_world_lab.md",
    "04_project_incubation.md",
    "05_reader_attraction_gate.md",
    "06_project_differentiation_gate.md",
    "07_knowledge_compiler.md",
    "08_project_constitution.md",
    "09_novel_workspace.md",
    "10_claude_code_execution.md",
    "11_writing_pipeline.md",
    "12_review_system.md",
    "13_feedback_control.md",
    "14_multi_project_scheduler.md",
    "15_model_routing.md",
    "16_risk_control.md",
    "17_mvp_roadmap.md",
    "18_templates.md",
]

TEMPLATE_FILES = [
    "project_constitution.md",
    "reader_attraction_gate.md",
    "project_differentiation_gate.md",
    "task_card.md",
    "chapter_plan.md",
    "review_report.md",
    "project_registry.md",
]

SCRIPT_FILES = [
    "check_docs_structure.py",
    "init_novel_project.py",
]


def check_paths(root: Path, paths: list[str]) -> list[str]:
    missing: list[str] = []
    for item in paths:
        if not (root / item).exists():
            missing.append(item)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Check NovelForge repository structure.")
    parser.add_argument("--root", default=".", help="Repository root path. Default: current directory.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    failures: list[str] = []

    failures.extend(check_paths(root, ROOT_FILES))
    failures.extend([f"docs/{p}" for p in check_paths(root / "docs", DOC_FILES)])
    failures.extend([f"templates/{p}" for p in check_paths(root / "templates", TEMPLATE_FILES)])
    failures.extend([f"scripts/{p}" for p in check_paths(root / "scripts", SCRIPT_FILES)])

    if failures:
        print("NovelForge structure check failed. Missing files:", file=sys.stderr)
        for item in failures:
            print(f"- {item}", file=sys.stderr)
        return 1

    print("NovelForge structure check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
