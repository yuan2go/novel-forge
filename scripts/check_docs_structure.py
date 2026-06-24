#!/usr/bin/env python3
"""Check NovelForge repository structure.

This script intentionally uses only the Python standard library.
It validates that required docs, templates, schemas, progress files, and
top-level files exist.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_FILES = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "PROJECT_STATE.md",
    "CURRENT_GOAL.md",
    "DECISIONS.md",
    "ROADMAP.md",
    "CHANGELOG.md",
    ".env.example",
    ".gitignore",
    "pyproject.toml",
    "Makefile",
]

ROOT_DIRS = [
    "docs",
    "skills",
    "templates",
    "scripts",
    "tests",
    "tasks",
    "schemas",
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
    "novel-forge-v4-final.md",
]

AI_WORKFLOW_FILES = [
    "README.md",
    "codex-task-template.md",
    "acceptance-criteria.md",
    "skill-usage.md",
]

ARCHITECTURE_FILES = [
    "v4-minimum-structure.md",
    "skills-system.md",
]

SKILLS_DOC_FILES = [
    "README.md",
    "agent-skill-map.md",
]

AUDIT_FILES = [
    "v4-business-audit.md",
    "v4-module-matrix.md",
    "v4-risk-register.md",
    "v4-next-actions.md",
]

PROGRESS_FILES = [
    "v4-goal-pool.md",
    "v4-test-log.md",
    "v4-loop-report.md",
    "v4-open-issues.md",
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

TASK_FILES = [
    "README.md",
    "backlog.md",
    "task-template.md",
]

SCRIPT_FILES = [
    "check_docs_structure.py",
    "init_novel_project.py",
]

SCHEMA_FILES = [
    "material.schema.json",
    "dissection.schema.json",
    "topic.schema.json",
    "chapter_plan.schema.json",
    "review.schema.json",
]

SKILL_NAMES = [
    "hot-novel-deconstruction",
    "anti-copy-abstraction",
    "character-design",
    "worldbuilding",
    "long-outline",
    "chapter-outline",
    "prose-generation",
    "quality-review",
]

SKILL_REQUIRED_SECTIONS = [
    "## 适用场景",
    "## 输入要求",
    "## 操作流程",
    "## 输出格式",
    "## 质量标准",
    "## 禁止事项",
    "## 与其他模块的关系",
]


def check_paths(root: Path, paths: list[str]) -> list[str]:
    missing: list[str] = []
    for item in paths:
        if not (root / item).exists():
            missing.append(item)
    return missing


def check_dirs(root: Path, paths: list[str]) -> list[str]:
    missing: list[str] = []
    for item in paths:
        if not (root / item).is_dir():
            missing.append(item)
    return missing


def check_json_schema_files(root: Path, paths: list[str]) -> list[str]:
    failures: list[str] = []
    for item in paths:
        path = root / item
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{item} is not valid JSON: {exc}")
            continue
        except OSError as exc:
            failures.append(f"{item} cannot be read: {exc}")
            continue

        if not isinstance(schema, dict):
            failures.append(f"{item} must be a JSON object")
            continue

        for required_key in ("$schema", "$id", "title", "type", "properties", "required"):
            if required_key not in schema:
                failures.append(f"{item} missing required schema key: {required_key}")

        if schema.get("type") != "object":
            failures.append(f"{item} must define top-level type object")
        if not isinstance(schema.get("properties"), dict):
            failures.append(f"{item} properties must be an object")
        if not isinstance(schema.get("required"), list):
            failures.append(f"{item} required must be a list")

    return failures


def check_skill_files(root: Path, skill_names: list[str]) -> list[str]:
    failures: list[str] = []
    for skill_name in skill_names:
        relative_path = Path(skill_name) / "SKILL.md"
        path = root / relative_path
        if not path.exists():
            failures.append(f"{relative_path} missing")
            continue

        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            failures.append(f"{relative_path} cannot be read: {exc}")
            continue

        lines = text.splitlines()
        if len(lines) < 5 or lines[0].strip() != "---":
            failures.append(f"{relative_path} missing YAML frontmatter start")
            continue
        try:
            frontmatter_end = lines[1:].index("---") + 1
        except ValueError:
            failures.append(f"{relative_path} missing YAML frontmatter end")
            continue

        frontmatter = "\n".join(lines[1:frontmatter_end])
        if f"name: {skill_name}" not in frontmatter:
            failures.append(f"{relative_path} frontmatter missing name: {skill_name}")
        if "description:" not in frontmatter:
            failures.append(f"{relative_path} frontmatter missing description")

        for section in SKILL_REQUIRED_SECTIONS:
            if section not in text:
                failures.append(f"{relative_path} missing required section: {section}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Check NovelForge repository structure.")
    parser.add_argument("--root", default=".", help="Repository root path. Default: current directory.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    failures: list[str] = []

    failures.extend(check_paths(root, ROOT_FILES))
    failures.extend([f"{p}/" for p in check_dirs(root, ROOT_DIRS)])
    failures.extend([f"docs/{p}" for p in check_paths(root / "docs", DOC_FILES)])
    failures.extend([f"docs/ai-workflow/{p}" for p in check_paths(root / "docs" / "ai-workflow", AI_WORKFLOW_FILES)])
    failures.extend([f"docs/architecture/{p}" for p in check_paths(root / "docs" / "architecture", ARCHITECTURE_FILES)])
    failures.extend([f"docs/skills/{p}" for p in check_paths(root / "docs" / "skills", SKILLS_DOC_FILES)])
    failures.extend([f"docs/audits/{p}" for p in check_paths(root / "docs" / "audits", AUDIT_FILES)])
    failures.extend([f"docs/progress/{p}" for p in check_paths(root / "docs" / "progress", PROGRESS_FILES)])
    failures.extend([f"templates/{p}" for p in check_paths(root / "templates", TEMPLATE_FILES)])
    failures.extend([f"tasks/{p}" for p in check_paths(root / "tasks", TASK_FILES)])
    failures.extend([f"scripts/{p}" for p in check_paths(root / "scripts", SCRIPT_FILES)])
    failures.extend([f"schemas/{p}" for p in check_paths(root / "schemas", SCHEMA_FILES)])

    schema_failures = check_json_schema_files(root / "schemas", SCHEMA_FILES)
    failures.extend([f"schemas/{p}" for p in schema_failures])

    skill_failures = check_skill_files(root / "skills", SKILL_NAMES)
    failures.extend([f"skills/{p}" for p in skill_failures])

    if failures:
        print("NovelForge structure check failed. Missing files:", file=sys.stderr)
        for item in failures:
            print(f"- {item}", file=sys.stderr)
        return 1

    print("NovelForge structure check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
