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
                "proof_ceiling": "CURRENT_CONTRACT_NO_REAL_PROVIDER",
            },
        ],
        "semantic_slice_policy": {
            "current_slice": {
                "role": "CURRENT_BUSINESS_CAPABILITY",
                "proof_ceiling": "CURRENT_CONTRACT_NO_REAL_PROVIDER",
                "production_targets": ["src/novel_forge/example.py"],
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


def test_mock_only_current_slice_fails_and_invariant_is_demoted(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from unittest.mock import Mock\nfrom novel_forge.example import VALUE\n"
        "def test_value():\n    assert Mock(return_value=VALUE)() == 1\n",
    )

    report = check_test_reality(tmp_path)

    assert report["status"] == "FAIL"
    assert report["mocked_invariant_demotions"] == ["tests/unit/test_example.py"]
    assert report["mock_fixture_false_qualification_count"] > 0
    record = next(
        item for item in report["files"] if item["path"].endswith("test_example.py")
    )
    assert record["classification"] == "FIXTURE_PROTOCOL"
    assert record["proof_ceiling"] == "FIXTURE_ONLY"


def test_unrelated_direct_test_does_not_rescue_mocked_target(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    _write(tmp_path / "src/novel_forge/unrelated.py", "VALUE = 2\n")
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE\n"
        "def test_value(monkeypatch):\n    assert VALUE == 1\n",
    )
    _write(
        tmp_path / "tests/unit/test_unrelated.py",
        "from novel_forge.unrelated import VALUE\n"
        "def test_other():\n    assert VALUE == 2\n",
    )
    path = tmp_path / "architecture/manifests/backend-qualification-manifest.yaml"
    qualification = json.loads(path.read_text())
    qualification["semantic_slices"]["current_slice"].append(
        "tests/unit/test_unrelated.py"
    )
    _write(path, json.dumps(qualification))

    report = check_test_reality(tmp_path)

    assert (
        "semantic slice target lacks direct evidence: current_slice:src/novel_forge/example.py"
        in report["errors"]
    )


def test_current_slice_accepts_same_target_direct_support(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    report = check_test_reality(tmp_path)
    assert report["status"] == "PASS", report["errors"]
    assert report["mock_fixture_false_qualification_count"] == 0


def test_manifest_target_cannot_replace_actual_test_import(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py", "def test_empty():\n    assert True\n"
    )
    path = tmp_path / "architecture/manifests/test-manifest.yaml"
    manifest = json.loads(path.read_text())
    manifest["classification_rules"][1]["production_target"] = (
        "src/novel_forge/example.py"
    )
    _write(path, json.dumps(manifest))
    report = check_test_reality(tmp_path)
    assert any("target lacks direct evidence" in error for error in report["errors"])


def test_mock_in_transitive_relative_helper_cannot_hide_as_direct(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(tmp_path / "tests/unit/helpers.py", "from .nested import value\n")
    _write(
        tmp_path / "tests/unit/nested.py",
        "from unittest.mock import Mock\nvalue = Mock()\n",
    )
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE\nfrom .helpers import value\n"
        "def test_value():\n    assert value() == VALUE\n",
    )
    report = check_test_reality(tmp_path)
    assert report["status"] == "FAIL"
    assert report["mocked_invariant_demotions"] == ["tests/unit/test_example.py"]


def test_custom_fake_and_runtime_classification_cannot_promote_fixture(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE\nclass FakeGateway: pass\n"
        "def test_value():\n    assert VALUE == 1\n",
    )
    path = tmp_path / "architecture/manifests/test-manifest.yaml"
    manifest = json.loads(path.read_text())
    manifest["classification_rules"][1]["classification"] = "CURRENT_RUNTIME_CONTRACT"
    _write(path, json.dumps(manifest))
    report = check_test_reality(tmp_path)
    assert report["status"] == "FAIL"
    assert any("target lacks direct evidence" in error for error in report["errors"])


def test_path_literal_cannot_stand_in_for_direct_contract_import(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py",
        'TARGET="src/novel_forge/example.py"\ndef test_value():\n    assert True\n',
    )
    report = check_test_reality(tmp_path)
    assert report["status"] == "FAIL"
    record = next(
        item for item in report["files"] if item["path"].endswith("test_example.py")
    )
    assert record["production_targets"] == ["src/novel_forge/example.py"]
    assert record["direct_production_targets"] == []


@pytest.mark.parametrize(
    "mode", ["explicit", "autouse", "usefixtures", "dynamic", "literal_dynamic"]
)
def test_mocked_conftest_dependency_cannot_qualify_current_slice(
    tmp_path: Path, mode: str
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/conftest.py",
        "import pytest\nfrom unittest.mock import Mock\n"
        "@pytest.fixture\ndef response():\n    return Mock(return_value=1)\n",
    )
    _write(
        tmp_path / "tests/unit/conftest.py",
        "import pytest\n"
        f"@pytest.fixture(autouse={mode == 'autouse'})\n"
        "def gateway(response):\n    return response\n",
    )
    test = {
        "explicit": "def test_value(gateway):\n    assert gateway() == VALUE\n",
        "autouse": "def test_value():\n    assert VALUE == 1\n",
        "usefixtures": '@pytest.mark.usefixtures("gateway")\ndef test_value():\n    assert VALUE == 1\n',
        "dynamic": 'def test_value(request):\n    name = "gateway"\n    assert request.getfixturevalue(name)() == VALUE\n',
        "literal_dynamic": 'def test_value(request):\n    assert request.getfixturevalue("gateway")() == VALUE\n',
    }[mode]
    _write(
        tmp_path / "tests/unit/test_example.py",
        "import pytest\nfrom novel_forge.example import VALUE\n" + test,
    )
    report = check_test_reality(tmp_path)
    assert report["status"] == "FAIL"
    assert report["mocked_invariant_demotions"] == ["tests/unit/test_example.py"]


def test_fixture_helper_and_same_name_ancestor_dependencies_are_followed(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/helpers.py",
        "from unittest.mock import Mock\ndef response_value():\n    return Mock(return_value=1)\n",
    )
    _write(
        tmp_path / "tests/conftest.py",
        "import pytest\nfrom tests.helpers import response_value\n@pytest.fixture\ndef gateway():\n    return response_value()\n",
    )
    _write(
        tmp_path / "tests/unit/conftest.py",
        "import pytest\n@pytest.fixture\ndef gateway(gateway):\n    return gateway\n",
    )
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE\ndef test_value(gateway):\n    assert gateway() == VALUE\n",
    )
    report = check_test_reality(tmp_path)
    assert report["status"] == "FAIL"
    assert report["mocked_invariant_demotions"] == ["tests/unit/test_example.py"]


@pytest.mark.parametrize(
    "fixture_location",
    ["tests/conftest.py", "tests/unit/conftest.py", "tests/unit/test_example.py"],
)
def test_unused_mock_fixture_does_not_demote_direct_database_contract(
    tmp_path: Path, fixture_location: str
) -> None:
    _fixture_repository(tmp_path)
    fixtures = (
        "import pytest\nimport psycopg\nfrom unittest.mock import Mock\n"
        "@pytest.fixture\ndef unused_gateway():\n    return Mock(return_value=1)\n"
        "@pytest.fixture\ndef database():\n    return psycopg.connect('postgresql://localhost/test')\n"
    )
    test = (
        "from novel_forge.example import VALUE\n"
        "def test_value(database):\n    assert database.execute('SELECT 1').fetchone()[0] == VALUE\n"
    )
    _write(
        tmp_path / fixture_location,
        fixtures + (test if fixture_location.endswith("test_example.py") else ""),
    )
    if not fixture_location.endswith("test_example.py"):
        _write(tmp_path / "tests/unit/test_example.py", test)
    report = check_test_reality(tmp_path)
    assert report["status"] == "PASS", report["errors"]
    assert report["mocked_invariant_demotions"] == []


def test_direct_autouse_database_fixture_does_not_demote_current_slice(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/conftest.py",
        "import pytest\nimport psycopg\n@pytest.fixture(autouse=True)\ndef database():\n    with psycopg.connect('postgresql://localhost/test') as connection:\n        yield connection\n",
    )
    report = check_test_reality(tmp_path)
    assert report["status"] == "PASS", report["errors"]


def test_imported_fixture_alias_and_helper_chain_remain_fixture_evidence(
    tmp_path: Path,
) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/helpers.py",
        "from pytest import fixture as fx\nfrom unittest.mock import Mock as Response\n@fx\ndef gateway():\n    return Response(return_value=1)\n",
    )
    _write(
        tmp_path / "tests/unit/conftest.py",
        "from .helpers import gateway as response\n",
    )
    _write(
        tmp_path / "tests/unit/test_example.py",
        "from novel_forge.example import VALUE\ndef test_value(response):\n    assert response() == VALUE\n",
    )
    report = check_test_reality(tmp_path)
    assert report["status"] == "FAIL"
    assert report["mocked_invariant_demotions"] == ["tests/unit/test_example.py"]


def test_unused_fixture_helper_does_not_contaminate_direct_test(tmp_path: Path) -> None:
    _fixture_repository(tmp_path)
    _write(
        tmp_path / "tests/unit/test_example.py",
        "import pytest\nfrom unittest.mock import Mock\nfrom novel_forge.example import VALUE\ndef response():\n    return Mock(return_value=1)\n@pytest.fixture\ndef unused_gateway():\n    return response()\ndef test_value():\n    assert VALUE == 1\n",
    )
    report = check_test_reality(tmp_path)
    assert report["status"] == "PASS", report["errors"]
