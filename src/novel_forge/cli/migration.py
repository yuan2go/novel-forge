from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from novel_forge.infrastructure.settings import IndustrialSettings


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novel-forge-migrate",
        description="Import frozen Legacy snapshots into PostgreSQL Authority",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    legacy_import = commands.add_parser(
        "authority-import-legacy",
        help="scan or import a frozen Legacy snapshot",
    )
    legacy_import.add_argument("--root", required=True)
    legacy_import.add_argument("--dry-run", action="store_true")
    legacy_import.add_argument("--no-resume", action="store_true")

    status = commands.add_parser(
        "authority-import-status",
        help="show a resumable Legacy migration run",
    )
    status.add_argument("--migration-run-id", required=True)

    verify = commands.add_parser(
        "authority-verify-migration",
        help="reconcile imported rows and snapshot hash",
    )
    verify.add_argument("--migration-run-id", required=True)
    verify.add_argument("--root", default=None)
    verify.add_argument(
        "--required-level",
        choices=("ARCHIVAL_NATIVE", "DOMAIN_NATIVE", "RELEASE_READY"),
        default="ARCHIVAL_NATIVE",
    )

    quarantine = commands.add_parser(
        "authority-quarantine-list",
        help="list unresolved migration quarantine rows",
    )
    quarantine.add_argument("--migration-run-id", default=None)
    quarantine.add_argument("--limit", type=int, default=200)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql":
        print(
            "error: Legacy migration targets PostgreSQL Authority",
            file=sys.stderr,
        )
        return 1
    try:
        if args.command == "authority-import-legacy" and args.dry_run:
            from novel_forge.modules.legacy_migration import scan_legacy_snapshot

            scan = scan_legacy_snapshot(args.root)
            print(
                json.dumps(
                    {
                        "mode": "DRY_RUN",
                        "snapshot_hash": scan.snapshot_hash,
                        "counts": scan.counts,
                        "records": [asdict(record) for record in scan.records],
                        "production_mutation_performed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        if not settings.database_url:
            raise RuntimeError("PostgreSQL database is required for migration")

        from novel_forge.api.authority_dependencies import authority_release_identity
        from novel_forge.modules.legacy_migration import LegacyMigrationService

        build_id, commit_sha = authority_release_identity()
        service = LegacyMigrationService(
            settings.database_url,
            application_build_id=build_id,
            commit_sha=commit_sha,
        )
        if args.command == "authority-import-legacy":
            result = service.import_snapshot(
                args.root,
                resume=not args.no_resume,
                require_read_only=True,
            )
        elif args.command == "authority-import-status":
            result = service.status(args.migration_run_id)
        elif args.command == "authority-verify-migration":
            result = service.verify(
                args.migration_run_id,
                snapshot_root=args.root,
                required_level=args.required_level,
            )
        elif args.command == "authority-quarantine-list":
            result = service.quarantine_list(
                migration_run_id=args.migration_run_id,
                limit=args.limit,
            )
        else:  # INVARIANT: argparse owns the closed command set.
            raise RuntimeError(f"unsupported migration command: {args.command}")
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


__all__ = ["main"]
