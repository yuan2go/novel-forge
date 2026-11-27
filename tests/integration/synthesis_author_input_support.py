from copy import deepcopy

from novel_forge.modules.story_design_authority.author_input import (
    GENERATOR_TARGETS, bind_author_design, planning_author_projection, text_hash,
)
from tests.integration.synthesis_production_support import SynthesisTransport


def author_fixture(project_id, book_id):
    lines = ['Keep the witnessed choice costly.', 'PRIVATE_AUTHOR_CAUSE_NOT_FOR_WRITER', 'The third chapter must preserve the prior witnessed cost.']
    text = '\n'.join(lines)
    return {
        'contract_version':'author-design-input.v1', 'project_id':project_id,'book_id':book_id,
        'version':'fixture-author-v2','evidence_class':'AI_ASSISTED_AUTHOR_INPUT',
        'source_task':'ENGINEERING_FIXTURE_ONLY',
        'documents':[{'path':'fixture/author.md','content':text,'content_hash':text_hash(text)}],
        'fragments':[
            {'fragment_id':f'author-fixture-{index}','source_path':'fixture/author.md',
             'start':text.index(line),'end':text.index(line)+len(line),'content_hash':text_hash(line),
             'targets':targets,'chapter_range':bounds,'visibility':visibility,'strength':strength}
            for index,(line,targets,bounds,visibility,strength) in enumerate(zip(lines,
                [list(GENERATOR_TARGETS.values()),['BOOK','ARC'],['CHAPTER']],
                [[1,3],[1,3],[3,3]],['SCENE_INTENT','AUTHOR_ONLY','SCENE_INTENT'],
                ['REQUIRED','DIRECTION','REQUIRED'],strict=True))
        ],
    }


class AuthorSynthesisTransport(SynthesisTransport):
    def __init__(self, author, brief):
        super().__init__()
        self.binding = bind_author_design(author, asset_version_id=brief.asset_version_id, content_hash=brief.content_hash)

    def planning(self, stage, inputs):
        result = super().planning(stage, inputs)
        if stage not in GENERATOR_TARGETS:
            return result
        command = inputs['planning_command']
        projected = planning_author_projection(
            self.binding, generator=stage, logical_key=command['logical_key'],
            chapter_range=(command.get('narrative_search_planning_horizon') or {}).get('chapter_range'),
        )
        decisions = []
        for item in projected['fragments']:
            decision = {'fragment_id':item['fragment_id'],'content_hash':item['content_hash'],
                        'decision':'ADAPT','rationale':'Explicit engineering fixture, not a literary judgment',
                        'target_pointer':'/objective','realization_excerpt':item['text']}
            if item['visibility'] == 'AUTHOR_ONLY':
                decision.update(decision='REJECT',target_pointer='',realization_excerpt='')
            else:
                result['objective'] = str(result.get('objective') or '') + ' ' + item['text']
            decisions.append(decision)
        if decisions:
            result['author_design_decisions'] = deepcopy(decisions)
        return result
