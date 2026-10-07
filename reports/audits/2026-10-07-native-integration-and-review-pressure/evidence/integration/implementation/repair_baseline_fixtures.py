from pathlib import Path

def edit(path,old,new):
 p=Path(path);s=p.read_text();assert old in s,(path,old);p.write_text(s.replace(old,new,1))
edit('tests/unit/test_narrative_search_branch_registration.py','''    def execute(self, statement: str, parameters: list[Any]) -> None:
        if "FROM authority_story_narrative_search\\n" in statement:''','''    def execute(self, statement: str, parameters: list[Any]) -> None:
        if "SELECT v.content_hash,e.request_payload" in statement:
            self._rows = []
            self._row = None
            return
        if "FROM authority_story_narrative_search\\n" in statement:''')
edit('tests/unit/test_chapter_agent_binding_boundary.py','''        "agent_session",
''','''        "agent_session",
        "model_reference_evaluate",
        "model_reference_adjudicate",
''')
edit('tests/unit/test_creation_runner_settings.py',"lambda _values: None)","lambda _values, **_kwargs: None)")
edit('tests/unit/test_cross_chapter_prose_review.py','''previous = CandidateEvidence("a", {}, 60, ("issue",), "review")''','''previous = CandidateEvidence("a", {"text": "original prose"}, 60, ("issue",), "review")''')
# Restrict this repair to the failing real-comparison fixture, preserving same-text counterexamples elsewhere.
p=Path('tests/unit/test_cross_chapter_prose_review.py');s=p.read_text();start=s.index('def test_high_score_cannot_replace_unresolved_or_regressed_candidate');tail=s[start:];tail=tail.replace('''        "b",
        {},''','''        "b",
        {"text": "revised prose"},''',1);p.write_text(s[:start]+tail)
edit('tests/unit/test_prose_reviewer_sampling.py','''== "1.2.0"''','''== "1.3.0"''')
edit('tests/unit/test_runtime_dispatch_control.py','''    formation, jobs = Mock(), Mock()
    formation.advance_expected.side_effect = pause''','''    formation, jobs = Mock(), Mock()
    formation.require.return_value = {"lifecycle": "RUNNING"}
    formation.advance_expected.side_effect = pause''')
edit('tests/unit/test_story_formation_worker_wait.py','''        failure_recorded = False

        def advance_expected''','''        failure_recorded = False

        def require(self, _formation_run_id):
            return {"lifecycle": "RUNNING"}

        def advance_expected''')
edit('tests/architecture/test_capability_pack_authority_boundaries.py','''    assert "CapabilityPackApprovalScope.from_payload" in runtime''','''    authorization = (
        ROOT / "src/novel_forge/modules/capability_pack_authority/validation_admission.py"
    ).read_text(encoding="utf-8")
    assert "require_deployment_authorization(" in runtime
    assert "CapabilityPackApprovalScope.from_payload" in authorization''')
