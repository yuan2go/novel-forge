from __future__ import annotations

import argparse
import json
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

    ingest_p = sub.add_parser("ingest", help="import a source file or directory into data/raw")
    ingest_p.add_argument("input")
    ingest_p.add_argument("--title")
    add_root(ingest_p)

    for name, help_text in [
        ("clean", "clean latest or selected raw source"),
        ("decompose", "extract abstract narrative/commercial patterns"),
        ("extract-knowledge", "turn decomposition into knowledge card"),
        ("build-materials", "turn knowledge card into reusable material"),
        ("generate-topic", "generate topic seed"),
        ("topic-development", "develop a differentiated schema-backed topic seed"),
        ("training-exercise", "generate a schema-backed writing training exercise"),
        ("generate-world", "generate world bible"),
        ("generate-characters", "generate character card"),
        ("generate-outline", "generate outline"),
        ("generate-chapter-plan", "generate chapter plan"),
        ("draft", "generate mock draft chapter"),
        ("review", "review draft chapter"),
        ("compare-reviews", "compare draft reviews across local mock reviewers"),
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

    search_p = sub.add_parser("search", help="list and filter local JSON assets")
    search_p.add_argument("--category", help="data category, for example materials or drafts")
    search_p.add_argument("--type", dest="asset_type", help="asset type, for example material_card")
    search_p.add_argument("--tag", action="append", default=[], help="required tag; can be repeated")
    search_p.add_argument("--keyword", help="keyword searched in title, tags, content, and metadata")
    search_p.add_argument("--limit", type=int, default=50)
    search_p.add_argument("--rank", choices=["path", "relevance"], default="path")
    search_p.add_argument("--rebuild-index", action="store_true", help="rebuild local retrieval index before search")
    search_p.add_argument("--no-index", action="store_true", help="use direct JSON scan instead of retrieval index")
    add_root(search_p)

    index_p = sub.add_parser("build-index", help="build local retrieval index for JSON assets")
    add_root(index_p)

    vector_index_p = sub.add_parser("build-vector-index", help="build local hash-vector index for JSON assets")
    add_root(vector_index_p)

    vector_search_p = sub.add_parser("vector-search", help="rank local JSON assets with hash-vector similarity")
    vector_search_p.add_argument("--query", required=True)
    vector_search_p.add_argument("--category", help="data category, for example materials or drafts")
    vector_search_p.add_argument("--type", dest="asset_type", help="asset type, for example material_card")
    vector_search_p.add_argument("--tag", action="append", default=[], help="required tag; can be repeated")
    vector_search_p.add_argument("--limit", type=int, default=50)
    vector_search_p.add_argument("--rebuild-index", action="store_true", help="rebuild local vector index before search")
    add_root(vector_search_p)

    workspace_init_p = sub.add_parser("init-workspace", help="initialize long-project workspace state")
    workspace_init_p.add_argument("--title", default="Sample Novel Workspace")
    add_root(workspace_init_p)

    workspace_update_p = sub.add_parser("update-workspace", help="update workspace state from a draft or review asset")
    workspace_update_p.add_argument("--input")
    workspace_update_p.add_argument("--workspace")
    workspace_update_p.add_argument("--chapter", type=int)
    workspace_update_p.add_argument("--status", default="drafted")
    add_root(workspace_update_p)

    workspace_status_p = sub.add_parser("workspace-status", help="show current workspace state summary")
    workspace_status_p.add_argument("--workspace")
    add_root(workspace_status_p)

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
            paths = pipeline.ingest_many(args.root, args.input, args.title)
            for path in paths:
                _print_path(path)
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
        if args.command == "topic-development":
            _print_path(pipeline.develop_topic(args.root, args.input))
            return 0
        if args.command == "training-exercise":
            _print_path(pipeline.generate_training_exercise(args.root, args.input))
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
        if args.command == "compare-reviews":
            _print_path(pipeline.compare_reviews(args.root, args.input))
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
        if args.command == "search":
            results = pipeline.search_assets(
                args.root,
                category=args.category,
                asset_type=args.asset_type,
                tags=args.tag,
                keyword=args.keyword,
                limit=args.limit,
                use_index=not args.no_index,
                rebuild_index=args.rebuild_index,
                rank=args.rank,
            )
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 0
        if args.command == "build-index":
            _print_path(pipeline.build_retrieval_index(args.root))
            return 0
        if args.command == "build-vector-index":
            _print_path(pipeline.build_vector_index(args.root))
            return 0
        if args.command == "vector-search":
            results = pipeline.vector_search_assets(
                args.root,
                query=args.query,
                category=args.category,
                asset_type=args.asset_type,
                tags=args.tag,
                limit=args.limit,
                rebuild_index=args.rebuild_index,
            )
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 0
        if args.command == "init-workspace":
            _print_path(pipeline.init_workspace(args.root, args.title))
            return 0
        if args.command == "update-workspace":
            _print_path(
                pipeline.update_workspace(
                    args.root,
                    input_path=args.input,
                    workspace_path=args.workspace,
                    chapter=args.chapter,
                    status=args.status,
                )
            )
            return 0
        if args.command == "workspace-status":
            print(json.dumps(pipeline.workspace_status(args.root, args.workspace), ensure_ascii=False, indent=2))
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
