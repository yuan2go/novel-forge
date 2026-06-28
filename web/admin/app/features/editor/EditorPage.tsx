"use client";

import { FileSearch, GitPullRequest, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { applyEditorPatch, createDraftDiffReport, createEditorPatch, loadDraftEditor, loadEditorData, type DraftEditorState, type EditorArtifactRow } from "./api";

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
  const [editorState, setEditorState] = useState<DraftEditorState | null>(null);
  const [editorText, setEditorText] = useState("");
  const [commandMode, setCommandMode] = useState("polish");
  const [selectedOperationIds, setSelectedOperationIds] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const drafts = assets.filter((asset) => ["draft_chapter", "draft_version"].includes(asset.type));
  const patches = artifacts.filter((artifact) => artifact.type === "editor_patch");
  const diffs = artifacts.filter((artifact) => artifact.type === "draft_diff_report");
  const selectedPatch = patches.find((patch) => patch.path === patchPath);
  const operations = selectedPatch?.operations ?? [];

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

  useEffect(() => {
    setSelectedOperationIds([]);
  }, [patchPath]);

  useEffect(() => {
    if (!draftPath) return;
    loadDraftEditor(draftPath)
      .then((state) => {
        setEditorState(state);
        setEditorText(state.text || "");
        setBasePath((current) => current || state.path);
      })
      .catch(() => {
        setEditorState(null);
        setEditorText("");
      });
  }, [draftPath]);

  return (
    <FeatureShell title="AI 编辑器" subtitle="基于 editor_patch 和 draft_diff_report 做段落级建议、应用、diff 和回滚前复盘。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="Patch" value={String(patches.length)} />
        <Metric label="Diff" value={String(diffs.length)} />
        <Metric label="Drafts" value={String(drafts.length)} />
        <Metric label="Artifacts" value={String(artifacts.length)} />
        <Metric label="当前字数" value={String(editorText.length)} />
      </section>
      <section className="editorWorkbenchGrid">
        <div className="panel">
          <PanelHeader title="相关资料侧栏" icon={<FileSearch size={18} />} />
          <DataTable
            emptyText="暂无相关资料"
            columns={["类型", "标题", "风险"]}
            rows={assets
              .filter((asset) => ["context_bundle", "chapter_plan", "review_report", "revision_plan", "continuity_bible", "quality_standard_profile", "style_profile"].includes(asset.type))
              .slice(0, 12)
              .map((asset) => [asset.type, asset.title, asset.risk_level || asset.status || "-"])}
          />
        </div>
        <div className="panel richEditorPanel">
          <PanelHeader title="富文本编辑区" icon={<Save size={18} />} />
          <div className="studioActions">
            {EDITOR_COMMANDS.map((command) => (
              <button className={commandMode === command.key ? "primaryButton" : "secondaryButton"} key={command.key} onClick={() => { setCommandMode(command.key); setInstructions(command.prompt); }}>
                {command.label}
              </button>
            ))}
          </div>
          <textarea className="richDraftEditor" value={editorText} onChange={(event) => setEditorText(event.target.value)} rows={20} />
          <div className="previewText">当前稿件：{editorState?.title || draftPath || "未选择"} / 状态 {editorState?.status || "-"} / 版本 {editorState?.version_index ?? "-"}</div>
        </div>
        <div className="panel">
          <PanelHeader title="版本历史侧栏" icon={<GitPullRequest size={18} />} />
          <DataTable
            emptyText="暂无版本"
            columns={["类型", "状态", "路径"]}
            rows={[...patches, ...diffs].slice(0, 12).map((artifact) => [
              artifact.type,
              <span className={statusClass(artifact.status || "")} key={`${artifact.path}-version-status`}>{artifact.status || "-"}</span>,
              <button className="linkButton" key={artifact.path} onClick={() => artifact.type === "editor_patch" ? setPatchPath(artifact.path) : setTargetPath(artifact.path)}>{artifact.path}</button>
            ])}
          />
        </div>
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
            <button className="secondaryButton" disabled={busy || !patchPath || !selectedOperationIds.length} onClick={() => runAction(() => applyEditorPatch(patchPath, selectedOperationIds), "选中建议已应用")}>应用选中</button>
            <button className="secondaryButton" disabled={busy || !patchPath} onClick={() => runAction(() => applyEditorPatch(patchPath), "Patch 已全部应用")}>应用全部</button>
            <input value={basePath} onChange={(event) => setBasePath(event.target.value)} placeholder="base draft path" />
            <input value={targetPath} onChange={(event) => setTargetPath(event.target.value)} placeholder="target draft path" />
            <button className="secondaryButton" disabled={busy || !basePath || !targetPath} onClick={() => runAction(() => createDraftDiffReport(basePath, targetPath), "Diff 报告已创建")}>创建 Diff</button>
          </div>
        </div>
      </section>
      <section className="panel">
        <PanelHeader title="段落级建议" icon={<GitPullRequest size={18} />} />
        <div className="studioActions">
          <button className="secondaryButton" disabled={!operations.length} onClick={() => setSelectedOperationIds(operations.map(operationId))}>全选</button>
          <button className="secondaryButton" disabled={!selectedOperationIds.length} onClick={() => setSelectedOperationIds([])}>清空</button>
        </div>
        <DataTable
          emptyText="选择或生成 editor_patch 后显示建议"
          columns={["选择", "段落", "风险", "修订原因", "原文", "建议"]}
          rows={operations.map((operation, index) => {
            const opId = operationId(operation, index);
            return [
              <input
                type="checkbox"
                checked={selectedOperationIds.includes(opId)}
                onChange={(event) => {
                  setSelectedOperationIds((current) => event.target.checked ? [...new Set([...current, opId])] : current.filter((item) => item !== opId));
                }}
                key={`${opId}-check`}
              />,
              String(operation.paragraph_index ?? operation.target ?? index + 1),
              <span className={statusClass(String(operation.risk ?? "low"))} key={`${opId}-risk`}>{String(operation.risk ?? "low")}</span>,
              String(operation.rationale || operation.instruction || "-"),
              <span className="previewText" key={`${opId}-before`}>{String(operation.before || "").slice(0, 160)}</span>,
              <span className="previewText" key={`${opId}-after`}>{String(operation.after || "").slice(0, 160)}</span>
            ];
          })}
        />
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

function operationId(operation: Record<string, unknown>, index = 0) {
  return String(operation.op_id || `op-${index + 1}`);
}

const EDITOR_COMMANDS = [
  { key: "continue", label: "继续写", prompt: "续写当前章节 600-1000 字，承接最后一段的因果，不引入未登记设定，保留下一章钩子。" },
  { key: "expand", label: "扩写", prompt: "扩写选中段落的动作、心理和环境压力，但不改变剧情事实和人物状态。" },
  { key: "shorten", label: "缩写", prompt: "压缩冗余表达，保留关键因果、情绪转折和伏笔信号。" },
  { key: "polish", label: "润色", prompt: "润色段落表达，降低 AI 味，保持项目 style_profile 参数，不模仿具体作者。" },
  { key: "risk", label: "风险修订", prompt: "根据审稿、原创性和连续性风险生成段落级修订建议，所有改动必须可回滚。" }
];
