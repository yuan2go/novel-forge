#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from novel_forge.api.authority_dependencies import authority_release_identity
from novel_forge.infrastructure.settings import IndustrialSettings
from novel_forge.modules.provider_qualification import (
    D0ProbeConfig,
    D0QualificationAuthority,
    D0QualificationCommand,
    D0QualificationScheduler,
    run_d0_probe,
)
from novel_forge.storage.object_store import MinioObjectStore


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config/provider/d0-openai-probe.json")
    parser.add_argument("--project-id")
    parser.add_argument("--workspace-id")
    parser.add_argument("--idempotency-key", default="d0-openai-qualification-v1")
    parser.add_argument("--contract-only", action="store_true")
    parser.add_argument("--run-worker-once", action="store_true")
    args = parser.parse_args()
    payload = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config = D0ProbeConfig.from_mapping(payload)
    if args.contract_only:
        report = run_d0_probe(config)
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report.status == "PASSED" else 2 if report.status.startswith("BLOCKED") else 1
    if not args.project_id or not args.workspace_id:
        parser.error(
            "Authority D0 requires --project-id and --workspace-id; use "
            "--contract-only only for the non-promotable protocol check"
        )
    settings = IndustrialSettings.from_env()
    if settings.storage_authority != "postgresql" or not settings.database_url:
        raise RuntimeError("Authority D0 requires PostgreSQL storage authority")
    build_id, commit_sha = authority_release_identity()
    authority = D0QualificationAuthority(
        settings.database_url,
        evidence_store=MinioObjectStore(settings),
        application_build_id=build_id,
        commit_sha=commit_sha,
    )
    command = D0QualificationCommand(
        project_id=args.project_id,
        workspace_id=args.workspace_id,
        actor_id=str(os.environ.get("NOVEL_FORGE_D0_ACTOR_ID") or "operator:d0"),
        idempotency_key=args.idempotency_key,
        trace_id=f"trace:d0:{args.idempotency_key}",
        correlation_id=f"correlation:d0:{args.project_id}",
        config=config,
    )
    admitted = authority.admit(command)
    result = {**admitted, "status": "READY"}
    if args.run_worker_once:
        result = D0QualificationScheduler(authority).run_or_recover(
            operation_id=str(admitted["operation_id"]), project_id=args.project_id
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if result.get("status") == "BLOCKED_MISSING_CREDENTIALS" else 0


if __name__ == "__main__":
    raise SystemExit(main())
