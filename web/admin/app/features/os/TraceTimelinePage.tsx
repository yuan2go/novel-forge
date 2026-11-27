"use client";

import { Activity, GitBranch, Route, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AgentEventRow, AgentRunRow, ProjectRow, WorkflowRunRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { loadTraceTimelineData, type RuntimeTraceTimeline } from "./api";
import { compactJson, durationLabel, pathCell } from "./helpers";

export function TraceTimelinePage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [timeline, setTimeline] = useState<RuntimeTraceTimeline | null>(null);
  const [workflowRuns, setWorkflowRuns] = useState<WorkflowRunRow[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRunRow[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEventRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [traceId, setTraceId] = useState("");
  const [spanType, setSpanType] = useState("");
  const [spanStatus, setSpanStatus] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function refresh(nextProjectId = projectId, nextTraceId = traceId) {
    setBusy(true);
    setError("");
    try {
      const [projectRows, traceData, workflowRows, agentRows, eventRows] = await loadTraceTimelineData(nextProjectId, nextTraceId.trim());
      setProjects(projectRows);
      setTimeline(traceData);
      setWorkflowRuns(workflowRows);
      setAgentRuns(agentRows);
      setAgentEvents(eventRows);
      setProjectId(nextProjectId || projectRows[0]?.project_id || "");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const spans = useMemo(() => {
    return (timeline?.spans || []).filter((span) => {
      if (spanType && String(span.span_type || "") !== spanType) return false;
      if (spanStatus && String(span.status || "") !== spanStatus) return false;
      return true;
    });
  }, [timeline, spanType, spanStatus]);
  const types = Array.from(new Set((timeline?.spans || []).map((span) => String(span.span_type || "unknown")))).sort();
  const statuses = Array.from(new Set((timeline?.spans || []).map((span) => String(span.status || "unknown")))).sort();
  const summary = timeline?.summary || {};
  const traceIds = Array.from(new Set(workflowRuns.map((run) => run.trace_id).filter(Boolean))).slice(0, 20);

  return (
    <FeatureShell title="Trace Timeline" subtitle="统一查看 Workflow、Node、Agent、Model Call、Context Bundle、Gate、Cost、Feedback span 的全链路证据。" eyebrow="OS Runtime">
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Spans" value={String(summary.span_count ?? spans.length)} />
        <Metric label="Failed" value={String(summary.failed_count ?? 0)} />
        <Metric label="Duration" value={`${String(summary.total_duration_ms ?? 0)} ms`} />
        <Metric label="Workflow Runs" value={String(workflowRuns.length)} />
        <Metric label="Agent Runs" value={String(agentRuns.length)} />
        <Metric label="Events" value={String(agentEvents.length)} />
      </section>

      <section className="panel">
        <PanelHeader title="Trace Filter" icon={<Search size={18} />} />
        <div className="formGrid wide">
          <select value={projectId} onChange={(event) => { setProjectId(event.target.value); refresh(event.target.value, traceId).catch(() => undefined); }}>
            <option value="">全局</option>
            {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
          </select>
          <input value={traceId} onChange={(event) => setTraceId(event.target.value)} placeholder="trace_id，可留空" list="trace-id-list" />
          <datalist id="trace-id-list">
            {traceIds.map((id) => <option value={id} key={id} />)}
          </datalist>
          <select value={spanType} onChange={(event) => setSpanType(event.target.value)}>
            <option value="">全部 span type</option>
            {types.map((type) => <option value={type} key={type}>{type}</option>)}
          </select>
          <select value={spanStatus} onChange={(event) => setSpanStatus(event.target.value)}>
            <option value="">全部状态</option>
            {statuses.map((status) => <option value={status} key={status}>{status}</option>)}
          </select>
          <button className="primaryButton" disabled={busy} onClick={() => refresh()}><Route size={16} />加载 Timeline</button>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Timeline Rail" icon={<Route size={18} />} />
          <div className="traceRail">
            {spans.slice(0, 80).map((span, index) => (
              <button className="traceRailItem" key={`${String(span.span_id || index)}-${index}`} onClick={() => setTraceId(String(span.trace_id || ""))}>
                <span className={statusClass(String(span.status || ""))}>{String(span.span_type || "-")}</span>
                <strong>{String(span.name || "-")}</strong>
                <small>{String(span.status || "-")} · {durationLabel(span)} · {String(span.started_at || "-")}</small>
              </button>
            ))}
            {!spans.length ? <p className="muted">暂无 trace span。</p> : null}
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="Trace Summary" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 span type"
            columns={["类型", "数量"]}
            rows={Object.entries((summary.by_type as Record<string, unknown> | undefined) || {}).map(([type, count]) => [type, String(count)])}
          />
          <DataTable
            emptyText="暂无状态"
            columns={["状态", "数量"]}
            rows={Object.entries((summary.by_status as Record<string, unknown> | undefined) || {}).map(([statusName, count]) => [
              <span className={statusClass(statusName)} key={statusName}>{statusName}</span>,
              String(count)
            ])}
          />
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Trace Spans" icon={<GitBranch size={18} />} />
        <DataTable
          emptyText="暂无 Trace Span"
          columns={["Type", "Name", "状态", "Trace", "Parent", "时间", "属性"]}
          rows={spans.slice(0, 180).map((span, index) => [
            String(span.span_type || "-"),
            String(span.name || "-"),
            <span className={statusClass(String(span.status || ""))} key={`span-${index}`}>{String(span.status || "-")}</span>,
            String(span.trace_id || "-"),
            String(span.parent_span_id || "-"),
            `${String(span.started_at || "-")} -> ${String(span.finished_at || "-")}`,
            compactJson(span.attributes, 160)
          ])}
        />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Workflow Trace Anchors" icon={<WorkflowIcon />} />
          <DataTable
            emptyText="暂无 workflow run"
            columns={["Run", "状态", "Trace", "Blocked", "路径"]}
            rows={workflowRuns.slice(0, 40).map((run) => [
              run.run_id,
              <span className={statusClass(run.status)} key={`${run.path}-status`}>{run.status}</span>,
              run.trace_id || "-",
              run.blocked_node_id || "-",
              pathCell(run.path, run.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Agent Events" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 Agent Event"
            columns={["事件", "状态", "消息", "Run"]}
            rows={agentEvents.slice(0, 70).map((event) => [
              event.event_type,
              <span className={statusClass(event.status)} key={`${event.path}-status`}>{event.status}</span>,
              event.message || "-",
              pathCell(event.agent_run_path, event.path)
            ])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}

function WorkflowIcon() {
  return <GitBranch size={18} />;
}
