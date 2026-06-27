import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const root = new URL("..", import.meta.url).pathname;

function read(relativePath) {
  return readFileSync(join(root, relativePath), "utf8");
}

describe("Novel Forge admin feature architecture", () => {
  it("keeps V6/V7 navigation groups and local factory centers wired", () => {
    const navigation = read("app/shared/navigation.tsx");
    for (const label of ["工作区", "创作资产", "分析拆解", "生产流程", "管理工具"]) {
      assert.match(navigation, new RegExp(label));
    }
    for (const key of ["publishing_center", "reader_feedback", "data_statistics", "settings_center", "health"]) {
      assert.match(navigation, new RegExp(key));
    }
    assert.doesNotMatch(navigation, /会员|付费|邀请|团队空间/);
  });

  it("has routed feature modules for P2 centers", () => {
    for (const path of [
      "app/features/assets/AssetsCenterPage.tsx",
      "app/features/impact/ChangeImpactPage.tsx",
      "app/features/quality/QualityGatePage.tsx",
      "app/features/evaluation/EvaluationCenterPage.tsx",
      "app/features/settings/SettingsCenterPage.tsx",
      "app/features/tasks/TasksCenterPage.tsx"
    ]) {
      assert.equal(existsSync(join(root, path)), true, `${path} should exist`);
    }
  });

  it("exposes asset graph, publishing calendar, version registry, and impact visualization in source", () => {
    const assets = read("app/features/assets/AssetsCenterPage.tsx");
    assert.match(assets, /loadAssetGraph/);
    assert.match(assets, /引用图谱/);
    assert.match(assets, /assetGraphCanvas layered/);

    const quality = read("app/features/quality/QualityGatePage.tsx");
    for (const token of ["发布日历", "发布版本库", "平台规则与发布日志", "preparePlatformRelease", "adapterDryRun"]) {
      assert.match(quality, new RegExp(token));
    }

    const impact = read("app/features/impact/ChangeImpactPage.tsx");
    for (const token of ["影响图谱", "impact_edges", "severity_summary"]) {
      assert.match(impact, new RegExp(token));
    }
  });

  it("keeps API client contracts for P2 endpoints explicit", () => {
    const assetsApi = read("app/features/assets/api.ts");
    assert.match(assetsApi, /\/product\/assets\/graph/);

    const qualityApi = read("app/features/quality/api.ts");
    for (const endpoint of ["/product/publishing/plan", "/product/publishing/log", "/product/publishing/release-package", "/product/publishing/adapters", "/product/publishing/adapter-release"]) {
      assert.match(qualityApi, new RegExp(endpoint.replaceAll("/", "\\/")));
    }
  });

  it("contains an optional Playwright browser smoke test", () => {
    const smoke = read("tests/playwright-smoke.test.mjs");
    assert.match(smoke, /playwright/);
    assert.match(smoke, /NOVEL_FORGE_WEB_BASE_URL/);
    assert.match(smoke, /个人本地小说工厂/);
  });
});
