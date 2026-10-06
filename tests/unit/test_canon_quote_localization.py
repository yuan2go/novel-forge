from copy import deepcopy
import pytest
from novel_forge.modules.command_kernel.errors import KernelError
from novel_forge.modules.canon_graph.evidence_localization import localize_provider_quotes
from novel_forge.modules.chapter_authority.provider_output_contracts import bind_canon_field_kinds


def test_quote_localization_preserves_rejected_result_and_cannot_prove_semantics():
    raw={'disclosure_events':[{'claim_kind':'KNOWLEDGE_ACQUISITION','evidence_quote':'他说‘限两份’。'}]}
    original=deepcopy(raw)
    corrected,evidence=localize_provider_quotes(raw,text='他说“限两份”。',target_asset_version_id='selected')
    assert raw==original
    assert corrected['disclosure_events'][0]['evidence_quote']=='他说“限两份”。'
    assert corrected['disclosure_events'][0]['claim_kind']=='KNOWLEDGE_ACQUISITION'
    assert evidence['semantic_support']=='NOT_RUN' and evidence['strict_certification_eligible'] is False
    assert evidence['mappings'][0]['original_literal_check']=='FAILED'
    assert len(evidence['mappings'][0]['differences'])==2


@pytest.mark.parametrize('quote,text,offsets', [
    ('他说‘限三份’。','他说“限两份”。',{}),
    ('他说"限两份"。','他说“限两份”。',{}),
    ('他说‘限两份’。','他说“限两份”。他说“限两份”。',{}),
    ('他说‘限两份’。','他说“限两份”。',{'evidence_start':1,'evidence_end':9}),
    ('他说 ‘限两份’。','他说“限两份”。',{}),
])
def test_localization_rejects_words_ascii_quotes_ambiguity_and_offset_changes(quote,text,offsets):
    with pytest.raises(KernelError,match='CANON_QUOTE_LOCALIZATION_INVALID'):
        localize_provider_quotes({'evidence_quote':quote,**offsets},text=text,target_asset_version_id='selected')


def test_field_schema_constrains_reader_and_character_identity_without_changing_historical_schema():
    schema={'type':'object','properties':{field:{'type':'array','items':{'type':'object','properties':{'claim_kind':{'type':'string','enum':['OBJECTIVE_EVENT','KNOWLEDGE_ACQUISITION','READER_DISCLOSURE']}}}} for field in ('disclosure_events','character_knowledge_changes')}}
    original=deepcopy(schema)
    result=bind_canon_field_kinds(deepcopy(schema))
    assert schema==original
    assert result['properties']['disclosure_events']['items']['properties']['claim_kind']['enum']==['READER_DISCLOSURE']
    assert result['properties']['character_knowledge_changes']['items']['properties']['claim_kind']['enum']==['KNOWLEDGE_ACQUISITION']


def test_new_canon_provider_view_retains_actual_rejected_output_and_diagnostic():
    from novel_forge.modules.chapter_authority.provider_views import build_provider_task_view
    feedback={'contract_version':'chapter-canon-output-repair.v1','rejected_output':{'disclosure_events':[{'claim_kind':'KNOWLEDGE_ACQUISITION'}]},'diagnostic':{'code':'CANON_GROUNDING_INVALID','reason':"claim kind 'KNOWLEDGE_ACQUISITION' cannot authorize disclosure_events"}}
    inputs={'revision':{'chapter':1,'text':'原文'},'execution_expectations':{},'canon_field_kind_contract':'canon-field-kinds.v1','canon_output_repair':feedback}
    view=build_provider_task_view('canon_extraction',inputs)
    assert view['contract_version']=='provider-task-view-v3'
    assert view['canon_output_repair']['rejected_output']==feedback['rejected_output']
    assert view['canon_output_repair']['feedback_selection']['selected_fields']==['disclosure_events']
    legacy=build_provider_task_view('canon_extraction',{k:v for k,v in inputs.items() if k!='canon_field_kind_contract'})
    assert 'canon_output_repair' not in legacy


def test_canon_repair_projection_omits_only_feedback_and_preserves_raw_type_failure():
    from novel_forge.modules.chapter_authority.canon_repair_projection import project_canon_repair
    from novel_forge.modules.production_execution.cost_routing import snapshot_hash
    raw={'disclosure_events':[{'claim_kind':'KNOWLEDGE_ACQUISITION'}],'canon_facts':[{'fact':'retained'}]}
    feedback={'contract_version':'chapter-canon-output-repair.v1','rejected_output':raw,'diagnostic':{'code':'CANON_GROUNDING_INVALID','reason':"claim kind 'KNOWLEDGE_ACQUISITION' cannot authorize disclosure_events"},'quote_localization':{'mappings':[]}}
    original=deepcopy(feedback)
    view=project_canon_repair(feedback)
    assert feedback==original and view['rejected_output']=={'disclosure_events':raw['disclosure_events']}
    assert view['feedback_selection']['omitted_fields']==['canon_facts']
    assert view['feedback_selection']['full_result_hash']==snapshot_hash(raw)
    assert view['quote_localization']['semantic_support']=='NOT_RUN'
