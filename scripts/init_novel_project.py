#!/usr/bin/env python3
"""Initialize a NovelForge single-novel workspace.

V1 scope: create a file-based project skeleton from built-in templates.
No external API calls. No secrets. Standard library only.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_WORKSPACE_DIR = "04_novel_projects"

PROJECT_DIRS = [
    "project_knowledge_pack",
    "00_project_gate",
    "01_bible",
    "02_outline/chapter_plans",
    "03_chapters/ch001",
    "04_reviews/ch001",
    "05_feedback",
    "06_memory",
    "07_style",
    "08_tasks/task_cards",
    "09_reports",
]

PROJECT_FILES = {
    "PROJECT.md": "# {title}\n\n类型：{genre}\n\n项目 ID：{project_id}\n\n## 当前状态\n\ncreated\n",
    "CLAUDE.md": "# CLAUDE.md\n\n本项目为 NovelForge 单本小说 workspace。执行任务前必须读取 `project_constitution.md`、`PROJECT.md` 和相关 task card。\n",
    "project_constitution.md": "templates/project_constitution.md",
    "00_project_gate/reader_attraction_gate.md": "templates/reader_attraction_gate.md",
    "00_project_gate/project_differentiation_gate.md": "templates/project_differentiation_gate.md",
    "08_tasks/task_cards/task_001.md": "templates/task_card.md",
    "02_outline/chapter_plans/ch001_plan.md": "templates/chapter_plan.md",
    "04_reviews/ch001/final_review.md": "templates/review_report.md",
    "06_memory/current_context.md": "# Current Context\n\n待补充。\n",
    "06_memory/decision_log.md": "# Decision Log\n\n待记录。\n",
    "09_reports/project_takeover_report.md": "# Project Takeover Report\n\n待生成。\n",
}


@dataclass(frozen=True)
class ProjectPlan:
    project_root: Path
    directories: list[str]
    files: list[str]


def render_text(text: str, project_id: str, title: str, genre: str) -> str:
    return text.format(project_id=project_id, title=title, genre=genre)


def copy_or_render(
    repo_root: Path,
    source_or_text: str,
    destination: Path,
    project_id: str,
    title: str,
    genre: str,
) -> None:
    candidate = repo_root / source_or_text
    if candidate.exists():
        content = candidate.read_text(encoding="utf-8")
    else:
        content = source_or_text
    destination.write_text(render_text(content, project_id, title, genre), encoding="utf-8")


def build_project_plan(repo_root: Path, project_id: str) -> ProjectPlan:
    project_root = repo_root / DEFAULT_WORKSPACE_DIR / project_id
    return ProjectPlan(
        project_root=project_root,
        directories=PROJECT_DIRS,
        files=list(PROJECT_FILES),
    )


def format_dry_run(plan: ProjectPlan, force: bool) -> str:
    lines = [
        "NovelForge project initialization dry run.",
        f"Project root: {plan.project_root}",
    ]
    if plan.project_root.exists():
        if force:
            lines.append("Existing project detected: would remove existing project directory because --force is set.")
        else:
            lines.append("Existing project detected: initialization would fail without --force.")
    else:
        lines.append("Existing project detected: no.")

    lines.append("Directories to create:")
    lines.extend(f"- {item}" for item in plan.directories)
    lines.append("Files to write:")
    lines.extend(f"- {item}" for item in plan.files)
    return "\n".join(lines)


def init_project(repo_root: Path, project_id: str, title: str, genre: str, force: bool) -> Path:
    plan = build_project_plan(repo_root, project_id)
    project_root = plan.project_root
    if project_root.exists() and not force:
        raise FileExistsError(f"Project already exists: {project_root}. Use --force to overwrite.")
    if project_root.exists() and force:
        shutil.rmtree(project_root)

    for relative_dir in plan.directories:
        (project_root / relative_dir).mkdir(parents=True, exist_ok=True)

    for relative_path, source_or_text in PROJECT_FILES.items():
        destination = project_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        copy_or_render(repo_root, source_or_text, destination, project_id, title, genre)

    return project_root


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize a NovelForge novel project workspace.")
    parser.add_argument("--project-id", required=True, help="Project slug, e.g. project_001_black_archive.")
    parser.add_argument("--title", required=True, help="Novel title.")
    parser.add_argument("--genre", default="未分类", help="Novel genre.")
    parser.add_argument("--root", default=".", help="Repository root path.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing project directory.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the planned project structure without creating, overwriting, or deleting files.",
    )
    args = parser.parse_args()

    repo_root = Path(args.root).resolve()
    if args.dry_run:
        plan = build_project_plan(repo_root, args.project_id)
        print(format_dry_run(plan, args.force))
        return 0

    try:
        project_root = init_project(repo_root, args.project_id, args.title, args.genre, args.force)
    except Exception as exc:  # noqa: BLE001 - command line script should print clear error
        print(f"Failed to initialize project: {exc}", file=sys.stderr)
        return 1

    print(f"Initialized NovelForge project: {project_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
