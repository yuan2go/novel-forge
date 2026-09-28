import assert from 'node:assert/strict';
import { chromium } from 'playwright';

const base = process.env.NOVEL_FORGE_WEB_BASE_URL;
if (!base) throw new Error('NOVEL_FORGE_WEB_BASE_URL must identify the isolated author UI');
const browser = await chromium.launch({headless: true, channel: process.env.NOVEL_FORGE_BROWSER_CHANNEL || 'chrome'});
const checks = [];
for (const scenario of ["NETWORK", "AMBIGUOUS_CONFLICT", "FORBIDDEN_AFTER_DECISION", "VERSION_CONFLICT"]) {
const context = await browser.newContext();
const page = await context.newPage();
const hash = digit => `sha256:${digit.repeat(64)}`;
const candidates = [
  {asset_version_id: 'candidate-first', content_hash: hash('1'), content: {candidate_payload: {core_conflict: '重复追逐同一个证人', reader_promise: '追查证词'}}, state: {qualification: 'QUALIFIED', approval: 'PENDING'}},
  {asset_version_id: 'candidate-second', content_hash: hash('2'), content: {candidate_payload: {core_conflict: '救下证人却失去唯一的证据', reader_promise: '每次作证付出具体代价', narrative_engine: '守住承诺与保存证据彼此冲突'}}, state: {qualification: 'QUALIFIED', approval: 'PENDING'}},
];
let run = {formation_run_id: 'review-fixture', version: 3, lifecycle: 'WAITING_APPROVAL', current_stage: 'CREATIVE_SEARCH', recovery_instruction: {candidate_asset_version_id: candidates[0].asset_version_id}, candidates};
const requests = [];
let lost = false;
try {
  await page.addInitScript(() => {
    if (!localStorage.getItem('formation-browser-initialized')) {
      localStorage.setItem('novel-forge.author-production.v1', JSON.stringify({project: 'review-project', bookId: 'review-book'}));
      localStorage.setItem('novel-forge:creative-input:review-project:review-book', JSON.stringify({formationId: 'review-fixture'}));
      localStorage.setItem('formation-browser-initialized', '1');
    }
  });
  await page.route('**/product/projects', route => route.fulfill({json: [{project_id: 'review-project', workspace_id: 'review-workspace', title: '隔离 UI 项目', path: ''}]}));
  await page.route('**/product/production/book-authority/author-workspace?*', route => route.fulfill({json: {books: [{book_id: 'review-book', workspace_id: 'review-workspace', title: '候选确认检查', version: 1, status: 'ACTIVE', production_profile: {}, runtime_policy: {}}], profiles: [], snapshots: [], runs: [], budget_scopes: []}}));
  await page.route('**/formation-runs/review-fixture', route => route.fulfill({json: run}));
  await page.route('**/formation-runs/review-fixture/author-decisions', async route => {
    const body = route.request().postDataJSON(); requests.push(body);
    if (!lost) {
      run = {...run, version: 4, recovery_instruction: {candidate_asset_version_id: body.candidate_asset_version_id, author_selection: {decision: body.decision, reason: body.reason}}};
      lost = true;
      if (scenario === 'NETWORK') await route.abort('failed');
      else await route.fulfill({status: scenario === 'FORBIDDEN_AFTER_DECISION' ? 403 : 409, json: {detail: {code: scenario === 'VERSION_CONFLICT' ? 'STORY_FORMATION_REVIEW_CONFLICT' : 'UNRESOLVED_SUBMISSION'}}});
    } else {
      if (scenario === 'VERSION_CONFLICT') {assert.notEqual(body.idempotency_key, requests[0].idempotency_key); assert.equal(body.expected_version, 4);}
      else assert.deepEqual(body, requests[0]);
      await route.fulfill({json: run});
    }
  });
  await page.goto(`${base}/production`);
  const review = page.getByRole('region', {name: '设计候选确认'});
  await review.getByText('救下证人却失去唯一的证据', {exact: true}).waitFor();
  const note = '保留证词的代价；选择第二候选，因为人物承诺与证据保护形成冲突。';
  await page.getByLabel('选择理由 / 修改意见', {exact: true}).fill(note);
  await page.reload();
  await page.waitForFunction(text => document.querySelector('textarea[aria-label="选择理由 / 修改意见"]')?.value === text, note);
  await review.getByRole('article').nth(1).getByRole('button', {name: '批准此候选', exact: true}).click();
  if (scenario === 'VERSION_CONFLICT') {
    await page.waitForFunction(() => document.querySelector('[aria-label="选择理由 / 修改意见"]')?.disabled === false);
    assert.equal(await review.getByRole('button', {name: '恢复候选决定（原幂等键）', exact: true}).count(), 0);
    await page.reload();
    await review.getByRole('article').nth(1).getByRole('button', {name: '批准此候选', exact: true}).click();
  } else {
    await review.getByRole('button', {name: '恢复候选决定（原幂等键）', exact: true}).waitFor();
    await page.reload();
    await review.getByRole('button', {name: '恢复候选决定（原幂等键）', exact: true}).click();
  }
  await review.getByText('候选 2 · 当前选择', {exact: true}).waitFor();
  assert.equal(requests.length, 2);
  assert.equal(requests[0].candidate_asset_version_id, 'candidate-second');
  assert.equal(requests[0].reason, note);
  await page.waitForFunction(() => !document.querySelector('[aria-label="设计候选确认"]')?.textContent.includes('恢复候选决定（原幂等键）'));
  checks.push(scenario);
} finally { await context.close(); }
}
await browser.close();
process.stdout.write(JSON.stringify({status: 'PASS', evidence_kind: 'BROWSER_WITH_ISOLATED_API_DOUBLES', checks}) + '\n');
