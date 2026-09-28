import { chromium } from 'playwright';
import assert from 'node:assert/strict';
const api = 'http://127.0.0.1:8137', ui = process.env.NOVEL_FORGE_AUTHOR_UI_URL || 'http://127.0.0.1:3141';
const project = 'reference-form-fixture', book = 'book:reference-form';
const browser = await chromium.launch({channel: 'chrome', headless: true});
const checks = [];
try {
  for (const scenario of ['NETWORK', '422', '409', 'FAILED_FINAL']) {
    const context = await browser.newContext(), page = await context.newPage();
    const sent = [], sample = {asset_version_id: 'sample:fixture', content_hash: 'sha256:' + 'a'.repeat(64), content: {core_conflict: '证人与证词争夺最后一段渡河时间。'}, reference_contract: {dimensions: ['GATE:CORE_CONFLICT_CLARITY']}};
    await page.route(`${api}/**`, async route => {
      const request = route.request(), url = new URL(request.url());
      const respond = (body, status = 200) => route.fulfill({status, contentType: 'application/json', body: JSON.stringify(body), headers: {'Access-Control-Allow-Origin': '*'}});
      if (request.method() === 'OPTIONS') return route.fulfill({status: 204, headers: {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET,POST,PUT,OPTIONS', 'Access-Control-Allow-Headers': 'content-type'}});
      if (url.pathname === '/product/system/health') return respond({summary: {}, embedding: {ok: false}});
      if (url.pathname === '/health') return respond({configured_services: {postgresql: true}});
      if (url.pathname === '/product/projects') return respond([{project_id: project, title: '隔离人工表单测试', workspace_id: 'workspace:fixture'}]);
      if (url.pathname.endsWith('/author-workspace')) return respond({books: [{book_id: book, workspace_id: 'workspace:fixture', title: '隔离作品', version: 1, status: 'DESIGN_PENDING', production_profile: {}, runtime_policy: {}}], runs: [], profiles: [], snapshots: [], budget_scopes: [], approved_characters: []});
      if (url.pathname.endsWith('/reference-samples')) return respond({samples: [sample, {...sample, asset_version_id: 'sample:other'}], actor_id: 'human:fixture', can_annotate: true});
      if (url.pathname.endsWith('/reference-evaluations')) {
        sent.push(request.postDataJSON());
        if (sent.length === 1) {
          if (scenario === 'NETWORK') return route.abort('failed');
          return respond({detail: 'Controlled fixture rejection'}, scenario === 'FAILED_FINAL' ? 409 : Number(scenario));
        }
        return respond({operation_id: 'annotation:fixture', asset_version_id: 'evaluation:fixture', status: 'SUCCEEDED'});
      }
      if (url.pathname.endsWith('/content-authority/operations')) {
        assert.equal(url.searchParams.get('idempotency_key'), `author-reference:${sent[0].idempotency_key}`);
        return respond([{operation_id: 'annotation:fixture', status: scenario === 'FAILED_FINAL' ? 'FAILED_FINAL' : 'SUCCEEDED'}]);
      }
      return respond([]);
    });
    await page.goto(`${ui}/production`); await page.waitForLoadState('networkidle');
    await page.getByLabel('项目', {exact: true}).selectOption(project);
    await page.getByLabel('作品', {exact: true}).selectOption(book);
    const panel = page.getByRole('region', {name: '真实样本人工评阅'});
    await panel.getByLabel('评阅样本', {exact: true}).selectOption(sample.asset_version_id);
    for (const [label, value] of [['评阅维度', 'GATE:CORE_CONFLICT_CLARITY'], ['评阅判断', 'PASSED'], ['本人评阅角色', 'AUTHOR_EDITOR']]) await panel.getByLabel(label, {exact: true}).selectOption(value);
    for (const [label, value] of [['评阅分数', '75'], ['判断把握', '0.8'], ['评阅起始章', '1'], ['评阅结束章', '1'], ['原文依据', '最后一段渡河时间'], ['判断理由', '隔离工程表单测试，不是实际真人评价。'], ['应保留的优点', '两个任务的竞争。']]) await panel.getByLabel(label, {exact: true}).fill(value);
    assert.equal(await panel.getByRole('button', {name: '保存本人评阅', exact: true}).isDisabled(), true);
    assert.equal(await panel.getByLabel('本人未见模型身份或其他评价', {exact: true}).isChecked(), false);
    await panel.getByLabel('确认本人完成评阅', {exact: true}).check();
    await panel.getByLabel('评阅样本', {exact: true}).selectOption('sample:other');
    assert.equal(await panel.getByLabel('原文依据', {exact: true}).inputValue(), '');
    await panel.getByLabel('评阅样本', {exact: true}).selectOption(sample.asset_version_id);
    await page.reload(); await panel.getByLabel('原文依据', {exact: true}).waitFor();
    assert.equal(await panel.getByLabel('原文依据', {exact: true}).inputValue(), '最后一段渡河时间');
    await panel.getByRole('button', {name: '保存本人评阅', exact: true}).click();
    await panel.getByRole('alert').waitFor();
    if (scenario === '422') {
      assert.equal(await panel.getByLabel('判断理由', {exact: true}).isEnabled(), true);
      await panel.getByLabel('判断理由', {exact: true}).fill('更正后的隔离测试意见');
      assert.equal(await panel.getByRole('button', {name: '恢复评阅提交（原幂等键）', exact: true}).count(), 0);
    } else {
      assert.equal(await panel.getByLabel('判断理由', {exact: true}).isDisabled(), true);
      await page.reload();
      if (scenario === 'NETWORK') {
        await panel.getByRole('button', {name: '恢复评阅提交（原幂等键）', exact: true}).click();
        await panel.getByText('评阅已保存', {exact: false}).waitFor(); assert.deepEqual(sent[0], sent[1]);
      } else {
        await panel.getByRole('button', {name: '查询原评阅任务', exact: true}).click();
        await panel.getByText(`原评阅任务：${scenario === 'FAILED_FINAL' ? 'FAILED_FINAL' : 'SUCCEEDED'}`, {exact: false}).waitFor(); assert.equal(sent.length, 1);
        if (scenario === 'FAILED_FINAL') await panel.getByRole('button', {name: '保留原请求后更正', exact: true}).click();
      }
      if (scenario !== 'FAILED_FINAL') assert.equal(await panel.getByLabel('确认本人完成评阅', {exact: true}).isChecked(), false);
      assert.equal(await panel.getByLabel('判断理由', {exact: true}).isEnabled(), true);
    }
    assert.equal(sent[0].blind, false); assert.equal('actor_id' in sent[0], false);
    checks.push(scenario); await context.close();
  }
  console.log(JSON.stringify({status: 'PASS', evidence_class: 'ISOLATED_BROWSER_WITH_API_RESPONSE_DOUBLES', checks, real_human_labels: 0, model_calls: 0}));
} finally {await browser.close();}
