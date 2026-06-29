"use client";

import { Activity, ListChecks, Play, RotateCcw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AgentEventRow, AgentRunRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { dispatchAgentRun, loadAgentDispatchData, recoverAgentDispatch, runAgentSchedulerTick } from "./api";
import { compactJson, pathCell, splitLines } from "./helpers";

const queueStatuses = ["", "queued", "claimed", "retry_scheduled", "waiting_human", "dead_letter", "acked"];

export function AgentDispatchCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRunRow[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEventRow[]>([]);
  const [schedulerStatus, setSchedulerStatus] = useState<Record<string, unknown>>({});
  const [queue, setQueue] = useState<Array<Record<string, unknown>>>([]);
  const [contracts, setContracts] = useState<Array<Record<string, unknown>>>([]);
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState("");
  const [agentRunPath, setAgentRunPath] = useState("");
  const [workflowRunId, setWorkflowRunId] = useState("");
  const [workflowNodeId, setWorkflowNodeId] = useState("");
  const [expectedOutputs, setExpectedOutputs] = useState("");
  const [schedulerResult, setSchedulerResult] = useState<Record<string, unknown> | null>(null);
  const [dispatchResult, setDispatchResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId, nextStatus = status) {
    const [projectRows, runRows, eventRows, schedulerState, queueRows, contractRows] = await loadAgentDispatchData(nextProjectId, nextStatus);
    setProjects(projectRows);
    setAgentRuns(runRows);
    setAgentEvents(eventRows);
    setSchedulerStatus(schedulerState);
    setQueue(queueRows);
    setContracts(contractRows.contracts || []);
    const resolvedProject = nextProjectId || projectRows[0]?.project_id || "";
    setProjectId(resolvedProject);
    setAgentRunPath((current) => current || runRows.find((run) => run.status === "prepared")?.path || runRows[0]?.path || "");
  }

  async function runAction(action: () => Promise<Record<string, unknown>>, message: string, setResult?: (result: Record<string, unknown>) => void) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action();
      setResult?.(result);
      setNotice(message);
      await refresh(projectId, status);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const lease = (schedulerStatus.lease as Record<string, unknown> | undefined) || {};
  const byStatus = (schedulerStatus.by_status as Record<string, unknown> | undefined) || {};
  const preparedRuns = agentRuns.filter((run) => ["prepared", "waiting_human", "failed", "dead_letter"].includes(run.status));
  const failedQueue = queue.filter((row) => ["dead_letter", "waiting_human", "retry_scheduled"].includes(String(row.status || "")));

  return (
    <FeatureShell title="Agent Dispatch Center" subtitle="让 prepared AgentRun 进入 queue，由 scheduler lease/claim/retry/recover 执行，并留下 checkpoint、gate、budget 和 trace 证据。" eyebrow="OS Runtime">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Runs" value={String(agentRuns.length)} />
        <Metric label="Queue" value={String(queue.length)} />
        <Metric label="Queued" value={String(byStatus.queued ?? 0)} />
        <Metric label="Acked" value={String(byStatus.acked ?? 0)} />
        <Metric label="Waiting" value={String(byStatus.waiting_human ?? 0)} />
        <Metric label="Lease" value={String(lease.status ?? "missing")} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Scheduler Control" icon={<Activity size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value, status)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={status} onChange={(event) => { setStatus(event.target.value); refresh(projectId, event.target.value).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught))); }}>
              {queueStatuses.map((item) => <option value={item} key={item}>{item || "全部状态"}</option>)}
            </select>
            <button className="primaryButton" disabled={busy} onClick={() => runAction(() => runAgentSchedulerTick(projectId, 1), "Agent scheduler tick 已完成", setSchedulerResult)}><Play size={16} />Scheduler Tick</button>
            <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => runAgentSchedulerTick(projectId, 5), "Agent scheduler loop 已完成", setSchedulerResult)}><RotateCcw size={16} />Loop x5</button>
          </div>
          <div className="summaryBand">
            <Metric label="Owner" value={String(lease.owner ?? "-")} />
            <Metric label="Last Tick" value={String(schedulerStatus.last_tick ?? "-")} />
            <Metric label="Contracts" value={String(contracts.length)} />
            <Metric label="Recoverable" value={String(failedQueue.length)} />
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="Manual Dispatch" icon={<ListChecks size={18} />} />
          <div className="formGrid">
            <select value={agentRunPath} onChange={(event) => setAgentRunPath(event.target.value)}>
              <option value="">选择 AgentRun</option>
              {preparedRuns.map((run) => <option value={run.path} key={run.path}>{run.status} · {run.agent_type} · {run.operation}</option>)}
            </select>
            <input value={workflowRunId} onChange={(event) => setWorkflowRunId(event.target.value)} placeholder="workflow_run_id，可选" />
            <input value={workflowNodeId} onChange={(event) => setWorkflowNodeId(event.target.value)} placeholder="workflow_node_id，可选" />
            <textarea rows={3} value={expectedOutputs} onChange={(event) => setExpectedOutputs(event.target.value)} placeholder="expected output assets，每行一个，可选" />
            <button
              className="primaryButton"
              disabled={busy || !agentRunPath}
              onClick={() => runAction(
                () => dispatchAgentRun({
                  agent_run_path: agentRunPath,
                  workflow_run_id: workflowRunId,
                  workflow_node_id: workflowNodeId,
                  expected_output_assets: splitLines(expectedOutputs)
                }),
                "AgentRun 已派发",
                setDispatchResult
              )}
            >
              <Play size={16} />Dispatch
            </button>
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Dispatch Queue" icon={<Activity size={18} />} />
        <DataTable
          emptyText="暂无 Agent dispatch queue"
          columns={["状态", "AgentRun", "Workflow", "尝试", "Lease", "Token/Cost", "恢复"]}
          rows={queue.slice(0, 80).map((row) => [
            <span className={statusClass(String(row.status || ""))} key={`${row.path}-status`}>{String(row.status || "-")}</span>,
            pathCell(String(row.agent_run_path || "-"), `${row.path}-agent`),
            `${String(row.workflow_node_id || "-")} · ${String(row.workflow_run_id || "-")}`,
            `${String(row.attempt_count ?? 0)}/${String(row.max_attempts ?? 0)}`,
            String(row.lease_owner || "-"),
            `${String(row.token_used ?? 0)} / ${String(row.cost_estimate ?? 0)}`,
            ["dead_letter", "waiting_human", "retry_scheduled"].includes(String(row.status || "")) ? (
              <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => recoverAgentDispatch(String(row.path || "")), "Dispatch 已恢复", setDispatchResult)} key={`${row.path}-recover`}>
                Recover
              </button>
            ) : String(row.last_error || "-")
          ])}
        />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Agent Runs" icon={<ShieldCheck size={18} />} />
          <DataTable
            emptyText="暂无 AgentRun"
            columns={["Agent", "操作", "状态", "模型", "Token", "Checkpoint", "路径"]}
            rows={agentRuns.slice(0, 60).map((run) => [
              run.agent_type,
              run.operation,
              <span className={statusClass(run.status)} key={`${run.path}-status`}>{run.status}</span>,
              `${run.model_provider || "-"} / ${run.model_name || "-"}`,
              `${run.token_used ?? 0}/${run.token_budget ?? 0}`,
              compactJson(run.checkpoint, 80),
              pathCell(run.path, run.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Operation Contracts" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 operation contract"
            columns={["Operation", "Agent", "I/O", "Checkpoint", "Rollback"]}
            rows={contracts.slice(0, 50).map((contract) => [
              String(contract.operation || "-"),
              String(contract.agent_key || contract.agent_type || "-"),
              `${String((contract.input_types as unknown[] | undefined)?.join(", ") || "-")} -> ${String((contract.output_types as unknown[] | undefined)?.join(", ") || "-")}`,
              String(contract.checkpoint_strategy || "-"),
              String(contract.rollback_strategy || "-")
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Agent Events" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 Agent Event"
            columns={["事件", "状态", "消息", "时间", "Run"]}
            rows={agentEvents.slice(0, 80).map((event) => [
              event.event_type,
              <span className={statusClass(event.status)} key={`${event.path}-status`}>{event.status}</span>,
              event.message || "-",
              event.created_at || "-",
              pathCell(event.agent_run_path, event.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Scheduler Result" icon={<Activity size={18} />} />
          <pre className="jsonPreview">{JSON.stringify(schedulerResult || dispatchResult || schedulerStatus, null, 2)}</pre>
        </div>
      </section>
    </FeatureShell>
  );
}
