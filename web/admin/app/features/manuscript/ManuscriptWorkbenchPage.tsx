"use client";

import { Activity, BookOpen, FileSearch, GitPullRequest, RefreshCw, Save, ShieldCheck, Workflow } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useMemo, useState } from "react";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { exportDraft, listProjects, loadDraftEditor, loadDraftWorkbench, loadManuscriptWorkbench, saveDraftEdit } from "./api";
import { traceField, type DraftEditorState, type DraftWorkbench, type ExportResult, type ManuscriptWorkbench, type ProjectOption } from "./types";

type Language = "zh" | "en";

export function ManuscriptWorkbenchPage() {
  const [language, setLanguage] = useState<Language>("zh");
  const [projects, setProjects] = useState<ProjectOption[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState("");
  const [drafts, setDrafts] = useState<DraftWorkbench | null>(null);
  const [selectedDraft, setSelectedDraft] = useState("");
  const [editor, setEditor] = useState<DraftEditorState | null>(null);
  const [workbench, setWorkbench] = useState<ManuscriptWorkbench | null>(null);
  const [exportResult, setExportResult] = useState<ExportResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const zh = language === "zh";
  const selectedProject = projects.find((project) => project.project_id === selectedProjectId);
  const trace = workbench?.trace_summary;
  const paragraphs = (editor?.text ?? "").split(/\n+/).map((line) => line.trim()).filter(Boolean);

  async function refresh(projectId = selectedProjectId, draftPath = selectedDraft) {
    setError("");
    const projectRows = await listProjects();
    const nextProjectId = projectId || projectRows[0]?.project_id || "";
    const draftRows = await loadDraftWorkbench(nextProjectId);
    const nextDraftPath = draftPath || draftRows.drafts[0]?.path || "";
    const [nextWorkbench, nextEditor] = await Promise.all([
      loadManuscriptWorkbench({ projectId: nextProjectId, draftPath: nextDraftPath || undefined }),
      nextDraftPath ? loadDraftEditor(nextDraftPath) : Promise.resolve(null)
    ]);
    setProjects(projectRows);
    setSelectedProjectId(nextProjectId);
    setDrafts(draftRows);
    setSelectedDraft(nextDraftPath);
    setWorkbench(nextWorkbench);
    setEditor(nextEditor);
  }

  async function runAction<T>(action: () => Promise<T>, message: string): Promise<T | undefined> {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await action();
      setNotice(message);
      return result;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return undefined;
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  useEffect(() => {
    if (!selectedDraft) return;
    Promise.all([
      loadDraftEditor(selectedDraft).then(setEditor),
      loadManuscriptWorkbench({ projectId: selectedProjectId, draftPath: selectedDraft }).then(setWorkbench)
    ]).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, [selectedDraft]);

  const profileRows = useMemo(() => {
    const context = workbench?.selected_draft?.production_context ?? {};
    const profiles = (context.profiles && typeof context.profiles === "object" ? context.profiles : {}) as Record<string, Record<string, unknown> | null>;
    return Object.entries(profiles).map(([key, value]) => [
      key,
      value?.title ? String(value.title) : "-",
      value?.path ? String(value.path) : "-",
      value?.id ? String(value.id) : "-"
    ]);
  }, [workbench]);

  return (
    <main className="manuscriptShell">
      <header className="manuscriptHeader panel">
        <div>
          <p className="eyebrow">Novel Forge Manuscript Workbench</p>
          <h1>{zh ? "稿件阅读、编辑与生产溯源" : "Read, Edit, And Trace Manuscript Production"}</h1>
          <p>{zh ? "围绕当前章节聚合草稿、上下文、生成记录、审稿、编辑补丁和 Agent 运行证据。" : "A chapter-centric view of drafts, context, generation runs, reviews, editor patches, and Agent evidence."}</p>
        </div>
        <div className="studioActions">
          <button className="secondaryButton" onClick={() => setLanguage(zh ? "en" : "zh")}>{zh ? "EN" : "中文"}</button>
          <a className="secondaryButton" href="/">{zh ? "返回总控台" : "Console"}</a>
          <button className="primaryButton" disabled={busy} onClick={() => runAction(() => refresh(), zh ? "已刷新" : "refreshed")}>
            <RefreshCw size={18} />
            {zh ? "刷新" : "Refresh"}
          </button>
        </div>
      </header>

      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="manuscriptGrid">
        <aside className="panel manuscriptSidebar">
          <PanelHeader title={zh ? "章节导航" : "Chapter Navigator"} icon={<BookOpen size={18} />} />
          <label className="selectWrap">
            <span>{zh ? "项目" : "Project"}</span>
            <select
              value={selectedProjectId}
              onChange={(event) => runAction(() => refresh(event.target.value, ""), zh ? "项目已切换" : "project changed")}
            >
              <option value="">{zh ? "选择项目" : "Select project"}</option>
              {projects.map((project) => (
                <option value={project.project_id} key={project.project_id}>{project.title}</option>
              ))}
            </select>
          </label>
          <div className="chapterList">
            {(workbench?.chapters ?? []).map((chapter) => (
              <button
                className={chapter.latest_draft_path === selectedDraft ? "chapterCard active" : "chapterCard"}
                key={chapter.latest_draft_path}
                onClick={() => setSelectedDraft(chapter.latest_draft_path)}
              >
                <span>{zh ? "第" : "Chapter"} {chapter.chapter}</span>
                <strong>{chapter.latest_title || chapter.latest_draft_path}</strong>
                <small>{chapter.draft_count} drafts / {chapter.review_count} reviews</small>
              </button>
            ))}
          </div>
        </aside>

        <section className="manuscriptMain">
          <div className="panel">
            <PanelHeader title={zh ? "正文阅读与编辑" : "Reader And Editor"} icon={<Save size={18} />} />
            <div className="formGrid">
              <label className="selectWrap">
                <span>{zh ? "草稿" : "Draft"}</span>
                <select value={selectedDraft} onChange={(event) => setSelectedDraft(event.target.value)}>
                  <option value="">{zh ? "选择草稿" : "Select draft"}</option>
                  {(drafts?.drafts ?? []).map((draft) => (
                    <option value={draft.path} key={draft.path}>{draft.title || draft.path}</option>
                  ))}
                </select>
              </label>
              <button
                className="secondaryButton"
                disabled={busy || !editor}
                onClick={() => runAction(async () => {
                  if (!editor) return;
                  const saved = await saveDraftEdit({
                    draft_path: editor.path,
                    title: editor.title,
                    text: editor.text,
                    workspace_path: selectedProject?.path
                  });
                  await refresh(selectedProjectId, saved.draft_path || editor.path);
                }, zh ? "草稿已保存" : "draft saved")}
              >
                <Save size={18} />
                {zh ? "保存为新版本" : "Save Version"}
              </button>
              {["markdown", "docx", "epub"].map((format) => (
                <button
                  className="secondaryButton tableButton"
                  key={format}
                  disabled={busy || !editor}
                  onClick={() => editor && runAction(async () => setExportResult(await exportDraft(editor.path, format)), `${format} exported`)}
                >
                  {format.toUpperCase()}
                </button>
              ))}
            </div>
            {editor ? (
              <>
                <input value={editor.title} onChange={(event) => setEditor({ ...editor, title: event.target.value })} aria-label={zh ? "章节标题" : "Chapter title"} />
                <div className="readerEditorGrid manuscriptReaderEditor">
                  <article className="novelReader">
                    <div className="readerMeta">
                      <span className="statPill">v{editor.version_index}</span>
                      <span className="statPill">{editor.status}</span>
                      <span className={trace?.ready_for_review ? "badge ok" : "badge muted"}>{trace?.ready_for_review ? (zh ? "可审稿" : "review ready") : (zh ? "溯源不完整" : "trace partial")}</span>
                    </div>
                    <h2>{editor.title}</h2>
                    <div className="readerBody">
                      {paragraphs.length ? paragraphs.map((paragraph, index) => <p key={`${index}-${paragraph.slice(0, 18)}`}>{paragraph}</p>) : <p>{zh ? "暂无正文。" : "No draft text."}</p>}
                    </div>
                  </article>
                  <textarea className="studioDraftEditor" value={editor.text} onChange={(event) => setEditor({ ...editor, text: event.target.value })} aria-label={zh ? "正文编辑器" : "Draft editor"} />
                </div>
              </>
            ) : (
              <p className="previewText">{zh ? "选择草稿后开始阅读和编辑。" : "Select a draft to start reading and editing."}</p>
            )}
            {exportResult?.path ? <p className="previewText">{zh ? "最近导出" : "Latest export"}: {exportResult.path}</p> : null}
          </div>

          <div className="summaryBand manuscriptSummary">
            <Metric label={zh ? "上下文来源" : "Context Sources"} value={String(trace?.context_source_count ?? 0)} />
            <Metric label={zh ? "生成记录" : "Generation Runs"} value={String(trace?.generation_run_count ?? 0)} />
            <Metric label={zh ? "审稿报告" : "Reviews"} value={String(trace?.review_count ?? 0)} />
            <Metric label="Agent Runs" value={String(trace?.agent_run_count ?? 0)} />
          </div>

          <div className="manuscriptEvidenceGrid">
            <EvidencePanel title={zh ? "实际上下文来源" : "Actual Context Sources"} icon={<FileSearch size={18} />}>
              <DataTable
                emptyText={zh ? "暂无上下文来源" : "No context sources"}
                columns={zh ? ["资产", "类型", "后端 / ranker", "分数", "预览"] : ["Asset", "Type", "Backend / Ranker", "Score", "Preview"]}
                rows={(workbench?.context_sources ?? []).map((source) => [
                  source.title || source.path || source.id || "-",
                  source.type || "-",
                  `${source.backend || "-"} / ${source.ranker || "-"}`,
                  String(source.score || source.rank || "-"),
                  source.preview || "-"
                ])}
              />
            </EvidencePanel>

            <EvidencePanel title={zh ? "生成与版本链" : "Generation And Versions"} icon={<Workflow size={18} />}>
              <DataTable
                emptyText={zh ? "暂无生成记录" : "No generation records"}
                columns={zh ? ["类型", "状态", "模型", "资产"] : ["Type", "Status", "Model", "Asset"]}
                rows={[...(workbench?.generation_runs ?? []), ...(workbench?.versions ?? [])].map((row) => [
                  row.type,
                  <span className={statusClass(traceField(row, "status"))} key={`status-${row.path}`}>{traceField(row, "status") || row.status || "-"}</span>,
                  `${traceField(row, "provider") || traceField(row, "model_provider") || "-"} / ${traceField(row, "model") || traceField(row, "model_name") || "-"}`,
                  row.path
                ])}
              />
            </EvidencePanel>

            <EvidencePanel title={zh ? "审稿与修订" : "Review And Revision"} icon={<ShieldCheck size={18} />}>
              <DataTable
                emptyText={zh ? "暂无审稿或修订" : "No reviews or revisions"}
                columns={zh ? ["类型", "分数", "风险", "资产"] : ["Type", "Score", "Risk", "Asset"]}
                rows={[...(workbench?.reviews ?? []), ...(workbench?.revision_plans ?? [])].map((row) => [
                  row.type,
                  String((row.score ?? traceField(row, "overall_score")) || "-"),
                  row.risk_level || "-",
                  row.path
                ])}
              />
            </EvidencePanel>

            <EvidencePanel title={zh ? "Agent 过程观察" : "Agent Observability"} icon={<Activity size={18} />}>
              <DataTable
                emptyText={zh ? "暂无 Agent 运行" : "No agent runs"}
                columns={zh ? ["Agent", "操作", "状态", "预算/成本", "资产"] : ["Agent", "Operation", "Status", "Budget/Cost", "Asset"]}
                rows={(workbench?.agent_runs ?? []).map((row) => [
                  traceField(row, "agent_type") || row.title,
                  traceField(row, "operation"),
                  <span className={statusClass(traceField(row, "status"))} key={`agent-${row.path}`}>{traceField(row, "status") || "-"}</span>,
                  `${traceField(row, "token_used") || "0"} / ${traceField(row, "cost_estimate") || "0"}`,
                  row.path
                ])}
              />
              <DataTable
                emptyText={zh ? "暂无 Agent 事件" : "No agent events"}
                columns={zh ? ["事件", "状态", "说明"] : ["Event", "Status", "Message"]}
                rows={(workbench?.agent_events ?? []).slice(0, 12).map((row) => [
                  traceField(row, "event_type"),
                  <span className={statusClass(traceField(row, "status"))} key={`event-${row.path}`}>{traceField(row, "status") || "-"}</span>,
                  traceField(row, "message") || row.summary
                ])}
              />
            </EvidencePanel>

            <EvidencePanel title={zh ? "项目生产输入" : "Production Inputs"} icon={<GitPullRequest size={18} />}>
              <DataTable
                emptyText={zh ? "暂无绑定生产输入" : "No bound production inputs"}
                columns={zh ? ["类型", "标题", "路径", "ID"] : ["Type", "Title", "Path", "ID"]}
                rows={profileRows}
              />
            </EvidencePanel>
          </div>
        </section>
      </section>
    </main>
  );
}

function EvidencePanel({ title, icon, children }: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <div className="panel">
      <PanelHeader title={title} icon={icon} />
      {children}
    </div>
  );
}
