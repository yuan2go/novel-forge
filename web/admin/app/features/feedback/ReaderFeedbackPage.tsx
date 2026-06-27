"use client";

import { Activity, ListChecks, MessageSquareText, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { FeedbackAssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { applyFeedbackStrategy, createFeedbackInsight, createSentimentReport, importFeedbackBatch, loadFeedbackData } from "./api";

export function ReaderFeedbackPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [feedbackAssets, setFeedbackAssets] = useState<FeedbackAssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [inputPath, setInputPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const feedbackRows = feedbackAssets.filter((row) => row.type === "reader_feedback");
  const sentimentRows = feedbackAssets.filter((row) => row.type === "reader_sentiment_report");
  const latestSentiment = sentimentRows[0];
  const distribution = latestSentiment?.sentiment_distribution || {};
  const followRisk = latestSentiment?.follow_read_risk || {};
  const strategy = latestSentiment?.next_chapter_strategy || {};
  const heat = latestSentiment?.character_heat || [];

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows] = await loadFeedbackData(nextProjectId);
    setProjects(projectRows);
    setFeedbackAssets(assetRows);
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
    <FeatureShell title="读者反馈中心" subtitle="导入本地评论反馈，生成情绪分布、爽点/毒点、角色热度、追读风险和下一章策略约束。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="反馈资产" value={String(feedbackRows.length)} />
        <Metric label="情绪报告" value={String(sentimentRows.length)} />
        <Metric label="负向反馈" value={String(distribution.negative ?? 0)} />
        <Metric label="追读风险" value={String(followRisk.level ?? "unknown")} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="导入评论" icon={<UploadCloud size={18} />} />
          <div className="formGrid">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <input value={inputPath} onChange={(event) => setInputPath(event.target.value)} placeholder="CSV path: reader, chapter, rating, comment" />
            <button className="primaryButton" disabled={busy || !inputPath.trim()} onClick={() => runAction(() => importFeedbackBatch(inputPath, selectedProject?.path), "反馈批次已导入")}>导入</button>
          </div>
          <p className="previewText">推荐列：reader, chapter, rating, comment。导入后生成 feedback_import_batch 与 reader_feedback 资产。</p>
        </div>

        <div className="panel">
          <PanelHeader title="生成洞察" icon={<MessageSquareText size={18} />} />
          <div className="summaryBand">
            <Metric label="positive" value={String(distribution.positive ?? 0)} />
            <Metric label="neutral" value={String(distribution.neutral ?? 0)} />
            <Metric label="negative" value={String(distribution.negative ?? 0)} />
          </div>
          <p className="previewText">{strategy.primary_strategy || "生成情绪报告后会出现下一章策略。"}</p>
          <div className="studioActions">
            <button className="primaryButton" disabled={busy || !feedbackRows.length} onClick={() => runAction(() => createSentimentReport(feedbackRows.slice(0, 12).map((row) => row.path), projectId, selectedProject?.path), "情绪报告已生成")}>情绪报告</button>
            <button className="secondaryButton" disabled={busy || !feedbackRows.length} onClick={() => runAction(() => createFeedbackInsight(feedbackRows[0]?.path), "反馈洞察已生成")}>反馈洞察</button>
            <button className="secondaryButton" disabled={busy || !latestSentiment} onClick={() => runAction(() => applyFeedbackStrategy(latestSentiment?.path || "", selectedProject?.path), "下一章策略已回写")}>回写策略</button>
          </div>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="角色热度" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无角色热度"
            columns={["角色", "提及", "热度"]}
            rows={heat.slice(0, 12).map((row) => [row.character, String(row.mentions), String(row.heat)])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="下一章策略" icon={<ListChecks size={18} />} />
          <ul className="plainList">
            {(strategy.constraints?.length ? strategy.constraints : ["暂无约束，先生成情绪报告。"]).map((item) => <li key={item}>{item}</li>)}
          </ul>
          <ul className="plainList">
            {(strategy.actions || []).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="反馈资产" icon={<ListChecks size={18} />} />
        <DataTable
          emptyText="暂无反馈资产"
          columns={["类型", "标题", "行数", "评分", "置信度", "建议", "状态", "路径"]}
          rows={feedbackAssets.map((row) => [
            row.type,
            row.title || row.id,
            String(row.row_count ?? 0),
            String(row.average_rating ?? "-"),
            row.confidence || "-",
            row.recommendation || "-",
            <span className={statusClass(row.status || "active")} key={`${row.path}-status`}>{row.status || "active"}</span>,
            <span className="pathText" key={`${row.path}-path`}>{row.path}</span>
          ])}
        />
      </section>
    </FeatureShell>
  );
}
