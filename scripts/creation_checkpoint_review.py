"""INVARIANT: Checkpoint commands read accepted prose and record evidence without Provider execution."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from types import SimpleNamespace

from novel_forge.api.authority_dependencies import authority_release_identity, build_content_authority_application, build_trusted_principal_resolver
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.book_authority.control_application import PostgresBookControlApplication
from novel_forge.modules.book_authority.production import PostgresBookAuthority
from novel_forge.modules.book_authority.queries import PostgresBookProductionQuery
from novel_forge.modules.production_execution.security import redact_secret_text
from scripts.creation_pilot import decide_reading_review, register_reading_review, require_reading_decision
from scripts.creation_reading import load_accepted_reading, write_accepted_reading
from scripts.creation_checkpoints import reading_review_template


def metadata_composition(settings, principal):
    build, sha = authority_release_identity()
    return SimpleNamespace(
        authority=PostgresBookAuthority(settings.database_url, chapter_port=None, followup_application=None,
                                       application_build_id=build, commit_sha=sha),
        query=PostgresBookProductionQuery(settings.database_url), principal=principal,
        controls=PostgresBookControlApplication(settings.database_url, application_build_id=build, commit_sha=sha),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "register", "decide", "verify"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--book-run-id", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--review-file", type=Path)
    parser.add_argument("--review-asset-version-id", default="")
    parser.add_argument("--decision-version-id", default="")
    parser.add_argument("--decision", choices=("APPROVE", "REJECT"))
    parser.add_argument("--reason", default="")
    parser.add_argument("--idempotency-key", default="")
    args = parser.parse_args(argv)
    try:
        settings = IndustrialSettings.from_env(os.environ, root=Path.cwd())
        principal = build_trusted_principal_resolver().resolve_api_principal()
        principal.require("book.authority.query", args.project_id)
        composition = metadata_composition(settings, principal)
        book = composition.authority.require(args.book_run_id)
        if book["project_id"] != args.project_id:
            raise ValueError("Book Run belongs to another project")
        if args.action == "preview":
            if not args.output:
                raise ValueError("preview requires a new --output directory")
            if book["accepted_through_chapter"] < 1:
                raise ValueError("No accepted manuscript exists to read or review")
            manifest = load_accepted_reading(composition=composition, book_run_id=args.book_run_id, require_closed_groups=True)
            args.output.mkdir(parents=True, exist_ok=False)
            write_accepted_reading(manifest, destination=args.output, book=book)
            (args.output / "review-template.json").write_text(json.dumps(reading_review_template(manifest), ensure_ascii=False, indent=2) + "\n")
            result = {"status": "ACCEPTED_READING_EXPORTED", "manifest_hash": manifest["manifest_hash"],
                      "accepted_through_chapter": manifest["accepted_through_chapter"],
                      "independent_human_review": "NOT_REVIEWED", "real_provider_execution": "NOT_RUN"}
        elif args.action == "register":
            if not args.review_file or not args.idempotency_key:
                raise ValueError("register requires --review-file and a stable --idempotency-key")
            result = register_reading_review(composition=composition, content_application=build_content_authority_application(settings),
                                            book_run_id=args.book_run_id, review=json.loads(args.review_file.read_text()),
                                            idempotency_key=args.idempotency_key)
        elif args.action == "decide":
            if not all((args.review_asset_version_id, args.decision, args.reason.strip(), args.idempotency_key)):
                raise ValueError("decide requires exact review version, decision, reason and stable idempotency key")
            result = decide_reading_review(composition=composition, book_run_id=args.book_run_id,
                                          review_asset_version_id=args.review_asset_version_id, decision=args.decision,
                                          reason=args.reason, idempotency_key=args.idempotency_key)
        else:
            result = require_reading_decision(composition=composition, book_run_id=args.book_run_id,
                                             boundary=book["accepted_through_chapter"], decision_version_id=args.decision_version_id)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED", "error": redact_secret_text(str(exc)), "real_provider_execution": "NOT_RUN"}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
