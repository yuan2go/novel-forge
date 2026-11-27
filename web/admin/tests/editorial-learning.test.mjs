import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../app/features/production/editorial-learning.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, {compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022}}).outputText;
const {eligibleEditorialCards, editorialProblems, editorialBriefExtension} = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const card = {project_id: 'p', asset_version_id: 'card:v1', content_hash: 'sha256:' + 'a'.repeat(64), lifecycle: 'ACTIVE', eligibility: 'ELIGIBLE', governance: 'CLEAR', card_status: 'ACTIVE'};
const decision = {decision_id: 'd', choice: 'ADAPT', finding: 'Preparation changes action', application: 'Use only when danger gives choices meaning', reader_effect: 'Adventure advances', tradeoff: 'Do not explain every resource', targets: ['BOOK'], chapter_range: [1, 10], knowledge_cards: [{asset_version_id: card.asset_version_id, content_hash: card.content_hash}]};
const learning = {contract_version: 'editorial-learning.v1', book_id: 'b', version: 'v1', evidence_class: 'AI_ASSISTED_AUTHOR_INPUT', reader_promise: 'Exploration and growth', decisions: [decision]};
test('only eligible knowledge in the current project is offered', () => {
  assert.deepEqual(eligibleEditorialCards([card, {...card, project_id: 'other'}, {...card, eligibility: 'BLOCKED'}, {...card, card_status: 'REVOKED'}], 'p'), [card]);
});
test('edited or unavailable knowledge cannot be submitted as previously approved learning', () => {
  assert.deepEqual(editorialProblems(learning, [card], 'p', 'b'), []);
  assert.ok(editorialProblems(learning, [], 'p', 'b').some(p => p.includes('版本')));
  assert.ok(editorialProblems(learning, [card], 'p', 'other').some(p => p.includes('另一部')));
  assert.ok(editorialProblems({...learning, decisions: [{...decision, knowledge_cards: []}]}, [card], 'p', 'b').some(p => p.includes('绑定')));
});
test('native editorial request freezes deduplicated knowledge and legacy brief remains usable', () => {
  const extended = editorialBriefExtension({...learning, decisions: [decision, {...decision, decision_id: 'second'}]});
  assert.equal(extended.creative_brief_contract_version, 'creative-brief-v4');
  assert.deepEqual(extended.input_asset_version_ids, ['card:v1']);
  assert.equal(extended.editorial_learning.decisions.length, 2);
  assert.deepEqual(editorialBriefExtension(), {creative_brief_contract_version: 'creative-brief-v2', input_asset_version_ids: []});
});
