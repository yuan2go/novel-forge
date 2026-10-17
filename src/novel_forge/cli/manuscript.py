from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _manuscript_runtime_values(settings, *, project_id, book_run_id):
    from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
    from novel_forge.modules.book_authority.creation_runtime import creation_runtime_environment
    binding = PostgresBookProductionQuery(settings.database_url).creation_executor_binding(
        project_id=project_id, subject_id=book_run_id)
    if binding:
        return creation_runtime_environment(project_id, input_only_policy=binding.get("codex_input_only_policy"))
    return None


def add_manuscript_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-manuscript", help="read, edit, compare, adopt or export the current work")
    parser.add_argument("action", choices=("read", "export", "edit", "diff", "adopt", "reject", "revise", "continue-revision", "revision-status", "use-working-candidate", "continue-retained-working", "recover-plan-references", "recover-upstream-plan", "adopt-author-workflow", "extend-delivery-window", "pause", "resume", "continue"))
    parser.add_argument("--project-id", default="")
    parser.add_argument("--book-run-id", required=True)
    parser.add_argument("--chapter", type=int)
    parser.add_argument("--text-file", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--candidate-version", default="")
    parser.add_argument("--proposal-id", default="")
    parser.add_argument("--corrected-plan-version", default="")
    parser.add_argument("--versions", nargs="+")
    parser.add_argument("--chapters", nargs="+", type=int)
    parser.add_argument("--reason", default="")
    parser.add_argument("--stop-after-chapter", type=int)
    parser.add_argument("--expected-version", type=int)
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--revision-root", default="")
    parser.add_argument("--foreground", action="store_true")
    parser.add_argument("--work-window-seconds", type=int, default=300)


def run_manuscript_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver
    from novel_forge.modules.book_authority.manuscript import require_manuscript
    from novel_forge.modules.chapter_authority.author_editor import ChapterAuthorEditingApplication, edit_map
    from novel_forge.modules.story_planning_runtime.domain import canonical_hash
    principal = build_trusted_principal_resolver().resolve_api_principal()
    if not args.project_id:
        from types import SimpleNamespace
        from novel_forge.storage.authority_uow import AuthorityUnitOfWork
        with AuthorityUnitOfWork(settings.database_url) as uow:
            uow.cursor.execute("SELECT project_id FROM authority_book_production WHERE book_run_id=%s", [args.book_run_id])
            owned = uow.cursor.fetchone()
        if owned is None:
            raise ValueError("Choose an existing work")
        args = SimpleNamespace(**vars(args))
        args.project_id = owned[0]

    if args.action in {"revise", "continue-revision", "revision-status"}:
        return _run_working_revision_command(settings, args, principal=principal)

    if args.action in {"recover-plan-references", "recover-upstream-plan", "resume"}:
        if args.action != "resume" and not args.proposal_id:
            raise ValueError("Require the active Chapter PlanChange --proposal-id")
        from novel_forge.api.authority_dependencies import build_book_production_composition, build_production_execution_composition, build_chapter_authority_application
        from novel_forge.modules.book_authority.plan_recovery import retire_reference_failed_chapter, retire_upstream_stale_chapter
        values = _manuscript_runtime_values(settings, project_id=args.project_id, book_run_id=args.book_run_id)
        execution = build_production_execution_composition(settings, env=values)
        try:
            chapter = build_chapter_authority_application(settings,execution=execution, env=values)
            composition = build_book_production_composition(settings,principal=principal,execution=execution,chapter_application=chapter, env=values)
            if composition.authority.require(args.book_run_id)["project_id"] != args.project_id:
                raise PermissionError("Work is outside this Project")
            if args.action == "resume":
                return composition.authority.resume(args.book_run_id, reason=args.reason or "Requested manuscript resume",
                    principal=principal, expected_version=args.expected_version)
            if args.action == "recover-upstream-plan":
                if not args.corrected_plan_version:
                    raise ValueError("Require exact current --corrected-plan-version")
                return retire_upstream_stale_chapter(composition.authority,book_run_id=args.book_run_id,proposal_id=args.proposal_id,corrected_plan_version_id=args.corrected_plan_version,plan_change=composition.plan_change,principal=principal)
            return retire_reference_failed_chapter(composition.authority,book_run_id=args.book_run_id,proposal_id=args.proposal_id,plan_change=composition.plan_change,principal=principal)
        finally:
            execution.close()
    if args.action in {"use-working-candidate", "continue-retained-working", "adopt-author-workflow", "extend-delivery-window", "pause", "resume", "continue"}:
        from novel_forge.modules.book_authority.production import PostgresBookAuthority
        from novel_forge.modules.book_followup_authority.application import BookFollowupAuthorityApplication
        from novel_forge.modules.book_authority.manuscript import adopt_author_workflow
        build_id, sha = authority_release_identity()
        followup = BookFollowupAuthorityApplication(settings.database_url, application_build_id=build_id, commit_sha=sha)
        authority = PostgresBookAuthority(settings.database_url, chapter_port=None, followup_application=followup, application_build_id=build_id, commit_sha=sha)
        book = authority.require(args.book_run_id)
        if book["project_id"] != args.project_id:
            raise PermissionError("Work is outside this Project")
        if args.action == "continue-retained-working":
            from novel_forge.modules.book_authority.retained_working import continue_retained_working
            return continue_retained_working(authority, args.book_run_id, candidate_id=args.candidate_version,
                expected_version=args.expected_version, idempotency_key=args.idempotency_key, reason=args.reason, principal=principal)
        if args.action == "use-working-candidate":
            if args.expected_version is None or not args.chapter or not args.candidate_version or not args.idempotency_key or not args.reason:
                raise ValueError("Working selection requires exact chapter, candidate, expected Book version, idempotency key and reason")
            from novel_forge.modules.book_authority.manuscript import select_working_candidate
            return select_working_candidate(authority, args.book_run_id, chapter=args.chapter,
                candidate_asset_version_id=args.candidate_version, expected_version=args.expected_version,
                idempotency_key=args.idempotency_key, reason=args.reason, principal=principal)
        if args.action == "extend-delivery-window":
            if args.expected_version is None or args.stop_after_chapter is None or not args.idempotency_key:
                raise ValueError("Delivery extension requires --expected-version, --stop-after-chapter and --idempotency-key; retain them on retry")
            from novel_forge.modules.book_authority.creation_window import extend_delivery_window
            return extend_delivery_window(authority, args.book_run_id, principal=principal,
                expected_version=args.expected_version, stop_after_chapter=args.stop_after_chapter,
                idempotency_key=args.idempotency_key)
        if args.action in {"pause", "resume"}:
            return getattr(authority, args.action)(args.book_run_id, reason=args.reason or "Author " + args.action, principal=principal)
        if args.action == "continue":
            from novel_forge.modules.book_authority.manuscript import author_first
            from novel_forge.storage.authority_uow import AuthorityUnitOfWork
            with AuthorityUnitOfWork(settings.database_url) as uow:
                uow.cursor.execute("SELECT formation_run_id FROM authority_story_formation_run WHERE project_id=%s AND book_id=%s AND formation_run_id || ':production'=%s", [args.project_id, book["book_id"], book["stable_idempotency_key"]])
                original = uow.cursor.fetchone()
            if author_first(book):
                return _continue_native_work(settings, args, book=book, principal=principal,
                    formation_run_id=original[0] if original else '')
            if original is None:
                return _continue_native_work(settings, args, book=book, principal=principal)
            from novel_forge.cli.authority import _authority_parser
            from novel_forge.cli.creation import run_creation_command
            request = _authority_parser().parse_args(["authority-creation", "continue", "--project-id", args.project_id,
                "--formation-run-id", original[0], "--repository-root", str(settings.root)])
            return run_creation_command(settings, request)
        return adopt_author_workflow(authority, args.book_run_id, principal=principal, expected_version=None, settings=settings,
            idempotency_key="author-workflow:" + canonical_hash({"book": args.book_run_id, "profile": book["production_profile_version"]}))
    if args.action in {"read", "export"} and args.candidate_version:
        from novel_forge.modules.book_authority.manuscript import require_retained_model_candidate
        candidate = require_retained_model_candidate(settings.database_url, project_id=args.project_id,
            book_run_id=args.book_run_id, asset_version_id=args.candidate_version, principal=principal)
        if args.action == "export" and args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                if args.output.suffix.lower() in {".md", ".txt"}:
                    body = candidate["text"] if candidate["text"] is not None else candidate["raw_text"]
                    origin = "\n源执行：" + str(candidate.get("source_operation_status")) + "；源Effect：" + str(candidate.get("source_effect_status")) + "；失败：" + ",".join(candidate.get("source_failure_codes") or []) if candidate.get("source_operation_status") else ""
                    stream.write(f"第{candidate['chapter']}章 — 候选正文\n\n来源：{candidate['asset_version_id']}\n状态：{candidate['completeness']}；{candidate['review_status']}；{candidate['selection_status']}；{candidate['acceptance_status']}{origin}\n\n{body}\n")
                else:
                    stream.write(json.dumps(candidate, ensure_ascii=False, indent=2))
        return candidate
    chapters = args.chapters or ([args.chapter] if args.chapter is not None else None)
    if args.chapters and args.chapter is not None and args.chapters != [args.chapter]:
        raise ValueError("Choose a single --chapter or a --chapters range")
    manifest = require_manuscript(settings.database_url, project_id=args.project_id, book_run_id=args.book_run_id,
        principal=principal, version_ids=args.versions, chapters=chapters)
    if args.action == "read":
        return manifest
    if args.action == "export":
        if not manifest["units"]:
            raise ValueError("No complete saved prose is available")
        exact = require_manuscript(settings.database_url, project_id=args.project_id, book_run_id=args.book_run_id,
            principal=principal, version_ids=[item["asset_version_id"] for item in manifest["units"]], chapters=chapters)
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                if args.output.suffix.lower() in {".md", ".txt"}:
                    for unit in exact["units"]:
                        heading = "# " if args.output.suffix.lower() == ".md" else ""
                        stream.write(f"{heading}第{unit['chapter']}章 {unit['title']}\n\n{unit['text']}\n\n")
                        stream.write(f"版本：{unit['asset_version_id']}\n\n"
                            f"状态：{unit['manuscript_status']}；审读 {unit['review_status']}；质量 {unit['quality_status']}；"
                            f"选稿 {unit['author_selection']}；正式接纳至第{exact['accepted_through_chapter']}章\n\n")
                        selection = unit["working_selection"]
                        if selection["status"] == "SELECTED":
                            stream.write(f"工作稿选用回执：{selection['asset_version_id']}；{selection['content_hash']}；"
                                f"作者认可 {selection['author_selection']}；正式接纳 {selection['formal_acceptance']}\n\n")
                else:
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
        body["rationale"] = args.reason or ("Author adopts the exact candidate" if action == "accept" else "Author rejects the exact candidate")
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


def _continue_native_work(settings: Any, args: Any, *, book: dict[str, Any], principal: Any, formation_run_id: str = '') -> dict[str, Any]:
    from time import monotonic
    from novel_forge.api.authority_dependencies import (
        build_book_production_composition, build_chapter_authority_application,
        build_production_execution_composition, build_trusted_principal_resolver,
    )
    from novel_forge.modules.book_authority.creation_runtime import drive_book, creation_cancellation, creation_runtime_environment
    from novel_forge.modules.book_authority.manuscript import author_first, require_manuscript, writing_frontier
    principal.require("book.authority.execute", book["project_id"])
    if not author_first(book):
        raise ValueError("This historical work requires its native Book worker or a traceable Formation successor")
    target = args.stop_after_chapter if args.stop_after_chapter is not None else book["target_chapter_count"]
    if type(target) is not int or target < 1 or target > book["target_chapter_count"]:
        raise ValueError("Round boundary must stay within the frozen delivery window")
    run = book["book_run_id"]

    def report(status: str, current: dict[str, Any]) -> dict[str, Any]:
        return {"status": status, "book_run_id": run, "round_end": target,
            "delivery_window": current["target_chapter_count"], "next_chapter": writing_frontier(current) + 1,
            "manuscript": require_manuscript(settings.database_url, project_id=current["project_id"],
                book_run_id=run, principal=principal)}

    def continuation_live():
        return not formation_run_id or not creation_cancellation(settings.database_url, formation_run_id)

    if not continuation_live():
        return report('SOURCE_CANCELLED', book)
    if writing_frontier(book) >= target:
        return report("MANUSCRIPT_READY", book)
    if book["state"] in {"ABORTED", "CANCELLED", "COMPLETED"}:
        return report(book["state"], book)
    values = _manuscript_runtime_values(settings, project_id=book["project_id"], book_run_id=run)
    if values is None and formation_run_id:
        values = creation_runtime_environment(book["project_id"])
    execution = build_production_execution_composition(settings, env=values)
    try:
        chapter = build_chapter_authority_application(settings, execution=execution, env=values)
        composition = build_book_production_composition(settings, principal=principal, execution=execution, chapter_application=chapter, env=values)
        worker = build_trusted_principal_resolver(env=values).resolve_worker_principal("manuscript-continuation-worker")
        if book["state"] == "PAUSED":
            composition.authority.resume(run, reason="Requested native manuscript continuation", principal=principal)
        for _ in range((target - writing_frontier(book) + 1) * 20):
            current = composition.authority.require(run)
            if writing_frontier(current) >= target:
                if current["state"] != "PAUSED":
                    composition.authority.pause(run, reason=f"Requested manuscript round reached chapter {target}; frozen delivery window retained", principal=principal)
                return report("MANUSCRIPT_READY", composition.authority.require(run))
            if current["state"] in {"PAUSED", "ABORTED", "CANCELLED", "COMPLETED"}:
                return report(current["state"], current)
            from novel_forge.modules.command_kernel.errors import KernelError
            try:
                outcome = drive_book(composition=composition, chapter=chapter, book_run_id=run, worker=worker,
                    maximum_ticks=1, deadline=monotonic() + 1800, continuation_live=continuation_live)
            except KernelError as exc:
                result = report("NATIVE_CONTINUATION_BLOCKED", composition.authority.require(run))
                result["failure"] = {"code": exc.code, "message": str(exc)}
                return result
            if outcome not in {"YIELDED_CHECKPOINT", "WAITING_CHAPTER_DEPENDENCY", "MANUSCRIPT_READY"}:
                return report(outcome, composition.authority.require(run))
        return report("YIELDED_CHECKPOINT", composition.authority.require(run))
    finally:
        execution.close()


def _run_working_revision_command(settings, args, *, principal):
    from novel_forge.modules.chapter_authority.working_revision import working_revision_status
    from dataclasses import asdict
    from time import monotonic
    from novel_forge.api.authority_dependencies import (build_book_production_composition,
        build_chapter_authority_application, build_production_execution_composition, build_trusted_principal_resolver)
    if args.action in {"revision-status", "continue-revision"}:
        if not args.revision_root:
            raise ValueError("Retain the original --revision-root for status or continuation")
        result = working_revision_status(settings.database_url, project_id=args.project_id,
            book_run_id=args.book_run_id, root_operation_id=args.revision_root, principal=principal)
        if args.action == "revision-status" or result["status"] in {"SUCCEEDED", "CANCELLED"}:
            return result
    if args.work_window_seconds <= 0:
        raise ValueError("A positive scheduling work window is required")
    values = _manuscript_runtime_values(settings, project_id=args.project_id, book_run_id=args.book_run_id)
    execution = build_production_execution_composition(settings, env=values)
    try:
        chapter = build_chapter_authority_application(settings, execution=execution, env=values)
        if args.action == "revise":
            if args.expected_version is None or not args.chapter or not args.idempotency_key or not args.reason:
                raise ValueError("Revision requires chapter, expected Book version, original idempotency key and purpose")
            composition = build_book_production_composition(settings, principal=principal, execution=execution, chapter_application=chapter, env=values)
            if composition.authority.require(args.book_run_id)["project_id"] != args.project_id:
                raise PermissionError("Revision is outside this Project")
            admitted = chapter.admit_manuscript_revision(authority=composition.authority, book_run_id=args.book_run_id,
                chapter=args.chapter, expected_version=args.expected_version, idempotency_key=args.idempotency_key,
                reason=args.reason, principal=principal)
            root_id = admitted.root_operation_id
            if not args.foreground:
                return {**asdict(admitted), "book_run_id": args.book_run_id, "chapter": args.chapter}
        else:
            root_id = args.revision_root
            composition = build_book_production_composition(settings, principal=principal, execution=execution, chapter_application=chapter, env=values)
        from novel_forge.modules.chapter_authority.context_transport_recovery import recover_schema_transport, recover_unsent_context_transport
        recover_unsent_context_transport(composition.authority, book_run_id=args.book_run_id, principal=principal, root_operation_id=root_id)
        recover_schema_transport(composition.authority, book_run_id=args.book_run_id, principal=principal, root_operation_id=root_id)
        from novel_forge.modules.command_kernel.generation_isolation import recover_chapter_generations
        recover_chapter_generations(composition.authority, book_run_id=args.book_run_id,
            principal=principal, working_revision_root_id=root_id)
        worker = build_trusted_principal_resolver(env=values).resolve_worker_principal("manuscript-revision-worker")
        scheduler = chapter.scheduler(principal=worker)
        deadline = monotonic() + args.work_window_seconds
        while monotonic() < deadline:
            tick = scheduler.tick(project_id=args.project_id, root_operation_id=root_id)
            if tick.operation_status not in {"SUCCEEDED", "ADMITTED", "READY"} or tick.saga_status == "SUCCEEDED":
                break
        return working_revision_status(settings.database_url, project_id=args.project_id,
            book_run_id=args.book_run_id, root_operation_id=root_id, principal=principal)
    finally:
        execution.close()
