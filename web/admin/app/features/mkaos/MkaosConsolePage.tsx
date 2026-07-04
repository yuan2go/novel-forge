"use client";

import { BookOpenCheck, Bug, Database, FileText, GitBranch, GitPullRequest, ListChecks, ShieldAlert, ShieldCheck, Sparkles, Workflow } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  buildKnowledgePack,
  buildKnowledgeGraph,
  createKnowledgeCard,
  createUsageBinding,
  importMkaosSource,
  loadMkaosOverview,
  loadMutations,
  loadPackDebug,
  loadPackPreview,
  patchKnowledge,
  patchUsageBinding,
  queryLineage,
  runKnowledgeEvolution,
  runKnowledgeAssetOsAcceptance,
  runMinimalAcceptance,
  runRegressionSuite,
  type MkaosOverview,
  type MkaosRow
} from "./api";

const flows = ["outline", "chapter_outline", "prose", "review"];

export function MkaosConsolePage() {
  const [overview, setOverview] = useState<MkaosOverview | null>(null);
  const [sourceTitle, setSourceTitle] = useState("土地兼并制度知识");
  const [sourceText, setSourceText] = useState("王朝末期，土地兼并严重，小农破产，流民增加，地方豪强扩张，中央税源减少。");
  const [lastChunkIds, setLastChunkIds] = useState<string[]>([]);
  const [conceptName, setConceptName] = useState("土地兼并");
  const [discipline, setDiscipline] = useState("历史制度");
  const [coreExplanation, setCoreExplanation] = useState("土地兼并通过田契、税源和佃户关系改变地方利益分配，可转化为豪强获利、小农受损、主角被案卷卷入的主线冲突。");
  const [selectedKnowledgeId, setSelectedKnowledgeId] = useState("");
  const [bindingFlow, setBindingFlow] = useState("outline");
  const [bindingConstraint, setBindingConstraint] = useState("地方土地案作为第一卷主线冲突；制度矛盾必须影响主角利益。");
  const [packFlow, setPackFlow] = useState("outline");
  const [packGoal, setPackGoal] = useState("构造 MKAOS P0 知识调用闭环");
  const [packPreview, setPackPreview] = useState("");
  const [packDebug, setPackDebug] = useState<Record<string, any> | null>(null);
  const [graphSummary, setGraphSummary] = useState<Record<string, any> | null>(null);
  const [graphData, setGraphData] = useState<Record<string, any> | null>(null);
  const [lineage, setLineage] = useState<Record<string, any> | null>(null);
  const [mutations, setMutations] = useState<MkaosRow[]>([]);
  const [evolution, setEvolution] = useState<Record<string, any> | null>(null);
  const [regression, setRegression] = useState<Record<string, any> | null>(null);
  const [acceptance, setAcceptance] = useState<Record<string, boolean> | null>(null);
  const [p1Acceptance, setP1Acceptance] = useState<Record<string, any> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedKnowledge = useMemo(() => {
    return overview?.knowledge.find((item) => item.id === selectedKnowledgeId) ?? overview?.knowledge[0] ?? null;
  }, [overview, selectedKnowledgeId]);

  async function refresh() {
    const next = await loadMkaosOverview();
    setOverview(next);
    if (!selectedKnowledgeId && next.knowledge[0]?.id) {
      setSelectedKnowledgeId(next.knowledge[0].id);
    }
  }

  async function runAction(action: () => Promise<any>, message: string) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action();
      setNotice(message);
      await refresh();
      return result;
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
      return null;
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const summary = overview?.summary ?? {};
  const knowledgeRows = overview?.knowledge ?? [];
  const bindingRows = overview?.bindings ?? [];
  const riskRows = overview?.risks ?? [];
  const ruleRows = overview?.rules ?? [];
  const usageRows = overview?.usage_events ?? [];
  const sourceRows = overview?.sources ?? [];
  const qualityDashboard = useMemo(() => {
    const statusCounts = knowledgeRows.reduce<Record<string, number>>((acc, row) => {
      const status = String(row.status || row.content.status || "verified");
      acc[status] = (acc[status] ?? 0) + 1;
      return acc;
    }, {});
    const qualityValues = knowledgeRows
      .map((row) => Number(row.content.overall_quality_score ?? row.content.quality_score ?? 0))
      .filter((value) => Number.isFinite(value) && value > 0);
    const averageQuality = qualityValues.length ? qualityValues.reduce((sum, value) => sum + value, 0) / qualityValues.length : 0;
    const highRisk = knowledgeRows.filter((row) => ["high", "critical"].includes(String(row.risk_level || row.content.risk_level || ""))).length;
    const lowEffect = knowledgeRows.filter((row) => Number(row.content.overall_quality_score ?? row.content.quality_score ?? 1) < 0.5).length;
    return { statusCounts, averageQuality, highRisk, lowEffect };
  }, [knowledgeRows]);

  return (
    <FeatureShell title="MKAOS 知识资产操作系统" subtitle="来源、知识卡、流程绑定、Knowledge Pack、审稿规则、使用留痕和反馈回写。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="来源" value={String(summary.source_documents ?? 0)} />
        <Metric label="知识卡" value={String(summary.knowledge_cards ?? 0)} />
        <Metric label="绑定" value={String(summary.usage_bindings ?? 0)} />
        <Metric label="Usage" value={String(summary.usage_events ?? 0)} />
        <Metric label="风险" value={String(summary.risk_items ?? 0)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="来源管理" icon={<FileText size={18} />} />
          <div className="formGrid">
            <input value={sourceTitle} onChange={(event) => setSourceTitle(event.target.value)} />
            <button
              className="primaryButton"
              disabled={busy || !sourceText.trim()}
              onClick={() => runAction(async () => {
                const result = await importMkaosSource(sourceTitle, sourceText);
                const chunks = Array.isArray((result as any).chunks) ? (result as any).chunks : [];
                setLastChunkIds(chunks.map((chunk: any) => String(chunk.id)).filter(Boolean));
                return result;
              }, "来源已导入并切片")}
            >
              导入
            </button>
          </div>
          <textarea rows={5} value={sourceText} onChange={(event) => setSourceText(event.target.value)} />
          <DataTable
            emptyText="暂无 MKAOS 来源"
            columns={["来源", "状态", "Chunks", "路径"]}
            rows={sourceRows.slice(0, 6).map((row) => [
              row.title || row.id,
              row.content.clean_status || "-",
              String(row.content.chunk_count ?? "-"),
              <span className="pathText" key={row.path}>{row.path}</span>
            ])}
          />
          <details className="jsonPreview">
            <summary>Source Evidence 原文层默认折叠</summary>
            <p className="mutedText">operator-only evidence 仅用于溯源审计；Knowledge Pack、Context Bundle、正文 prompt 默认只使用 source ids、evidence hash 和抽象知识。</p>
          </details>
        </div>

        <div className="panel">
          <PanelHeader title="知识卡管理" icon={<Database size={18} />} />
          <div className="formGrid">
            <input value={conceptName} onChange={(event) => setConceptName(event.target.value)} />
            <input value={discipline} onChange={(event) => setDiscipline(event.target.value)} />
            <button
              className="primaryButton"
              disabled={busy || !conceptName.trim()}
              onClick={() => runAction(async () => {
                const result = await createKnowledgeCard({ conceptName, discipline, coreExplanation, sourceChunkIds: lastChunkIds });
                setSelectedKnowledgeId(String((result as any).asset?.id ?? ""));
                return result;
              }, "知识卡已创建")}
            >
              创建
            </button>
          </div>
          <textarea rows={4} value={coreExplanation} onChange={(event) => setCoreExplanation(event.target.value)} />
          <DataTable
            emptyText="暂无知识卡"
            columns={["知识", "状态", "风险", "权重", "操作"]}
            rows={knowledgeRows.slice(0, 8).map((row) => [
              <button className="linkButton" key={row.id} onClick={() => setSelectedKnowledgeId(row.id)}>{row.title || row.id}</button>,
              <span className={statusClass(row.status || "active")} key={`${row.id}-status`}>{row.status || "active"}</span>,
              row.risk_level || "-",
              String(row.content.weight ?? row.metadata.weight ?? "-"),
              <span className="buttonRow" key={`${row.id}-actions`}>
                <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => patchKnowledge(row.id, { status: "needs_review" }), "知识卡已标记复审")}>复审</button>
                <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => patchKnowledge(row.id, { status: "active" }), "知识卡已恢复")}>启用</button>
              </span>
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="流程用途绑定" icon={<GitPullRequest size={18} />} />
          <div className="formGrid">
            <select value={selectedKnowledge?.id ?? ""} onChange={(event) => setSelectedKnowledgeId(event.target.value)}>
              {knowledgeRows.map((row) => <option value={row.id} key={row.id}>{row.title || row.id}</option>)}
            </select>
            <select value={bindingFlow} onChange={(event) => setBindingFlow(event.target.value)}>
              {flows.map((flow) => <option value={flow} key={flow}>{flow}</option>)}
            </select>
            <button
              className="primaryButton"
              disabled={busy || !selectedKnowledge?.id}
              onClick={() => runAction(() => createUsageBinding(selectedKnowledge?.id ?? "", {
                flow: bindingFlow,
                usageType: bindingFlow === "review" ? "review_rule" : bindingFlow === "prose" ? "optional" : "required",
                inputRole: bindingFlow === "review" ? "review_rule" : bindingFlow === "prose" ? "optional" : "required",
                outputForm: bindingFlow === "prose" ? "动作、对话、物件或场景" : "结构约束",
                constraintText: bindingConstraint
              }), "用途绑定已创建")}
            >
              绑定
            </button>
          </div>
          <textarea rows={3} value={bindingConstraint} onChange={(event) => setBindingConstraint(event.target.value)} />
          <DataTable
            emptyText="暂无绑定"
            columns={["知识", "Flow", "Role", "Enabled", "操作"]}
            rows={bindingRows.slice(0, 10).map((row) => [
              row.content.knowledge_id || "-",
              row.content.flow || "-",
              row.content.input_role || row.content.usage_type || "-",
              String(row.content.enabled),
              <button className="secondaryButton" key={row.id} disabled={busy} onClick={() => runAction(() => patchUsageBinding(row.id, { enabled: !row.content.enabled }), "绑定状态已更新")}>
                {row.content.enabled ? "禁用" : "启用"}
              </button>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Knowledge Pack 预览" icon={<Workflow size={18} />} />
          <div className="formGrid">
            <select value={packFlow} onChange={(event) => setPackFlow(event.target.value)}>
              {flows.map((flow) => <option value={flow} key={flow}>{flow}</option>)}
            </select>
            <input value={packGoal} onChange={(event) => setPackGoal(event.target.value)} />
            <button
              className="primaryButton"
              disabled={busy}
              onClick={() => runAction(async () => {
                const pack = await buildKnowledgePack(packFlow, packGoal);
                const preview = await loadPackPreview(String((pack as any).asset?.id ?? ""));
                const debug = await loadPackDebug(String((pack as any).asset?.id ?? ""));
                setPackPreview(preview.preview);
                setPackDebug(debug);
                return pack;
              }, "Knowledge Pack 已构造")}
            >
              构造
            </button>
          </div>
          <pre className="jsonPreview">{packPreview || "No pack preview"}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Quality Dashboard" icon={<Sparkles size={18} />} />
          <section className="summaryBand">
            <Metric label="平均质量" value={qualityDashboard.averageQuality ? qualityDashboard.averageQuality.toFixed(2) : "0.00"} />
            <Metric label="高风险知识" value={String(qualityDashboard.highRisk)} />
            <Metric label="低效果知识" value={String(qualityDashboard.lowEffect)} />
            <Metric label="Needs Review" value={String(qualityDashboard.statusCounts.needs_review ?? 0)} />
          </section>
          <DataTable
            emptyText="暂无质量数据"
            columns={["状态", "数量"]}
            rows={Object.entries(qualityDashboard.statusCounts).map(([status, count]) => [status, String(count)])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Pack Debugger" icon={<Bug size={18} />} />
          <DataTable
            emptyText="先构造一个 Knowledge Pack"
            columns={["选中", "拒绝", "预算", "阻断风险"]}
            rows={packDebug ? [[
              String(Array.isArray(packDebug.selected_items) ? packDebug.selected_items.length : 0),
              String(Array.isArray(packDebug.rejected_items) ? packDebug.rejected_items.length : 0),
              `${packDebug.budget_usage?.estimated_tokens ?? 0} tokens`,
              String(Array.isArray(packDebug.blocking_risks) ? packDebug.blocking_risks.length : 0)
            ]] : []}
          />
          <pre className="jsonPreview">{packDebug ? JSON.stringify({
            selected: packDebug.selected_items?.map((item: any) => item.concept_name),
            rejected: packDebug.rejected_items?.map((item: any) => ({ knowledge_id: item.knowledge_id, reason: item.reason })),
            source_isolation: packDebug.source_isolation_result
          }, null, 2) : "No debug report"}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Knowledge Graph" icon={<GitBranch size={18} />} />
          <button className="primaryButton" disabled={busy} onClick={() => runAction(async () => {
            const graph = await buildKnowledgeGraph();
            setGraphData(graph as Record<string, any>);
            setGraphSummary((graph as any).summary ?? null);
            return graph;
          }, "Knowledge Graph 已刷新")}>刷新图谱</button>
          <DataTable
            emptyText="暂无图谱摘要"
            columns={["Nodes", "Edges", "Knowledge", "Flows"]}
            rows={graphSummary ? [[
              String(graphSummary.node_count ?? 0),
              String(graphSummary.edge_count ?? 0),
              String(graphSummary.coverage?.knowledge_card ?? 0),
              String(graphSummary.coverage?.flow ?? 0)
            ]] : []}
          />
          <GraphPreview graph={graphData} />
        </div>

        <div className="panel">
          <PanelHeader title="Lineage Audit" icon={<ListChecks size={18} />} />
          <button className="primaryButton" disabled={busy || !selectedKnowledge?.id} onClick={() => runAction(async () => {
            const report = await queryLineage(selectedKnowledge?.id ?? "");
            setLineage(report as Record<string, any>);
            const rows = await loadMutations(selectedKnowledge?.id ?? "");
            setMutations(rows);
            return report;
          }, "Lineage Audit 已生成")}>查看当前知识链路</button>
          <DataTable
            emptyText="暂无 lineage report"
            columns={["Knowledge", "Packs", "Issues", "Feedback", "Mutations"]}
            rows={lineage ? [[
              String(lineage.knowledge_ids?.length ?? 0),
              String(lineage.knowledge_packs?.length ?? 0),
              String(lineage.review_issues?.length ?? 0),
              String(lineage.feedback_attributions?.length ?? 0),
              String(mutations.length)
            ]] : []}
          />
          <pre className="jsonPreview">{lineage ? JSON.stringify({
            knowledge: lineage.knowledge_ids,
            consistency: lineage.consistency_checks,
            references: lineage.references?.slice?.(0, 8) ?? []
          }, null, 2) : "No lineage selected"}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="审稿规则库" icon={<ShieldCheck size={18} />} />
          <DataTable
            emptyText="暂无规则"
            columns={["规则", "类型", "严重度", "Flows"]}
            rows={ruleRows.map((row) => [
              row.content.rule_name || row.title,
              row.content.rule_type || "-",
              row.content.severity || "-",
              (row.content.applicable_flows ?? []).join(", ")
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="知识使用记录" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 usage event"
            columns={["知识", "Flow", "Agent", "Used As", "Artifact"]}
            rows={usageRows.slice(0, 10).map((row) => [
              row.content.knowledge_id || "-",
              row.content.flow || "-",
              row.content.agent_name || "-",
              row.content.used_as || "-",
              row.content.target_artifact_id || "-"
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Knowledge Evolution" icon={<Sparkles size={18} />} />
          <button
            className="primaryButton"
            disabled={busy}
            onClick={() => runAction(async () => {
              const result = await runKnowledgeEvolution();
              setEvolution(result as Record<string, any>);
              return result;
            }, "知识资产进化循环已生成")}
          >
            运行进化循环
          </button>
          <section className="summaryBand">
            {evolution ? (
              <>
                <Metric label="学习建议" value={String(evolution.learning_snapshot?.recommendation_count ?? 0)} />
                <Metric label="规则候选" value={String(evolution.review_rule_evolution?.candidates?.length ?? 0)} />
                <Metric label="模板候选" value={String(evolution.hot_template_backflow?.candidates?.length ?? 0)} />
                <Metric label="淘汰建议" value={String(evolution.low_effect_elimination?.recommendations?.length ?? 0)} />
              </>
            ) : <Metric label="状态" value="未运行" />}
          </section>
          <pre className="jsonPreview">{evolution ? JSON.stringify({
            graph: evolution.graph_snapshot?.summary,
            feedback: evolution.reader_feedback_backflow,
            governance: evolution.governance_policy
          }, null, 2) : "No evolution report"}</pre>
        </div>

        <div className="panel">
          <PanelHeader title="知识风险列表" icon={<ShieldAlert size={18} />} />
          <DataTable
            emptyText="暂无风险知识"
            columns={["知识", "状态", "风险", "原因"]}
            rows={riskRows.map((row) => [
              row.title || row.id,
              row.status || "-",
              row.risk_level || "-",
              Array.isArray((row as any).risk_reasons) ? (row as any).risk_reasons.join(", ") : "-"
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Regression Cases" icon={<BookOpenCheck size={18} />} />
          <button
            className="primaryButton"
            disabled={busy}
            onClick={() => runAction(async () => {
              const result = await runRegressionSuite();
              setRegression(result as Record<string, any>);
              return result;
            }, "MKAOS regression suite 已运行")}
          >
            运行回归套件
          </button>
          <div className="summaryBand">
            {regression ? (
              <>
                <Metric label="Cases" value={String(regression.summary?.case_count ?? 0)} />
                <Metric label="Passed" value={String(regression.summary?.passed ?? 0)} />
                <Metric label="Failed" value={String(regression.summary?.failed ?? 0)} />
              </>
            ) : <Metric label="状态" value="未运行" />}
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="MKAOS Acceptance" icon={<BookOpenCheck size={18} />} />
          <button
            className="primaryButton"
            disabled={busy}
            onClick={() => runAction(async () => {
              const result = await runMinimalAcceptance();
              setAcceptance((result as any).acceptance ?? null);
              return result;
            }, "P0 最小验收样例已运行")}
          >
            运行验收
          </button>
          <div className="summaryBand">
            {acceptance ? Object.entries(acceptance).map(([key, value]) => (
              <Metric label={key} value={String(value)} key={key} />
            )) : <Metric label="状态" value="未运行" />}
          </div>
          <button
            className="secondaryButton"
            disabled={busy}
            onClick={() => runAction(async () => {
              const result = await runKnowledgeAssetOsAcceptance();
              setP1Acceptance(result as Record<string, any>);
              return result;
            }, "P1 Knowledge Asset OS 验收已运行")}
          >
            运行 P1 验收
          </button>
          {p1Acceptance ? (
            <div className="summaryBand">
              <Metric label="P1" value={String(Boolean(p1Acceptance.passed))} />
              <Metric label="Issues" value={String(p1Acceptance.validation_issue_count ?? 0)} />
              <Metric label="Regressions" value={String(p1Acceptance.regression_summary?.failed ?? 0)} />
            </div>
          ) : null}
        </div>
      </section>
    </FeatureShell>
  );
}

function GraphPreview({ graph }: { graph: Record<string, any> | null }) {
  const allNodes = Array.isArray(graph?.nodes) ? graph?.nodes : [];
  const allEdges = Array.isArray(graph?.edges) ? graph?.edges : [];
  const nodes = allNodes.slice(0, 10);
  const edges = allEdges.slice(0, 16);
  const nodeCoverage = graph?.summary?.coverage ?? {};
  const edgeCoverage = graph?.summary?.edge_relation_counts ?? {};
  if (!allNodes.length) {
    return <p className="mutedText">暂无图谱路径；刷新后会显示知识、学科、流程、规则和模板的 first-slice 可视化。</p>;
  }
  const positions = new Map<string, { x: number; y: number }>();
  nodes.forEach((node: any, index: number) => {
    const angle = (Math.PI * 2 * index) / Math.max(1, nodes.length);
    positions.set(String(node.id), { x: 160 + Math.cos(angle) * 118, y: 120 + Math.sin(angle) * 78 });
  });
  return (
    <div className="mkaosGraphExplorer">
      <div className="summaryBand">
        <Metric label="Graph Explorer" value={`${nodes.length}/${allNodes.length} nodes`} />
        <Metric label="Edges" value={`${edges.length}/${allEdges.length}`} />
        <Metric label="Knowledge" value={String(nodeCoverage.knowledge_card ?? 0)} />
        <Metric label="Relations" value={String(Object.keys(edgeCoverage).length)} />
      </div>
      <svg className="mkaosGraphCanvas" viewBox="0 0 320 240" role="img" aria-label="MKAOS knowledge graph preview">
        {edges.map((edge: any) => {
          const source = positions.get(String(edge.source));
          const target = positions.get(String(edge.target));
          if (!source || !target) return null;
          return <line key={edge.id || `${edge.source}-${edge.target}`} x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke="var(--line)" strokeWidth="1.2" />;
        })}
        {nodes.map((node: any) => {
          const position = positions.get(String(node.id)) ?? { x: 0, y: 0 };
          const type = String(node.node_type || "");
          const fill = type === "knowledge_card" ? "var(--accent)" : type === "discipline" ? "var(--ok-text)" : type === "flow" ? "var(--warn-text)" : "var(--muted)";
          return (
            <g key={node.id}>
              <circle cx={position.x} cy={position.y} r={type === "knowledge_card" ? 10 : 7} fill={fill} />
              <text x={position.x} y={position.y + 22} textAnchor="middle" fontSize="9" fill="var(--muted)">
                {String(node.label || node.id).slice(0, 12)}
              </text>
            </g>
          );
        })}
      </svg>
      <DataTable
        emptyText="暂无图谱分布"
        columns={["Node Type", "Count", "Edge Type", "Count"]}
        rows={Object.entries(nodeCoverage).slice(0, 6).map(([nodeType, count], index) => {
          const edge = Object.entries(edgeCoverage)[index] ?? ["-", "-"];
          return [nodeType, String(count), String(edge[0]), String(edge[1])];
        })}
      />
    </div>
  );
}
