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


def test_restricted_research_preserves_unknown_without_granting_generation():
    from novel_forge.modules.source_authority.corpus import RightsDeclaration, CorpusUse, CorpusPurpose, corpus_use_admission
    rights = RightsDeclaration(action='declare_rights', source_id='source:test', dataset_license='user supplied', underlying_rights='UNKNOWN', allowed_purposes=('RESEARCH',), allowed_uses=('SOURCE_ANALYSIS',), restrictions=('PRIVATE_ANALYSIS_ONLY','NO_RAW_WRITER_INPUT','NO_PUBLIC_DISTRIBUTION'), evidence_refs=('user:test',), copyright_boundary='private analysis only', scope='ALL_WORKS_IN_SNAPSHOT')
    args=dict(rights=rights, source_purpose=CorpusPurpose.RESEARCH, external_work_id='work:test', retired=False, rights_current=True)
    assert corpus_use_admission(**args, use=CorpusUse.SOURCE_ANALYSIS)['decision']=='DENY'
    assert corpus_use_admission(**args, use=CorpusUse.SOURCE_ANALYSIS, restricted_research=True)['decision']=='ALLOW'
    assert rights.underlying_rights=='UNKNOWN'
    assert corpus_use_admission(**args, use=CorpusUse.ABSTRACT_GENERATION, restricted_research=True)['decision']=='DENY'
    for changes in ({'retired':True},{'rights_current':False},{'rights':rights.model_copy(update={'restrictions':('NO_TRANSMISSION',)})},{'rights':rights.model_copy(update={'underlying_rights':'CONFLICTING'})}):
        assert corpus_use_admission(**{**args,**changes}, use=CorpusUse.SOURCE_ANALYSIS, restricted_research=True)['decision']=='DENY'


def test_local_observation_keeps_whole_review_and_rejects_intersecting_damage():
    from novel_forge.modules.source_authority.observation import validate_local_integrity
    from novel_forge.modules.command_kernel.errors import KernelError
    import pytest
    assessment={'acquisition_integrity':'VERIFIED_BYTES','structure_usable':False,'coverage':'REVIEW_REQUIRED','issues':[{'blocking':True,'evidence':[{'locator':{'path':'source.txt','original_byte_offset':100,'original_byte_end':200}}]}]}
    units=[{'source_locator':{'path':'source.txt','original_byte_offset':0,'original_byte_end':100}}]
    validate_local_integrity(assessment, units)
    assert assessment['coverage']=='REVIEW_REQUIRED'
    with pytest.raises(KernelError,match='intersects'):
        validate_local_integrity(assessment,[{'source_locator':{'path':'source.txt','original_byte_offset':150,'original_byte_end':300}}])
    with pytest.raises(KernelError,match='unverified'):
        validate_local_integrity({**assessment,'acquisition_integrity':'UNKNOWN'}, units)


def test_numbering_discontinuity_requires_exact_scoped_acknowledgement():
    from copy import deepcopy
    from novel_forge.modules.source_authority.observation import validate_local_integrity
    from novel_forge.modules.command_kernel.errors import KernelError

    locator = {"path": "source.txt", "original_byte_offset": 100, "original_byte_end": 200, "precision": "UNIT_BYTES"}
    digest = "sha256:" + "a" * 64
    identity = "sha256:" + "b" * 64
    unit = {"source_locator": locator, "status": "AVAILABLE", "kind": "chapter", "normalized_content_hash": digest}
    issue = {"issue_id": identity, "code": "MISSING_OR_UNORDERED_CHAPTER", "blocking": True, "evidence": [{"locator": locator, "content_hash": digest}]}
    assessment = {"acquisition_integrity": "VERIFIED_BYTES", "coverage": "REVIEW_REQUIRED", "structure_usable": False, "issues": [issue]}
    original = deepcopy(assessment)
    with pytest.raises(KernelError, match="intersects"):
        validate_local_integrity(assessment, [unit])
    validate_local_integrity(assessment, [unit], acknowledged_numbering_issue_ids=(identity,))
    assert assessment == original
    for changed in ({**unit, "normalized_content_hash": "sha256:" + "c" * 64}, {**unit, "status": "UNAVAILABLE"}, {**unit, "source_locator": {**locator, "original_byte_offset": 99}}):
        with pytest.raises(KernelError, match="intersects"):
            validate_local_integrity(assessment, [changed], acknowledged_numbering_issue_ids=(identity,))
    with pytest.raises(KernelError, match="intersects"):
        validate_local_integrity({**assessment, "issues": [{**issue, "code": "SHORT_OR_TOC_UNIT"}]}, [unit], acknowledged_numbering_issue_ids=(identity,))
    with pytest.raises(KernelError, match="exact observed issue"):
        validate_local_integrity({**assessment, "issues": []}, [unit], acknowledged_numbering_issue_ids=(identity,))
