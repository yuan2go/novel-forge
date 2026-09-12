"""TEST: Explicit volume repair retains review gates and appends exact Source processing."""

from copy import deepcopy

import psycopg

from tests.integration.authority_postgres_support import DATABASE_URL
from tests.integration.test_corpus_ingestion_postgres import _manifest, _runtime
from tests.unit.test_corpus_nonbody_review_replay import volume_fixture

pytest_plugins = ["tests.integration.test_corpus_foundation_postgres"]
BASE = "/product/source-imports/corpus"


def test_native_volume_repair_then_nonbody_review_preserves_exact_source(corpus, tmp_path, monkeypatch):
    _, scheduler = _runtime(tmp_path, monkeypatch)
    path, original, revised = volume_fixture(tmp_path)
    request = corpus.client.post(BASE, json={"project_id": corpus.project, "workspace_id": corpus.workspace,
        "run_key": "original-nonbody", "manifest": {**_manifest(path), "parser": original}})
    assert request.status_code == 202, request.text
    acquired = scheduler.run_or_recover(operation_id=request.json()["operation_id"], project_id=corpus.project)
    imported = scheduler.run_or_recover(operation_id=acquired["result"]["children"][0]["operation_id"], project_id=corpus.project)["result"]

    def inspect(processing):
        response = corpus.client.get(BASE + "/processing/" + processing, params={"project_id": corpus.project})
        assert response.status_code == 200, response.text
        return response.json()

    def reprocess(key):
        response = corpus.client.post(BASE + "/reprocess", json={"project_id": corpus.project,
            "edition_id": imported["edition_id"], "run_key": key, "parser": revised})
        assert response.status_code == 202, response.text
        result = scheduler.run_or_recover(operation_id=response.json()["operation_id"], project_id=corpus.project)
        assert result["status"] == "SUCCEEDED", result
        return result["result"]

    before = inspect(imported["processing_id"])
    frozen_before = deepcopy(before["assessment"])
    assert sum(f["blocking"] for f in frozen_before["issues"]) == 2
    adjusted = reprocess("volume-boundaries-v2")
    candidate = inspect(adjusted["processing_id"])
    blockers = [f for f in candidate["assessment"]["issues"] if f["blocking"]]
    current_ids = {row["unit_id"] for row in candidate["assessment"]["units"]}
    assert len(blockers) == 2
    assert all(f["code"] == "NON_BODY_UNIT" and f["evidence"][0]["unit_id"] in current_ids for f in blockers)
    assert candidate["assessment"]["structure_usable"] is False
    assert candidate["assessment"]["coverage"] == "REVIEW_REQUIRED"
    review = corpus.run({"action": "review_processing", "processing_id": adjusted["processing_id"],
        "decisions": [{"issue_id": f["issue_id"], "resolution": "MARK_NON_BODY",
                       "reason": "Synthetic structural fixture; exclude publisher/license occurrence, not independent human review",
                       "evidence_refs": ["fixture:original-authored-span"]} for f in blockers],
        "reason": "Synthetic operator review of exact nonbody ranges"})
    assert review["assessment"]["requires_reprocessing"]
    assert not review["assessment"]["structure_usable"]
    final = reprocess("apply-exact-nonbody-review-v3")
    active = inspect(final["processing_id"])
    assessment = active["assessment"]
    assert assessment["structure_usable"] is True
    assert assessment["coverage"] == "UNKNOWN"
    assert sum(row.get("excluded_from_analysis", False) for row in assessment["units"]) == 2
    chapters = [row for row in assessment["units"] if row["kind"] == "CHAPTER"]
    boundaries = [b for b in revised["normalization"]["boundaries"] if b["kind"] == "CHAPTER"]
    assert [(row["locator"]["original_byte_offset"], row["locator"]["original_byte_end"]) for row in chapters] == [(b["start"], b["end"]) for b in boundaries]
    assert active["parent_id"] == adjusted["processing_id"]
    assert inspect(imported["processing_id"])["assessment"] == frozen_before
    replay = corpus.client.post(BASE + "/reprocess", json={"project_id": corpus.project,
        "edition_id": imported["edition_id"], "run_key": "apply-exact-nonbody-review-v3", "parser": revised})
    assert replay.status_code == 202 and replay.json()["replayed"]
    with psycopg.connect(DATABASE_URL) as connection:
        assert connection.execute("SELECT count(*) FROM authority_corpus_processing WHERE project_id=%s", [corpus.project]).fetchone()[0] == 3
        assert connection.execute("SELECT count(*) FROM authority_external_effect WHERE project_id=%s AND provider='production_execution_gateway'", [corpus.project]).fetchone()[0] == 0
