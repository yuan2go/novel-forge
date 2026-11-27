from __future__ import annotations

from dataclasses import dataclass

from novel_forge.modules.authority_handler_runtime import AuthorityHandlerOutput, AuthorityHandlerRequest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.storage.authority_uow import AuthorityUnitOfWork

from .contracts import ReaderOutcomeModelPort
from .screenplay import CANDIDATE_TYPE, REVIEW_TYPE, SOURCE_TYPE, require_source, validate_candidate, validate_review


def require_validated_source(uow, *, project_id: str, source: dict) -> None:
    require_source(source)
    from .screenplay_sources import accepted_source_evidence
    if source.get("accepted_source_evidence") != accepted_source_evidence(uow, project_id=project_id, source=source):
        raise KernelError("SCREENPLAY_SOURCE_EVIDENCE_INVALID", "Frozen source must retain its exact accepted narrative and knowledge evidence")
    if "character_display" in source:
        from .screenplay_sources import accepted_character_display
        if source["character_display"] != accepted_character_display(uow, project_id=project_id, source=source):
            raise KernelError("SCREENPLAY_CHARACTER_SOURCE_INVALID", "Display names must retain the exact accepted Cast and Chapter sources")
    if source["schema_version"] == "screenplay-source.v2":
        from .screenplay_craft import freeze_screenplay_craft
        if source.get("screenplay_craft") != freeze_screenplay_craft(uow, source=source):
            raise KernelError("SCREENPLAY_CRAFT_SOURCE_DRIFT", "The exact approved Card or Book access policy changed")


@dataclass(frozen=True, slots=True)
class ScreenplayHandler:
    model_port: ReaderOutcomeModelPort
    stage: str

    def __post_init__(self) -> None:
        if not getattr(self.model_port, "external_effect_backed", False):
            raise ValueError("Screenplay generation and review require native ExternalEffect transport")

    def execute(self, request: AuthorityHandlerRequest) -> AuthorityHandlerOutput:
        source_asset = request.require_input(SOURCE_TYPE)
        source = source_asset.content
        require_source(source)
        if source["source_digest"] != request.command["payload"].get("source_digest"):
            raise KernelError("SCREENPLAY_SOURCE_DRIFT", "Operation and source contract must agree")
        predecessor = request.require_input(CANDIDATE_TYPE) if self.stage != "screenplay_generate" else None
        if predecessor and predecessor.content.get("source_asset_version_id") != source_asset.asset_version_id:
            raise KernelError("SCREENPLAY_CANDIDATE_SCOPE_INVALID", "A candidate cannot be reviewed or revised against another source")
        review = request.require_input(REVIEW_TYPE) if self.stage == "screenplay_revision" else None
        if review and (review.content.get("candidate_asset_version_id") != predecessor.asset_version_id
                       or review.content.get("verdict") != "REVISE"):
            raise KernelError("SCREENPLAY_REVISION_REVIEW_REQUIRED", "Revision consumes the exact native review requesting changes")
        round_number = int(predecessor.content.get("revision_round", 0)) + 1 if review else 0
        if round_number > source["policy"]["max_revision_rounds"]:
            raise KernelError("SCREENPLAY_REVISION_EXHAUSTED", "Retain the rejected candidate and review when the approved revision bound is exhausted")

        def check_source():
            with AuthorityUnitOfWork(self.model_port.database_url) as uow:
                require_validated_source(uow, project_id=request.project_id, source=source)

        check_source()
        result = self.model_port.invoke(request, stage=self.stage,
            payload={"book_id": source["book_id"], "source_digest": source["source_digest"],
                     "candidate_digest": predecessor.content.get("candidate_digest", "") if predecessor else "",
                     **({"screenplay_source_contract": source["schema_version"]} if source["schema_version"] == "screenplay-source.v2" else {})},
            reservation_tokens=source["policy"]["context_token_budget"], pre_send_assertion=check_source)
        if self.stage == "screenplay_review":
            content = validate_review(result.output, source, predecessor.content)
            content["candidate_asset_version_id"] = predecessor.asset_version_id
            asset_type = REVIEW_TYPE
        else:
            content = validate_candidate(result.output, source)
            content.update(revision_round=round_number,
                           predecessor_candidate_asset_version_id=predecessor.asset_version_id if predecessor else "",
                           revision_review_asset_version_id=review.asset_version_id if review else "")
            asset_type = CANDIDATE_TYPE
        content.update(book_id=source["book_id"], source_revision_id=source["source_revision_id"],
                       source_asset_version_id=source_asset.asset_version_id, publication_authorized=False)
        references = [source_asset.asset_version_id]
        references.extend(item.asset_version_id for item in (predecessor, review) if item is not None)
        return AuthorityHandlerOutput(asset_type=asset_type, output_key=self.stage + ".result", role="primary",
            content=content, qualification_policy="scene-screenplay.v1", reference_asset_version_ids=tuple(references),
            evidence={"model_evidence": result.to_evidence(), "novel_canon_mutation_allowed": False,
                      "literary_or_human_qualification": "NOT_ESTABLISHED"})
