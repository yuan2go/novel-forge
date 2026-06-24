#!/usr/bin/env python3
"""Sync repository Skills into a Claude Code runtime skills directory.

The repository root `skills/` directory remains the source of truth.
The default target `.claude/skills/` is intended as generated runtime output.
"""

from __future__ import annotations

import argparse
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SyncPlan:
    source: Path
    target: Path
    copied: list[str]
    pruned: list[str]
    drifted: list[str]


def find_skill_dirs(skills_root: Path) -> dict[str, Path]:
    if not skills_root.is_dir():
        raise FileNotFoundError(f"skills directory not found: {skills_root}")

    skills: dict[str, Path] = {}
    for path in sorted(skills_root.iterdir()):
        if path.is_dir() and (path / "SKILL.md").exists():
            skills[path.name] = path
    return skills


def build_plan(root: Path, target: Path, prune: bool) -> SyncPlan:
    source_root = root / "skills"
    source_skills = find_skill_dirs(source_root)
    copied = sorted(source_skills)
    pruned: list[str] = []
    drifted: list[str] = []

    if target.exists():
        for name, source in source_skills.items():
            destination = target / name
            if not destination.exists() or not skill_dirs_match(source, destination):
                drifted.append(name)
    else:
        drifted = copied[:]

    if prune and target.exists():
        for path in sorted(target.iterdir()):
            if path.is_dir() and (path / "SKILL.md").exists() and path.name not in source_skills:
                pruned.append(path.name)

    return SyncPlan(source=source_root, target=target, copied=copied, pruned=pruned, drifted=drifted)


def skill_dirs_match(source: Path, target: Path) -> bool:
    source_files = sorted(path.relative_to(source) for path in source.rglob("*") if path.is_file())
    target_files = sorted(path.relative_to(target) for path in target.rglob("*") if path.is_file())
    if source_files != target_files:
        return False
    for relative_path in source_files:
        if (source / relative_path).read_bytes() != (target / relative_path).read_bytes():
            return False
    return True


def sync_skills(root: Path, target: Path, prune: bool, dry_run: bool) -> SyncPlan:
    plan = build_plan(root, target, prune)
    if dry_run:
        return plan

    target.mkdir(parents=True, exist_ok=True)
    source_skills = find_skill_dirs(plan.source)
    for name, source in source_skills.items():
        destination = target / name
        shutil.copytree(source, destination, dirs_exist_ok=True)

    for name in plan.pruned:
        shutil.rmtree(target / name)

    return plan


def print_plan(plan: SyncPlan, dry_run: bool) -> None:
    mode = "dry-run" if dry_run else "synced"
    print(f"{mode}: {plan.source} -> {plan.target}")
    for name in plan.copied:
        print(f"copy: {name}")
    for name in plan.pruned:
        print(f"prune: {name}")
    for name in plan.drifted:
        print(f"drift: {name}")


def check_skills(root: Path, target: Path, prune: bool) -> SyncPlan:
    plan = build_plan(root, target, prune)
    print(f"check: {plan.source} -> {plan.target}")
    for name in plan.drifted:
        print(f"drift: {name}")
    for name in plan.pruned:
        print(f"extra: {name}")
    if plan.drifted or plan.pruned:
        raise SystemExit(1)
    return plan


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync repository Skills to Claude Code runtime.")
    parser.add_argument("--root", default=".", help="Repository root. Default: current directory.")
    parser.add_argument("--target", default=".claude/skills", help="Runtime target path. Default: .claude/skills")
    parser.add_argument("--dry-run", action="store_true", help="Show planned operations without writing.")
    parser.add_argument("--prune", action="store_true", help="Remove target Skill dirs that no longer exist in source.")
    parser.add_argument("--check", action="store_true", help="Fail if runtime target differs from repository skills.")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    target = Path(args.target)
    if not target.is_absolute():
        target = root / target

    if args.check:
        check_skills(root=root, target=target, prune=args.prune)
        return 0

    plan = sync_skills(root=root, target=target, prune=args.prune, dry_run=args.dry_run)
    print_plan(plan, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
