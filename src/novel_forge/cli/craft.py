from __future__ import annotations

from typing import Any
from uuid import uuid4


def add_craft_parser(subparsers: Any) -> None:
    parser = subparsers.add_parser("authority-craft", help="inspect or explicitly govern the original Craft catalog in native MKAOS")
    parser.add_argument("action", choices=("catalog", "cards", "author", "approve-core", "trace"))
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--workspace-id", default="")
    parser.add_argument("--mechanism-id", default="")
    parser.add_argument("--catalog-hash", default="")
    parser.add_argument("--candidate-asset-version-id", default="")
    parser.add_argument("--supersedes-card-asset-version-id", default="")
    parser.add_argument("--knowledge-card-asset-version-id", default="")
    parser.add_argument("--rationale", default="")
    parser.add_argument("--idempotency-key", default="")
    parser.add_argument("--book-id", default="")
    parser.add_argument("--limit", type=int, default=50)


def run_craft_command(settings: Any, args: Any) -> dict[str, Any]:
    from novel_forge.api.authority_dependencies import authority_release_identity, build_trusted_principal_resolver
    from novel_forge.modules.mkaos_authority.application import ApproveKnowledgeCandidateCommand, MkaosAuthorityApplication
    from novel_forge.modules.mkaos_authority.craft import CRAFT_ORIGINAL_POLICY, core_catalog, core_catalog_hash
    from novel_forge.modules.mkaos_authority.craft_authoring import AuthorCoreCraftCommand
    from novel_forge.modules.mkaos_authority.query import MkaosAuthorityQuery
    principal = build_trusted_principal_resolver().resolve_api_principal()
    permission = "mkaos.authority.approve" if args.action == "approve-core" else "mkaos.authority.execute" if args.action == "author" else "mkaos.authority.query"
    principal.require(permission, args.project_id)
    if args.action == "catalog":
        catalog = core_catalog()
        if args.mechanism_id:
            catalog = [item for item in catalog if item["mechanism_id"] == args.mechanism_id]
        return {"catalog_hash": core_catalog_hash(), "mechanisms": catalog,
                "activation": "EXPLICIT_CANDIDATE_AND_APPROVAL_REQUIRED", "evidence_ceiling": "ORIGINAL_HYPOTHESES_NOT_CREATIVE_QUALITY"}
    if args.action == "cards":
        cards = MkaosAuthorityQuery(settings.database_url).list_cards(project_id=args.project_id, limit=args.limit)
        cards = [card for card in cards if dict(card.get("content") or {}).get("abstract_content", {}).get("craft_mechanism")]
        if args.mechanism_id:
            cards = [card for card in cards if card["content"]["abstract_content"]["craft_mechanism"]["mechanism_id"] == args.mechanism_id]
        return {"cards": cards, "trace_command": "authority-craft trace --knowledge-card-asset-version-id <exact-version>"}
    if args.action == "trace":
        from novel_forge.modules.mkaos_authority.trace import require_knowledge_trace
        return require_knowledge_trace(settings.database_url, project_id=args.project_id,
            knowledge_card_asset_version_id=args.knowledge_card_asset_version_id, book_id=args.book_id, limit=args.limit)
    if not all((args.workspace_id, args.idempotency_key, args.catalog_hash)):
        raise ValueError("Craft mutation requires workspace, idempotency key and exact reviewed catalog hash")
    build, sha = authority_release_identity()
    application = MkaosAuthorityApplication(settings.database_url, application_build_id=build, commit_sha=sha)
    shared = {"project_id": args.project_id, "workspace_id": args.workspace_id,
              "actor_id": principal.principal_id, "idempotency_key": args.idempotency_key,
              "trace_id": f"trace:craft:{uuid4()}", "correlation_id": f"correlation:craft:{uuid4()}"}
    if args.action == "author":
        return application.execute_core_craft(AuthorCoreCraftCommand(**shared, mechanism_id=args.mechanism_id, catalog_hash=args.catalog_hash,
            supersedes_card_asset_version_id=args.supersedes_card_asset_version_id), principal=principal)
    if not args.candidate_asset_version_id or not args.rationale:
        raise ValueError("approve-core requires the exact candidate AssetVersion and operator rationale")
    return application.execute_approval(ApproveKnowledgeCandidateCommand(**shared,
        candidate_asset_version_id=args.candidate_asset_version_id,
        policy_version=CRAFT_ORIGINAL_POLICY+":"+args.catalog_hash, rationale=args.rationale), principal=principal)
