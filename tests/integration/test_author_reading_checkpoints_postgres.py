from copy import deepcopy
from dataclasses import replace
import json
import time

import pytest

from novel_forge.modules.authority_security import PrincipalType
from novel_forge.modules.content_authority import ContentAuthorityApplication
from novel_forge.modules.content_authority.codecs import CONTENT_CODECS
from scripts.creation_checkpoints import decide_reading_review, reading_review_template, register_reading_review, require_reading_decision
from scripts.creation_reading import load_accepted_reading
from scripts.run_world_production_smoke import drive, export
from tests.integration.authority_postgres_support import DATABASE_URL, ensure_migrated, transaction


def test_native_twelve_chapter_reading_gates_resume_and_export_preserve_accepted_history(request, monkeypatch, tmp_path):
    from tests.integration import operator_plan_change_support as fixture
    from tests.integration import test_core_functional_loops_postgres as core
    ensure_migrated()
    original = fixture.execute_operator_plan_change_vertical
    decisions = {}
    records = []

    def review_checkpoint(composition, book_run_id, boundary, *, exercise_issues=False):
        principal = replace(composition.principal, principal_type=PrincipalType.LOCAL_OPERATOR,
                            permissions=composition.principal.permissions | {"content.authority.execute", "content.operation:chapter.operator_checklist.author"})
        operator = replace(composition, principal=principal)
        manifest = load_accepted_reading(composition=operator, book_run_id=book_run_id, require_closed_groups=True)
        assert manifest["accepted_through_chapter"] == boundary
        review = reading_review_template(manifest)
        review.update(status="REVIEWED", reviewer_id="scripted-fixture-editor", summary="Synthetic reading evidence tests native protocol; no independent human review")
        for assessment in review["chapter_assessments"]:
            chapter = manifest["chapters"][assessment["chapter_number"] - 1]
            assessment.update(assessment="The fixture checks this exact accepted passage and retains its stated consequence.",
                              locations=[{"start": 0, "end": min(20, len(chapter["text"])), "text": chapter["text"][:20]}])
        content = ContentAuthorityApplication(DATABASE_URL, application_build_id="operator-plan-fixture", commit_sha="e" * 40, integration_proven=CONTENT_CODECS)
        key = f"{book_run_id}:author-reading:{boundary}:{manifest['book_version']}"
        if exercise_issues:
            review["issues"] = [{"issue_id": "fixture-reading-preservation", "chapter_number": 6, "status": "OPEN",
                                 "severity": "major", "repair_target": "Reassess this exact accepted consequence without modifying history",
                                 "location": {"start": 0, "end": 20, "text": manifest["chapters"][5]["text"][:20]},
                                 "diagnosis": "Fixture diagnosis remains unresolved", "preservation_requirements": ["Retain exact accepted history"],
                                 "acceptance_criteria": ["Record a grounded reassessment before proceeding"]}]
            blocked = register_reading_review(composition=operator, content_application=content, book_run_id=book_run_id,
                                             review=review, idempotency_key=key + ":open")
            with pytest.raises(ValueError, match="Unresolved"):
                decide_reading_review(composition=operator, book_run_id=book_run_id,
                                      review_asset_version_id=blocked["review_asset_version_id"], decision="APPROVE",
                                      reason="Cannot approve unresolved evidence", idempotency_key=key + ":denied")
            missing = {**review, "issues": []}
            with pytest.raises(ValueError, match="cannot disappear"):
                register_reading_review(composition=operator, content_application=content, book_run_id=book_run_id,
                                        review=missing, idempotency_key=key + ":omitted")
            review["issues"][0].update(status="RESOLVED", resolution_evidence=[{
                "evidence_class": "SCRIPTED_FIXTURE_REASSESSMENT", "text_hash": manifest["chapters"][5]["text_hash"],
                "chapter_number": 6, "candidate_asset_version_id": manifest["chapters"][5]["candidate_asset_version_id"],
                "location": review["issues"][0]["location"], "preservation_check": "The quoted accepted history remains exact",
                "reason": "Explicit fixture reassessment; it proves persistence only",
            }])
        registered = register_reading_review(composition=operator, content_application=content, book_run_id=book_run_id,
                                            review=review, idempotency_key=key + ":reviewed")
        replay = register_reading_review(composition=operator, content_application=content, book_run_id=book_run_id,
                                        review=deepcopy(review), idempotency_key=key + ":reviewed")
        assert replay["review_asset_version_id"] == registered["review_asset_version_id"]
        command = dict(composition=operator, book_run_id=book_run_id, review_asset_version_id=registered["review_asset_version_id"],
                       decision="APPROVE", reason="Fixture AI_OPERATOR_AUTOMATION decision; independent human NOT_REVIEWED",
                       idempotency_key=key + ":decision")
        decision = decide_reading_review(**command)
        assert decide_reading_review(**command)["replayed"] is True
        decisions[boundary] = decision["result"]["decision_version_id"] if "result" in decision else decision["decision_version_id"]
        verified = require_reading_decision(composition=operator, book_run_id=book_run_id, boundary=boundary,
                                           decision_version_id=decisions[boundary])
        assert verified["independent_human_review"] == "NOT_REVIEWED"
        assert verified["reading_manifest_hash"] == manifest["manifest_hash"]
        if boundary == 3:
            paused = composition.authority.require(book_run_id)
            assert paused["state"] == "PAUSED"
            composition.authority.resume(
                book_run_id, principal=composition.principal,
                expected_version=paused["version"],
                reason="Fixture explicit continuation after the approved chapter-3 reading checkpoint",
            )

    def exercise(**arguments):
        result = original(**arguments, checkpoint_observer=review_checkpoint)
        composition, chapter = arguments["composition"], arguments["chapter"]
        book_run_id = result["book_run_id"]
        assert result["accepted_chapters"] == 6 and result["checkpoint_chapter"] == 3
        with transaction() as connection:
            accepted_before = connection.execute("SELECT chapter_number,chapter_outcome_asset_version_id,story_state_asset_version_id,canon_snapshot_asset_version_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s ORDER BY chapter_number", [book_run_id]).fetchall()
        worker = replace(composition.principal, principal_id="author-checkpoint-fixture-worker", principal_type=PrincipalType.WORKER)
        def run(boundary):
            return drive(composition=composition, chapter=chapter, book_run_id=book_run_id, worker=worker,
                         events=records.append, maximum_ticks=240, deadline=time.monotonic() + 480,
                         pilot_stop_after_chapter=12, checkpoints=(3, 6, 9, 12), resume_after_checkpoint=boundary,
                         checkpoint_review_decision_id=decisions.get(boundary, ""))
        assert run(6) == "AUTHOR_READING_REVIEW_REQUIRED"
        with transaction() as connection:
            assert connection.execute("SELECT COUNT(*) FROM authority_book_chapter_request WHERE book_run_id=%s AND chapter_number>6", [book_run_id]).fetchone() == (0,)
        review_checkpoint(composition, book_run_id, 6, exercise_issues=True)
        checkpoint = composition.authority.require(book_run_id)
        composition.authority.resume(book_run_id, principal=composition.principal, expected_version=checkpoint["version"],
                                     reason="Fixture explicit approved continuation before operator interrupts")
        composition.authority.pause(book_run_id, principal=composition.principal, reason="Operator STOP after earlier approved continuation")
        assert run(6) == "AUTHOR_READING_PAUSE_VERSION_CHANGED"
        with transaction() as connection:
            assert connection.execute("SELECT COUNT(*) FROM authority_book_chapter_request WHERE book_run_id=%s AND chapter_number>6", [book_run_id]).fetchone() == (0,)
        review_checkpoint(composition, book_run_id, 6, exercise_issues=True)
        assert run(6) == "AUTHOR_READING_CHECKPOINT_REQUIRED", records[-5:]
        assert composition.authority.require(book_run_id)["accepted_through_chapter"] == 9
        review_checkpoint(composition, book_run_id, 9)
        assert run(9) == "PILOT_ACCEPTED_CURSOR_REACHED", records[-5:]
        book = composition.authority.require(book_run_id)
        assert book["accepted_through_chapter"] == 12 and book["state"] == "PAUSED"
        assert book["target_chapter_count"] == 180
        assert run(9) == "PILOT_ACCEPTED_CURSOR_REACHED"
        with transaction() as connection:
            assert connection.execute("SELECT chapter_number,chapter_outcome_asset_version_id,story_state_asset_version_id,canon_snapshot_asset_version_id FROM authority_book_chapter_acceptance WHERE book_run_id=%s AND chapter_number<=6 ORDER BY chapter_number", [book_run_id]).fetchall() == accepted_before
            assert connection.execute("SELECT COUNT(*) FROM authority_book_chapter_request WHERE book_run_id=%s AND chapter_number>12", [book_run_id]).fetchone() == (0,)
        from scripts.creation_checkpoint_review import main as checkpoint_cli
        monkeypatch.setenv("NOVEL_FORGE_APPLICATION_BUILD_ID", "operator-plan-fixture")
        monkeypatch.setenv("NOVEL_FORGE_COMMIT_SHA", "e" * 40)
        assert checkpoint_cli(["preview", "--project-id", book["project_id"], "--book-run-id", book_run_id,
                               "--output", str(tmp_path / "checkpoint-12")]) == 0
        template = json.loads((tmp_path / "checkpoint-12" / "review-template.json").read_text())
        assert template["status"] == "NOT_REVIEWED"
        assert [row["chapter_number"] for row in template["chapter_assessments"]] == [10, 11, 12]
        export(composition=composition, book_run_id=book_run_id, destination=tmp_path, include_artifacts=False)
        manifest = json.loads((tmp_path / "accepted-manuscript.json").read_text())
        assert len(manifest["chapters"]) == 12
        assert len({row["group_run_id"] for row in manifest["chapters"]}) == 4
        assert all(row["group_state"] == "COMPLETED" for row in manifest["chapters"])
        assert len(list((tmp_path / "reading").glob("chapter-*.md"))) == 12
        assert manifest["independent_human_review"] == "NOT_REVIEWED"
        (tmp_path / "reading-checkpoints.json").write_text(json.dumps({"events": records, "decisions": decisions, "proof_ceiling": "SCRIPTED_PROVIDER_ENGINEERING_ONLY"}, default=str, indent=2))
        return {**result, "accepted_chapters": 12, "pilot_stop_after_chapter": 12, "reading_decisions": decisions}

    monkeypatch.setattr(fixture, "execute_operator_plan_change_vertical", exercise)
    core.test_open_book_runs_foundation_search_and_snapshot_vertical_in_postgres(request, "long_novel_pilot")
