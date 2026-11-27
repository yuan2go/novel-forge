from __future__ import annotations

from novel_forge.modules.book_design_authority.query import BookDesignAuthorityQuery
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.content_authority.application import ContentOperationRequest
from novel_forge.storage.authority_asset_store import AuthorityAssetQuery
from novel_forge.modules.narrative_state.reality import narrative_hash


def require_style_scope_frontier(uow, request):
    payload = request.command.get("payload") or {}
    proof = payload.get("style_scope_revalidation")
    if proof is None:
        return
    if proof.get("contract_version") != "creation-style-scope.v1":
        raise KernelError("CREATION_STYLE_SCOPE_INVALID", "Unknown prospective Style correction contract")
    uow.cursor.execute("""SELECT formation.book_design_asset_version_id,root.actor_id
        FROM authority_story_formation_run formation JOIN authority_operation root ON root.operation_id=formation.root_operation_id
        WHERE formation.formation_run_id=%s AND formation.project_id=%s AND formation.workspace_id=%s
          AND formation.book_id=%s AND formation.lifecycle='READY' FOR UPDATE OF formation""",
        [proof["formation_run_id"], request.project_id, request.workspace_id, payload["book_id"]])
    formation = uow.cursor.fetchone()
    uow.cursor.execute("""SELECT version,active_chapter_request_id,book_design_version,state,stable_idempotency_key
        FROM authority_book_production WHERE book_run_id=%s AND project_id=%s AND workspace_id=%s AND book_id=%s FOR UPDATE""",
        [proof["book_run_id"], request.project_id, request.workspace_id, payload["book_id"]])
    book = uow.cursor.fetchone()
    uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=%s)", [proof["formation_run_id"]])
    if (not formation or formation != (proof["book_design_asset_version_id"], request.actor_id)
        or not book or book[0] != proof["book_version"] or book[1]
        or book[2] != formation[0] or book[3] in {"COMPLETED", "ABORTED", "CANCELLED", "PAUSED"}
        or book[4] != proof["formation_run_id"] + ":production" or uow.cursor.fetchone()[0]
        or request.require_input("book_design").asset_version_id != formation[0]):
        raise KernelError("CREATION_STYLE_SCOPE_FRONTIER_CHANGED", "Style correction requires the original Creator and exact uncancelled future checkpoint")
    uow.cursor.execute("""SELECT v.content_hash,v.content->>'contract_version',v.content->'source_bindings' FROM authority_asset_version v
        JOIN authority_asset a USING(asset_id) WHERE v.asset_version_id=%s AND a.project_id=%s
          AND a.asset_type='style_policy' AND v.content->>'book_id'=%s AND v.lifecycle='ACTIVE'
          AND v.eligibility='ELIGIBLE' AND v.governance='CLEAR'""", [proof["source_style"]["asset_version_id"], request.project_id, payload["book_id"]])
    if uow.cursor.fetchone() != (proof["source_style"]["content_hash"], "foundation-style-projection.v4",
            [{"asset_version_id": item.asset_version_id, "content_hash": item.content_hash} for item in request.inputs]):
        raise KernelError("CREATION_STYLE_SCOPE_SOURCE_DRIFT", "Retain the exact governed legacy Style")
    uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE project_id=%s
        AND request_payload #>> '{_production_execution,book_id}'=%s
        AND status IN ('DISPATCHING','UNKNOWN','RECONCILIATION_REQUIRED')
        AND NOT authority_generation_isolated(external_effect_id))""", [request.project_id, payload["book_id"]])
    if uow.cursor.fetchone()[0]:
        raise KernelError("CREATION_STYLE_SCOPE_EXECUTION_UNRESOLVED", "Reconcile live generation before future Style correction")


def refresh_creation_style_scope(*, composition, book_run_id):
    from novel_forge.modules.content_authority.application import ContentAuthorityApplication
    from novel_forge.modules.content_authority.definitions import CONTENT_INTEGRATION_PROVEN
    from novel_forge.storage.authority_uow import AuthorityUnitOfWork

    book = composition.authority.require(book_run_id)
    if (not str(book.get("stable_idempotency_key") or "").startswith("story-formation:")
        or book.get("active_chapter_request_id") or book["state"] in {"COMPLETED", "ABORTED", "CANCELLED", "PAUSED"}):
        return False
    principal = composition.principal
    principal.require("book.authority.execute", book["project_id"])
    with AuthorityUnitOfWork(composition.authority.database_url) as uow:
        uow.cursor.execute("""SELECT formation.formation_run_id,formation.book_design_asset_version_id,root.actor_id
            FROM authority_story_formation_run formation JOIN authority_operation root ON root.operation_id=formation.root_operation_id
            WHERE formation.project_id=%s AND formation.book_id=%s AND formation.lifecycle='READY'
              AND formation.formation_run_id || ':production'=%s FOR UPDATE OF formation""",
            [book["project_id"], book["book_id"], book["stable_idempotency_key"]])
        formation = uow.cursor.fetchone()
        if not formation or formation[2] != principal.principal_id or formation[1] != book["book_design_version"]:
            return False
        uow.cursor.execute("SELECT EXISTS(SELECT 1 FROM authority_story_creation_cancellation WHERE formation_run_id=%s)", [formation[0]])
        if uow.cursor.fetchone()[0]:
            return False
        uow.cursor.execute("""SELECT v.content,v.asset_version_id,v.content_hash FROM authority_asset a JOIN authority_asset_version v USING(asset_id)
            WHERE a.project_id=%s AND a.asset_type='style_policy' AND v.content->>'book_id'=%s
              AND v.lifecycle='ACTIVE' AND v.eligibility='ELIGIBLE' AND v.governance='CLEAR'
            ORDER BY v.created_at DESC,v.asset_version_id DESC LIMIT 1""", [book["project_id"], book["book_id"]])
        style = uow.cursor.fetchone()
        if not style or style[0].get("contract_version") != "foundation-style-projection.v4":
            return False
        uow.cursor.execute("""SELECT EXISTS(SELECT 1 FROM authority_external_effect WHERE project_id=%s
            AND request_payload #>> '{_production_execution,book_id}'=%s
            AND status IN ('DISPATCHING','UNKNOWN','RECONCILIATION_REQUIRED')
            AND NOT authority_generation_isolated(external_effect_id))""", [book["project_id"], book["book_id"]])
        if uow.cursor.fetchone()[0]:
            return False
    query = AuthorityAssetQuery(composition.authority.database_url)
    design = query.require(project_id=book["project_id"], asset_version_id=formation[1])
    bindings = {binding["role"]: binding for binding in design.content["foundation_set"]["bindings"]}
    sources = [design, *(query.require(project_id=book["project_id"], asset_version_id=bindings[role]["asset_version_id"])
        for role in ("CREATIVE_FOUNDATION", "CHARACTER_CAST"))]
    content = ContentAuthorityApplication(composition.authority.database_url,
        application_build_id=composition.authority.application_build_id, commit_sha=composition.authority.commit_sha,
        integration_proven=CONTENT_INTEGRATION_PROVEN, trusted_only=True)
    content.execute(ContentOperationRequest(definition_name="chapter.style_policy.compile", project_id=book["project_id"],
        workspace_id=book["workspace_id"], actor_id=principal.principal_id, trace_id=f"trace:{formation[0]}:style-scope",
        correlation_id=book["root_operation_id"], idempotency_key=f"{formation[0]}:style-scope:2.1.6:{design.content_hash}:{style[1]}:{book['version']}",
        payload={"book_id": book["book_id"], "style_scope_revalidation": {"contract_version": "creation-style-scope.v1",
            "formation_run_id": formation[0], "book_run_id": book_run_id, "book_version": book["version"],
            "book_design_asset_version_id": design.asset_version_id,
            "source_style": {"asset_version_id": str(style[1]), "content_hash": str(style[2])}}},
        input_assets=tuple({"asset_version_id": asset.asset_version_id, "content_hash": asset.content_hash} for asset in sources)),
        principal=principal)
    return True


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
