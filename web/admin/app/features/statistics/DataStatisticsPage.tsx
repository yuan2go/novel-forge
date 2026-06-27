"use client";

import { Activity, BarChart3, ListChecks, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AgentRunRow, MetricSnapshotRow, ProjectHealthReport, ProjectRow, TaskCenter } from "../../shared/types";
import { DataTable, Metric, PanelHeader } from "../../shared/ui";
import { createMetricSnapshot, loadStatisticsData } from "./api";

export function DataStatisticsPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [snapshots, setSnapshots] = useState<MetricSnapshotRow[]>([]);
  const [taskCenter, setTaskCenter] = useState<TaskCenter | null>(null);
  const [agentRuns, setAgentRuns] = useState<AgentRunRow[]>([]);
  const [projectHealth, setProjectHealth] = useState<ProjectHealthReport | null>(null);
  const [projectId, setProjectId] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const latest = snapshots[0];
  const throughput = latest?.throughput || {};
  const quality = latest?.quality || {};
  const taskHealth = latest?.task_health || {};
  const agentHealth = latest?.agent_health || {};
  const trends = latest?.trends || {};
  const modelCost = latest?.model_cost || {};
  const originality = latest?.originality || {};
  const failedAgents = agentRuns.filter((row) => ["failed", "dead_letter"].includes(row.status)).length;

  async function refresh(nextProjectId = projectId) {
    const [projectRows, metricRows, taskRows, agentRows, healthReport] = await loadStatisticsData(nextProjectId);
    setProjects(projectRows);
    setSnapshots(metricRows);
    setTaskCenter(taskRows);
    setAgentRuns(agentRows);
    setProjectHealth(healthReport);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
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
    <FeatureShell title="数据统计中心" subtitle="产能、质量趋势、任务健康、Agent 失败率、原创风险和模型成本都沉淀为 project_metric_snapshot。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="资产" value={String(throughput.asset_count ?? projectHealth?.summary.asset_count ?? 0)} />
        <Metric label="审稿均分" value={String(quality.average_review_score ?? 0)} />
        <Metric label="失败 Agent" value={String(agentHealth.failed ?? failedAgents)} />
        <Metric label="模型成本" value={String(modelCost.cost_estimate ?? 0)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="当前快照" icon={<BarChart3 size={18} />} />
          <div className="formGrid">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <button className="primaryButton" disabled={busy} onClick={() => runAction(() => createMetricSnapshot(projectId, selectedProject?.path), "指标快照已创建")}>
              <Save size={18} />
              生成快照
            </button>
          </div>
          <div className="summaryBand">
            <Metric label="草稿" value={String(throughput.draft_count ?? 0)} />
            <Metric label="失败任务" value={String(taskHealth.failed ?? taskCenter?.summary.by_status.failed ?? 0)} />
            <Metric label="Dead Letter" value={String(taskHealth.dead_letters ?? 0)} />
            <Metric label="SLA" value={String(agentHealth.sla_breaches ?? 0)} />
            <Metric label="原创风险" value={String(originality.high_or_medium_count ?? 0)} />
            <Metric label="质量变化" value={String(trends.quality_delta ?? 0)} />
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="建议" icon={<Activity size={18} />} />
          <ul className="plainList">
            {(latest?.recommendations?.length ? latest.recommendations : ["暂无快照，先生成一次项目指标。"]).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="指标快照资产" icon={<ListChecks size={18} />} />
        <DataTable
          emptyText="暂无指标快照"
          columns={["时间", "风险", "资产", "审稿均分", "失败任务", "Agent 失败", "路径"]}
          rows={snapshots.map((row) => [
            row.snapshot_at || row.updated_at,
            <span className={row.risk_level === "low" ? "badge ok" : "badge warn"} key={`${row.path}-risk`}>{row.risk_level}</span>,
            String(row.throughput.asset_count ?? 0),
            String(row.quality.average_review_score ?? 0),
            String(row.task_health.failed ?? 0),
            String(row.agent_health.failed ?? 0),
            <span className="pathText" key={row.path}>{row.path}</span>
          ])}
        />
      </section>
    </FeatureShell>
  );
}
