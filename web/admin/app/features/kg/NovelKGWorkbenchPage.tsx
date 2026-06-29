"use client";

import { GitBranch, Network, RefreshCw, Route, Search, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  createIdentityResolution,
  createSemanticExtraction,
  createNovelKGSnapshot,
  loadNovelKGCypher,
  loadNovelKGData,
  loadNovelKGImpact,
  loadNovelKGPath,
  refreshNovelKG,
  runNovelKGGate,
  type NovelKGGraph,
  type NovelKGNode
} from "./api";

const emptyGraph: NovelKGGraph = {
  ontology_version: "",
  entities: [],
  events: [],
  rules: [],
  timelines: [],
  foreshadowing: [],
  factions: [],
  locations: [],
  props: [],
  power_scales: [],
  review_rules: [],
  templates: [],
  relations: []
};

export function NovelKGWorkbenchPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [graph, setGraph] = useState<NovelKGGraph>(emptyGraph);
  const [conflicts, setConflicts] = useState<Record<string, unknown>>({ conflicts: [], count: 0, blocking_count: 0, recommendation: "-" });
  const [dirty, setDirty] = useState<Record<string, unknown>>({});
  const [targetPath, setTargetPath] = useState("");
  const [sourceNode, setSourceNode] = useState("");
  const [targetNode, setTargetNode] = useState("");
  const [query, setQuery] = useState("人物 世界观 伏笔");
  const [pathResult, setPathResult] = useState<Record<string, unknown> | null>(null);
  const [impactResult, setImpactResult] = useState<Record<string, unknown> | null>(null);
  const [gateResult, setGateResult] = useState<Record<string, unknown> | null>(null);
  const [semanticResult, setSemanticResult] = useState<Record<string, unknown> | null>(null);
  const [identityResult, setIdentityResult] = useState<Record<string, unknown> | null>(null);
  const [cypher, setCypher] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const nodes = useMemo(() => allNodes(graph), [graph]);
  const timeline = [...(graph.timelines || []), ...(graph.events || [])].slice(0, 36);
  const foreshadowing = graph.foreshadowing || [];
  const conflictRows = (conflicts.conflicts as Array<Record<string, unknown>> | undefined) || [];

  async function refresh(nextProjectId = projectId) {
    const [projectRows, kgGraph, conflictResult, dirtyResult, assetRows] = await loadNovelKGData(nextProjectId);
    setProjects(projectRows);
    setGraph(kgGraph);
    setConflicts(conflictResult as unknown as Record<string, unknown>);
    setDirty(dirtyResult);
    setAssets(assetRows);
    const resolvedProject = nextProjectId || projectRows[0]?.project_id || "";
    setProjectId(resolvedProject);
    setTargetPath((current) => current || assetRows[0]?.path || "");
    setSourceNode((current) => current || kgGraph.entities[0]?.name || kgGraph.factions[0]?.name || "");
    setTargetNode((current) => current || kgGraph.factions[0]?.name || kgGraph.locations[0]?.name || "");
  }

  async function runAction(action: () => Promise<unknown>, message: string, reload = true) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action();
      setNotice(message);
      if (reload) await refresh(projectId);
      return result;
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
    <FeatureShell title="Novel Knowledge Graph" subtitle="统一查看实体、关系、时间线、伏笔、规则、模板和 KG 门禁证据。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="Ontology" value={graph.ontology_version || "-"} />
        <Metric label="节点" value={String(nodes.length)} />
        <Metric label="关系" value={String(graph.relations?.length ?? 0)} />
        <Metric label="冲突" value={String(conflicts.count ?? 0)} />
        <Metric label="Dirty" value={dirty.dirty ? "yes" : "no"} />
        <Metric label="平均置信度" value={String(graph.summary?.confidence?.average ?? "-")} />
      </section>

      <section className="panel">
        <PanelHeader title="操作台" icon={<RefreshCw size={18} />} />
        <div className="formGrid wide">
          <select value={projectId} onChange={(event) => refresh(event.target.value)}>
            <option value="">全局</option>
            {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
          </select>
          <select value={targetPath} onChange={(event) => setTargetPath(event.target.value)}>
            <option value="">选择目标资产</option>
            {assets.map((asset) => <option value={asset.path} key={asset.path}>{asset.type}: {asset.title}</option>)}
          </select>
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="KG 查询词" />
          <button className="primaryButton" disabled={busy} onClick={() => runAction(() => createNovelKGSnapshot(projectId, selectedProject?.path), "KG snapshot 已创建")}>创建 Snapshot</button>
          <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => refreshNovelKG(projectId, selectedProject?.path, targetPath), "KG 已刷新")}>刷新 Dirty</button>
          <button className="secondaryButton" disabled={busy} onClick={() => runAction(async () => setGateResult(await runNovelKGGate(targetPath, projectId, selectedProject?.path)), "KG gate 已运行", false)}>KG Gate</button>
          <button className="secondaryButton" disabled={busy} onClick={() => runAction(async () => setSemanticResult(await createSemanticExtraction(targetPath, projectId, selectedProject?.path)), "语义抽取报告已创建", false)}>语义抽取</button>
          <button className="secondaryButton" disabled={busy} onClick={() => runAction(async () => setIdentityResult(await createIdentityResolution(undefined, projectId, selectedProject?.path)), "Identity merge queue 已创建", false)}>别名归并队列</button>
          <button className="secondaryButton" disabled={busy} onClick={() => runAction(async () => setCypher(await loadNovelKGCypher(query)), "Cypher 已生成", false)}>Cypher</button>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="关系网络" icon={<Network size={18} />} />
          <div className="assetGraphCanvas">
            {nodes.slice(0, 30).map((node) => (
              <button className="graphNode" key={node.id} onClick={() => setSourceNode(node.name)}>
                <strong>{node.name}</strong>
                <span>{node.kind} / {node.entity_type || "-"}</span>
                <small>{Math.round((node.confidence ?? 0) * 100)}% · {(node.aliases || []).slice(0, 2).join(", ")}</small>
              </button>
            ))}
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="路径与影响" icon={<Route size={18} />} />
          <div className="formGrid">
            <input value={sourceNode} onChange={(event) => setSourceNode(event.target.value)} placeholder="source node/name" />
            <input value={targetNode} onChange={(event) => setTargetNode(event.target.value)} placeholder="target node/name" />
            <button className="secondaryButton" disabled={busy || !sourceNode || !targetNode} onClick={() => runAction(async () => setPathResult(await loadNovelKGPath(sourceNode, targetNode, projectId)), "路径查询完成", false)}>查路径</button>
            <button className="secondaryButton" disabled={busy || !sourceNode} onClick={() => runAction(async () => setImpactResult(await loadNovelKGImpact(sourceNode, projectId)), "影响查询完成", false)}>查影响</button>
          </div>
          <DataTable
            emptyText="暂无路径结果"
            columns={["Depth", "节点链"]}
            rows={((pathResult?.paths as Array<Record<string, unknown>> | undefined) || []).map((path, index) => [
              String(path.depth ?? index),
              <span className="pathText" key={`path-${index}`}>{((path.node_ids as string[] | undefined) || []).join(" -> ")}</span>
            ])}
          />
          <DataTable
            emptyText="暂无影响结果"
            columns={["节点", "类型", "Depth", "原因"]}
            rows={((impactResult?.impacted_nodes as Array<Record<string, unknown>> | undefined) || []).slice(0, 12).map((node) => [
              String(node.name || node.id || "-"),
              String(node.kind || "-"),
              String(node.depth ?? "-"),
              String(node.impact_reason || "-")
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="时间线" icon={<GitBranch size={18} />} />
          <DataTable
            emptyText="暂无时间线"
            columns={["名称", "类型", "来源", "置信度"]}
            rows={timeline.map((node) => [
              node.name,
              node.entity_type || node.kind,
              <span className="pathText" key={`${node.id}-source`}>{node.source_path || "-"}</span>,
              String(Math.round((node.confidence ?? 0) * 100))
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="伏笔生命周期" icon={<GitBranch size={18} />} />
          <DataTable
            emptyText="暂无伏笔"
            columns={["伏笔", "状态", "来源", "证据"]}
            rows={foreshadowing.map((node) => [
              node.name,
              node.entity_type || "-",
              <span className="pathText" key={`${node.id}-source`}>{node.source_path || "-"}</span>,
              node.evidence_spans?.[0]?.snippet || "-"
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="门禁与冲突" icon={<ShieldCheck size={18} />} />
          <div className="summaryBand">
            <Metric label="Gate" value={String(gateResult?.status ?? "-")} />
            <Metric label="Semantic Report" value={String((semanticResult?.asset as Record<string, unknown> | undefined)?.content ? "created" : "-")} />
            <Metric label="Merge Queue" value={String((((identityResult?.asset as Record<string, unknown> | undefined)?.content as Record<string, unknown> | undefined)?.summary as Record<string, unknown> | undefined)?.human_gate_count ?? "-")} />
            <Metric label="建议" value={String(gateResult?.recommendation ?? conflicts.recommendation ?? "-")} />
            <Metric label="Blocking" value={String(conflicts.blocking_count ?? 0)} />
          </div>
          <DataTable
            emptyText="暂无冲突"
            columns={["严重度", "类型", "说明", "建议"]}
            rows={conflictRows.slice(0, 12).map((conflict, index) => [
              <span className={statusClass(String(conflict.severity || ""))} key={`${index}-severity`}>{String(conflict.severity || "-")}</span>,
              String(conflict.conflict_type || "-"),
              String(conflict.message || "-"),
              String(conflict.recommendation || "-")
            ])}
          />
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Cypher Preview" icon={<Search size={18} />} />
        <textarea className="contextPreview" readOnly rows={5} value={String(cypher?.cypher || "运行 Cypher 生成后显示查询语句。")} />
        <p className="previewText">{cypher ? JSON.stringify(cypher.params || {}) : "Neo4j 仍是可选投影；此处生成可审查的参数化 Cypher。"}</p>
      </section>
    </FeatureShell>
  );
}

function allNodes(graph: NovelKGGraph): NovelKGNode[] {
  return [
    ...graph.entities,
    ...graph.factions,
    ...graph.locations,
    ...graph.props,
    ...graph.power_scales,
    ...graph.foreshadowing,
    ...graph.events,
    ...graph.rules,
    ...graph.review_rules,
    ...graph.templates
  ];
}
