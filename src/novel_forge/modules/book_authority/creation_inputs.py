from __future__ import annotations

from novel_forge.modules.book_design_authority.query import BookDesignAuthorityQuery
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority.application import ContentOperationRequest
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.modules.narrative_state.reality import narrative_hash


def prepare_creation_inputs(*, composition, content, formation_run_id, policy):
    if policy.get("contract_version") != "creation-input-policy.v1":
        raise KernelError(
            "CREATION_POLICY_INVALID",
            "An explicit versioned creation policy is required",
        )
    formation = composition.formation.require(formation_run_id)
    project, book = formation["project_id"], formation["book_id"]
    composition.principal.require("book.authority.execute", project)
    current = BookDesignAuthorityQuery(content.database_url).require_book(
        project_id=project, book_id=book
    )
    if (
        formation["lifecycle"] != "READY"
        or current["active_book_design_version_id"]
        != formation["book_design_asset_version_id"]
    ):
        raise KernelError(
            "CREATION_FOUNDATION_NOT_CURRENT",
            "Creation requires its exact ready Foundation and active Book Design",
        )
    query = AuthorityAssetQuery(content.database_url)
    design = query.require(
        project_id=project, asset_version_id=formation["book_design_asset_version_id"]
    )
    versions = {
        binding["role"].lower(): binding["asset_version_id"]
        for binding in design.content["foundation_set"]["bindings"]
    }
    versions["book_design"] = design.asset_version_id
    portfolio = query.require(
        project_id=project, logical_ref=f"books/{book}/character-arc-portfolio"
    )
    if (
        portfolio.content.get("foundation_design_asset_version_id")
        != design.asset_version_id
    ):
        raise KernelError(
            "CREATION_CHARACTER_PROJECTION_STALE",
            "Character trajectories do not belong to the active Foundation",
        )
    versions["character_arc_portfolio"] = portfolio.asset_version_id
    policy_digest = narrative_hash(policy)

    def execute(name, payload, inputs=()):
        return content.execute(
            ContentOperationRequest(
                definition_name=name,
                project_id=project,
                workspace_id=formation["workspace_id"],
                actor_id=composition.principal.principal_id,
                trace_id=f"trace:{formation_run_id}:inputs",
                correlation_id=formation["root_operation_id"],
                idempotency_key=f"{formation_run_id}:inputs:{policy_digest}:{name}",
                input_assets=tuple(
                    {
                        "asset_version_id": item.asset_version_id,
                        "content_hash": item.content_hash,
                    }
                    for item in inputs
                ),
                payload=payload,
            ),
            principal=composition.principal,
        )

    from novel_forge.modules.content_authority.codecs import _BOOK_BOOTSTRAP_INPUT_SPECS

    allowed = set(_BOOK_BOOTSTRAP_INPUT_SPECS) | {
        "chapter.platform_profile.author",
        "chapter.quality_rubric.author",
    }
    for role, item in policy["profiles"].items():
        if role in versions or item["operation"] not in allowed:
            raise KernelError(
                "CREATION_POLICY_AUTHORITY_INVALID",
                "Configuration cannot replace Foundation or invoke arbitrary mutations",
            )
        document = dict(item["content"])
        if document.get("book_id", book) != book:
            raise KernelError(
                "CREATION_POLICY_BOOK_MISMATCH", "Policy belongs to another Book"
            )
        document["book_id"] = book
        versions[role] = execute(
            item["operation"], {"content": document}
        ).asset_version_id
    genesis = execute(
        "book.initial_story_state.author",
        {"book_id": book, "campaign_contract_identity": policy_digest},
    )
    versions["story_state"] = genesis.asset_version_id
    genesis_asset = query.require(
        project_id=project, asset_version_id=genesis.asset_version_id
    )
    versions["canon_snapshot"] = execute(
        "book.initial_canon.author",
        {"book_id": book, "campaign_contract_identity": policy_digest},
        (genesis_asset,),
    ).asset_version_id
    style_sources = (
        design,
        *(
            query.require(project_id=project, asset_version_id=versions[role])
            for role in ("creative_foundation", "character_cast")
        ),
    )
    versions["style_policy"] = execute(
        "chapter.style_policy.compile", {}, style_sources
    ).asset_version_id
    return {
        "contract_version": "creation-inputs.v1",
        "formation_run_id": formation_run_id,
        "policy_digest": policy_digest,
        "book_version": current["version"],
        "versions": versions,
    }
