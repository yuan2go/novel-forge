"use client";

import { Activity, CheckCircle2, RotateCcw, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AgentRunRow, BatchItem, DeadLetter, HandoffRow, NodeRunRow, ProjectHealthReport, ProjectRow, TaskCenter, TaskControl } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { loadProductionControlData, runAgentBoundaryAudit, runWorkflowSchedulerTick } from "./api";

export function ProductionControlPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [taskCenter, setTaskCenter] = useState<TaskCenter | null>(null);
  const [taskControl, setTaskControl] = useState<TaskControl | null>(null);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [batchItems, setBatchItems] = useState<BatchItem[]>([]);
  const [handoffs, setHandoffs] = useState<HandoffRow[]>([]);
  const [nodeRuns, setNodeRuns] = useState<NodeRunRow[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRunRow[]>([]);
  const [projectHealth, setProjectHealth] = useState<ProjectHealthReport | null>(null);
  const [projectId, setProjectId] = useState("");
  const [boundaryAudit, setBoundaryAudit] = useState<Record<string, unknown> | null>(null);
  const [schedulerResult, setSchedulerResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const failedItems = batchItems.filter((item) => item.status === "failed");
  const waitingHandoffs = handoffs.filter((item) => item.status !== "completed" && item.status !== "superseded");
  const failedAgents = agentRuns.filter((run) => ["failed", "dead_letter", "needs_revision"].includes(run.status));
  const activeNodeRuns = nodeRuns.filter((run) => ["running", "waiting_human", "verifying"].includes(run.status));
  const workflowRuns = taskCenter?.workflow_runs || [];
  const activeWorkflowRuns = workflowRuns.filter((run) => ["running", "prepared", "paused"].includes(String(run.status || "")));

  async function refresh(nextProjectId = projectId) {
    const [projectRows, tasks, control, deadLetterRows, itemRows, handoffRows, nodeRows, agentRows, healthReport] = await loadProductionControlData(nextProjectId);
    setProjects(projectRows);
    setTaskCenter(tasks);
    setTaskControl(control);
    setDeadLetters(deadLetterRows);
    setBatchItems(itemRows);
    setHandoffs(handoffRows);
    setNodeRuns(nodeRows);
    setAgentRuns(agentRows);
    setProjectHealth(healthReport);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  async function auditAgentBoundaries() {
    setBusy(true);
    setError("");
    try {
      const result = await runAgentBoundaryAudit(true);
      setBoundaryAudit((result.asset?.content as Record<string, unknown>) || result);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function tickWorkflowScheduler() {
    setBusy(true);
    setError("");
    try {
      const result = await runWorkflowSchedulerTick(projectId);
      setSchedulerResult(result);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <FeatureShell title="生产总控中心" subtitle="任务、工作流节点、Agent、批处理 item、Handoff、dead-letter 和 worker health 的统一观测台。">
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="任务" value={String(taskCenter?.summary.task_count ?? 0)} />
        <Metric label="NodeRun" value={String(nodeRuns.length)} />
        <Metric label="AgentRun" value={String(agentRuns.length)} />
        <Metric label="失败总数" value={String((taskCenter?.summary.by_status.failed ?? 0) + failedAgents.length + deadLetters.length)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="控制面板" icon={<Activity size={18} />} />
          <div className="formGrid">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <button className="secondaryButton" onClick={() => refresh()}>刷新</button>
            <button className="primaryButton" disabled={busy} onClick={tickWorkflowScheduler}>Workflow Scheduler</button>
            <button className="primaryButton" disabled={busy} onClick={auditAgentBoundaries}>Agent 边界审计</button>
          </div>
          <div className="summaryBand">
            <Metric label="Worker" value={taskControl?.celery.healthy ? "healthy" : "offline"} />
            <Metric label="Workflow" value={String(activeWorkflowRuns.length)} />
            <Metric label="活跃节点" value={String(activeNodeRuns.length)} />
            <Metric label="等待 Handoff" value={String(waitingHandoffs.length)} />
            <Metric label="Dead Letter" value={String(deadLetters.length)} />
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="项目风险" icon={<CheckCircle2 size={18} />} />
          <div className="summaryBand">
            <Metric label="scope" value={String(projectHealth?.summary.scope_issue_count ?? 0)} />
            <Metric label="failed tasks" value={String(projectHealth?.summary.failed_task_count ?? 0)} />
            <Metric label="pending handoff" value={String(projectHealth?.summary.pending_handoff_count ?? 0)} />
            <Metric label="assets" value={String(projectHealth?.summary.asset_count ?? 0)} />
          </div>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Workflow Scheduler" icon={<Workflow size={18} />} />
          <div className="summaryBand">
            <Metric label="候选" value={String(schedulerResult?.candidate_count ?? "-")} />
            <Metric label="恢复" value={String(schedulerResult?.resumed_count ?? "-")} />
            <Metric label="跳过" value={String(schedulerResult?.skipped_count ?? "-")} />
            <Metric label="错误" value={String(schedulerResult?.error_count ?? "-")} />
          </div>
          <DataTable
            emptyText="点击 Workflow Scheduler 后显示自动恢复结果"
            columns={["节点", "状态", "AgentRun", "ResumeRun", "输出"]}
            rows={((schedulerResult?.resumed as Array<Record<string, unknown>> | undefined) || []).slice(0, 12).map((row) => [
              String(row.node_id || "-"),
              <span className={statusClass(String(row.status || ""))} key={`scheduler-status-${row.resume_run_id}`}>{String(row.status || "-")}</span>,
              <span className="pathText" key={`scheduler-agent-${row.agent_run_path}`}>{String(row.agent_run_path || "-")}</span>,
              <span className="pathText" key={`scheduler-resume-${row.resume_workflow_run_path}`}>{String(row.resume_workflow_run_path || "-")}</span>,
              String((row.output_assets as unknown[] | undefined)?.length ?? 0)
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Agent 全边界证明" icon={<CheckCircle2 size={18} />} />
          <div className="summaryBand">
            <Metric label="状态" value={String(boundaryAudit?.status ?? "-")} />
            <Metric label="扫描文件" value={String((boundaryAudit?.summary as Record<string, unknown> | undefined)?.scanned_files ?? "-")} />
            <Metric label="高风险" value={String((boundaryAudit?.summary as Record<string, unknown> | undefined)?.high_count ?? "-")} />
            <Metric label="中风险" value={String((boundaryAudit?.summary as Record<string, unknown> | undefined)?.medium_count ?? "-")} />
          </div>
          <DataTable
            emptyText="点击 Agent 边界审计后显示 findings"
            columns={["文件", "写边界", "模型边界", "级别", "建议"]}
            rows={((boundaryAudit?.findings as Array<Record<string, unknown>> | undefined) || []).slice(0, 20).map((finding) => [
              String(finding.path || "-"),
              String(finding.write_boundary_hits ?? 0),
              String(finding.model_boundary_hits ?? 0),
              <span className={statusClass(String(finding.severity || ""))} key={`${finding.path}-severity`}>{String(finding.severity || "-")}</span>,
              String(finding.recommendation || "-")
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Runtime Guard Probe" icon={<Activity size={18} />} />
          <pre className="jsonPreview">{JSON.stringify(boundaryAudit?.runtime_guard_probe || {}, null, 2)}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Agent 运行" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 AgentRun"
            columns={["Agent", "操作", "状态", "I/O", "模型", "运行资产"]}
            rows={agentRuns.slice(0, 30).map((run) => [
              run.agent_type,
              run.operation,
              <span className={statusClass(run.status)} key={`agent-status-${run.path}`}>{run.status}</span>,
              `${run.input_count} -> ${run.output_count}`,
              `${run.model_provider}/${run.model_name}`,
              <span className="pathText" key={run.path}>{run.path}</span>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="节点运行" icon={<Workflow size={18} />} />
          <DataTable
            emptyText="暂无 NodeRun"
            columns={["节点", "操作", "状态", "I/O", "错误", "运行资产"]}
            rows={nodeRuns.slice(0, 30).map((run) => [
              `${run.node_type}/${run.node_id}`,
              run.operation,
              <span className={statusClass(run.status)} key={`node-status-${run.path}`}>{run.status}</span>,
              `${run.input_count} -> ${run.output_count}`,
              run.error || "-",
              <span className="pathText" key={run.path}>{run.path}</span>
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="失败与恢复入口" icon={<RotateCcw size={18} />} />
          <DataTable
            emptyText="暂无失败项"
            columns={["类型", "状态", "错误", "路径"]}
            rows={[
              ...failedItems.slice(0, 12).map((item) => ["batch_item", item.status, item.error_message || "-", <span className="pathText" key={item.path}>{item.path}</span>]),
              ...deadLetters.slice(0, 12).map((letter) => ["dead_letter", letter.error_type || "failed", letter.error_message, <span className="pathText" key={letter.path}>{letter.path}</span>]),
              ...failedAgents.slice(0, 12).map((run) => ["agent_run", run.status, run.error || "-", <span className="pathText" key={run.path}>{run.path}</span>])
            ]}
          />
        </div>

        <div className="panel">
          <PanelHeader title="人工门禁" icon={<CheckCircle2 size={18} />} />
          <DataTable
            emptyText="暂无人工门禁"
            columns={["类型", "状态", "技能/操作", "路径"]}
            rows={[
              ...waitingHandoffs.slice(0, 16).map((handoff) => ["handoff", handoff.status, handoff.skill || handoff.operation, <span className="pathText" key={handoff.path}>{handoff.path}</span>]),
              ...agentRuns
                .filter((run) => run.status === "waiting_human" || String(run.human_gate?.status ?? "").includes("waiting"))
                .slice(0, 16)
                .map((run) => ["agent_run", run.status, run.operation, <span className="pathText" key={run.path}>{run.path}</span>])
            ]}
          />
        </div>
      </section>
    </FeatureShell>
  );
}
