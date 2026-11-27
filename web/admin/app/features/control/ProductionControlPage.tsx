"use client";

import { Activity, CheckCircle2, Play, RotateCcw, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AgentRunRow, BatchItem, DeadLetter, HandoffRow, NodeRunRow, ProjectHealthReport, ProjectRow, TaskCenter, TaskControl, WorkflowDefinitionRow, WorkflowRunRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { controlWorkflowRun, enqueueWorkflowSchedulerLoop, executeWorkflow, loadProductionControlData, loadWorkflowRuntimeConsole, recoverAgentDispatch, resumeWorkflow, runAgentBoundaryAudit, runAgentSchedulerTick, runWorkflowSchedulerTick } from "./api";

export function ProductionControlPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [taskCenter, setTaskCenter] = useState<TaskCenter | null>(null);
  const [taskControl, setTaskControl] = useState<TaskControl | null>(null);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [batchItems, setBatchItems] = useState<BatchItem[]>([]);
  const [handoffs, setHandoffs] = useState<HandoffRow[]>([]);
  const [nodeRuns, setNodeRuns] = useState<NodeRunRow[]>([]);
  const [workflowDefinitions, setWorkflowDefinitions] = useState<WorkflowDefinitionRow[]>([]);
  const [workflowRunRows, setWorkflowRunRows] = useState<WorkflowRunRow[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRunRow[]>([]);
  const [projectHealth, setProjectHealth] = useState<ProjectHealthReport | null>(null);
  const [projectId, setProjectId] = useState("");
  const [boundaryAudit, setBoundaryAudit] = useState<Record<string, unknown> | null>(null);
  const [schedulerResult, setSchedulerResult] = useState<Record<string, unknown> | null>(null);
  const [schedulerQueue, setSchedulerQueue] = useState<Record<string, unknown> | null>(null);
  const [workflowAction, setWorkflowAction] = useState<Record<string, unknown> | null>(null);
  const [workflowRuntime, setWorkflowRuntime] = useState<Record<string, unknown> | null>(null);
  const [agentSchedulerStatus, setAgentSchedulerStatus] = useState<Record<string, unknown> | null>(null);
  const [agentDispatchQueue, setAgentDispatchQueue] = useState<Array<Record<string, unknown>>>([]);
  const [agentSchedulerResult, setAgentSchedulerResult] = useState<Record<string, unknown> | null>(null);
  const [selectedWorkflow, setSelectedWorkflow] = useState("");
  const [selectedWorkflowRun, setSelectedWorkflowRun] = useState("");
  const [workflowInputText, setWorkflowInputText] = useState("");
  const [workflowOutputText, setWorkflowOutputText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const failedItems = batchItems.filter((item) => item.status === "failed");
  const waitingHandoffs = handoffs.filter((item) => item.status !== "completed" && item.status !== "superseded");
  const failedAgents = agentRuns.filter((run) => ["failed", "dead_letter", "needs_revision"].includes(run.status));
  const activeNodeRuns = nodeRuns.filter((run) => ["running", "waiting_human", "verifying"].includes(run.status));
  const workflowRuns = workflowRunRows.length ? workflowRunRows : (taskCenter?.workflow_runs || []);
  const activeWorkflowRuns = workflowRuns.filter((run) => ["running", "prepared", "paused"].includes(String(run.status || "")));

  async function refresh(nextProjectId = projectId) {
    const [projectRows, tasks, control, deadLetterRows, itemRows, handoffRows, nodeRows, workflowDefinitionRows, workflowRunsFromApi, agentRows, agentSchedulerState, dispatchRows, healthReport] = await loadProductionControlData(nextProjectId);
    setProjects(projectRows);
    setTaskCenter(tasks);
    setTaskControl(control);
    setDeadLetters(deadLetterRows);
    setBatchItems(itemRows);
    setHandoffs(handoffRows);
    setNodeRuns(nodeRows);
    setWorkflowDefinitions(workflowDefinitionRows);
    setWorkflowRunRows(workflowRunsFromApi);
    setAgentRuns(agentRows);
    setAgentSchedulerStatus(agentSchedulerState);
    setAgentDispatchQueue(dispatchRows);
    setProjectHealth(healthReport);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    setSelectedWorkflow((current) => current || workflowDefinitionRows[0]?.path || "");
    setSelectedWorkflowRun((current) => current || workflowRunsFromApi.find((run) => ["running", "failed"].includes(run.status))?.path || workflowRunsFromApi[0]?.path || "");
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

  async function queueWorkflowScheduler() {
    setBusy(true);
    setError("");
    try {
      const result = await enqueueWorkflowSchedulerLoop(projectId);
      setSchedulerQueue(result);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function tickAgentScheduler() {
    setBusy(true);
    setError("");
    try {
      const result = await runAgentSchedulerTick(projectId);
      setAgentSchedulerResult(result);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function recoverDispatch(queuePath: string) {
    setBusy(true);
    setError("");
    try {
      const result = await recoverAgentDispatch(queuePath);
      setAgentSchedulerResult(result);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function executeSelectedWorkflow() {
    if (!selectedWorkflow) {
      setError("请选择 workflow definition");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await executeWorkflow({
        workflow_path_or_id: selectedWorkflow,
        input_assets: splitLines(workflowInputText),
        max_nodes: 5,
        execute_agents: false
      });
      setWorkflowAction(result);
      await refresh();
      await loadSelectedWorkflowRuntime(selectedWorkflow, selectedWorkflowRun);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function resumeSelectedWorkflow() {
    if (!selectedWorkflowRun) {
      setError("请选择 workflow run");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const selectedRun = workflowRunRows.find((run) => run.path === selectedWorkflowRun);
      const result = await resumeWorkflow({
        workflow_run_path_or_id: selectedWorkflowRun,
        resume_node_id: selectedRun?.blocked_node_id || undefined,
        output_assets: splitLines(workflowOutputText)
      });
      setWorkflowAction(result);
      await refresh();
      await loadSelectedWorkflowRuntime(selectedWorkflow, selectedWorkflowRun);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function loadSelectedWorkflowRuntime(workflowPath = selectedWorkflow, workflowRunPath = selectedWorkflowRun) {
    if (!workflowPath && !workflowRunPath) {
      return;
    }
    const result = await loadWorkflowRuntimeConsole({
      workflow_path_or_id: workflowPath || undefined,
      workflow_run_path_or_id: workflowRunPath || undefined,
      input_assets: splitLines(workflowInputText)
    });
    setWorkflowRuntime(result);
  }

  async function controlSelectedWorkflow(action: "pause" | "retry" | "cancel" | "resume") {
    if (!selectedWorkflowRun) {
      setError("请选择 workflow run");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const selectedRun = workflowRunRows.find((run) => run.path === selectedWorkflowRun);
      const result = await controlWorkflowRun({
        workflow_run_path_or_id: selectedWorkflowRun,
        action,
        reason: `ui ${action}`,
        resume_node_id: selectedRun?.blocked_node_id || undefined,
        output_assets: splitLines(workflowOutputText)
      });
      setWorkflowAction(result);
      await refresh();
      await loadSelectedWorkflowRuntime(selectedWorkflow, selectedWorkflowRun);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  const dagNodes = (((workflowRuntime?.dag as Record<string, unknown> | undefined)?.nodes as Array<Record<string, unknown>> | undefined) || []);
  const readyQueue = (((workflowRuntime?.ready_queue as Record<string, unknown> | undefined)?.queue as Array<Record<string, unknown>> | undefined) || []);
  const processorContracts = ((workflowRuntime?.processor_contracts as Array<Record<string, unknown>> | undefined) || []);
  const agentSchedulerLease = ((agentSchedulerStatus?.lease as Record<string, unknown> | undefined) || {});
  const agentSchedulerByStatus = ((agentSchedulerStatus?.by_status as Record<string, unknown> | undefined) || {});

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
            <button className="secondaryButton" disabled={busy} onClick={queueWorkflowScheduler}>入队 Scheduler Loop</button>
            <button className="primaryButton" disabled={busy} onClick={tickAgentScheduler}>Agent Scheduler</button>
            <button className="primaryButton" disabled={busy} onClick={auditAgentBoundaries}>Agent 边界审计</button>
          </div>
          <div className="summaryBand">
            <Metric label="Worker" value={taskControl?.celery.healthy ? "healthy" : "offline"} />
            <Metric label="Workflow" value={String(activeWorkflowRuns.length)} />
            <Metric label="活跃节点" value={String(activeNodeRuns.length)} />
            <Metric label="等待 Handoff" value={String(waitingHandoffs.length)} />
            <Metric label="Dead Letter" value={String(deadLetters.length)} />
          </div>
          <div className="summaryBand">
            <Metric label="Scheduler" value={String(taskControl?.scheduler?.status ?? "missing")} />
            <Metric label="Owner" value={String(taskControl?.scheduler?.owner ?? "-")} />
            <Metric label="Last Tick" value={String(taskControl?.scheduler?.last_tick ?? "-")} />
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
          <PanelHeader title="Workflow Console" icon={<Play size={18} />} />
          <div className="formGrid">
            <select value={selectedWorkflow} onChange={(event) => setSelectedWorkflow(event.target.value)}>
              <option value="">选择 Definition</option>
              {workflowDefinitions.map((definition) => (
                <option value={definition.path} key={definition.path}>{definition.name || definition.workflow_id}</option>
              ))}
            </select>
            <select value={selectedWorkflowRun} onChange={(event) => setSelectedWorkflowRun(event.target.value)}>
              <option value="">选择 Run</option>
              {workflowRunRows.map((run) => (
                <option value={run.path} key={run.path}>{run.status} · {run.blocked_node_id || run.run_id}</option>
              ))}
            </select>
            <textarea value={workflowInputText} onChange={(event) => setWorkflowInputText(event.target.value)} placeholder="输入资产路径，每行一个" rows={3} />
            <textarea value={workflowOutputText} onChange={(event) => setWorkflowOutputText(event.target.value)} placeholder="resume 输出资产路径，每行一个" rows={3} />
            <button className="primaryButton" disabled={busy || !selectedWorkflow} onClick={executeSelectedWorkflow}>执行 Workflow</button>
            <button className="secondaryButton" disabled={busy || !selectedWorkflowRun} onClick={resumeSelectedWorkflow}>Resume Run</button>
            <button className="secondaryButton" disabled={busy || (!selectedWorkflow && !selectedWorkflowRun)} onClick={() => loadSelectedWorkflowRuntime().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>刷新 DAG</button>
            <button className="secondaryButton" disabled={busy || !selectedWorkflowRun} onClick={() => controlSelectedWorkflow("pause")}>Pause</button>
            <button className="secondaryButton" disabled={busy || !selectedWorkflowRun} onClick={() => controlSelectedWorkflow("retry")}>Retry</button>
            <button className="secondaryButton" disabled={busy || !selectedWorkflowRun} onClick={() => controlSelectedWorkflow("cancel")}>Cancel</button>
          </div>
          <div className="summaryBand">
            <Metric label="Definitions" value={String(workflowDefinitions.length)} />
            <Metric label="Runs" value={String(workflowRunRows.length)} />
            <Metric label="Blocked" value={String(workflowRunRows.filter((run) => run.blocked_node_id).length)} />
            <Metric label="Action" value={String(workflowAction?.status ?? "-")} />
            <Metric label="Ready" value={String(readyQueue.length)} />
          </div>
          <DataTable
            emptyText="选择 definition 后刷新 DAG"
            columns={["节点", "处理器", "输入", "输出", "Contract"]}
            rows={dagNodes.slice(0, 12).map((node) => {
              const contract = node.processor_contract as Record<string, unknown> | undefined;
              return [
                String(node.node_id || "-"),
                `${String(node.processor_kind || "-")} · ${String(node.processor_operation || node.operation || "-")}`,
                String((node.input_types as unknown[] | undefined)?.join(", ") || "-"),
                String((node.output_types as unknown[] | undefined)?.join(", ") || "-"),
                `${String(contract?.category || "-")} · ${String(contract?.checkpoint_strategy || "-")}`
              ];
            })}
          />
          <DataTable
            emptyText="暂无 ready node"
            columns={["Ready 节点", "状态", "处理器", "输入", "恢复"]}
            rows={readyQueue.slice(0, 12).map((row) => [
              String(row.node_id || "-"),
              String(row.blocked_status || row.workflow_run_status || "-"),
              `${String(row.processor_kind || "-")} · ${String(row.processor_operation || row.operation || "-")}`,
              String((row.input_assets as unknown[] | undefined)?.length ?? 0),
              String(row.resume_supported ? "yes" : "no")
            ])}
          />
          <DataTable
            emptyText="暂无 processor contract"
            columns={["Operation", "Kind", "类别", "Checkpoint", "Gate"]}
            rows={processorContracts.slice(0, 10).map((contract) => [
              String(contract.operation || "-"),
              String(contract.kind || "-"),
              String(contract.category || "-"),
              String(contract.checkpoint_strategy || "-"),
              `${contract.pre_gates ? "pre" : "-"} / ${contract.post_gates ? "post" : "-"}`
            ])}
          />
          <DataTable
            emptyText="暂无 workflow run"
            columns={["Run", "状态", "Blocked", "节点/Agent", "Trace", "路径"]}
            rows={workflowRunRows.slice(0, 12).map((run) => [
              run.run_id,
              <span className={statusClass(run.status)} key={`workflow-status-${run.path}`}>{run.status}</span>,
              run.blocked_node_id ? `${run.blocked_node_id} · ${run.blocked_status}` : "-",
              `${run.node_run_count}/${run.agent_run_count}`,
              run.trace_id || "-",
              <span className="pathText" key={run.path}>{run.path}</span>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Workflow Scheduler" icon={<Workflow size={18} />} />
          <div className="summaryBand">
            <Metric label="候选" value={String(schedulerResult?.candidate_count ?? "-")} />
            <Metric label="恢复" value={String(schedulerResult?.resumed_count ?? "-")} />
            <Metric label="跳过" value={String(schedulerResult?.skipped_count ?? "-")} />
            <Metric label="错误" value={String(schedulerResult?.error_count ?? "-")} />
            <Metric label="队列任务" value={String(schedulerQueue?.task_id ?? "-")} />
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
          <PanelHeader title="Agent Scheduler" icon={<Activity size={18} />} />
          <div className="summaryBand">
            <Metric label="Lease" value={String(agentSchedulerLease.status ?? "missing")} />
            <Metric label="Owner" value={String(agentSchedulerLease.owner ?? "-")} />
            <Metric label="Queued" value={String(agentSchedulerByStatus.queued ?? 0)} />
            <Metric label="Acked" value={String(agentSchedulerByStatus.acked ?? 0)} />
            <Metric label="Waiting" value={String(agentSchedulerByStatus.waiting_human ?? 0)} />
            <Metric label="Tick" value={String(agentSchedulerResult?.status ?? "-")} />
          </div>
          <DataTable
            emptyText="暂无 Agent dispatch queue"
            columns={["状态", "Agent", "Workflow", "尝试", "Lease", "错误/恢复"]}
            rows={agentDispatchQueue.slice(0, 18).map((row) => [
              <span className={statusClass(String(row.status || ""))} key={`dispatch-status-${row.path}`}>{String(row.status || "-")}</span>,
              <span className="pathText" key={`dispatch-agent-${row.path}`}>{String(row.agent_run_path || "-")}</span>,
              `${String(row.workflow_node_id || "-")} · ${String(row.workflow_run_id || "-")}`,
              `${String(row.attempt_count ?? 0)}/${String(row.max_attempts ?? 0)}`,
              String(row.lease_owner || "-"),
              ["dead_letter", "waiting_human", "retry_scheduled"].includes(String(row.status || "")) ? (
                <button className="secondaryButton" disabled={busy} onClick={() => recoverDispatch(String(row.path || ""))} key={`recover-${row.path}`}>
                  Recover
                </button>
              ) : String(row.last_error || "-")
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

function splitLines(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}
