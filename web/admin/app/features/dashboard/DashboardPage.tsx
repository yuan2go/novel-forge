"use client";

import { Activity, BarChart3, CheckCircle2, FileSearch, ListChecks, MessageSquareText, PenLine, ShieldCheck, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { Health, ProjectHealthReport, ProjectRow, TaskCenter } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { loadDashboardData } from "./api";

const quickLinks = [
  { href: "/projects", label: "创建/绑定项目", icon: <CheckCircle2 size={18} /> },
  { href: "/analysis", label: "拆解作品", icon: <FileSearch size={18} /> },
  { href: "/context", label: "构建上下文", icon: <Workflow size={18} /> },
  { href: "/manuscript", label: "进入稿件工作台", icon: <PenLine size={18} />, primary: true },
  { href: "/review", label: "审稿修订", icon: <ShieldCheck size={18} /> },
  { href: "/feedback", label: "导入反馈", icon: <MessageSquareText size={18} /> }
];

export function DashboardPage() {
  const [health, setHealth] = useState<Health | null>(null);
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [tasks, setTasks] = useState<TaskCenter | null>(null);
  const [projectHealth, setProjectHealth] = useState<ProjectHealthReport | null>(null);
  const [error, setError] = useState("");

  async function refresh() {
    const [healthData, projectRows, taskData, projectHealthData] = await loadDashboardData();
    setHealth(healthData);
    setProjects(projectRows);
    setTasks(taskData);
    setProjectHealth(projectHealthData);
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  return (
    <FeatureShell title="个人本地小说工厂" subtitle="围绕题材、素材、知识、上下文、章节生产、审稿、发布和反馈形成可审计的工业化闭环。" eyebrow="Production Console">
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand factoryMetrics">
        <Metric label="项目" value={String(projects.length)} />
        <Metric label="资产" value={String(projectHealth?.summary.asset_count ?? Object.values(health?.local_counts ?? {}).reduce((sum, value) => sum + value, 0))} />
        <Metric label="任务" value={String(tasks?.summary.task_count ?? 0)} />
        <Metric label="风险" value={String((projectHealth?.summary.failed_task_count ?? 0) + (projectHealth?.summary.scope_issue_count ?? 0) + (projectHealth?.summary.dead_letter_count ?? 0))} />
      </section>

      <section className="workspaceGrid">
        <div className="panel heroPanel">
          <div>
            <p className="eyebrow">Production Chain</p>
            <h2>今日生产入口</h2>
            <p>从项目空间开始，按拆解、资产转换、上下文、章节、审稿、修订、反馈复盘推进。</p>
          </div>
          <div className="placeholderActions">
            {quickLinks.map((link) => (
              <a className={link.primary ? "primaryButton" : "secondaryButton"} href={link.href} key={link.href}>
                {link.icon}
                {link.label}
              </a>
            ))}
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="项目健康" icon={<Activity size={18} />} />
          <div className="summaryBand">
            <Metric label="失败任务" value={String(projectHealth?.summary.failed_task_count ?? 0)} />
            <Metric label="待 Handoff" value={String(projectHealth?.summary.pending_handoff_count ?? 0)} />
            <Metric label="范围问题" value={String(projectHealth?.summary.scope_issue_count ?? 0)} />
            <Metric label="Dead Letter" value={String(projectHealth?.summary.dead_letter_count ?? 0)} />
          </div>
          <div className="actionRow">
            <a className="secondaryButton" href="/health">健康检查</a>
            <a className="secondaryButton" href="/control">生产总控</a>
            <a className="secondaryButton" href="/tasks">任务中心</a>
          </div>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="最近任务" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无任务"
            columns={["任务", "步骤", "状态", "时间"]}
            rows={(tasks?.latest ?? tasks?.tasks ?? []).slice(0, 12).map((task) => [
              task.task_type,
              task.step,
              <span className={statusClass(task.status)} key={`${task.path}-status`}>{task.status}</span>,
              task.updated_at || task.recorded_at || "-"
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="系统指标" icon={<BarChart3 size={18} />} />
          <DataTable
            emptyText="暂无本地资产计数"
            columns={["目录", "数量"]}
            rows={Object.entries(health?.local_counts ?? {}).sort((a, b) => b[1] - a[1]).slice(0, 16).map(([name, count]) => [name, String(count)])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}
