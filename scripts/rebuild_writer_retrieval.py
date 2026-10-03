from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from novel_forge.modules.context_builder.retrieval_rebuild import apply_writer_index_rebuild, plan_writer_index_rebuild


def main() -> None:
    parser = argparse.ArgumentParser(description="Scoped Writer index rebuild; dry-run by default. No Provider calls.")
    parser.add_argument("--project-id")
    parser.add_argument("--book-id")
    parser.add_argument("--from-chapter", type=int)
    parser.add_argument("--to-chapter", type=int)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--after-id", default="")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    database_url = os.environ.get("NOVEL_FORGE_DATABASE_URL", "")
    if not database_url:
        parser.error("NOVEL_FORGE_DATABASE_URL is required")
    if args.rollback and not args.apply:
        parser.error("rollback requires --apply and an existing manifest")
    if args.apply:
        result = apply_writer_index_rebuild(database_url, json.loads(args.manifest.read_text()), rollback=args.rollback)
    else:
        if not args.project_id or not args.book_id or args.from_chapter is None or args.to_chapter is None:
            parser.error("dry-run requires Project, Book and explicit chapter bounds")
        if args.manifest.exists():
            parser.error("manifest already exists; use a new path or explicitly apply the frozen manifest")
        plan = plan_writer_index_rebuild(database_url, project_id=args.project_id, book_id=args.book_id,
                                        from_chapter=args.from_chapter, to_chapter=args.to_chapter, limit=args.limit, after_id=args.after_id)
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        with args.manifest.open("x") as file:
            json.dump(plan, file, ensure_ascii=False, indent=2)
            file.write("\n")
        args.manifest.chmod(0o600)
        result = {key: value for key, value in plan.items() if key != "entries"}
        result.update(mode="DRY_RUN", inspected=len(plan["entries"]), rebuild=sum(row["action"] == "REBUILD" for row in plan["entries"]))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
