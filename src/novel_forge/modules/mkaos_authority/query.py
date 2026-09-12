from __future__ import annotations

import hashlib
import json
from typing import Any

from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork
from novel_forge.storage.mkaos_authority_repositories import MkaosAuthorityRepository

from .domain import (
    NarrativeIntelligenceNeed,
    select_narrative_intelligence,
    validate_book_knowledge_access_policy,
)


class MkaosAuthorityQuery:
    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("PostgreSQL database_url is required")
        self.database_url = database_url

    def resolve_narrative_intelligence(
        self,
        *,
        project_id: str,
        need: NarrativeIntelligenceNeed,
        limit: int = 6,
        book_id: str = "",
        knowledge_access_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        if limit < 1 or limit > 12:
            raise ValueError("Narrative Intelligence limit must be within 1..12")
        if knowledge_access_policy is None:
            access = {
                "mode": "PROJECT_DEFAULT",
                "allowed_knowledge_card_asset_version_ids": [],
                "policy_hash": "",
                "configured_explicitly": False,
            }
        else:
            if not book_id:
                raise ValueError("Book identity is required for Knowledge access policy")
            access = validate_book_knowledge_access_policy(
                knowledge_access_policy,
                project_id=project_id,
                book_id=book_id,
            )
        mode = str(access["mode"])
        allowed_ids = tuple(access["allowed_knowledge_card_asset_version_ids"])
        if mode == "DENY_ALL":
            cards: list[dict[str, Any]] = []
            pool_query_mode = "DENY_ALL_NO_QUERY"
        else:
            cards = self._planning_cards(
                project_id=project_id,
                allowed_asset_version_ids=(
                    allowed_ids if mode == "ALLOW_ONLY" else None
                ),
            )
            pool_query_mode = (
                "EXACT_ALLOWLIST"
                if mode == "ALLOW_ONLY"
                else "ALL_PROJECT_ELIGIBLE_NO_TRUNCATION"
            )
        eligible = tuple(
            card
            for card in cards
            if card["lifecycle"] == "ACTIVE"
            and card["eligibility"] in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
            and card["governance"] == "CLEAR"
            and card["operation_status"] == "SUCCEEDED"
            and _context_eligible_card(card, access)
        )
        if mode == "ALLOW_ONLY" and {
            str(card["asset_version_id"]) for card in eligible
        } != set(allowed_ids):
            raise KernelError(
                "PLANNING_KNOWLEDGE_ALLOWLIST_INELIGIBLE",
                "one or more exact KnowledgeCard versions are missing or ineligible",
            )
        selection = select_narrative_intelligence(need, eligible, limit=limit)
        selection["project_id"] = project_id
        selection["eligible_card_count"] = len(eligible)
        selection["examined_card_count"] = len(cards)
        selection["pool_query_mode"] = pool_query_mode
        selection["pool_truncated"] = False
        selection["knowledge_access_policy"] = dict(access)
        selection["selection_digest"] = _canonical_hash(
            {key: value for key, value in selection.items() if key != "selection_digest"}
        )
        return selection

    def _planning_cards(
        self,
        *,
        project_id: str,
        allowed_asset_version_ids: tuple[str, ...] | None,
    ) -> list[dict[str, Any]]:
        if not project_id:
            raise ValueError("project_id is required")
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT card.knowledge_card_id, card.project_id,
                       card.workspace_id, card.asset_version_id,
                       card.candidate_asset_version_id,
                       card.governance_decision_asset_version_id,
                       card.created_by_operation_id, card.content_hash,
                       card.status, version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, card.created_at
                FROM authority_mkaos_knowledge_card AS card
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=card.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=card.created_by_operation_id
                WHERE card.project_id=%s
                  AND card.status='ACTIVE'
                  AND version.lifecycle='ACTIVE'
                  AND version.eligibility IN ('ELIGIBLE', 'PRODUCTION_ELIGIBLE')
                  AND version.governance='CLEAR'
                  AND operation.status='SUCCEEDED'
                  AND (
                    %s OR card.asset_version_id=ANY(%s::text[])
                  )
                ORDER BY card.created_at DESC, card.knowledge_card_id
                """,
                [
                    project_id,
                    allowed_asset_version_ids is None,
                    list(allowed_asset_version_ids or ()),
                ],
            )
            rows = uow.cursor.fetchall()
            blocked = MkaosAuthorityRepository(uow.cursor).corpus_candidate_origins(
                project_id, tuple(str(row[4]) for row in rows)
            )
            rows = [row for row in rows if str(row[4]) not in blocked]
            keys = (
                "knowledge_card_id",
                "project_id",
                "workspace_id",
                "asset_version_id",
                "candidate_asset_version_id",
                "governance_decision_asset_version_id",
                "created_by_operation_id",
                "content_hash",
                "card_status",
                "lifecycle",
                "eligibility",
                "governance",
                "content",
                "operation_status",
                "created_at",
            )
            cards = [dict(zip(keys, row, strict=True)) for row in rows]
            _recheck_card_qualifications(self.database_url, project_id=project_id, cards=cards, cursor=uow.cursor)
            return cards

    def list_candidates(
        self, *, project_id: str, status: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        _validate(project_id, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT candidate.knowledge_candidate_id, candidate.project_id,
                       candidate.workspace_id, candidate.asset_version_id,
                       candidate.execution_asset_version_id,
                       candidate.candidate_hash,
                       candidate.abstraction_policy_version, candidate.status,
                       candidate.created_by_operation_id,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, candidate.created_at
                FROM authority_mkaos_knowledge_candidate AS candidate
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = candidate.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id = candidate.created_by_operation_id
                WHERE candidate.project_id = %s
                  AND (%s = '' OR candidate.status = %s)
                ORDER BY candidate.created_at DESC,
                         candidate.knowledge_candidate_id
                LIMIT %s
                """,
                [project_id, status, status, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "knowledge_candidate_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "execution_asset_version_id",
            "candidate_hash",
            "abstraction_policy_version",
            "candidate_status",
            "created_by_operation_id",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "operation_status",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_cards(
        self, *, project_id: str, status: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        _validate(project_id, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT card.knowledge_card_id, card.project_id,
                       card.workspace_id, card.asset_version_id,
                       card.candidate_asset_version_id,
                       card.governance_decision_asset_version_id,
                       card.created_by_operation_id, card.content_hash,
                       card.status, version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, card.created_at
                FROM authority_mkaos_knowledge_card AS card
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = card.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id = card.created_by_operation_id
                WHERE card.project_id = %s
                  AND (%s = '' OR card.status = %s)
                ORDER BY card.created_at DESC, card.knowledge_card_id
                LIMIT %s
                """,
                [project_id, status, status, limit],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "knowledge_card_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "candidate_asset_version_id",
            "governance_decision_asset_version_id",
            "created_by_operation_id",
            "content_hash",
            "card_status",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "operation_status",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def require_planning_card_current(
        self,
        *,
        project_id: str,
        asset_version_id: str,
        content_hash: str,
        book_id: str = "",
        knowledge_access_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:

        if not project_id or not asset_version_id or not content_hash:
            raise ValueError(
                "project_id, asset_version_id, and content_hash are required"
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT card.knowledge_card_id, card.project_id,
                       card.workspace_id, card.asset_version_id,
                       card.candidate_asset_version_id,
                       card.governance_decision_asset_version_id,
                       card.created_by_operation_id, card.content_hash,
                       card.status, version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, card.created_at
                FROM authority_mkaos_knowledge_card AS card
                JOIN authority_asset_version AS version
                  ON version.asset_version_id=card.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=card.created_by_operation_id
                WHERE card.project_id=%s AND card.asset_version_id=%s
                FOR SHARE OF card, version, operation
                """,
                [project_id, asset_version_id],
            )
            row = uow.cursor.fetchone()
            qualification_card = None
            if row is not None:
                MkaosAuthorityRepository(uow.cursor).require_corpus_bridge(project_id, (str(row[4]),))
                qualification_card = {"asset_version_id": str(row[3]), "workspace_id": str(row[2]), "content": row[12]}
                _recheck_card_qualifications(self.database_url, project_id=project_id, cards=[qualification_card], cursor=uow.cursor)
        if row is None:
            raise KernelError(
                "PLANNING_NARRATIVE_INTELLIGENCE_DRIFT",
                "Frozen KnowledgeCard is no longer registered in MKAOS Authority",
            )
        keys = (
            "knowledge_card_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "candidate_asset_version_id",
            "governance_decision_asset_version_id",
            "created_by_operation_id",
            "content_hash",
            "card_status",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "operation_status",
            "created_at",
        )
        card = dict(zip(keys, row, strict=True))
        if qualification_card and "runtime_qualification_current" in qualification_card:
            card["runtime_qualification_current"] = qualification_card["runtime_qualification_current"]
        access = (
            validate_book_knowledge_access_policy(
                knowledge_access_policy,
                project_id=project_id,
                book_id=book_id,
            )
            if knowledge_access_policy is not None
            else {
                "mode": "PROJECT_DEFAULT",
                "usage_scope": "PRODUCTION",
                "allowed_knowledge_card_asset_version_ids": [],
            }
        )
        if (
            card["content_hash"] != content_hash
            or card["card_status"] != "ACTIVE"
            or card["lifecycle"] != "ACTIVE"
            or card["eligibility"] not in {"ELIGIBLE", "PRODUCTION_ELIGIBLE"}
            or card["governance"] != "CLEAR"
            or card["operation_status"] != "SUCCEEDED"
            or not _context_eligible_card(card, access)
        ):
            raise KernelError(
                "PLANNING_NARRATIVE_INTELLIGENCE_DRIFT",
                "Frozen KnowledgeCard is no longer production eligible",
            )
        return card

    def list_packs(
        self,
        *,
        project_id: str,
        target_asset_version_id: str = "",
        knowledge_pack_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        _validate(project_id, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT pack.knowledge_pack_id, pack.project_id,
                       pack.workspace_id, pack.asset_version_id,
                       pack.target_asset_version_id,
                       pack.created_by_operation_id,
                       pack.selector_policy_version,
                       pack.selector_policy_hash, pack.selection_hash,
                       pack.item_count, pack.status,
                       version.lifecycle, version.eligibility,
                       version.governance, version.content,
                       operation.status, pack.created_at
                FROM authority_mkaos_knowledge_pack AS pack
                JOIN authority_asset_version AS version
                  ON version.asset_version_id = pack.asset_version_id
                JOIN authority_operation AS operation
                  ON operation.operation_id = pack.created_by_operation_id
                WHERE pack.project_id = %s
                  AND (%s = '' OR pack.target_asset_version_id = %s)
                  AND (%s = '' OR pack.knowledge_pack_id = %s)
                ORDER BY pack.created_at DESC, pack.knowledge_pack_id
                LIMIT %s
                """,
                [
                    project_id,
                    target_asset_version_id,
                    target_asset_version_id,
                    knowledge_pack_id,
                    knowledge_pack_id,
                    limit,
                ],
            )
            rows = uow.cursor.fetchall()
        keys = (
            "knowledge_pack_id",
            "project_id",
            "workspace_id",
            "asset_version_id",
            "target_asset_version_id",
            "created_by_operation_id",
            "selector_policy_version",
            "selector_policy_hash",
            "selection_hash",
            "item_count",
            "pack_status",
            "lifecycle",
            "eligibility",
            "governance",
            "content",
            "operation_status",
            "created_at",
        )
        return [dict(zip(keys, row, strict=True)) for row in rows]

    def list_planning_usage(
        self,
        *,
        project_id: str,
        book_id: str = "",
        knowledge_card_asset_version_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:

        _validate(project_id, limit)
        with AuthorityUnitOfWork(self.database_url) as uow:
            uow.cursor.execute(
                """
                SELECT context_output.operation_id,
                       context_version.asset_version_id,
                       context_version.content_hash,
                       context_version.content,
                       operation.status,
                       candidate_output.asset_version_id,
                       candidate_version.content,
                       binding.binding_id, binding.execution_scope,
                       binding.freshness, context_output.created_at,
                       COALESCE((
                           SELECT jsonb_agg(jsonb_build_object(
                               'external_effect_id', effect.external_effect_id,
                               'status', effect.status,
                               'provider', effect.provider,
                               'model_id', effect.model_id,
                               'selection_digest', effect.request_payload #>> '{input,narrative_intelligence,selection_digest}'
                           ))
                           FROM authority_external_effect effect
                           WHERE effect.operation_id=context_output.operation_id
                             AND effect.project_id=context_asset.project_id
                             AND effect.effect_type='model.invoke'
                             AND effect.status='SUCCEEDED'
                             AND effect.request_payload #>> '{input,narrative_intelligence,selection_digest}'=
                                 context_version.content #>> '{narrative_intelligence,selection_digest}'
                       ), '[]'::jsonb)
                FROM authority_operation_output_asset AS context_output
                JOIN authority_asset_version AS context_version
                  ON context_version.asset_version_id=
                     context_output.asset_version_id
                JOIN authority_asset AS context_asset
                  ON context_asset.asset_id=context_version.asset_id
                JOIN authority_operation AS operation
                  ON operation.operation_id=context_output.operation_id
                LEFT JOIN authority_operation_output_asset AS candidate_output
                  ON candidate_output.operation_id=context_output.operation_id
                 AND candidate_output.output_key='story_planning.candidate'
                LEFT JOIN authority_asset_version AS candidate_version
                  ON candidate_version.asset_version_id=
                     candidate_output.asset_version_id
                LEFT JOIN story_plan_binding AS binding
                  ON binding.project_id=context_asset.project_id
                 AND binding.asset_version_id=candidate_output.asset_version_id
                WHERE context_asset.project_id=%s
                  AND context_output.output_key='planning.context_bundle'
                  AND context_version.content->>'schema_version'=
                      'novelos.planning_context_bundle.v1'
                  AND (%s='' OR context_version.content->>'book_id'=%s)
                  AND (%s='' OR EXISTS (
                      SELECT 1 FROM jsonb_array_elements(
                          COALESCE(context_version.content->'narrative_intelligence'->'selected', '[]'::jsonb)
                      ) AS selected_card
                      WHERE selected_card->>'knowledge_card_asset_version_id'=%s
                  ))
                ORDER BY context_output.created_at DESC,
                         context_version.asset_version_id
                LIMIT %s
                """,
                [project_id, book_id, book_id, knowledge_card_asset_version_id,
                 knowledge_card_asset_version_id, limit],
            )
            rows = uow.cursor.fetchall()
        usage: list[dict[str, Any]] = []
        for row in rows:
            context = dict(row[3] or {})
            selection = context.get("narrative_intelligence")
            if not isinstance(selection, dict):
                continue
            need = selection.get("need")
            if not isinstance(need, dict):
                need = {}
            candidate_content = dict(row[6] or {})
            evidence = dict(candidate_content.get("execution_evidence") or {})
            for item in selection.get("selected") or ():
                if not isinstance(item, dict):
                    continue
                if knowledge_card_asset_version_id and item.get("knowledge_card_asset_version_id") != knowledge_card_asset_version_id:
                    continue
                selected_content = dict(item.get("selected_content") or {})
                translations = [
                    translation for translation in candidate_content.get("knowledge_translations") or ()
                    if isinstance(translation, dict) and translation.get("knowledge_card_asset_version_id") == item.get("knowledge_card_asset_version_id")
                ]
                usage.append(
                    {
                        "project_id": project_id,
                        "book_id": str(context.get("book_id") or ""),
                        "planning_stage": str(need.get("target_stage") or ""),
                        "planning_operation_id": str(row[0]),
                        "planning_operation_status": str(row[4]),
                        "context_bundle_asset_version_id": str(row[1]),
                        "context_bundle_content_hash": str(row[2]),
                        "selection_digest": str(
                            selection.get("selection_digest") or ""
                        ),
                        "knowledge_card_asset_version_id": str(
                            item.get("knowledge_card_asset_version_id") or ""
                        ),
                        "repetition_key": str(
                            selected_content.get("repetition_key") or ""
                        ),
                        "candidate_asset_version_id": str(row[5] or ""),
                        "plan_binding_id": str(row[7] or ""),
                        "plan_execution_scope": str(row[8] or ""),
                        "plan_freshness": str(row[9] or ""),
                        "applicability_assessment": dict(item.get("applicability_assessment") or {}),
                        "knowledge_translations": translations,
                        "usage_states": {
                            "selected": True,
                            "delivered": bool(row[11]),
                            "claimed_adoption": any(translation.get("decision") in {"ADOPT", "ADAPT"} for translation in translations),
                            "prose_verified": False,
                            "independent_review_accepted": False,
                        },
                        "usage_evidence_ceiling": "PLANNING_CLAIM_NOT_PROSE_VERIFICATION",
                        "delivery_receipts": list(row[11] or []),
                        "consumption_status": (
                            "REAL_PROVIDER_CONSUMED"
                            if evidence.get("real_provider_proven") is True
                            else "FIXTURE_PROTOCOL_USED"
                            if evidence.get("fixture_protocol_only") is True
                            else "PLANNING_CANDIDATE_MATERIALIZED"
                            if row[5]
                            else "CONTEXT_FROZEN"
                        ),
                        "selected_at": row[10],
                    }
                )
                if len(usage) >= limit:
                    return usage
        return usage

    def require_pack(
        self, *, project_id: str, knowledge_pack_id: str
    ) -> dict[str, Any]:
        if not knowledge_pack_id:
            raise ValueError("knowledge_pack_id is required")
        matches = self.list_packs(
            project_id=project_id,
            knowledge_pack_id=knowledge_pack_id,
            limit=1,
        )
        if not matches:
            raise KernelError(
                "MKAOS_PACK_NOT_FOUND", "KnowledgePack does not exist in project"
            )
        with AuthorityUnitOfWork(self.database_url) as uow:
            MkaosAuthorityRepository(uow.cursor).knowledge_cards(
                project_id=project_id, asset_version_ids=tuple(_pack_items(matches[0]))
            )
        return matches[0]

    def diff_packs(
        self,
        *,
        project_id: str,
        knowledge_pack_id: str,
        against_knowledge_pack_id: str,
    ) -> dict[str, Any]:
        current = self.require_pack(
            project_id=project_id, knowledge_pack_id=knowledge_pack_id
        )
        baseline = self.require_pack(
            project_id=project_id, knowledge_pack_id=against_knowledge_pack_id
        )
        current_items = _pack_items(current)
        baseline_items = _pack_items(baseline)
        added = sorted(set(current_items) - set(baseline_items))
        removed = sorted(set(baseline_items) - set(current_items))
        changed = sorted(
            identity
            for identity in set(current_items) & set(baseline_items)
            if current_items[identity] != baseline_items[identity]
        )
        unchanged = sorted(
            identity
            for identity in set(current_items) & set(baseline_items)
            if current_items[identity] == baseline_items[identity]
        )
        current_lineage = dict(current["content"].get("lineage") or {})
        baseline_lineage = dict(baseline["content"].get("lineage") or {})
        return {
            "schema_version": "mkaos-knowledge-pack-diff.v1",
            "project_id": project_id,
            "knowledge_pack_id": knowledge_pack_id,
            "against_knowledge_pack_id": against_knowledge_pack_id,
            "target_changed": (
                current["target_asset_version_id"]
                != baseline["target_asset_version_id"]
            ),
            "selector_policy_changed": (
                current["selector_policy_version"]
                != baseline["selector_policy_version"]
                or current["selector_policy_hash"] != baseline["selector_policy_hash"]
            ),
            "directly_supersedes_baseline": (
                current_lineage.get("supersedes_pack_asset_version_id")
                == baseline["asset_version_id"]
            ),
            "baseline_directly_supersedes_current": (
                baseline_lineage.get("supersedes_pack_asset_version_id")
                == current["asset_version_id"]
            ),
            "added": [current_items[identity] for identity in added],
            "removed": [baseline_items[identity] for identity in removed],
            "changed": [
                {
                    "knowledge_card_asset_version_id": identity,
                    "before": baseline_items[identity],
                    "after": current_items[identity],
                }
                for identity in changed
            ],
            "unchanged_count": len(unchanged),
        }

    def list_runtime_usage(
        self, *, project_id: str, book_id: str = "",
        target_capability_id: str = "", result_asset_version_id: str = "",
        knowledge_card_asset_version_id: str = "", limit: int = 100,
    ) -> list[dict[str, Any]]:
        from .runtime_usage import list_runtime_usage

        _validate(project_id, limit)
        return list_runtime_usage(
            self.database_url, project_id=project_id, book_id=book_id,
            target_capability_id=target_capability_id,
            result_asset_version_id=result_asset_version_id,
            knowledge_card_asset_version_id=knowledge_card_asset_version_id, limit=limit,
        )

    def list_runtime_selections(
        self, *, project_id: str, book_id: str = "",
        target_capability_id: str = "", knowledge_card_asset_version_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        from .runtime_usage import list_runtime_selections

        _validate(project_id, limit)
        return list_runtime_selections(
            self.database_url, project_id=project_id, book_id=book_id,
            target_capability_id=target_capability_id,
            knowledge_card_asset_version_id=knowledge_card_asset_version_id, limit=limit,
        )


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _validate(project_id: str, limit: int) -> None:
    if not project_id or limit < 1 or limit > 500:
        raise ValueError("project_id and a limit between 1 and 500 are required")


def _recheck_card_qualifications(database_url: str, *, project_id: str,
                                cards: list[dict[str, Any]], cursor: Any) -> None:
    from novel_forge.modules.provider_qualification.source_binding import source_runtime_qualifications_current
    from novel_forge.modules.provider_qualification.domain import request_hash
    requests = {}
    for card in cards:
        content = card.get("content") or {}
        binding = (content.get("source_policy") or {}).get("provider_runtime_qualification")
        if binding:
            card["runtime_qualification_current"] = False
            if isinstance(binding, dict):
                requests[str(card["asset_version_id"])] = {
                    "workspace_id": card["workspace_id"],
                    "execution_asset_version_id": binding.get("execution_asset_version_id"),
                    "execution_content_hash": binding.get("execution_content_hash"),
                    "candidate_payload_hash": request_hash(content.get("abstract_content") or {}), "frozen": binding,
                }
    current = source_runtime_qualifications_current(database_url, project_id=project_id, requests=requests, approval_cursor=cursor)
    for card in cards:
        if str(card["asset_version_id"]) in current:
            card["runtime_qualification_current"] = current[str(card["asset_version_id"])]


def _context_eligible_card(
    card: dict[str, Any], access: dict[str, Any]
) -> bool:
    if card.get("runtime_qualification_current") is False:
        return False
    content = card.get("content")
    policy = content.get("source_policy") if isinstance(content, dict) else None
    if not (
        isinstance(policy, dict)
        and policy.get("knowledge_card_context_eligible") is True
        and policy.get("raw_source_expression_included") is False
        and policy.get("source_chunks_direct_context_eligible") is False
        and policy.get("fixture_protocol_only") is False
    ):
        return False
    approval_class = str(policy.get("approval_class") or "PRODUCTION")
    usage_scope = str(access.get("usage_scope") or "PRODUCTION")
    if usage_scope == "EXPERIMENTAL_VALIDATION":
        activation_scope = dict(policy.get("activation_scope") or {})
        return bool(
            access.get("mode") == "ALLOW_ONLY"
            and approval_class == "EXPERIMENTAL_VALIDATION"
            and policy.get("review_class")
            == "EXPERIMENTAL_POLICY_APPROVAL_NOT_HUMAN"
            and policy.get("production_context_eligible") is False
            and policy.get("experimental_context_eligible") is True
            and policy.get("approval_policy_version")
            == access.get("experimental_policy_version")
            and activation_scope.get("kind") == "ISOLATED_PROJECT_AND_WORKSPACE"
            and activation_scope.get("project_id") == card.get("project_id")
            and activation_scope.get("workspace_id") == card.get("workspace_id")
        )
    return bool(
        approval_class == "PRODUCTION"
        and policy.get("production_context_eligible", True) is True
    )


def _pack_items(pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    content = dict(pack.get("content") or {})
    items = content.get("items")
    if not isinstance(items, list):
        raise KernelError(
            "MKAOS_PACK_CONTENT_INVALID",
            "KnowledgePack does not expose its immutable item composition",
        )
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            raise KernelError(
                "MKAOS_PACK_CONTENT_INVALID",
                "KnowledgePack item composition is malformed",
            )
        identity = str(item.get("knowledge_card_asset_version_id") or "")
        if not identity or identity in result:
            raise KernelError(
                "MKAOS_PACK_CONTENT_INVALID",
                "KnowledgePack item identities are incomplete or duplicated",
            )
        result[identity] = {
            "knowledge_card_asset_version_id": identity,
            "content_hash": str(item.get("content_hash") or ""),
            "usage_role": str(item.get("usage_role") or ""),
            "frozen_weight": str(item.get("frozen_weight") or ""),
            "ordinal": int(item.get("ordinal") or 0),
        }
    return result


__all__ = ["MkaosAuthorityQuery"]
