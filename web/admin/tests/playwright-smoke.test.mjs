import { describe, it } from "node:test";
import assert from "node:assert/strict";

const REQUIRED = process.env.NOVEL_FORGE_REQUIRE_PLAYWRIGHT === "1";
const BASE_URL = process.env.NOVEL_FORGE_WEB_BASE_URL || "http://127.0.0.1:3000";

async function loadPlaywright(t) {
  try {
    return await import("playwright");
  } catch (error) {
    if (REQUIRED) {
      throw new Error("Playwright is required for this smoke run. Install it in web/admin and run with NOVEL_FORGE_WEB_BASE_URL.", { cause: error });
    }
    t.skip("Playwright is not installed; browser smoke is available via npm run smoke:browser after installing playwright.");
    return null;
  }
}

describe("Novel Forge browser smoke", () => {
  it("opens key local factory pages with Playwright when available", async (t) => {
    const playwright = await loadPlaywright(t);
    if (!playwright) return;

    const browser = await playwright.chromium.launch();
    const page = await browser.newPage();
    const consoleErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });

    const routes = [
      ["/", "个人本地小说工厂"],
      ["/assets", "创作资产工作台"],
      ["/impact", "变更影响分析中心"],
      ["/quality", "质量与发布门禁"],
      ["/evaluation", "模型评测"],
      ["/settings", "设置中心"],
      ["/tasks", "任务中心"],
      ["/os", "Novel Operating System Console"],
      ["/workflow-runtime", "Workflow Runtime Console"],
      ["/agent-dispatch", "Agent Dispatch Center"],
      ["/novel-kg", "Novel KG Workbench"],
      ["/trace-timeline", "Trace Timeline"],
      ["/cost-dashboard", "Cost Dashboard"],
      ["/invalidation", "Invalidation Map"],
      ["/review-rework", "Review Rework Board"],
      ["/health", "健康"]
    ];

    for (const [route, expectedText] of routes) {
      const response = await page.goto(`${BASE_URL}${route}`, { waitUntil: "domcontentloaded", timeout: 15000 });
      assert.ok(response && response.status() < 500, `${route} returned ${response?.status()}`);
      await page.getByText(expectedText, { exact: false }).first().waitFor({ timeout: 10000 });
    }

    await browser.close();
    assert.equal(consoleErrors.filter((item) => !item.includes("favicon")).length, 0, consoleErrors.join("\n"));
  });
});
