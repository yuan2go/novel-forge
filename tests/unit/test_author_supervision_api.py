from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from novel_forge.modules.authority_security import Principal, PrincipalType
from tests.unit.test_planning_runtime_continuation_api import _client, _principal, _RESOLVER


@dataclass
class ReviewResult:
    literary_qualification: str = "NOT_PROVEN"


@pytest.mark.parametrize("wrong", [None, "book", "hash", "strict", "author"])
def test_author_review_resolves_native_evaluator_and_exact_candidate(wrong):
    operator = _principal()
    evaluator = Principal("configured-reviewer", PrincipalType.SERVICE, frozenset({"narrative_design.evaluate"}), frozenset({"project:1"}), "test")
    planning = Mock()
    planning.require_candidate.return_value = {"project_id":"project:1", "workspace_id":"workspace:1", "book_id":"book:other" if wrong=="book" else "book:1",
        "content_hash":"sha256:"+"a"*64, "generation_operation_id":"generated:1", "generator_operation_name":"creative.candidates.generate"}
    planning.story_design.require.return_value = {"qualification":"QUALIFIED" if wrong=="strict" else "STRUCTURALLY_VALID",
        "execution_evidence":{"author_supervision":{"mode":"AUTHOR_SUPERVISED", "author_id":"other" if wrong=="author" else operator.principal_id}}}
    planning.evaluate_candidate.return_value = ReviewResult()
    resolver = SimpleNamespace(resolve_api_principal=lambda:operator, resolve_narrative_evaluator_principal=lambda:evaluator)
    with patch(_RESOLVER, return_value=resolver), _client(planning) as client:
        response = client.post("/product/production/book-authority/books/book:1/planning-candidates/candidate:1/model-reviews",
            json={"project_id":"project:1","content_hash":"sha256:"+("b" if wrong=="hash" else "a")*64,"idempotency_key":"review-original-key"})
    if wrong:
        assert response.status_code == (403 if wrong=="author" else 409), response.text
        planning.evaluate_candidate.assert_not_called()
    else:
        assert response.status_code == 200, response.text
        command = planning.evaluate_candidate.call_args.args[0]
        assert command.actor_id == "configured-reviewer"
        assert command.generation_operation_id == "generated:1"
        assert command.idempotency_key == "review-original-key"
        assert command.evaluator_execution_class == "MODEL_PROVIDER"
        assert planning.evaluate_candidate.call_args.kwargs["transition_principal"] == operator
