from __future__ import annotations

import json
from pathlib import Path

from novel_forge.tools.test_reality import check_test_reality


ROOT = Path(__file__).resolve().parents[2]


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _fixture_manifest() -> dict[str, object]:
    return {
        "schema_version": "novel-forge.test-reality-manifest.v1",
        "collections": ["tests/unit", "tests/integration"],
        "classification_rules": [
            {
                "id": "migration",
                "patterns": ["tests/integration/test_*migration*.py"],
                "classification": "MIGRATION_COMPATIBILITY",
                "owner": "migration-authority",
                "capability": "schema-evolution",
                "production_target": "src/novel_forge/storage/migrations/runner.py",
                "qualification_role": "COMPATIBILITY_ONLY",
                "proof_ceiling": "MIGRATION_COMPATIBILITY_ONLY",
            },
            {
                "id": "unit",
                "patterns": ["tests/unit/test_*.py"],
                "classification": "CURRENT_DOMAIN_INVARIANT",
                "owner": "AUTO_FROM_PRODUCTION_TARGET",
                "capability": "current-domain",
                "production_target": "AUTO_FROM_TEST_IMPORTS",
                "qualification_role": "CURRENT_BUSINESS_SUPPORT",
                "proof_ceiling": "CURRENT_CONTRACT_ONLY",
            },
        ],
        "semantic_slice_policy": {
            "current_slice": {
                "role": "CURRENT_BUSINESS_CAPABILITY",
                "proof_ceiling": "CURRENT_CONTRACT_ONLY",
            },
            "migration_matrix": {
                "role": "MIGRATION_COMPATIBILITY",
                "proof_ceiling": "MIGRATION_COMPATIBILITY_ONLY",
            },
        },
    }


def _fixture_repository(root: Path) -> None:
    _write(root / "src/novel_forge/example.py", "VALUE = 1\n")
    _write(root / "src/novel_forge/storage/migrations/runner.py", "MIGRATIONS = ()\n")
    _write(
        root / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE\n\ndef test_value():\n    assert VALUE == 1\n",
    )
    _write(
        root / "tests/integration/test_schema_migration_postgres.py",
        "def test_migration():\n    assert True\n",
    )
    _write(
        root / "architecture/manifests/test-manifest.yaml",
        json.dumps(_fixture_manifest()),
    )
    qualification = {
        "semantic_slices": {
            "current_slice": ["tests/unit/test_example.py"],
            "migration_matrix": [
                "tests/integration/test_schema_migration_postgres.py"
            ],
        }
    }
    _write(
        root / "architecture/manifests/backend-qualification-manifest.yaml",
        json.dumps(qualification),
    )


def test_repository_tests_have_one_reality_class_and_no_historical_authority() -> None:
    report = check_test_reality(ROOT)

    assert report["status"] == "PASS", report["errors"]
    assert sum(report["classification_file_counts"].values()) == report["test_file_count"]
    assert report["classification_file_counts"]["HISTORICAL_REDUNDANT"] == 0
    assert report["unclassified_files"] == []


def test_unclassified_test_fails_closed(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    _write(tmp_path / "tests/other/test_hidden.py", "def test_hidden(): pass\n")

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert report["unclassified_files"] == ["tests/other/test_hidden.py"]


def test_current_capability_cannot_be_supported_only_by_migration_evidence(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    qualification_path = (
        tmp_path / "architecture/manifests/backend-qualification-manifest.yaml"
    )
    qualification = json.loads(qualification_path.read_text(encoding="utf-8"))
    qualification["semantic_slices"]["current_slice"] = [
        "tests/integration/test_schema_migration_postgres.py"
    ]
    qualification_path.write_text(json.dumps(qualification), encoding="utf-8")

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert (
        "current semantic slice has no current-behavior evidence: current_slice"
        in report["errors"]
    )


def test_fixture_evidence_cannot_be_promoted_to_real_provider_proof(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    manifest_path = tmp_path / "architecture/manifests/test-manifest.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["semantic_slice_policy"]["current_slice"]["proof_ceiling"] = (
        "REAL_PROVIDER_PROVEN"
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert (
        "semantic slice has unsupported proof ceiling: current_slice"
        in report["errors"]
    )


def test_retained_historical_redundant_test_is_rejected(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    manifest_path = tmp_path / "architecture/manifests/test-manifest.yaml"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["classification_rules"].insert(
        0,
        {
            "id": "historical",
            "patterns": ["tests/unit/test_example.py"],
            "classification": "HISTORICAL_REDUNDANT",
            "owner": "none",
            "capability": "none",
            "production_target": "src/novel_forge/example.py",
            "qualification_role": "FORBIDDEN",
            "proof_ceiling": "NONE",
        },
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert (
        "historical redundant tests must be deleted: tests/unit/test_example.py"
        in report["errors"]
    )
