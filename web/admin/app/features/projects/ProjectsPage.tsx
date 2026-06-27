"use client";

import { Boxes, Copy, RotateCcw, Save, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { ProjectHealthReport, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createProject, duplicateProject, loadProjectsData, repairProjectScope, transitionProject } from "./api";

export function ProjectsPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [health, setHealth] = useState<ProjectHealthReport | null>(null);
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
    const [projectRows, healthReport] = await loadProjectsData();
    setProjects(projectRows);
    setHealth(healthReport);
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
        <Metric label="范围问题" value={String(health?.summary.scope_issue_count ?? 0)} />
        <Metric label="待 Handoff" value={String(health?.summary.pending_handoff_count ?? 0)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="创建项目" icon={<Boxes size={18} />} />
          <div className="formGrid wide">
            <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="项目标题" />
            <input value={seriesTitle} onChange={(event) => setSeriesTitle(event.target.value)} placeholder="系列名" />
            <input value={bookNumber} onChange={(event) => setBookNumber(event.target.value)} placeholder="书号" />
            <input value={platformProfilePath} onChange={(event) => setPlatformProfilePath(event.target.value)} placeholder="platform_profile path" />
            <input value={genreMarketProfilePath} onChange={(event) => setGenreMarketProfilePath(event.target.value)} placeholder="genre_market_profile path" />
            <input value={qualityStandardProfilePath} onChange={(event) => setQualityStandardProfilePath(event.target.value)} placeholder="quality_standard_profile path" />
            <input value={styleProfilePath} onChange={(event) => setStyleProfilePath(event.target.value)} placeholder="style_profile path" />
            <input value={continuityBiblePath} onChange={(event) => setContinuityBiblePath(event.target.value)} placeholder="continuity_bible path" />
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
