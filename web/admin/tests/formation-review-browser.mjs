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
} catch(error) {process.stderr.write(JSON.stringify({scenario,rendered:await page.locator("body").innerText()}) + "\n"); throw error;} finally { await context.close(); }
}
const creationContext = await browser.newContext();
const creationPage = await creationContext.newPage();
try {
  const sourceHash = `sha256:${'a'.repeat(64)}`;
  await creationPage.addInitScript(() => {
    if (!localStorage.getItem('continuous-fixture-initialized')) {
      localStorage.setItem('novel-forge.author-production.v1', JSON.stringify({project:'continuous-project',bookId:'continuous-book'}));
      localStorage.setItem('novel-forge:creative-input:continuous-project:continuous-book',JSON.stringify({title:'原创调查',idea:'调查名册矛盾',genre:'现实悬疑',audience:'成年读者',constraints:'知识边界',sources:'原创表达',target:12,candidates:2,continuous:true,language:'zh-CN',lengthMinimum:1200,lengthMaximum:2400,operationId:'saved-brief',formationId:'',pending:null}));
      localStorage.setItem('continuous-fixture-initialized','1');
    }
  });
  await creationPage.route('**/product/projects', route=>route.fulfill({json:[{project_id:'continuous-project',workspace_id:'continuous-workspace',title:'隔离连续 UI'}]}));
  await creationPage.route('**/author-workspace?*',route=>route.fulfill({json:{books:[{book_id:'continuous-book',workspace_id:'continuous-workspace',title:'原创调查',version:1,status:'ACTIVE',production_profile:{},runtime_policy:{}}],profiles:[],snapshots:[],runs:[],budget_scopes:[]}}));
  await creationPage.route('**/operations/saved-brief?*',route=>route.fulfill({json:{operation_id:'saved-brief',status:'SUCCEEDED',outputs:[{asset_version_id:'exact-saved-brief',content_hash:sourceHash}]}}));
  let formation={formation_run_id:'continuous-source',version:1,lifecycle:'ADMITTED',current_stage:'CREATIVE_SEARCH',creation:{author_state:'PRODUCING',responsible_party:'BOOK_AUTHORITY_WORKER',next_action:'WAIT_FOR_NATIVE_EXECUTOR',production:{book_run_id:'continuous-book-run',state:'READY',accepted_chapters:0,target_chapters:12,version:0},stage:'CREATIVE_SEARCH',cancellation:null,coordination:{status:'READY',result:null},progress:[]}};
  const requests=[];
  await creationPage.route('**/books/continuous-book/formation-runs',async route=>{
    requests.push(route.request().postDataJSON());
    if (requests.length===1) await route.abort('failed');
    else await route.fulfill({json:formation});
  });
  await creationPage.route('**/formation-runs/continuous-source',route=>route.fulfill({json:formation}));
  const recoveries=[];
  await creationPage.route('**/formation-runs/continuous-source/resume',async route=>{
    recoveries.push(route.request().postDataJSON());
    formation={...formation,version:2,creation:{...formation.creation,coordination:{status:'READY',result:null}}};
    if(recoveries.length===1) await route.abort('failed');
    else await route.fulfill({json:formation});
  });
  await creationPage.route('**/formation-runs/continuous-source/abort',async route=>{
    const body=route.request().postDataJSON();assert.equal(body.expected_version,2);assert.ok(body.idempotency_key);assert.ok(body.reason);
    formation={...formation,version:3,lifecycle:'ABORTED',creation:{...formation.creation,author_state:'CANCELLATION_REQUESTED',cancellation:{reason:body.reason},coordination:{status:'SUCCEEDED',result:{wait_class:'CANCELLED',stop_reason:'CANCELLED'}}}};
    await route.fulfill({json:formation});
  });
  await creationPage.goto(`${base}/production`);
  await creationPage.getByRole('button',{name:'启动连续创作（先比较并确认方向）',exact:true}).click();
  await creationPage.getByRole('button',{name:'恢复上次提交（保留原输入和幂等键）',exact:true}).waitFor();
  await creationPage.reload();
  await creationPage.getByRole('button',{name:'恢复上次提交（保留原输入和幂等键）',exact:true}).click();
  await creationPage.getByRole('button',{name:'取消连续创作',exact:true}).waitFor();
  await creationPage.getByRole('status').filter({hasText:'创作进度：正在创作。已接纳 0/12 章。'}).waitFor();
  assert.ok((await creationPage.getByRole('status').filter({hasText:'创作进度：'}).innerText()).includes('下一动作：等待执行器自动推进'));
  assert.deepEqual(requests[0],requests[1]);
  assert.equal(requests[0].creative_brief_asset_version_id,'exact-saved-brief');
  assert.equal(requests[0].creative_brief_content_hash,sourceHash);
  assert.deepEqual(requests[0].production_intent,{title:'原创调查',target_chapters:12,creative_candidates:2,language_contract:{required_language:'zh-CN'},chapter_length:{minimum:1200,maximum:2400}});
  assert.equal(requests[0].generation_policy,undefined);
  formation={...formation,creation:{...formation.creation,author_state:'OWNER_RECOVERY_REQUIRED',responsible_party:'RUNTIME_OWNER',next_action:'RECOVER_ORIGINAL_CREATION_AFTER_RESOLVING_RETAINED_FAILURE',failure:{code:'PLANNING_RESULT_REPAIR_BOUND_EXCEEDED'},coordination:{status:'SUCCEEDED',result:{wait_class:'OWNER_RECOVERY_REQUIRED',stop_reason:'PLANNING_RESULT_REPAIR_BOUND_EXCEEDED'}}}};
  await creationPage.reload();
  await creationPage.getByRole('alert').filter({hasText:'方案修复次数已用完'}).waitFor();
  const ownerProgress = await creationPage.getByRole('status').filter({hasText:'创作进度：等待责任方解决停点'}).innerText();
  assert.ok(ownerProgress.includes('当前责任方：生产运行责任方'));
  assert.ok(ownerProgress.includes('下一动作：先解决已保存问题，再恢复原任务'));
  await creationPage.getByRole('button',{name:'核对停点后恢复创作',exact:true}).click();
  await creationPage.getByRole('button',{name:'恢复上次提交（保留原输入和幂等键）',exact:true}).waitFor();
  await creationPage.reload();
  await creationPage.getByRole('button',{name:'恢复上次提交（保留原输入和幂等键）',exact:true}).click();
  await creationPage.waitForFunction(()=>JSON.parse(localStorage.getItem('novel-forge:creative-input:continuous-project:continuous-book')).pending===null);
  assert.deepEqual(recoveries[0],recoveries[1]);
  assert.equal(recoveries[0].expected_version,1);
  assert.ok(recoveries[0].idempotency_key);
  checks.push('CONTINUOUS_RECOVERY_LOST_RESPONSE_ORIGINAL_IDENTITY');
  await creationPage.getByRole('button',{name:'取消连续创作',exact:true}).click();
  await creationPage.getByRole('status').filter({hasText:'创作进度：已取消。'}).waitFor();
  assert.equal(await creationPage.getByRole('button',{name:'取消连续创作',exact:true}).isDisabled(),true);
  checks.push('CONTINUOUS_NATIVE_INTENT_LOST_RESPONSE_AND_CANCELLATION');
} finally {await creationContext.close();}
await browser.close();
process.stdout.write(JSON.stringify({status: 'PASS', evidence_kind: 'BROWSER_WITH_ISOLATED_API_DOUBLES', checks}) + '\n');
