"use client";

import { Activity, BrainCircuit, ListChecks, MessageSquareText, RefreshCcw, UploadCloud } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { FeedbackAssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  applyFeedbackStrategy,
  createFeedbackInsight,
  createOperationalSnapshot,
  createReaderSimulation,
  createSentimentReport,
  importFeedbackBatch,
  loadFeedbackData,
  runPublishFeedbackLoop,
  runRealFeedbackBackflow
} from "./api";

export function ReaderFeedbackPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [feedbackAssets, setFeedbackAssets] = useState<FeedbackAssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [inputPath, setInputPath] = useState("");
  const [platform, setPlatform] = useState("qidian");
  const [draftPath, setDraftPath] = useState("");
  const [chapterText, setChapterText] = useState("");
  const [realMetricsText, setRealMetricsText] = useState("{\n  \"completion_rate\": 0.58,\n  \"follow_read_rate\": 0.44,\n  \"comments\": [\"节奏有点拖\", \"想看下章反转\"],\n  \"favorites\": 12,\n  \"bookshelf_adds\": 18,\n  \"reward_count\": 1,\n  \"chapter_drop_points\": [{\"chapter\": 3, \"drop_rate\": 0.31, \"reason\": \"铺垫过长\"}],\n  \"negative_keywords\": [\"拖\", \"看不懂\"]\n}");
  const [releasePackagePath, setReleasePackagePath] = useState("");
  const [publishLoopResult, setPublishLoopResult] = useState<Record<string, unknown> | null>(null);
  const [simulationResult, setSimulationResult] = useState<Record<string, unknown> | null>(null);
  const [realBackflowResult, setRealBackflowResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const feedbackRows = feedbackAssets.filter((row) => row.type === "reader_feedback");
  const sentimentRows = feedbackAssets.filter((row) => row.type === "reader_sentiment_report");
  const simulationRows = feedbackAssets.filter((row) => row.type === "reader_simulation_report");
  const operationalRows = feedbackAssets.filter((row) => row.type === "operational_metric_snapshot");
  const realBackflowRows = feedbackAssets.filter((row) => row.type === "reader_feedback_backflow_report");
  const latestSentiment = sentimentRows[0];
  const latestSimulation = simulationRows[0];
  const latestOperational = operationalRows[0];
  const latestBackflow = realBackflowRows[0];
  const distribution = latestSentiment?.sentiment_distribution || {};
  const followRisk = latestOperational?.follow_read_risk || latestSentiment?.follow_read_risk || {};
  const strategy = latestSentiment?.next_chapter_strategy || {};
  const heat = latestOperational?.character_heat || latestSentiment?.character_heat || [];
  const readMetrics = latestOperational?.read_metrics || {};
  const engagement = latestOperational?.engagement_metrics || {};
  const dropoffs = latestOperational?.chapter_dropoffs || [];
  const simulation = latestSimulation?.reader_simulation || {};
  const simulationResultAggregate = ((simulationResult?.asset as { content?: { aggregate?: Record<string, unknown> } } | undefined)?.content?.aggregate || {}) as Record<string, unknown>;
  const simulationScore = simulation.predicted_score ?? simulationResultAggregate.predicted_score ?? "-";
  const simulationRisk = simulation.dropout_risk ?? simulationResultAggregate.dropout_risk ?? "-";
  const backflowTargets = latestBackflow?.target_updates || {};

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows] = await loadFeedbackData(nextProjectId);
    setProjects(projectRows);
    setFeedbackAssets(assetRows);
    setProjectId(nextProjectId || projectRows[0]?.project_id || "");
  }

  async function runAction(action: () => Promise<unknown>, message: string, after?: (result: unknown) => void) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action();
      after?.(result);
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
        <Metric label="读者模拟" value={String(simulationRows.length)} />
        <Metric label="运营快照" value={String(operationalRows.length)} />
        <Metric label="真实回流" value={String(realBackflowRows.length)} />
        <Metric label="负向反馈" value={String(distribution.negative ?? 0)} />
        <Metric label="追读风险" value={String(simulation.dropout_risk ?? followRisk.level ?? "unknown")} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="模拟读者预读" icon={<BrainCircuit size={18} />} />
          <div className="formGrid">
            <select value={platform} onChange={(event) => setPlatform(event.target.value)}>
              <option value="qidian">起点</option>
              <option value="fanqie">番茄</option>
              <option value="feilu">飞卢</option>
              <option value="jinjiang">晋江</option>
              <option value="zhihu_yanxuan">知乎盐选</option>
              <option value="wechat_publish">微信读书/出版向</option>
            </select>
            <input value={draftPath} onChange={(event) => setDraftPath(event.target.value)} placeholder="Draft path，留空则使用下方章节文本" />
            <textarea value={chapterText} onChange={(event) => setChapterText(event.target.value)} placeholder="预发布章节文本" rows={5} />
            <button
              className="primaryButton"
              disabled={busy || (!draftPath.trim() && !chapterText.trim())}
              onClick={() => runAction(
                () => createReaderSimulation({
                  draftPath,
                  chapterText,
                  projectId,
                  workspacePath: selectedProject?.path,
                  platform
                }),
                "模拟读者报告已生成",
                (result) => setSimulationResult(result as Record<string, unknown>)
              )}
            >
              运行模拟
            </button>
          </div>
          <div className="summaryBand">
            <Metric label="预测分" value={String(simulationScore)} />
            <Metric label="风险" value={String(simulationRisk)} />
          </div>
          <ul className="plainList">
            {(simulation.revision_suggestions?.length ? simulation.revision_suggestions : ["模拟会输出弃读风险、追读动机、爽点缺口、下章期待和修订建议。"]).slice(0, 5).map((item) => <li key={item}>{item}</li>)}
          </ul>
        </div>

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
            <button className="secondaryButton" disabled={busy || !feedbackRows.length} onClick={() => runAction(() => createOperationalSnapshot(feedbackRows.slice(0, 24).map((row) => row.path), projectId, selectedProject?.path), "运营指标快照已生成")}>运营快照</button>
            <button className="secondaryButton" disabled={busy || !feedbackRows.length} onClick={() => runAction(() => createFeedbackInsight(feedbackRows[0]?.path), "反馈洞察已生成")}>反馈洞察</button>
            <button className="secondaryButton" disabled={busy || !latestSentiment} onClick={() => runAction(() => applyFeedbackStrategy(latestSentiment?.path || "", selectedProject?.path), "下一章策略已回写")}>回写策略</button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="真实反馈回流" icon={<RefreshCcw size={18} />} />
          <div className="formGrid">
            <textarea value={realMetricsText} onChange={(event) => setRealMetricsText(event.target.value)} rows={8} />
            <button
              className="primaryButton"
              disabled={busy || !realMetricsText.trim()}
              onClick={() => runAction(
                () => {
                  const metrics = JSON.parse(realMetricsText) as Record<string, unknown>;
                  return runRealFeedbackBackflow({
                    metrics,
                    projectId,
                    workspacePath: selectedProject?.path,
                    platform,
                    releasePackagePath
                  });
                },
                "真实反馈已回流",
                (result) => setRealBackflowResult(result as Record<string, unknown>)
              )}
            >
              回流指标
            </button>
          </div>
          <p className="previewText">真实指标会写入 MKAOS 权重、平台策略、审稿规则、题材库、人设模板和节奏模板。</p>
          <div className="summaryBand">
            <Metric label="风险" value={String(realBackflowResult?.risk_level ?? latestBackflow?.status ?? "-")} />
            <Metric label="MKAOS" value={String(realBackflowResult?.mkaos_weight_update_count ?? backflowTargets.mkaos_weight?.updates?.length ?? 0)} />
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="发布反馈闭环" icon={<ListChecks size={18} />} />
          <div className="formGrid">
            <input value={releasePackagePath} onChange={(event) => setReleasePackagePath(event.target.value)} placeholder="Release package path" />
            <button
              className="primaryButton"
              disabled={busy || !feedbackRows.length}
              onClick={() => runAction(
                () => runPublishFeedbackLoop({
                  feedbackPaths: feedbackRows.slice(0, 24).map((row) => row.path),
                  projectId,
                  workspacePath: selectedProject?.path,
                  releasePackagePath
                }),
                "发布反馈闭环已生成",
                (result) => setPublishLoopResult(result as Record<string, unknown>)
              )}
            >
              闭环回写
            </button>
          </div>
          <p className="previewText">汇总读者反馈、生成回流计划，并把可追溯的权重更新写回 MKAOS。</p>
          {publishLoopResult ? (
            <div className="summaryBand">
              <Metric label="状态" value={String(publishLoopResult.status ?? "unknown")} />
              <Metric label="MKAOS 回写" value={String(publishLoopResult.mkaos_weight_update_count ?? 0)} />
              <Metric label="修订候选" value={String(publishLoopResult.revision_task_proposal_count ?? 0)} />
            </div>
          ) : null}
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
          <PanelHeader title="运营数据" icon={<Activity size={18} />} />
          <div className="summaryBand">
            <Metric label="阅读" value={String(readMetrics.total_reads ?? 0)} />
            <Metric label="完读" value={String(readMetrics.average_completion_rate ?? 0)} />
            <Metric label="评论率" value={String(engagement.comment_rate ?? 0)} />
          </div>
          <DataTable
            emptyText="暂无章节流失点"
            columns={["章节", "阅读", "流失率", "弃读信号", "评分", "风险"]}
            rows={dropoffs.slice(0, 12).map((row) => [
              String(row.chapter),
              String(row.reads),
              String(row.drop_rate),
              String(row.explicit_drop_signals),
              String(row.average_rating),
              <span className={statusClass(row.risk)} key={`drop-${row.chapter}`}>{row.risk}</span>
            ])}
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
