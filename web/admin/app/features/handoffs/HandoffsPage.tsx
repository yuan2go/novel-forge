"use client";

import { CheckCircle2, Copy, Database, FileSearch, RotateCcw, Workflow } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetDetail, GitHubSource, HandoffAcceptance, HandoffOutputValidation, HandoffRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  bindHandoffOutput,
  createDeconstructHandoff,
  createGitHubKnowledgeHandoff,
  createKnowledgeHandoff,
  failHandoff,
  loadHandoffAcceptance,
  loadHandoffData,
  loadHandoffDetail,
  retryHandoff,
  updateAcceptance,
  validateHandoffOutput
} from "./api";

export function HandoffsPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [handoffs, setHandoffs] = useState<HandoffRow[]>([]);
  const [githubSources, setGithubSources] = useState<GitHubSource[]>([]);
  const [projectId, setProjectId] = useState("");
  const [detail, setDetail] = useState<AssetDetail | null>(null);
  const [acceptance, setAcceptance] = useState<HandoffAcceptance | null>(null);
  const [validation, setValidation] = useState<HandoffOutputValidation | null>(null);
  const [handoffInput, setHandoffInput] = useState("");
  const [genre, setGenre] = useState("");
  const [targetReader, setTargetReader] = useState("");
  const [purpose, setPurpose] = useState("");
  const [discipline, setDiscipline] = useState("");
  const [credibility, setCredibility] = useState("registered source metadata; license review required before raw access");
  const [scope, setScope] = useState("");
  const [context, setContext] = useState("");
  const [githubRefs, setGithubRefs] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const content = useMemo(() => {
    const raw = detail?.asset.content;
    return raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  }, [detail]);
  const promptText = useMemo(() => buildPrompt(detail, content), [detail, content]);

  async function refresh(nextProjectId = projectId) {
    const [projectRows, handoffRows, sources] = await loadHandoffData(nextProjectId);
    setProjects(projectRows);
    setHandoffs(handoffRows);
    setGithubSources(sources);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setHandoffInput((current) => current || handoffRows[0]?.source_path || "");
  }

  async function selectHandoff(path: string) {
    setError("");
    setValidation(null);
    try {
      const nextDetail = await loadHandoffDetail(path);
      setDetail(nextDetail);
      setOutputPath(String((nextDetail.asset.content as Record<string, unknown> | undefined)?.output_path ?? ""));
      setAcceptance(await loadHandoffAcceptance(path));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  async function runAction(action: () => Promise<unknown>, message: string, refreshAfter = true) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action();
      setNotice(message);
      if (refreshAfter) await refresh();
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

  return (
    <FeatureShell title="Claude Code / Codex Handoff 中心" subtitle="生成、执行、复制提示、逐项验收、绑定输出、失败重做和人工 gate 的独立工作台。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Handoff" value={String(handoffs.length)} />
        <Metric label="待处理" value={String(handoffs.filter((row) => !["completed", "superseded"].includes(row.status)).length)} />
        <Metric label="失败" value={String(handoffs.filter((row) => row.status === "failed").length)} />
        <Metric label="GitHub 源" value={String(githubSources.length)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="创建执行包" icon={<Workflow size={18} />} />
          <div className="formGrid">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <input value={handoffInput} onChange={(event) => setHandoffInput(event.target.value)} placeholder="输入资产路径" />
          </div>
          <div className="handoffForms">
            <div className="handoffForm">
              <h3>网文拆解</h3>
              <input value={genre} onChange={(event) => setGenre(event.target.value)} placeholder="题材" />
              <input value={targetReader} onChange={(event) => setTargetReader(event.target.value)} placeholder="目标读者" />
              <input value={purpose} onChange={(event) => setPurpose(event.target.value)} placeholder="拆解目的" />
              <button className="primaryButton" disabled={busy || !handoffInput.trim()} onClick={() => runAction(async () => {
                const created = await createDeconstructHandoff(handoffInput, genre, targetReader, purpose, selectedProject?.path) as AssetDetail;
                setDetail(created);
                return created;
              }, "拆解 Handoff 已创建")}>创建拆解</button>
            </div>
            <div className="handoffForm">
              <h3>知识解析</h3>
              <input value={discipline} onChange={(event) => setDiscipline(event.target.value)} placeholder="学科" />
              <input value={credibility} onChange={(event) => setCredibility(event.target.value)} placeholder="可信度/授权说明" />
              <input value={scope} onChange={(event) => setScope(event.target.value)} placeholder="范围" />
              <input value={context} onChange={(event) => setContext(event.target.value)} placeholder="项目上下文" />
              <button className="secondaryButton" disabled={busy || !handoffInput.trim()} onClick={() => runAction(async () => {
                const created = await createKnowledgeHandoff(handoffInput, discipline, credibility, scope, context, selectedProject?.path) as AssetDetail;
                setDetail(created);
                return created;
              }, "知识 Handoff 已创建")}>创建知识包</button>
            </div>
            <div className="handoffForm">
              <h3>GitHub 知识源</h3>
              <input value={githubRefs} onChange={(event) => setGithubRefs(event.target.value)} placeholder="repo refs, comma separated" />
              <button className="secondaryButton" disabled={busy || !githubRefs.trim()} onClick={() => runAction(async () => {
                const result = await createGitHubKnowledgeHandoff(githubRefs.split(",").map((item) => item.trim()).filter(Boolean), discipline, credibility, scope, context, selectedProject?.path) as { handoff?: AssetDetail };
                if (result.handoff) setDetail(result.handoff);
                return result;
              }, "GitHub 知识 Handoff 已创建")}>
                <Database size={18} />
                创建 GitHub 包
              </button>
            </div>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="GitHub 资料源" icon={<Database size={18} />} />
          <DataTable
            emptyText="暂无 GitHub source"
            columns={["Repo", "Category", "Risk", "License", "操作"]}
            rows={githubSources.slice(0, 12).map((source) => [
              <a href={source.url} target="_blank" rel="noreferrer" key={`repo-${source.id}`}>{source.repo}</a>,
              source.category,
              <span className={source.commercial_risk.includes("high") ? "badge warn" : "badge muted"} key={`risk-${source.id}`}>{source.commercial_risk}</span>,
              source.license_check,
              <button className="secondaryButton tableButton" disabled={busy} onClick={() => setGithubRefs(Array.from(new Set([...githubRefs.split(",").map((item) => item.trim()).filter(Boolean), source.repo])).join(", "))} key={`add-${source.id}`}>加入</button>
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Handoff 队列" icon={<ListIcon />} />
          <DataTable
            emptyText="暂无 Handoff"
            columns={["操作", "状态", "技能", "期望输出", "输入", "路径"]}
            rows={handoffs.map((handoff) => [
              handoff.operation,
              <span className={statusClass(handoff.status)} key={`status-${handoff.path}`}>{handoff.status}</span>,
              handoff.skill,
              handoff.expected_output_type,
              handoff.source_path,
              <button className="linkButton" key={handoff.path} onClick={() => selectHandoff(handoff.path)}>{handoff.path}</button>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="执行包详情" icon={<FileSearch size={18} />} />
          {detail ? (
            <div className="detailStack">
              <div className="detailTitle">{detail.summary.title || detail.summary.id}</div>
              <div className="miniMetrics">
                <span className="statPill">{String(content.operation ?? "")}</span>
                <span className={statusClass(String(content.status ?? ""))}>status: {String(content.status ?? "")}</span>
                <span className="statPill">{String(content.runtime ?? "")}/{String(content.runtime_model ?? "")}</span>
              </div>
              <div className="handoffDetailGrid">
                <div><strong>源文件</strong><span className="pathText">{String((content.source_asset as Record<string, unknown> | undefined)?.path ?? detail.asset.source ?? "")}</span></div>
                <div><strong>技能</strong><span>{String(content.skill ?? "")}</span></div>
                <div><strong>期望输出</strong><span>{String(content.expected_output_type ?? "")} {"->"} {String(content.expected_output_dir ?? "")}</span></div>
                <div><strong>校验命令</strong><span className="pathText">{String((content.manual_execution as Record<string, unknown> | undefined)?.validation_command ?? "make validate")}</span></div>
              </div>
              <textarea value={promptText} readOnly rows={12} />
              <div className="studioActions">
                <button className="secondaryButton" onClick={() => navigator.clipboard.writeText(promptText)}>
                  <Copy size={18} />
                  复制执行提示
                </button>
                <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => retryHandoff(detail.path, selectedProject?.path), "Handoff 已重试")}>
                  <RotateCcw size={18} />
                  重试
                </button>
                <button className="secondaryButton dangerButton" disabled={busy} onClick={() => runAction(() => failHandoff(detail.path, "operator marked failed from feature workbench"), "Handoff 已标记失败")}>失败</button>
              </div>
              <HandoffAcceptancePanel acceptance={acceptance} busy={busy} onUpdate={(index, status) => runAction(async () => setAcceptance(await updateAcceptance(detail.path, index, status)), "验收项已更新", false)} />
              <div className="formGrid wide">
                <input value={outputPath} onChange={(event) => setOutputPath(event.target.value)} placeholder="输出资产路径" />
                <button className="secondaryButton" disabled={busy || !outputPath.trim()} onClick={() => runAction(async () => setValidation(await validateHandoffOutput(detail.path, outputPath, selectedProject?.path)), "输出校验完成", false)}>校验输出</button>
                <button className="primaryButton" disabled={busy || !outputPath.trim()} onClick={() => runAction(() => bindHandoffOutput(detail.path, outputPath, selectedProject?.path), "输出已绑定并推进")}>绑定输出</button>
              </div>
              {validation ? <div className={validation.ok ? "noticeLine" : "errorLine"}>{validation.ok ? "输出匹配" : validation.errors.join("; ")}</div> : null}
            </div>
          ) : (
            <div className="emptyCell">选择 Handoff 查看详情</div>
          )}
        </div>
      </section>
    </FeatureShell>
  );
}

function HandoffAcceptancePanel({ acceptance, busy, onUpdate }: { acceptance: HandoffAcceptance | null; busy: boolean; onUpdate: (index: number, status: string) => void }) {
  if (!acceptance) return null;
  return (
    <div>
      <h3>验收项</h3>
      <DataTable
        emptyText="暂无验收项"
        columns={["序号", "验收项", "状态", "备注", "操作"]}
        rows={acceptance.checks.map((check) => [
          String(check.index),
          check.check,
          <span className={statusClass(check.status)} key={`check-${check.index}`}>{check.status}</span>,
          check.note || "-",
          <div className="studioActions" key={`actions-${check.index}`}>
            <button className="secondaryButton tableButton" disabled={busy} onClick={() => onUpdate(check.index, "accepted")}>通过</button>
            <button className="secondaryButton tableButton" disabled={busy} onClick={() => onUpdate(check.index, "failed")}>失败</button>
          </div>
        ])}
      />
    </div>
  );
}

function ListIcon() {
  return <CheckCircle2 size={18} />;
}

function buildPrompt(detail: AssetDetail | null, content: Record<string, unknown>) {
  if (!detail) return "";
  const inputFiles = Array.isArray(content.input_files) ? content.input_files as Array<Record<string, unknown>> : [];
  const acceptance = Array.isArray(content.acceptance_checks) ? content.acceptance_checks : [];
  const instructions = content.instructions || content.expected_output || content.manual_execution;
  return [
    `Handoff asset: ${detail.path}`,
    `Operation: ${String(content.operation ?? "")}`,
    `Skill: ${String(content.skill ?? "")}`,
    `Expected output type: ${String(content.expected_output_type ?? "")}`,
    `Expected output dir: ${String(content.expected_output_dir ?? "")}`,
    "",
    "Input files:",
    ...inputFiles.map((item) => `- ${String(item.path ?? "")} (${String(item.role ?? "input")})`),
    "",
    "Instructions:",
    typeof instructions === "string" ? instructions : JSON.stringify(instructions ?? {}, null, 2),
    "",
    "Acceptance checks:",
    ...acceptance.map((item) => `- ${String(item)}`),
    "",
    `Validation command: ${String((content.manual_execution as Record<string, unknown> | undefined)?.validation_command ?? "make validate")}`
  ].join("\n");
}
