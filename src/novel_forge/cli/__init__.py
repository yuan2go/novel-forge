from __future__ import annotations

import argparse
import sys
from pathlib import Path

from novel_forge.storage.local import LocalStorage
from novel_forge.workflows import pipeline


def add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=".", help="project root; default: current directory")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="novel-forge", description="Novel Forge V5 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="initialize local project directories")
    add_root(init_p)

    ingest_p = sub.add_parser("ingest", help="import a source text file into data/raw")
    ingest_p.add_argument("input")
    ingest_p.add_argument("--title")
    add_root(ingest_p)

    for name, help_text in [
        ("clean", "clean latest or selected raw source"),
        ("decompose", "extract abstract narrative/commercial patterns"),
        ("extract-knowledge", "turn decomposition into knowledge card"),
        ("build-materials", "turn knowledge card into reusable material"),
        ("generate-topic", "generate topic seed"),
        ("generate-world", "generate world bible"),
        ("generate-characters", "generate character card"),
        ("generate-outline", "generate outline"),
        ("generate-chapter-plan", "generate chapter plan"),
        ("draft", "generate mock draft chapter"),
        ("review", "review draft chapter"),
        ("revise", "create revision plan"),
        ("analyze-feedback", "analyze imported reader feedback"),
    ]:
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--input")
        add_root(command)

    fb_p = sub.add_parser("import-feedback", help="import reader feedback CSV")
    fb_p.add_argument("input")
    add_root(fb_p)

    run_p = sub.add_parser("run-pipeline", help="run end-to-end workflow")
    run_p.add_argument("--sample", action="store_true")
    add_root(run_p)

    status_p = sub.add_parser("status", help="show local asset counts")
    add_root(status_p)

    validate_p = sub.add_parser("validate", help="validate project structure and JSON assets")
    add_root(validate_p)

    return parser


def _print_path(path: Path) -> None:
    print(path)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            storage = pipeline.ensure_project(args.root)
            print(f"initialized: {storage.root}")
            return 0
        if args.command == "ingest":
            _print_path(pipeline.ingest(args.root, args.input, args.title))
            return 0
        if args.command == "clean":
            _print_path(pipeline.clean(args.root, args.input))
            return 0
        if args.command == "decompose":
            _print_path(pipeline.decompose(args.root, args.input))
            return 0
        if args.command == "extract-knowledge":
            _print_path(pipeline.extract_knowledge(args.root, args.input))
            return 0
        if args.command == "build-materials":
            _print_path(pipeline.build_materials(args.root, args.input))
            return 0
        if args.command == "generate-topic":
            _print_path(pipeline.generate_topic(args.root, args.input))
            return 0
        if args.command == "generate-world":
            _print_path(pipeline.generate_world(args.root, args.input))
            return 0
        if args.command == "generate-characters":
            _print_path(pipeline.generate_characters(args.root, args.input))
            return 0
        if args.command == "generate-outline":
            _print_path(pipeline.generate_outline(args.root, args.input))
            return 0
        if args.command == "generate-chapter-plan":
            _print_path(pipeline.generate_chapter_plan(args.root, args.input))
            return 0
        if args.command == "draft":
            _print_path(pipeline.draft(args.root, args.input))
            return 0
        if args.command == "review":
            _print_path(pipeline.review(args.root, args.input))
            return 0
        if args.command == "revise":
            _print_path(pipeline.revise(args.root, args.input))
            return 0
        if args.command == "import-feedback":
            _print_path(pipeline.import_feedback(args.root, args.input))
            return 0
        if args.command == "analyze-feedback":
            _print_path(pipeline.analyze_feedback(args.root, args.input))
            return 0
        if args.command == "run-pipeline":
            _print_path(pipeline.run_pipeline(args.root, args.sample))
            return 0
        if args.command == "status":
            storage = pipeline.ensure_project(args.root)
            for category, count in storage.counts().items():
                print(f"{category}: {count}")
            return 0
        if args.command == "validate":
            ok, errors = pipeline.validate_project(args.root)
            if ok:
                print("validation passed")
                return 0
            for error in errors:
                print(f"validation error: {error}", file=sys.stderr)
            return 1
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    parser.print_help()
    return 2
