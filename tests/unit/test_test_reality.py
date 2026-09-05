from __future__ import annotations

import json
from pathlib import Path

import pytest

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
                "proof_ceiling": "IN_PROCESS_CONTRACT_ONLY",
            },
        ],
        "semantic_slice_policy": {
            "current_slice": {
                "role": "CURRENT_BUSINESS_CAPABILITY",
                "proof_ceiling": "CURRENT_CONTRACT_NO_REAL_PROVIDER",
                "direct_contract_targets": ["src/novel_forge/example.py"],
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
            "migration_matrix": ["tests/integration/test_schema_migration_postgres.py"],
        }
    }
    _write(
        root / "architecture/manifests/backend-qualification-manifest.yaml",
        json.dumps(qualification),
    )


def test_repository_tests_have_one_reality_class_and_no_historical_authority() -> None:
    report = check_test_reality(ROOT)

    assert report["status"] == "PASS", report["errors"]
    assert (
        sum(report["classification_file_counts"].values()) == report["test_file_count"]
    )
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
        "current semantic slice has no direct current-contract evidence: current_slice"
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


def _read_manifest(root: Path) -> dict[str, object]:
    return json.loads((root / "architecture/manifests/test-manifest.yaml").read_text())


def _save_manifest(root: Path, manifest: dict[str, object]) -> None:
    _write(root / "architecture/manifests/test-manifest.yaml", json.dumps(manifest))


def _set_current_slice(root: Path, paths: list[str]) -> None:
    path = root / "architecture/manifests/backend-qualification-manifest.yaml"
    payload = json.loads(path.read_text())
    payload["semantic_slices"]["current_slice"] = paths
    _write(path, json.dumps(payload))


def _record(report: dict[str, object], path: str) -> dict[str, object]:
    return next(record for record in report["files"] if record["path"] == path)


def test_direct_current_contract_passes_without_upgrading_evidence(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)

    report = check_test_reality(tmp_path)

    assert report["status"] == "PASS", report["errors"]
    assert report["semantic_slice_evidence"]["current_slice"][
        "direct_current_witnesses"
    ] == ["tests/unit/test_example.py"]
    assert _record(report, "tests/unit/test_example.py")["proof_ceiling"] == (
        "IN_PROCESS_CONTRACT_ONLY"
    )


def test_mock_only_current_slice_fails_and_retains_declared_metadata(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from unittest.mock import Mock\nfrom novel_forge.example import VALUE\n"
        "def test_value():\n    assert Mock(return_value=VALUE)() == 1\n",
    )

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    record = _record(report, "tests/unit/test_example.py")
    assert record["classification"] == "FIXTURE_PROTOCOL"
    assert record["declared_classification"] == "CURRENT_DOMAIN_INVARIANT"
    assert record["qualification_role"] == "FIXTURE_CONTRACT_ONLY"
    assert record["proof_ceiling"] == "FIXTURE_ONLY"
    assert record["declared_proof_ceiling"] == "IN_PROCESS_CONTRACT_ONLY"
    assert record["owner"] == "platform"
    assert record["production_targets"] == ["src/novel_forge/example.py"]
    assert record["current_semantic_evidence"] is False
    assert report["downgraded_fixture_files"] == ["tests/unit/test_example.py"]


def test_matching_direct_witness_supports_mock_contract_but_never_promotes_it(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_mock_example.py",
        "from unittest.mock import Mock\nfrom novel_forge.example import VALUE\n"
        "def test_value():\n    assert Mock(return_value=VALUE)() == 1\n",
    )
    _set_current_slice(tmp_path, ["tests/unit/test_mock_example.py"])

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    record = _record(report, "tests/unit/test_mock_example.py")
    assert record["classification"] == "CURRENT_DOMAIN_INVARIANT"
    assert record["direct_contract_witnesses"] == ["tests/unit/test_example.py"]
    assert record["current_semantic_evidence"] is False
    _set_current_slice(
        tmp_path, ["tests/unit/test_mock_example.py", "tests/unit/test_example.py"]
    )
    assert check_test_reality(tmp_path)["status"] == "PASS"


@pytest.mark.parametrize(
    "declared_target", ["AUTO_FROM_TEST_IMPORTS", "src/novel_forge/example.py"]
)
def test_unrelated_direct_witness_cannot_rescue_current_slice(
    tmp_path: Path,
    declared_target: str,
) -> None:
    _fixture_repository(tmp_path)
    _write(tmp_path / "src/novel_forge/unrelated.py", "VALUE = 2\n")
    _write(
        tmp_path / "tests/unit/test_unrelated.py",
        "from novel_forge.unrelated import VALUE\ndef test_value():\n    assert VALUE == 2\n",
    )
    manifest = _read_manifest(tmp_path)
    rule = dict(manifest["classification_rules"][1])
    rule.update(
        id="unrelated",
        patterns=["tests/unit/test_unrelated.py"],
        production_target=declared_target,
    )
    manifest["classification_rules"].insert(0, rule)
    _save_manifest(tmp_path, manifest)
    _set_current_slice(tmp_path, ["tests/unit/test_unrelated.py"])

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert (
        "current semantic slice lacks direct target evidence: current_slice:src/novel_forge/example.py"
        in report["errors"]
    )


def test_different_capability_does_not_witness_mock_domain_invariant(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_mock_example.py",
        "from unittest.mock import Mock\nfrom novel_forge.example import VALUE\n"
        "def test_value():\n    assert Mock(return_value=VALUE)() == 1\n",
    )
    manifest = _read_manifest(tmp_path)
    rule = dict(manifest["classification_rules"][1])
    rule.update(
        id="mock",
        patterns=["tests/unit/test_mock_example.py"],
        capability="other-capability",
    )
    manifest["classification_rules"].insert(0, rule)
    _save_manifest(tmp_path, manifest)

    report = check_test_reality(tmp_path)

    assert report["status"] == "PASS", report["errors"]
    assert (
        _record(report, "tests/unit/test_mock_example.py")["classification"]
        == "FIXTURE_PROTOCOL"
    )


@pytest.mark.parametrize(
    ("classification", "ceiling"),
    [
        ("MIGRATION_COMPATIBILITY", "MIGRATION_COMPATIBILITY_ONLY"),
        ("RETIREMENT_GUARD", "RETIREMENT_ONLY"),
        ("FIXTURE_PROTOCOL", "FIXTURE_ONLY"),
        ("QUALIFICATION_INFRASTRUCTURE", "INFRASTRUCTURE_ONLY"),
        ("CURRENT_AUTHORITY_BOUNDARY", "STATIC_AUTHORITY_BOUNDARY"),
    ],
)
def test_non_business_evidence_cannot_become_current_by_importing_production_code(
    tmp_path: Path,
    classification: str,
    ceiling: str,
) -> None:
    _fixture_repository(tmp_path)
    manifest = _read_manifest(tmp_path)
    manifest["classification_rules"][1].update(
        classification=classification, proof_ceiling=ceiling
    )
    _save_manifest(tmp_path, manifest)

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert (
        "current semantic slice has no direct current-contract evidence: current_slice"
        in report["errors"]
    )


def test_transitive_helper_mock_is_supporting_even_through_relative_import_cycle(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE\nfrom tests.unit.helpers import result\n"
        "def test_value():\n    assert result() == VALUE\n",
    )
    _write(tmp_path / "tests/unit/helpers.py", "from .doubles import result\n")
    _write(
        tmp_path / "tests/unit/doubles.py",
        "from . import helpers\nfrom unittest.mock import Mock\nresult = Mock(return_value=1)\n",
    )

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    record = _record(report, "tests/unit/test_example.py")
    assert record["evidence_basis"] == "FIXTURE_OR_MOCK_BACKED"
    assert record["fixture_or_mock_sources"] == ["tests/unit/doubles.py"]
    assert record["current_semantic_evidence"] is False


def test_fake_provider_is_never_direct_contract_evidence(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE, FakeDeterministicProvider\n"
        "def test_value():\n    assert FakeDeterministicProvider().result() == VALUE\n",
    )

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert (
        _record(report, "tests/unit/test_example.py")["evidence_basis"]
        == "FIXTURE_OR_MOCK_BACKED"
    )


def test_fixture_control_slice_retains_explicit_supporting_ceiling(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    manifest = _read_manifest(tmp_path)
    manifest["semantic_slice_policy"]["current_slice"].update(
        role="SUPPORTING_CONTRACT", proof_ceiling="FIXTURE_CONTROL_ONLY"
    )
    _save_manifest(tmp_path, manifest)
    assert check_test_reality(tmp_path)["status"] == "PASS"
    manifest["semantic_slice_policy"]["current_slice"]["proof_ceiling"] = (
        "POSTGRESQL_CURRENT_CONTRACT"
    )
    _save_manifest(tmp_path, manifest)
    report = check_test_reality(tmp_path)
    assert report["status"] == "FAIL"
    assert (
        "supporting semantic slice must retain fixture proof ceiling: current_slice"
        in report["errors"]
    )


def test_migration_and_fixture_classifications_cannot_raise_record_proof_ceiling(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    manifest = _read_manifest(tmp_path)
    manifest["classification_rules"][0]["proof_ceiling"] = "IN_PROCESS_CONTRACT_ONLY"
    manifest["semantic_slice_policy"]["migration_matrix"]["proof_ceiling"] = (
        "POSTGRESQL_CURRENT_CONTRACT"
    )
    _save_manifest(tmp_path, manifest)

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert (
        "test classification has unsupported proof ceiling: migration"
        in report["errors"]
    )
    assert (
        "migration semantic slice must retain compatibility proof ceiling: migration_matrix"
        in report["errors"]
    )


@pytest.mark.parametrize(
    "setup",
    [
        "from novel_forge.example import FakeDeterministicProvider as Adapter\nvalue = Adapter()\n",
        "class _RecordingPort:\n    def execute(self):\n        return 1\nvalue = _RecordingPort()\n",
        "from types import SimpleNamespace\nvalue = SimpleNamespace(result=1)\n",
        "value = object.__new__(object)\n",
    ],
)
def test_manual_or_aliased_doubles_cannot_hide_as_direct_contract(
    tmp_path: Path,
    setup: str,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE\n"
        + setup
        + "def test_value():\n    assert VALUE == 1\n",
    )

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert (
        _record(report, "tests/unit/test_example.py")["classification"]
        == "FIXTURE_PROTOCOL"
    )


def test_autouse_conftest_mock_is_part_of_test_evidence_lineage(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/conftest.py",
        "import pytest\nfrom unittest.mock import patch\n"
        "@pytest.fixture(autouse=True)\ndef override():\n"
        "    with patch('novel_forge.example.VALUE', 1):\n        yield\n",
    )

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert _record(report, "tests/unit/test_example.py")["fixture_or_mock_sources"] == [
        "tests/conftest.py"
    ]


def test_empty_file_cannot_witness_a_current_contract(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE\n",
    )

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert (
        report["semantic_slice_evidence"]["current_slice"]["direct_current_witnesses"]
        == []
    )
