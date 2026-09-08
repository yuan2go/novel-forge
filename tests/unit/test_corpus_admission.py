import pytest
from pydantic import ValidationError

from novel_forge.modules.source_authority.corpus import (
    CORPUS_ACTION,
    CorpusPurpose,
    RightsDeclaration,
    corpus_admission,
)


def declaration(**changes):
    return RightsDeclaration.model_validate(
        {
            "action": "declare_rights",
            "source_id": "source",
            "dataset_license": "MIT",
            "underlying_rights": "UNKNOWN",
            "allowed_purposes": ["RESEARCH", "BENCHMARK", "PRODUCTION_REFERENCE"],
            "evidence_refs": ["rights-document:1"],
            "copyright_boundary": "explicit catalog declaration only",
            "scope": "ALL_WORKS_IN_SNAPSHOT",
            **changes,
        }
    )


@pytest.mark.parametrize("underlying", ["UNKNOWN", "CONFLICTING", "RESTRICTED"])
@pytest.mark.parametrize("license_name", ["MIT", "Apache-2.0", "CC0"])
def test_dataset_license_never_authorizes_underlying_prose(underlying, license_name):
    decision = corpus_admission(
        rights=declaration(underlying_rights=underlying, dataset_license=license_name),
        source_purpose=CorpusPurpose.PRODUCTION_REFERENCE,
        requested_purpose=CorpusPurpose.PRODUCTION_REFERENCE,
    )
    assert decision["decision"] == "DENY"
    assert "UNDERLYING_WORK_RIGHTS_NOT_CLEARED" in decision["reasons"]
    assert not decision["generation_context_allowed"]


def test_benchmark_isolation_deny_wins_and_versioned_rights():
    rights = declaration(underlying_rights="OWNED")
    for source, requested, options, reason in [
        ("BENCHMARK", "PRODUCTION_REFERENCE", {}, "BENCHMARK_PRODUCTION_FORBIDDEN"),
        ("RESEARCH", "PRODUCTION_REFERENCE", {}, "CORPUS_PURPOSE_ISOLATION"),
        (
            "PRODUCTION_REFERENCE",
            "PRODUCTION_REFERENCE",
            {"rights_current": False},
            "RIGHTS_REVIEW_REQUIRED",
        ),
        ("RESEARCH", "RESEARCH", {"retired": True}, "SOURCE_RETIRED"),
    ]:
        decision = corpus_admission(
            rights=rights,
            source_purpose=CorpusPurpose(source),
            requested_purpose=CorpusPurpose(requested),
            **options,
        )
        assert decision["decision"] == "DENY"
        assert reason in decision["reasons"]
    decision = corpus_admission(
        rights=declaration(
            underlying_rights="OWNED", denied_purposes=["PRODUCTION_REFERENCE"]
        ),
        source_purpose=CorpusPurpose.PRODUCTION_REFERENCE,
        requested_purpose=CorpusPurpose.PRODUCTION_REFERENCE,
    )
    assert "PURPOSE_EXPLICITLY_DENIED" in decision["reasons"]
    with pytest.raises(ValidationError, match="independently of dataset"):
        declaration(underlying_rights="LICENSED")


def test_manifest_is_typed_bounded_and_not_an_acquisition_adapter():
    with pytest.raises(ValidationError):
        CORPUS_ACTION.validate_python(
            {"action": "download", "url": "https://example.org/novel.txt"}
        )
    with pytest.raises(ValidationError):
        CORPUS_ACTION.validate_python(
            {
                "action": "import_batch",
                "snapshot_id": "s",
                "batch_key": "k",
                "entries": [],
            }
        )
