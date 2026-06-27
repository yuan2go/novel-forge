"use client";

import { FileSearch, GitPullRequest, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { applyEditorPatch, createDraftDiffReport, createEditorPatch, loadEditorData, type EditorArtifactRow } from "./api";

export function EditorPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [artifacts, setArtifacts] = useState<EditorArtifactRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [draftPath, setDraftPath] = useState("");
  const [patchPath, setPatchPath] = useState("");
  const [basePath, setBasePath] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [instructions, setInstructions] = useState("按审稿问题生成段落级修改建议，保持原创性边界和项目连续性。");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const drafts = assets.filter((asset) => ["draft_chapter", "draft_version"].includes(asset.type));
  const patches = artifacts.filter((artifact) => artifact.type === "editor_patch");
  const diffs = artifacts.filter((artifact) => artifact.type === "draft_diff_report");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, artifactRows, assetRows] = await loadEditorData(nextProjectId);
    setProjects(projectRows);
    setArtifacts(artifactRows);
    setAssets(assetRows);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setDraftPath((current) => current || assetRows.find((asset) => asset.type.includes("draft"))?.path || "");
    setPatchPath((current) => current || artifactRows.find((row) => row.type === "editor_patch")?.path || "");
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
    <FeatureShell title="AI 编辑器" subtitle="基于 editor_patch 和 draft_diff_report 做段落级建议、应用、diff 和回滚前复盘。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="Patch" value={String(patches.length)} />
        <Metric label="Diff" value={String(diffs.length)} />
        <Metric label="Drafts" value={String(drafts.length)} />
        <Metric label="Artifacts" value={String(artifacts.length)} />
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="生成修订建议" icon={<Save size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={draftPath} onChange={(event) => setDraftPath(event.target.value)}>
              <option value="">选择稿件</option>
              {drafts.map((asset) => <option value={asset.path} key={asset.path}>{asset.title}</option>)}
            </select>
            <textarea value={instructions} onChange={(event) => setInstructions(event.target.value)} rows={5} />
            <button className="primaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => createEditorPatch(draftPath, instructions, selectedProject?.path), "编辑 Patch 已创建")}>创建 Patch</button>
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="应用与 Diff" icon={<GitPullRequest size={18} />} />
          <div className="formGrid wide">
            <select value={patchPath} onChange={(event) => setPatchPath(event.target.value)}>
              <option value="">选择 Patch</option>
              {patches.map((patch) => <option value={patch.path} key={patch.path}>{patch.title}</option>)}
            </select>
            <button className="secondaryButton" disabled={busy || !patchPath} onClick={() => runAction(() => applyEditorPatch(patchPath), "Patch 已应用")}>应用 Patch</button>
            <input value={basePath} onChange={(event) => setBasePath(event.target.value)} placeholder="base draft path" />
            <input value={targetPath} onChange={(event) => setTargetPath(event.target.value)} placeholder="target draft path" />
            <button className="secondaryButton" disabled={busy || !basePath || !targetPath} onClick={() => runAction(() => createDraftDiffReport(basePath, targetPath), "Diff 报告已创建")}>创建 Diff</button>
          </div>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="编辑资产" icon={<FileSearch size={18} />} />
        <DataTable
          emptyText="暂无编辑资产"
          columns={["类型", "标题", "状态", "目标稿件", "操作数", "路径"]}
          rows={artifacts.map((artifact) => [
            artifact.type,
            artifact.title,
            <span className={statusClass(artifact.status || "")} key={`${artifact.path}-status`}>{artifact.status || "-"}</span>,
            artifact.target_draft_path || "-",
            String(artifact.operations?.length ?? 0),
            <span className="pathText" key={artifact.path}>{artifact.path}</span>
          ])}
        />
      </section>
    </FeatureShell>
  );
}
