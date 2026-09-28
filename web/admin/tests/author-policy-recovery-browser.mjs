import { chromium } from "playwright";
import assert from "node:assert/strict";

const browser = await chromium.launch({channel: "chrome", headless: true});
const api = "http://127.0.0.1:8137";
const ui = process.env.NOVEL_FORGE_AUTHOR_UI_URL || "http://127.0.0.1:3138";
const project = "policy-recovery-fixture", book = "book:policy-recovery";
const workspace = {books: [{book_id: book, workspace_id: "workspace:policy", title: "配置恢复隔离页面", version: 1, status: "DESIGN_PENDING", production_profile: {}, runtime_policy: {}}], runs: [], profiles: [], snapshots: [], budget_scopes: [], approved_characters: []};
const checks = [];
try {
  for (const scenario of ["422", "403", "500", "NETWORK", "409", "FAILED_RETRYABLE", "DEAD_LETTER"]) {
    const context = await browser.newContext();
    const page = await context.newPage();
    page.on("pageerror", error => console.error(scenario, error.message));
    const sent = []; let state = scenario === "FAILED_RETRYABLE" ? "FAILED_RETRYABLE" : scenario === "DEAD_LETTER" ? "DEAD_LETTER" : "FAILED_FINAL";
    let lookedUp = false, cancelled = false;
    const operation = {operation_id: `operation:${scenario}`, status: state, outputs: []};
    await page.route(`${api}/**`, async route => {
      const request = route.request(), url = new URL(request.url());
      const respond = (body, status = 200) => route.fulfill({status, contentType: "application/json", body: JSON.stringify(body), headers: {"Access-Control-Allow-Origin": "*"}});
      if (request.method() === "OPTIONS") return route.fulfill({status: 204, headers: {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS", "Access-Control-Allow-Headers": "content-type"}});
      if (url.pathname === "/product/projects") return respond([{project_id: project, title: "配置恢复测试", workspace_id: "workspace:policy"}]);
      if (url.pathname.endsWith("/author-workspace")) return respond(workspace);
      if (url.pathname === "/product/content-authority/commands") {
        sent.push(request.postDataJSON());
        if (sent.length === 1 && ["422", "403", "500", "409"].includes(scenario)) return respond({detail: {code: scenario === "409" ? "IDEMPOTENCY_CONFLICT" : "TEST_REJECTION", message: "controlled API response fixture"}}, Number(scenario));
        if (sent.length === 1 && scenario === "NETWORK") return route.abort("failed");
        return respond({...operation, status: "READY"}, 202);
      }
      if (url.pathname === "/product/content-authority/operations") {
        assert.equal(url.searchParams.get("idempotency_key"), sent[0].idempotency_key); lookedUp = true;
        return respond([{operation_id: operation.operation_id, definition_name: "book.production_profile.author"}]);
      }
      if (url.pathname.endsWith("/cancel")) {assert.equal(request.postDataJSON().idempotency_key, `author-config-cancel:${operation.operation_id}`); cancelled = true; state = "CANCELLED"; return respond({status: "CANCELLATION_REQUESTED"}, 202);}
      if (url.pathname.includes("/content-authority/operations/")) return respond({...operation, status: state});
      return route.continue();
    });
    await page.goto(`${ui}/production`);
    await page.getByLabel("项目", {exact: true}).selectOption(project);
    await page.getByLabel("作品", {exact: true}).selectOption(book);
    await page.getByLabel("配置名称", {exact: true}).fill(`配置 ${scenario}`);
    await page.getByLabel("策略选择依据", {exact: true}).fill("Controlled UI failure recovery fixture; no model calls.");
    await page.getByRole("button", {name: "确认并保存新配置", exact: true}).click();
    const input = page.getByLabel("配置名称", {exact: true});
    if (["422", "403"].includes(scenario)) {
      await page.getByRole("alert").waitFor();
      await input.fill(`更正 ${scenario}`);
      await page.reload();
      await page.getByText("配置提交拒绝记录（1）", {exact: true}).waitFor();
      assert.equal(await input.inputValue(), `更正 ${scenario}`);
      assert.equal(await page.getByRole("button", {name: "恢复配置提交（原输入和幂等键）", exact: true}).count(), 0);
    } else if (["500", "NETWORK"].includes(scenario)) {
      await page.getByRole("alert").waitFor(); assert.equal(await input.isDisabled(), true);
      await page.reload();
      await page.getByRole("button", {name: "恢复配置提交（原输入和幂等键）", exact: true}).click();
      await page.getByText(`配置任务：FAILED_FINAL · ${operation.operation_id}`, {exact: false}).waitFor();
      assert.deepEqual(sent[0], sent[1]); await input.fill("终止后更正");
    } else if (scenario === "409") {
      await page.getByRole("button", {name: "按原幂等键查询配置任务", exact: true}).click();
      await page.getByRole("button", {name: "跟踪已提交的原任务", exact: true}).waitFor();
      assert.equal(await input.isDisabled(), true); assert.equal(lookedUp, true); assert.equal(sent.length, 1);
      await page.getByRole("button", {name: "跟踪已提交的原任务", exact: true}).click();
      await input.fill("保留拒绝历史后更正");
    } else if (scenario === "FAILED_RETRYABLE") {
      await page.getByRole("button", {name: "停止原任务后更正配置", exact: true}).waitFor(); assert.equal(await input.isDisabled(), true);
      await page.getByRole("button", {name: "停止原任务后更正配置", exact: true}).click();
      await input.fill("原任务取消后更正"); assert.equal(cancelled, true);
    } else {
      await page.getByText(`配置任务：DEAD_LETTER · ${operation.operation_id}`, {exact: false}).waitFor();
      await input.fill("死信保留后更正");
    }
    checks.push(scenario); await context.close();
  }
  console.log(JSON.stringify({status: "PASS", evidence_class: "ISOLATED_BROWSER_WITH_API_RESPONSE_DOUBLES", checks}));
} finally {await browser.close();}
