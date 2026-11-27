"use client";

import { Activity, RotateCcw, Server, TimerReset } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AgentEventRow, AgentRunRow, DeadLetter, ProjectRow, TaskCenter, TaskControl, TaskRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { loadTaskData, recoverAuthorityOperation, requeueAuthorityOutbox, type RuntimeCostDashboard, type RuntimeTraceTimeline } from "./api";

export function TasksCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [center, setCenter] = useState<TaskCenter | null>(null);
  const [control, setControl] = useState<TaskControl | null>(null);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRunRow[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEventRow[]>([]);
  const [traceTimeline, setTraceTimeline] = useState<RuntimeTraceTimeline | null>(null);
  const [costDashboard, setCostDashboard] = useState<RuntimeCostDashboard | null>(null);
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState("");
  const [taskType, setTaskType] = useState("");
  const [step, setStep] = useState("");
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const costSummary = costDashboard?.asset?.content?.summary || {};
  const costSnapshots = costDashboard?.asset?.content?.snapshots || {};
  const costRecommendations = costDashboard?.asset?.content?.recommendations || [];
  const authorityWorkers = control?.scheduler?.workers ?? [];
  const busyAuthorityWorkers = authorityWorkers.filter((worker) => worker.status === "BUSY").length;

  async function refresh(nextOffset = offset) {
    const [projectRows, taskCenter, taskControl, deadLetterRows, runRows, eventRows, runtimeTrace, runtimeCost] = await loadTaskData({ projectId, status, taskType, step, offset: nextOffset });
    setProjects(projectRows);
    setCenter(taskCenter);
    setControl(taskControl);
    setDeadLetters(deadLetterRows);
    setAgentRuns(runRows);
    setAgentEvents(eventRows);
    setTraceTimeline(runtimeTrace);
    setCostDashboard(runtimeCost);
    setOffset(nextOffset);
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

  function taskRow(row: TaskRow) {
    const identity = row.operation_id || row.id || row.run_id;
    const recoverable = ["FAILED_RETRYABLE", "WAITING_EXTERNAL_RESULT", "RECONCILIATION_REQUIRED"].includes(row.status);
    return [
      row.task_type,
      row.step,
      <span className={statusClass(row.status)} key={`${identity}-status`}>{row.status}</span>,
      `${Math.round((row.progress ?? 0) * 100)}%`,
      row.updated_at || row.recorded_at || "-",
      <span className="pathText" key={`${identity}-authority`}>{identity}</span>,
      recoverable ? (
        <button
          className="secondaryButton"
          disabled={busy}
          key={`${identity}-recover`}
          onClick={() => runAction(
            () => recoverAuthorityOperation(row),
            `Authority recovery admitted: ${identity}`
          )}
        >恢复</button>
      ) : <span className="pathText" key={`${identity}-no-recovery`}>—</span>
    ];
  }

  useEffect(() => {
    refresh(0).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  return (
    <FeatureShell title="任务中心" subtitle="最新状态、完整 timeline、dead-letter、worker health 和队列压力统一进入任务恢复操作台。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="任务总数" value={String(center?.summary.task_count ?? 0)} />
        <Metric label="失败" value={String((center?.summary.by_status?.FAILED_FINAL ?? 0) + (center?.summary.by_status?.FAILED_RETRYABLE ?? 0))} />
        <Metric label="Dead Letter" value={String(control?.dead_letters?.count ?? deadLetters.length)} />
        <Metric label="Authority Worker" value={control?.scheduler?.readiness ?? "DEGRADED"} />
        <Metric label="Agent Runs" value={String(agentRuns.length)} />
        <Metric label="Trace Spans" value={String(traceTimeline?.summary?.span_count ?? 0)} />
        <Metric label="成本" value={`$${Number(costSummary.total_cost ?? 0).toFixed(4)}`} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="筛选" icon={<TimerReset size={18} />} />
          <div className="formGrid">
            <select value={projectId} onChange={(event) => setProjectId(event.target.value)}>
              <option value="">全部项目</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <input placeholder="状态 failed/running" value={status} onChange={(event) => setStatus(event.target.value)} />
            <input placeholder="任务类型" value={taskType} onChange={(event) => setTaskType(event.target.value)} />
            <input placeholder="步骤" value={step} onChange={(event) => setStep(event.target.value)} />
            <button className="primaryButton" disabled={busy} onClick={() => refresh(0)}>应用</button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="Authority Worker / Outbox" icon={<Server size={18} />} />
          <div className="summaryBand">
            <Metric label="Workers" value={String(authorityWorkers.length)} />
            <Metric label="Busy" value={String(busyAuthorityWorkers)} />
            <Metric label="Outbox Lag" value={String(control?.scheduler?.outbox_lag ?? 0)} />
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="最新状态" icon={<Activity size={18} />} />
        <DataTable
          emptyText="暂无任务"
          columns={["任务", "步骤", "状态", "进度", "更新时间", "Operation", "恢复"]}
          rows={(center?.latest ?? []).map(taskRow)}
        />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Agent Timeline / Evidence" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 Agent Run"
            columns={["Agent", "操作", "状态", "模型", "Token", "证据", "输出", "路径"]}
            rows={agentRuns.slice(0, 40).map((run) => [
              run.agent_type,
              run.operation,
              <span className={statusClass(run.status)} key={`${run.id}-status`}>{run.status}</span>,
              `${run.model_provider || "-"} / ${run.model_name || "-"}`,
              `${run.token_used ?? 0}/${run.token_budget ?? 0}`,
              compactJson(run.evidence),
              String(run.output_assets?.length ?? 0),
              <span className="pathText" key={run.id}>{run.id}</span>
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Agent Events" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 Agent Event"
            columns={["事件", "状态", "消息", "时间", "Run"]}
            rows={agentEvents.slice(0, 60).map((event) => [
              event.event_type,
              <span className={statusClass(event.status)} key={`${event.id}-status`}>{event.status}</span>,
              event.message || "-",
              event.created_at || "-",
              <span className="pathText" key={event.id}>{event.agent_run_id}</span>
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Trace Timeline" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 Trace Span"
            columns={["类型", "名称", "状态", "开始", "结束", "证据"]}
            rows={(traceTimeline?.spans ?? []).slice(0, 80).map((span, index) => [
              String(span.span_type || "-"),
              String(span.name || "-"),
              <span className={statusClass(String(span.status || ""))} key={`trace-${index}`}>{String(span.status || "-")}</span>,
              String(span.started_at || "-"),
              String(span.finished_at || "-"),
              compactJson(span.attributes)
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Cost Quality" icon={<Activity size={18} />} />
          <div className="summaryBand">
            <Metric label="Ledger" value={String(costSummary.ledger_count ?? 0)} />
            <Metric label="Model Calls" value={String(costSummary.model_call_count ?? 0)} />
            <Metric label="质量均分" value={String(costSummary.average_quality_score ?? 0)} />
            <Metric label="成本/质量点" value={String(costSummary.cost_per_quality_point ?? 0)} />
          </div>
          <DataTable
            emptyText="暂无成本建议"
            columns={["建议"]}
            rows={costRecommendations.map((item) => [item])}
          />
          <p className="pathText">Project snapshot: {String(costSnapshots.project_cost_snapshot_path || "-")}</p>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="完整 Timeline" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无事件"
            columns={["任务", "步骤", "状态", "进度", "时间", "Operation", "恢复"]}
            rows={(center?.timeline.events ?? []).map(taskRow)}
          />
          <div className="studioActions">
            <button className="secondaryButton" disabled={offset <= 0 || busy} onClick={() => refresh(Math.max(0, offset - 120))}>上一页</button>
            <button className="secondaryButton" disabled={!center?.pagination?.next_offset || busy} onClick={() => refresh(center?.pagination?.next_offset ?? offset)}>下一页</button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="Dead Letter" icon={<RotateCcw size={18} />} />
          <DataTable
            emptyText="暂无 dead-letter"
            columns={["任务", "ID", "错误", "时间", "操作"]}
            rows={deadLetters.map((letter) => [
              letter.task_name,
              letter.task_id,
              letter.error_message || "-",
              letter.created_at,
              letter.kind === "outbox" ? (
                <button
                  className="secondaryButton"
                  disabled={busy}
                  key={letter.id || letter.task_id}
                  onClick={() => runAction(
                    () => requeueAuthorityOutbox(letter),
                    `New outbox generation admitted: ${letter.task_id}`
                  )}
                >新建投递 generation</button>
              ) : (
                <span className="pathText" key={letter.id || letter.task_id}>需由所属 Authority 创建新 Operation generation</span>
              )
            ])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}

function compactJson(value: unknown) {
  if (!value || typeof value !== "object") return "-";
  const text = JSON.stringify(value);
  return text.length > 90 ? `${text.slice(0, 90)}...` : text;
}
