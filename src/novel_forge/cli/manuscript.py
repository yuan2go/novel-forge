from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def add_manuscript_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-manuscript", help="read, edit, compare, adopt or export the current work")
    parser.add_argument("action", choices=("read", "export", "edit", "diff", "adopt", "reject", "adopt-author-workflow", "pause", "resume", "continue"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--book-run-id", required=True)
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--text-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--candidate-version", default="")
    parser.add_argument("--versions", nargs="+")
    parser.add_argument("--chapters", nargs="+", type=int)
    parser.add_argument("--reason", default="")


def run_manuscript_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver
    from novel_forge.modules.book_authority.manuscript import require_manuscript
    from novel_forge.modules.chapter_authority.author_editor import ChapterAuthorEditingApplication, edit_map
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    principal = build_trusted_principal_resolver().resolve_api_principal()
    if args.action in {"adopt-author-workflow", "pause", "resume", "continue"}:
        from novel_forge.modules.book_authority.production import PostgresBookAuthority
        from novel_forge.modules.book_followup_authority.application import BookFollowupAuthorityApplication
        from novel_forge.modules.book_authority.manuscript import adopt_author_workflow
        build_id, sha = authority_release_identity()
        followup = BookFollowupAuthorityApplication(settings.database_url, application_build_id=build_id, commit_sha=sha)
        authority = PostgresBookAuthority(settings.database_url, chapter_port=None, followup_application=followup, application_build_id=build_id, commit_sha=sha)
        book = authority.require(args.book_run_id)
        if book["project_id"] != args.project_id:
            raise PermissionError("Work is outside this Project")
        if args.action in {"pause", "resume"}:
            return getattr(authority, args.action)(args.book_run_id, reason=args.reason or "Author " + args.action, principal=principal)
        if args.action == "continue":
            from novel_forge.storage.authority_uow import AuthorityUnitOfWork
            with AuthorityUnitOfWork(settings.database_url) as uow:
                uow.cursor.execute("SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s AND formation_run_id || ':production'=%s", [args.project_id, book["book_id"], book["stable_idempotency_key"]])
                original = uow.cursor.fetchone()
            if original is None:
                raise ValueError("This historical work requires its native Book worker or a traceable Formation successor")
            from novel_forge.cli.authority import _authority_parser
            from novel_forge.cli.creation import run_creation_command
            request = _authority_parser().parse_args(["authority-creation", "continue", "--project-id", args.project_id,
                "--formation-run-id", original[0], "--repository-root", str(Path(__file__).resolve().parents[3])])
            return run_creation_command(settings, request)
        return adopt_author_workflow(authority, args.book_run_id, principal=principal, expected_version=None, settings=settings,
            idempotency_key="author-workflow:" + canonical_hash({"book": args.book_run_id, "profile": book["production_profile_version"]}))
    manifest = require_manuscript(settings.database_url, project_id=args.project_id, book_run_id=args.book_run_id,
        principal=principal, version_ids=args.versions, chapters=args.chapters)
    if args.action == "read":
        return manifest
    if args.action == "export":
        if not manifest["units"]:
            raise ValueError("No complete saved prose is available")
        exact = require_manuscript(settings.database_url, project_id=args.project_id, book_run_id=args.book_run_id,
            principal=principal, version_ids=[item["asset_version_id"] for item in manifest["units"]], chapters=args.chapters)
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(exact, ensure_ascii=False, indent=2))
        return exact
    unit = next((item for item in manifest["units"] if item["chapter"] == args.chapter), None)
    if unit is None:
        raise ValueError("Choose a saved chapter")
    build_id, sha = authority_release_identity()
    application = ChapterAuthorEditingApplication(settings.database_url, application_build_id=build_id, commit_sha=sha)
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork
    with AuthorityUnitOfWork(settings.database_url) as uow:
        uow.cursor.execute("SELECT workspace_id FROM authority_book_production WHERE book_run_id=%s AND project_id=%s", [args.book_run_id, args.project_id])
        workspace = uow.cursor.fetchone()[0]
    scope = dict(project_id=args.project_id, workspace_id=workspace, book_id=manifest["book_id"],
        chapter=args.chapter, base_asset_version_id=unit["asset_version_id"])
    state = application.require(**scope, principal=principal)
    if args.action == "diff":
        return {"chapter": args.chapter, "selected_asset_version_id": unit["asset_version_id"],
            "candidates": state["candidates"], "decisions": state["decisions"]}
    text = args.text_file.read_text() if args.text_file else None
    body = {**scope, "base_asset_hash": unit["content_hash"], "base_text_hash": unit["text_hash"],
        "expected_version": state["version"], "rationale": args.reason}
    action = {"edit": "save", "adopt": "accept", "reject": "reject"}[args.action]
    if action == "save":
        if text is None:
            raise ValueError("Editing requires --text-file; the original remains protected")
        body.update(text=text, rights_basis="ORIGINAL_AUTHOR_INPUT",
            allowed_ranges=[{"start": item["start"], "end": item["end"]} for item in edit_map(unit["text"], text)])
    else:
        if not args.candidate_version:
            raise ValueError("Choose the exact candidate version from the diff")
        body["candidate_asset_version_id"] = args.candidate_version
    intent = {key: value for key, value in body.items() if key != "expected_version"}
    if action != "save":
        for key in ("base_asset_version_id", "base_asset_hash", "base_text_hash"):
            intent.pop(key, None)
    key = "author-manuscript:" + canonical_hash({"action": action, "actor_id": principal.principal_id, **intent})
    with AuthorityUnitOfWork(settings.database_url) as uow:
        uow.cursor.execute("""SELECT command_payload FROM authority_operation
            WHERE project_id=%s AND idempotency_scope='chapter:author-edit' AND idempotency_key=%s AND actor_id=%s""",
            [args.project_id, key, principal.principal_id])
        prior = uow.cursor.fetchone()
    if prior:
        body = {name: value for name, value in prior[0].items() if name != "action"}
    return application.execute(action=action, payload=body, idempotency_key=key, principal=principal)
