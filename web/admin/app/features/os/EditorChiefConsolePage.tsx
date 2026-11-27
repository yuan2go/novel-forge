"use client";

import { AlertTriangle, BookOpenCheck, CheckCircle2, GitPullRequest, ListChecks, Network, PauseCircle, Send, ShieldCheck, TrendingUp, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { loadEditorChiefSnapshot, type EditorChiefSnapshot } from "./api";
import { compactJson, pathCell, selectedWorkspace } from "./helpers";

const governanceLinks = [
  { key: "canon", label: "Canon", fallback: "/canon-console" },
  { key: "character", label: "Character", fallback: "/character-console" },
  { key: "arc", label: "Arc", fallback: "/arc-console" },
  { key: "foreshadowing", label: "Foreshadowing", fallback: "/foreshadowing-console" },
  { key: "review_issues", label: "Review Issues", fallback: "/review-issues" },
  { key: "longform_recap", label: "Longform Recap", fallback: "/longform-recap" },
  { key: "loop_runs", label: "Loop Runs", fallback: "/loop-runs" },
  { key: "agent_center", label: "Agent Center", fallback: "/agent-center" },
  { key: "publish_gate", label: "Publish Gate", fallback: "/publish-gate" }
];

export function EditorChiefConsolePage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [snapshot, setSnapshot] = useState<EditorChiefSnapshot | null>(null);
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId) {
    setError("");
    const workspacePath = selectedWorkspace(projects, nextProjectId);
    const [projectRows, data] = await loadEditorChiefSnapshot(nextProjectId || undefined, workspacePath || undefined);
    setProjects(projectRows);
    setSnapshot(data);
    setProjectId(nextProjectId);
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const decision = snapshot?.executive_decision || {};
  const health = snapshot?.overall_health || {};
  const arc = snapshot?.arc_progress || {};
  const character = snapshot?.character_drift || {};
  const foreshadowing = snapshot?.foreshadowing || {};
  const fatigue = snapshot?.recent_fatigue || {};
  const next10 = snapshot?.next_10_chapter_strategy || {};
  const repairQueue = snapshot?.blocking_repair_queue || {};
  const publishFit = snapshot?.publish_and_platform_fit || {};
  const governance = snapshot?.governance_loop || {};
  const governanceRegistry = asRecord(governance.agent_registry);
  const governanceAudit = asRecord(governance.audit);
  const governanceEvaluation = asRecord(governance.evaluation);
  const governanceAnalytics = asRecord(governance.analytics);
  const governanceRetrieval = asRecord(governance.retrieval);
  const controlLinks = snapshot?.control_links || {};
  const issueRows = asRows(repairQueue.issues);
  const revisionRows = asRows(repairQueue.revision_tasks);
  const pillars = asStrings(next10.editorial_pillars);
  const doNot = asStrings(next10.do_not);
  const platformBeats = asStrings(next10.platform_beats);
  const clues = asRows(foreshadowing.clues);
  const characters = asRows(character.characters);
  const recentAssets = asRows(snapshot?.evidence?.recent_assets);
  const range = next10.chapter_range as Record<string, unknown> | undefined;

  return (
    <FeatureShell title="Editor-in-Chief Console" subtitle="把 Canon、Character、Arc、Foreshadowing、ReviewIssue、Recap、Loop、Agent 和 Publish Gate 聚合成一本书能否继续生产的总编判断。" eyebrow="OS Runtime">
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="panel">
        <PanelHeader title="Editorial Scope" icon={<BookOpenCheck size={18} />} />
        <div className="formGrid wide">
          <select value={projectId} onChange={(event) => refresh(event.target.value).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>
            <option value="">全部项目</option>
            {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
          </select>
          <button className="secondaryButton" onClick={() => refresh(projectId).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>
            <CheckCircle2 size={16} />Refresh
          </button>
          {governanceLinks.map((link) => <a className="linkButton" href={controlLinks[link.key] || link.fallback} key={link.key}>{link.label}</a>)}
        </div>
      </section>

      <section className="summaryBand manuscriptSummary">
        <Metric label="Decision" value={decisionLabel(String(decision.decision || "-"))} />
        <Metric label="Quality" value={String(health.quality_score ?? 0)} />
        <Metric label="Risk" value={String(health.risk_level ?? "-")} />
        <Metric label="Continue" value={decision.can_continue ? "yes" : "no"} />
        <Metric label="Pause" value={decision.must_pause ? "yes" : "no"} />
        <Metric label="Publish" value={decision.can_publish ? "yes" : "no"} />
        <Metric label="Blocking" value={String(health.blocking_issue_count ?? 0)} />
        <Metric label="Evidence Gaps" value={String(health.evidence_gap_count ?? 0)} />
      </section>

      <section className="panel">
        <PanelHeader title="总编判断" icon={decision.must_pause ? <PauseCircle size={18} /> : <CheckCircle2 size={18} />} />
        <div className="decisionCard">
          <span className={statusClass(String(health.risk_level || decision.decision || ""))}>{decisionLabel(String(decision.decision || ""))}</span>
          <strong>{String(decision.summary || health.headline || "等待治理证据")}</strong>
          <p className="mutedText">{String(health.headline || "")}</p>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="这本书现在健康吗？" icon={<ShieldCheck size={18} />} />
          <DataTable
            emptyText="暂无健康指标"
            columns={["Metric", "Value"]}
            rows={[
              ["总体质量分", String(health.quality_score ?? 0)],
              ["风险等级", <span className={statusClass(String(health.risk_level || ""))} key="risk">{String(health.risk_level || "-")}</span>],
              ["Longform Acceptance", String(health.acceptance_status || "-")],
              ["Canon Issue", String(health.canon_issue_count ?? 0)],
              ["Active Issue", String(health.active_issue_count ?? 0)]
            ]}
          />
        </div>

        <div className="panel">
          <PanelHeader title="主线是否偏了？" icon={<GitPullRequest size={18} />} />
          <div className="summaryBand">
            <Metric label="Status" value={String(arc.status || "-")} />
            <Metric label="Score" value={String(arc.progress_score ?? 0)} />
            <Metric label="Chapter" value={String(arc.current_chapter ?? 0)} />
            <Metric label="Arc Plans" value={String(arc.arc_plan_count ?? 0)} />
          </div>
          <DataTable
            emptyText="暂无主线偏移报警"
            columns={["Severity", "Source", "Message"]}
            rows={asRows(arc.drift_alerts).slice(0, 8).map((item) => [
              <span className={statusClass(String(item.severity || ""))} key={`${String(item.message)}-severity`}>{String(item.severity || "-")}</span>,
              String(item.source || "-"),
              String(item.message || "-")
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="人物是否崩了？" icon={<Users size={18} />} />
          <div className="summaryBand">
            <Metric label="Status" value={String(character.status || "-")} />
            <Metric label="Issues" value={String(character.drift_issue_count ?? 0)} />
            <Metric label="Liability" value={String(character.liability_count ?? 0)} />
            <Metric label="Debt" value={String(character.remaining_debt_total ?? 0)} />
          </div>
          <DataTable
            emptyText="暂无人物状态"
            columns={["Character", "Status", "Burdens", "Debt"]}
            rows={characters.slice(0, 8).map((item) => [
              String(item.canonical_name || item.character_id || "-"),
              String(item.status || "-"),
              Array.isArray(item.active_burdens) ? item.active_burdens.join(", ") || "-" : "-",
              String(item.remaining_debt ?? "-")
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="伏笔是否乱了？" icon={<Network size={18} />} />
          <div className="summaryBand">
            <Metric label="Status" value={String(foreshadowing.status || "-")} />
            <Metric label="Open" value={String(foreshadowing.open_clue_count ?? 0)} />
            <Metric label="Dropped" value={String(foreshadowing.dropped_clue_count ?? 0)} />
            <Metric label="Expired" value={String(foreshadowing.expired_clue_count ?? 0)} />
          </div>
          <DataTable
            emptyText="暂无伏笔线索"
            columns={["Clue", "Status", "Payoff", "Target Truth"]}
            rows={clues.slice(0, 10).map((item) => [
              String(item.name || "-"),
              <span className={statusClass(String(item.status || ""))} key={`${String(item.name)}-status`}>{String(item.status || "-")}</span>,
              String(item.planned_payoff_chapter || "-"),
              String(item.target_truth || "-")
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="最近10章是否疲劳？" icon={<TrendingUp size={18} />} />
          <div className="summaryBand">
            <Metric label="Window" value={String(fatigue.window || "-")} />
            <Metric label="Pattern High" value={String(fatigue.pattern_high_count ?? 0)} />
            <Metric label="Motif High" value={String(fatigue.motif_high_count ?? 0)} />
            <Metric label="Fatigue" value={String(fatigue.average_fatigue_score ?? 0)} />
          </div>
          <DataTable
            emptyText="暂无疲劳证据"
            columns={["Type", "Chapter", "Status", "Path"]}
            rows={asRows(fatigue.alerts).slice(0, 10).map((item) => [
              String(item.type || "-"),
              String(item.chapter || "-"),
              <span className={statusClass(String(item.status || item.decision || ""))} key={`${String(item.path)}-status`}>{String(item.status || item.decision || "-")}</span>,
              pathCell(String(item.path || ""), String(item.path || "fatigue"))
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="下10章应该怎么写？" icon={<ListChecks size={18} />} />
          <div className="summaryBand">
            <Metric label="Range" value={`${String(range?.from ?? 1)}-${String(range?.to ?? 10)}`} />
            <Metric label="Platform" value={String(next10.target_platform || "-")} />
            <Metric label="Pillars" value={String(pillars.length)} />
          </div>
          <DataTable
            emptyText="暂无总编策略"
            columns={["Type", "Instruction"]}
            rows={[
              ...pillars.map((item) => ["Strategy", item]),
              ...platformBeats.slice(0, 6).map((item) => ["Platform Beat", item]),
              ...doNot.map((item) => ["Do Not", item])
            ]}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="哪些问题必须先修？" icon={<AlertTriangle size={18} />} />
          <DataTable
            emptyText="暂无 blocking issue"
            columns={["Type", "Severity", "Message", "Path"]}
            rows={issueRows.slice(0, 12).map((issue) => [
              String(issue.issue_type || "-"),
              <span className={statusClass(String(issue.severity || ""))} key={`${String(issue.issue_id)}-severity`}>{String(issue.severity || "-")}</span>,
              String(issue.message || "-"),
              pathCell(String(issue.path || ""), String(issue.issue_id || issue.path || "issue"))
            ])}
          />
          <DataTable
            emptyText="暂无 RevisionTask"
            columns={["Task", "Status", "Path"]}
            rows={revisionRows.slice(0, 8).map((task) => [
              String(task.title || task.id || "-"),
              <span className={statusClass(String(task.status || ""))} key={`${String(task.path)}-task-status`}>{String(task.status || "-")}</span>,
              pathCell(String(task.path || ""), String(task.path || "task"))
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="是否可以发布？" icon={<Send size={18} />} />
          <div className="summaryBand">
            <Metric label="Status" value={String(publishFit.status || "-")} />
            <Metric label="Can Publish" value={publishFit.can_publish ? "yes" : "no"} />
            <Metric label="Gate" value={String(publishFit.latest_gate_decision || "-")} />
            <Metric label="Platform" value={String(publishFit.target_platform || "-")} />
          </div>
          <pre className="jsonPreview">{compactJson(publishFit, 2200)}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Novel OS 治理闭环" icon={<ShieldCheck size={18} />} />
          <div className="summaryBand">
            <Metric label="Registry" value={String(governanceRegistry.entry_count ?? 0)} />
            <Metric label="Audit Events" value={String(governanceAudit.event_count ?? 0)} />
            <Metric label="Eval Assets" value={String(governanceEvaluation.asset_count ?? 0)} />
            <Metric label="Retrieval" value={String(governanceRetrieval.status || "-")} />
          </div>
          <DataTable
            emptyText="暂无治理证据"
            columns={["System", "Status", "Evidence"]}
            rows={[
              ["Agent Registry", String(governanceRegistry.scheduler_policy || "active only"), `${String(governanceRegistry.entry_count ?? 0)} entries`],
              ["Audit Trail", String(governanceAudit.latest_event_at || "-"), `${String(governanceAudit.event_count ?? 0)} events`],
              ["Evaluation Center", `${String(governanceEvaluation.blocked_count ?? 0)} blocked`, `${String(governanceEvaluation.asset_count ?? 0)} assets`],
              ["Analytics", String(asRecord(governanceAnalytics.capabilities).status || "-"), `${String(asRecord(governanceAnalytics.capabilities).local_event_count ?? 0)} events`],
              ["Retrieval", String(governanceRetrieval.status || "-"), `${String(governanceRetrieval.local_projection_chunk_count ?? 0)} chunks`]
            ]}
          />
        </div>

        <div className="panel">
          <PanelHeader title="治理入口" icon={<ListChecks size={18} />} />
          <DataTable
            columns={["Console", "Path"]}
            rows={[
              ["Agent Registry", pathCell("/agent-registry", "agent-registry")],
              ["Audit Log", pathCell("/audit-log", "audit-log")],
              ["Evaluation", pathCell("/evaluation", "evaluation")],
              ["Retrieval", pathCell("/retrieval", "retrieval")],
              ["Analytics", pathCell("/analytics", "analytics")]
            ]}
          />
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Evidence Trace" icon={<BookOpenCheck size={18} />} />
        <DataTable
          emptyText="暂无证据资产"
          columns={["Type", "Title", "Chapter", "Status", "Path"]}
          rows={recentAssets.slice(0, 30).map((asset) => [
            String(asset.type || "-"),
            String(asset.title || "-"),
            String(asset.chapter || "-"),
            <span className={statusClass(String(asset.status || asset.decision || ""))} key={`${String(asset.path)}-evidence-status`}>{String(asset.status || asset.decision || "-")}</span>,
            pathCell(String(asset.path || ""), String(asset.path || "asset"))
          ])}
        />
      </section>
    </FeatureShell>
  );
}

function asRows(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object" && !Array.isArray(item)) : [];
}

function asStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.map((item) => String(item)).filter(Boolean) : [];
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function decisionLabel(value: string) {
  if (value === "pause_for_revision") return "暂停修复";
  if (value === "ready_to_publish") return "可发布";
  if (value === "continue_with_caution") return "谨慎继续";
  if (value === "continue_production") return "继续生产";
  return value || "-";
}
