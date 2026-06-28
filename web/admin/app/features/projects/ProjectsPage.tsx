"use client";

import { Boxes, Copy, RotateCcw, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { FeatureAssetRow, ProjectHealthReport, ProjectOperatingDashboard, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createProject, duplicateProject, loadProjectsData, repairProjectScope, transitionProject, type ProjectWizardLibrary } from "./api";

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [health, setHealth] = useState<ProjectHealthReport | null>(null);
  const [libraries, setLibraries] = useState<ProjectWizardLibrary[]>([]);
  const [operating, setOperating] = useState<ProjectOperatingDashboard | null>(null);
  const [title, setTitle] = useState("");
  const [seriesTitle, setSeriesTitle] = useState("");
  const [bookNumber, setBookNumber] = useState("");
  const [platformProfilePath, setPlatformProfilePath] = useState("");
  const [genreMarketProfilePath, setGenreMarketProfilePath] = useState("");
  const [qualityStandardProfilePath, setQualityStandardProfilePath] = useState("");
  const [styleProfilePath, setStyleProfilePath] = useState("");
  const [continuityBiblePath, setContinuityBiblePath] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    const [projectRows, healthReport, libraryRows, operatingRows] = await loadProjectsData();
    setProjects(projectRows);
    setHealth(healthReport);
    setLibraries(libraryRows);
    setOperating(operatingRows);
    setPlatformProfilePath((current) => current || firstAssetPath(libraryRows, "platform_profile"));
    setGenreMarketProfilePath((current) => current || firstAssetPath(libraryRows, "genre_market_profile"));
    setQualityStandardProfilePath((current) => current || firstAssetPath(libraryRows, "quality_standard_profile"));
    setStyleProfilePath((current) => current || firstAssetPath(libraryRows, "style_profile"));
    setContinuityBiblePath((current) => current || firstAssetPath(libraryRows, "continuity_bible"));
  }

  async function runAction(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      await action();
      setNotice(message);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  return (
    <FeatureShell title="项目管理" subtitle="创建项目时绑定平台、题材、精品标准、文风和连续性设定，保证后续生产链有稳定输入。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="项目数" value={String(projects.length)} />
        <Metric label="资产" value={String(health?.summary.asset_count ?? 0)} />
        <Metric label="平均投资分" value={String(operating?.summary.average_investment_score ?? 0)} />
        <Metric label="高风险项目" value={String(operating?.summary.high_risk_project_count ?? 0)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="创建项目向导" icon={<Boxes size={18} />} />
          <div className="wizardSteps">
            <span>1. 基本信息</span>
            <span>2. 平台/题材</span>
            <span>3. 精品/文风</span>
            <span>4. 连续性设定</span>
          </div>
          <div className="formGrid wide">
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="项目标题" />
            <input value={seriesTitle} onChange={(event) => setSeriesTitle(event.target.value)} placeholder="系列名" />
            <input value={bookNumber} onChange={(event) => setBookNumber(event.target.value)} placeholder="书号" />
            <ProfileSelect label="平台画像" value={platformProfilePath} onChange={setPlatformProfilePath} options={assetsByType(libraries, "platform_profile")} />
            <ProfileSelect label="题材画像" value={genreMarketProfilePath} onChange={setGenreMarketProfilePath} options={assetsByType(libraries, "genre_market_profile")} />
            <ProfileSelect label="精品标准" value={qualityStandardProfilePath} onChange={setQualityStandardProfilePath} options={assetsByType(libraries, "quality_standard_profile")} />
            <ProfileSelect label="文风目标" value={styleProfilePath} onChange={setStyleProfilePath} options={assetsByType(libraries, "style_profile")} />
            <ProfileSelect label="连续性设定" value={continuityBiblePath} onChange={setContinuityBiblePath} options={assetsByType(libraries, "continuity_bible")} />
            <button className="primaryButton" disabled={busy || !title.trim()} onClick={() => runAction(() => createProject({
              title,
              seriesTitle,
              bookNumber: bookNumber ? Number(bookNumber) : undefined,
              platformProfilePath,
              genreMarketProfilePath,
              qualityStandardProfilePath,
              styleProfilePath,
              continuityBiblePath
            }), "项目已创建")}>
              <Save size={18} />
              创建
            </button>
          </div>
          <p className="muted">缺少可选 profile 时，先到创作资产工作台创建平台画像、题材画像、精品标准、文风目标或连续性设定。</p>
        </div>

        <div className="panel">
          <PanelHeader title="项目级审计" icon={<ShieldCheck size={18} />} />
          <p className="previewText">项目范围审计用于发现无项目资产、跨项目 lineage、handoff 产物错绑。</p>
          <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => repairProjectScope(), "项目范围已审计并尝试修复")}>
            <RotateCcw size={18} />
            审计并修复
          </button>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="经营排序" icon={<ShieldCheck size={18} />} />
        <DataTable
          emptyText="暂无经营评分"
          columns={["项目", "投资分", "风险分", "动量", "今日动作", "瓶颈", "Profile"]}
          rows={(operating?.projects ?? []).map((project) => [
            project.title,
            String(project.investment_score),
            String(project.risk_score),
            String(project.momentum_score),
            project.today_action.label,
            project.bottleneck.label,
            `${project.profile_binding_count}/${project.profile_binding_total}`
          ])}
        />
      </section>

      <section className="panel">
        <PanelHeader title="项目列表" icon={<Boxes size={18} />} />
        <DataTable
          emptyText="暂无项目"
          columns={["标题", "系列", "状态", "章节", "绑定", "路径", "操作"]}
          rows={projects.map((project) => {
            const config = project.project_config ?? {};
            const bindingCount = ["platform_profile_path", "genre_market_profile_path", "quality_standard_profile_path", "style_profile_path", "continuity_bible_path"].filter((key) => Boolean(config[key])).length;
            return [
              project.title,
              project.series_title || "-",
              <span className={statusClass(project.status || "")} key={`${project.project_id}-status`}>{project.status || "-"}</span>,
              String(project.chapter_count ?? 0),
              `${bindingCount}/5`,
              <span className="pathText" key={`${project.project_id}-path`}>{project.path}</span>,
              <div className="studioActions" key={`${project.project_id}-actions`}>
                <button className="secondaryButton tableButton" disabled={busy} onClick={() => runAction(() => duplicateProject(project.project_id, `${project.title} copy`), "项目已复制")}><Copy size={15} />复制</button>
                <button className="secondaryButton tableButton" disabled={busy} onClick={() => runAction(() => transitionProject(project.project_id, project.status === "paused" ? "restore" : "pause"), "项目状态已更新")}>{project.status === "paused" ? "恢复" : "暂停"}</button>
                <button className="secondaryButton tableButton" disabled={busy} onClick={() => runAction(() => transitionProject(project.project_id, "archive"), "项目已归档")}>归档</button>
              </div>
            ];
          })}
        />
      </section>
    </FeatureShell>
  );
}

function ProfileSelect({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: FeatureAssetRow[] }) {
  return (
    <label className="selectWrap">
      <span>{label}</span>
      <select value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">自动创建/稍后绑定</option>
        {options.map((asset) => (
          <option value={asset.path} key={asset.path}>{asset.title || asset.id}</option>
        ))}
      </select>
    </label>
  );
}

function assetsByType(libraries: ProjectWizardLibrary[], assetType: string): FeatureAssetRow[] {
  return libraries.flatMap((library) => library.assets).filter((asset) => asset.type === assetType);
}

function firstAssetPath(libraries: ProjectWizardLibrary[], assetType: string): string {
  return assetsByType(libraries, assetType)[0]?.path || "";
}
