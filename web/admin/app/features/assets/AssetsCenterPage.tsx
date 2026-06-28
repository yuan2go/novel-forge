"use client";

import { BookOpen, Database, Edit3, Library, Network, Search, ShieldCheck, Target } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetDetail, AssetGraph, AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { createCreativeAsset, loadAssetDetail, loadAssetGraph, loadAssetsData, saveAssetContent, type CreativeLibrary } from "./api";

const assetTypes = [
  "platform_profile",
  "genre_market_profile",
  "topic_fit_report",
  "material_card",
  "knowledge_card",
  "character_card",
  "world_bible",
  "continuity_bible",
  "foreshadowing_thread",
  "chapter_plan",
  "review_report",
  "style_profile",
  "quality_standard_profile",
  "writing_template",
  "craft_template",
  "review_rule_pack"
];

export function AssetsCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [libraries, setLibraries] = useState<CreativeLibrary[]>([]);
  const [projectId, setProjectId] = useState("");
  const [keyword, setKeyword] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [detail, setDetail] = useState<AssetDetail | null>(null);
  const [graph, setGraph] = useState<AssetGraph | null>(null);
  const [draftContent, setDraftContent] = useState("{}");
  const [newType, setNewType] = useState(assetTypes[0]);
  const [newTitle, setNewTitle] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const selectedProject = projects.find((project) => project.project_id === projectId);
  const topicAssets = assetsForLibrary(libraries, "topic_library");
  const materialAssets = assetsForLibrary(libraries, "material_library");
  const knowledgeAssets = assetsForLibrary(libraries, "knowledge_library");
  const bibleAssets = assetsForLibrary(libraries, "setting_bible");
  const topicAverage = averageScore(topicAssets);
  const materialRiskCount = materialAssets.filter((asset) => ["high", "blocked"].includes(String(asset.risk_level || "").toLowerCase())).length;
  const knowledgeTags = topTags(knowledgeAssets);
  const materialTags = topTags(materialAssets);
  const bibleTypeCounts = countBy(bibleAssets, (asset) => asset.type);
  const openForeshadowingCount = bibleAssets.filter((asset) => asset.type === "foreshadowing_thread" && !["paid_off", "closed", "completed"].includes(String(asset.content?.status ?? "").toLowerCase())).length;
  const typedContent = parseDraftContent(draftContent);
  const typedFields = detail ? typedEditorFields(detail.summary.type) : [];
  const graphBounds = useMemo(() => {
    const nodes = graph?.nodes ?? [];
    const width = Math.max(520, ...nodes.map((node) => Number(node.layout?.x ?? 0) + 230));
    const height = Math.max(240, ...nodes.map((node) => Number(node.layout?.y ?? 0) + 110));
    return { width, height };
  }, [graph]);
  const byType = useMemo(() => {
    return assets.reduce<Record<string, number>>((counts, asset) => {
      counts[asset.type] = (counts[asset.type] ?? 0) + 1;
      return counts;
    }, {});
  }, [assets]);

  async function refresh(nextProjectId = projectId, nextKeyword = keyword) {
    const [projectRows, assetRows, libraryRows] = await loadAssetsData(nextProjectId, nextKeyword);
    const selected = nextProjectId || projectRows[0]?.project_id || "";
    setProjects(projectRows);
    setProjectId(selected);
    setAssets(assetRows);
    setLibraries(libraryRows);
    setSelectedPath((current) => current || assetRows[0]?.path || "");
  }

  async function selectAsset(path: string) {
    setSelectedPath(path);
    setError("");
    try {
      const nextDetail = await loadAssetDetail(path);
      const nextGraph = await loadAssetGraph(path, 2);
      setDetail(nextDetail);
      setGraph(nextGraph);
      setDraftContent(JSON.stringify(nextDetail.asset.content ?? {}, null, 2));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
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

  function updateTypedField(field: string, value: unknown) {
    const nextContent = { ...parseDraftContent(draftContent), [field]: value };
    setDraftContent(JSON.stringify(nextContent, null, 2));
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  useEffect(() => {
    if (selectedPath) {
      selectAsset(selectedPath);
    }
  }, [selectedPath]);

  return (
    <FeatureShell title="创作资产工作台" subtitle="题材库、素材库、知识库、设定书、文风、写作模板和精品标准统一进入 schema-backed 资产工作台。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="资产总数" value={String(assets.length)} />
        <Metric label="知识卡" value={String(byType.knowledge_card ?? 0)} />
        <Metric label="素材卡" value={String(byType.material_card ?? 0)} />
        <Metric label="标准/文风" value={String((byType.quality_standard_profile ?? 0) + (byType.style_profile ?? 0))} />
      </section>

      <section className="assetDomainGrid">
        <div className="panel domainPanel">
          <PanelHeader title="题材策略" icon={<Target size={18} />} />
          <div className="summaryBand">
            <Metric label="平台/题材资产" value={String(topicAssets.length)} />
            <Metric label="平均评分" value={String(topicAverage || "-")} />
            <Metric label="题材报告" value={String(topicAssets.filter((asset) => asset.type === "topic_fit_report").length)} />
          </div>
          <DataTable
            emptyText="暂无题材资产"
            columns={["资产", "类型", "评分", "风险"]}
            rows={topicAssets.slice(0, 6).map((asset) => [
              <button className="linkButton" key={asset.path} onClick={() => setSelectedPath(asset.path)}>{asset.title || asset.id}</button>,
              asset.type,
              String(numericScore(asset) || "-"),
              asset.risk_level || "-"
            ])}
          />
        </div>

        <div className="panel domainPanel">
          <PanelHeader title="素材运营" icon={<Library size={18} />} />
          <div className="summaryBand">
            <Metric label="素材/模板" value={String(materialAssets.length)} />
            <Metric label="高风险" value={String(materialRiskCount)} />
            <Metric label="分类标签" value={String(materialTags.length)} />
          </div>
          <div className="tagCloud">
            {materialTags.map(([tag, count]) => <span className="badge muted" key={tag}>{tag} {count}</span>)}
          </div>
          <DataTable
            emptyText="暂无素材"
            columns={["素材", "类型", "状态", "关系"]}
            rows={materialAssets.slice(0, 5).map((asset) => [
              <button className="linkButton" key={asset.path} onClick={() => setSelectedPath(asset.path)}>{asset.title || asset.id}</button>,
              asset.type,
              asset.status || asset.asset_status || "-",
              asset.tags?.slice(0, 3).join(", ") || "-"
            ])}
          />
        </div>

        <div className="panel domainPanel">
          <PanelHeader title="知识治理" icon={<Database size={18} />} />
          <div className="summaryBand">
            <Metric label="知识卡" value={String(knowledgeAssets.length)} />
            <Metric label="可信资产" value={String(knowledgeAssets.filter((asset) => credibility(asset) !== "unknown").length)} />
            <Metric label="分类" value={String(knowledgeTags.length)} />
          </div>
          <div className="tagCloud">
            {knowledgeTags.map(([tag, count]) => <span className="badge muted" key={tag}>{tag} {count}</span>)}
          </div>
          <DataTable
            emptyText="暂无知识卡"
            columns={["知识", "可信度", "来源", "过期提示"]}
            rows={knowledgeAssets.slice(0, 5).map((asset) => [
              <button className="linkButton" key={asset.path} onClick={() => setSelectedPath(asset.path)}>{asset.title || asset.id}</button>,
              credibility(asset),
              asset.source || "-",
              staleHint(asset)
            ])}
          />
        </div>

        <div className="panel domainPanel">
          <PanelHeader title="设定书连续性" icon={<BookOpen size={18} />} />
          <div className="summaryBand">
            <Metric label="人物" value={String(bibleTypeCounts.character_card ?? 0)} />
            <Metric label="世界/连续性" value={String((bibleTypeCounts.world_bible ?? 0) + (bibleTypeCounts.continuity_bible ?? 0))} />
            <Metric label="未回收伏笔" value={String(openForeshadowingCount)} />
          </div>
          <DataTable
            emptyText="暂无设定资产"
            columns={["设定", "类型", "状态", "业务字段"]}
            rows={bibleAssets.slice(0, 6).map((asset) => [
              <button className="linkButton" key={asset.path} onClick={() => setSelectedPath(asset.path)}>{asset.title || asset.id}</button>,
              asset.type,
              asset.status || asset.asset_status || String(asset.content?.status ?? "-"),
              bibleBusinessHint(asset)
            ])}
          />
          <a className="secondaryButton" href="/impact"><ShieldCheck size={16} />打开变更影响分析</a>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="筛选与创建" icon={<Search size={18} />} />
          <div className="formGrid">
            <label className="selectWrap">
              <span>项目</span>
              <select value={projectId} onChange={(event) => refresh(event.target.value)}>
                <option value="">全局</option>
                {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
              </select>
            </label>
            <label className="selectWrap">
              <span>关键词</span>
              <input value={keyword} onChange={(event) => setKeyword(event.target.value)} onBlur={() => refresh(projectId, keyword)} />
            </label>
            <button className="secondaryButton" onClick={() => refresh(projectId, keyword)} disabled={busy}>搜索</button>
          </div>
          <div className="formGrid">
            <select value={newType} onChange={(event) => setNewType(event.target.value)}>
              {assetTypes.map((type) => <option value={type} key={type}>{type}</option>)}
            </select>
            <input placeholder="资产标题" value={newTitle} onChange={(event) => setNewTitle(event.target.value)} />
            <button className="primaryButton" disabled={busy || !newTitle.trim()} onClick={() => runAction(() => createCreativeAsset(newType, newTitle.trim(), projectId, selectedProject?.path), "资产已创建")}>创建</button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="资产库分布" icon={<Library size={18} />} />
          <DataTable
            emptyText="暂无资产库"
            columns={["资产库", "类型", "数量"]}
            rows={libraries.map((library) => [
              library.title,
              library.asset_types.join(", "),
              String(library.assets.length)
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="资产列表" icon={<Database size={18} />} />
          <DataTable
            emptyText="暂无资产"
            columns={["类型", "标题", "状态", "风险", "路径"]}
            rows={assets.map((asset) => [
              asset.type,
              <button className="linkButton" key={asset.path} onClick={() => setSelectedPath(asset.path)}>{asset.title || asset.id}</button>,
              <span className={statusClass(asset.asset_status || "")} key={`${asset.path}-status`}>{asset.asset_status || "-"}</span>,
              asset.risk_level || "-",
              <span className="pathText" key={`${asset.path}-path`}>{asset.path}</span>
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="深度编辑" icon={<Edit3 size={18} />} />
          {detail ? (
            <>
              <div className="summaryBand">
                <Metric label="类型" value={detail.summary.type} />
                <Metric label="标题" value={detail.summary.title || detail.summary.id} />
                <Metric label="风险" value={detail.summary.risk_level || "-"} />
              </div>
              {typedFields.length ? (
                <div className="typedEditorGrid">
                  {typedFields.map((field) => (
                    <label className={field.kind === "textarea" || field.kind === "list" ? "typedField wide" : "typedField"} key={field.key}>
                      <span>{field.label}</span>
                      {field.kind === "textarea" ? (
                        <textarea
                          rows={field.rows ?? 5}
                          value={String(typedContent[field.key] ?? "")}
                          onChange={(event) => updateTypedField(field.key, event.target.value)}
                        />
                      ) : field.kind === "number" ? (
                        <input
                          type="number"
                          value={Number(typedContent[field.key] ?? field.defaultValue ?? 0)}
                          onChange={(event) => updateTypedField(field.key, Number(event.target.value || 0))}
                        />
                      ) : field.kind === "list" ? (
                        <textarea
                          rows={field.rows ?? 4}
                          value={listToText(typedContent[field.key])}
                          onChange={(event) => updateTypedField(field.key, textToList(event.target.value))}
                        />
                      ) : (
                        <input
                          value={String(typedContent[field.key] ?? "")}
                          onChange={(event) => updateTypedField(field.key, event.target.value)}
                        />
                      )}
                    </label>
                  ))}
                </div>
              ) : null}
              <textarea value={draftContent} onChange={(event) => setDraftContent(event.target.value)} rows={18} />
              <button
                className="primaryButton"
                disabled={busy}
                onClick={() => runAction(() => saveAssetContent(detail.path, JSON.parse(draftContent) as Record<string, unknown>), "资产内容已保存")}
              >
                保存内容
              </button>
            </>
          ) : (
            <p className="muted">选择资产后可编辑 schema content。</p>
          )}
        </div>
      </section>
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="引用图谱" icon={<Network size={18} />} />
          {graph ? (
            <>
              <div className="assetGraphCanvas layered" style={{ minWidth: graphBounds.width, minHeight: graphBounds.height }}>
                {graph.nodes.map((node) => (
                  <div
                    className={node.id === graph.start_id ? "graphNode active" : "graphNode"}
                    key={node.id}
                    style={{ left: Number(node.layout?.x ?? 0), top: Number(node.layout?.y ?? 0) }}
                  >
                    <strong>{node.title || node.id}</strong>
                    <span>{node.type}</span>
                    <span>level {String(node.layout?.level ?? "-")}</span>
                    <small>{node.path}</small>
                  </div>
                ))}
              </div>
              <DataTable
                emptyText="暂无引用边"
                columns={["来源", "关系", "目标"]}
                rows={graph.edges.map((edge, index) => [
                  <span className="pathText" key={`${index}-source`}>{edge.source}</span>,
                  edge.relation,
                  <span className="pathText" key={`${index}-target`}>{edge.target}</span>
                ])}
              />
            </>
          ) : (
            <p className="muted">选择资产后显示引用图谱。</p>
          )}
        </div>
        <div className="panel">
          <PanelHeader title="影响提示" icon={<Network size={18} />} />
          <p className="muted">引用图谱展示直接和二级上下游关系；需要正式变更前，进入“变更影响分析中心”生成可保存的影响报告。</p>
          <DataTable
            emptyText="暂无引用节点"
            columns={["类型", "标题", "路径"]}
            rows={(graph?.nodes ?? []).map((node) => [
              node.type,
              node.title || node.id,
              <span className="pathText" key={node.path}>{node.path}</span>
            ])}
          />
        </div>
      </section>
    </FeatureShell>
  );
}

type TypedEditorField = {
  key: string;
  label: string;
  kind?: "text" | "textarea" | "list" | "number";
  rows?: number;
  defaultValue?: number;
};

function assetsForLibrary(libraries: CreativeLibrary[], key: string) {
  return libraries.find((library) => library.key === key)?.assets ?? [];
}

function numericScore(asset: { score?: number; content?: Record<string, unknown>; metadata?: Record<string, unknown> }) {
  const value = asset.score ?? asset.content?.score ?? asset.content?.fit_score ?? asset.content?.quality_score ?? asset.metadata?.score;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? Math.round(numberValue) : 0;
}

function averageScore(assets: Array<{ score?: number; content?: Record<string, unknown>; metadata?: Record<string, unknown> }>) {
  const scores = assets.map(numericScore).filter((score) => score > 0);
  if (!scores.length) return 0;
  return Math.round(scores.reduce((sum, score) => sum + score, 0) / scores.length);
}

function topTags(assets: Array<{ tags?: string[] }>) {
  const counts: Record<string, number> = {};
  for (const asset of assets) {
    for (const tag of asset.tags ?? []) {
      counts[tag] = (counts[tag] ?? 0) + 1;
    }
  }
  return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 8);
}

function countBy<T>(items: T[], keyFn: (item: T) => string) {
  return items.reduce<Record<string, number>>((counts, item) => {
    const key = keyFn(item);
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {});
}

function credibility(asset: { content?: Record<string, unknown>; metadata?: Record<string, unknown> }) {
  return String(asset.content?.credibility || asset.metadata?.credibility || asset.metadata?.license_review_status || "unknown");
}

function staleHint(asset: { updated_at?: string }) {
  if (!asset.updated_at) return "unknown";
  const updated = Date.parse(asset.updated_at);
  if (!Number.isFinite(updated)) return "unknown";
  const days = Math.floor((Date.now() - updated) / 86_400_000);
  if (days > 180) return "stale";
  if (days > 90) return "review";
  return "fresh";
}

function bibleBusinessHint(asset: { type: string; content?: Record<string, unknown> }) {
  if (asset.type === "character_card") {
    return [asset.content?.role, asset.content?.current_state, asset.content?.power_level].filter(Boolean).join(" / ") || "-";
  }
  if (asset.type === "foreshadowing_thread") {
    return [asset.content?.status, asset.content?.payoff_plan].filter(Boolean).join(" / ") || "-";
  }
  if (asset.type === "power_scale_rule") {
    return String(asset.content?.scale_name || asset.content?.rule_id || "-");
  }
  if (asset.type === "continuity_bible") {
    return `timeline ${Array.isArray(asset.content?.timeline) ? asset.content.timeline.length : 0}`;
  }
  return Array.isArray(asset.content?.constraints) ? `constraints ${asset.content.constraints.length}` : "-";
}

const TYPE_EDITOR_FIELDS: Record<string, TypedEditorField[]> = {
  platform_profile: [
    { key: "platform_id", label: "平台 ID" },
    { key: "platform_name", label: "平台名" },
    { key: "business_model", label: "商业模式" },
    { key: "reader_expectation", label: "读者期待", kind: "list" },
    { key: "update_frequency", label: "更新频率" },
    { key: "review_risks", label: "审核风险", kind: "list" },
    { key: "style_tendency", label: "文风倾向", kind: "list" }
  ],
  genre_market_profile: [
    { key: "genre", label: "题材" },
    { key: "platform_id", label: "适配平台" },
    { key: "reader_promise", label: "读者承诺", kind: "textarea", rows: 3 },
    { key: "common_hooks", label: "常见钩子", kind: "list" },
    { key: "fatigue_points", label: "疲劳点", kind: "list" },
    { key: "differentiation_axes", label: "差异化轴", kind: "list" },
    { key: "chapter_rhythm_template", label: "章节节奏模板", kind: "textarea", rows: 3 }
  ],
  topic_fit_report: [
    { key: "topic", label: "选题" },
    { key: "platform_fit_score", label: "平台适配分", kind: "number", defaultValue: 0 },
    { key: "reader_promise_score", label: "读者承诺分", kind: "number", defaultValue: 0 },
    { key: "differentiation_score", label: "差异化分", kind: "number", defaultValue: 0 },
    { key: "risks", label: "风险", kind: "list" },
    { key: "next_actions", label: "下一步", kind: "list" }
  ],
  material_card: [
    { key: "material_type", label: "素材类型" },
    { key: "category", label: "分类" },
    { key: "reuse_scope", label: "复用范围" },
    { key: "rating", label: "评分", kind: "number", defaultValue: 0 },
    { key: "copyright_risk", label: "版权风险" },
    { key: "abstract_pattern", label: "抽象结构", kind: "textarea", rows: 4 },
    { key: "related_assets", label: "关联资产", kind: "list" }
  ],
  knowledge_card: [
    { key: "discipline", label: "学科" },
    { key: "concept", label: "概念" },
    { key: "credibility", label: "可信度" },
    { key: "source_policy", label: "来源策略" },
    { key: "allowed_pipeline", label: "允许流程", kind: "list" },
    { key: "fictionalization_notes", label: "小说化说明", kind: "textarea", rows: 4 },
    { key: "review_warnings", label: "审稿提醒", kind: "list" }
  ],
  character_card: [
    { key: "name", label: "人物名" },
    { key: "role", label: "角色定位" },
    { key: "external_goal", label: "外在目标", kind: "textarea", rows: 3 },
    { key: "internal_need", label: "内在需求", kind: "textarea", rows: 3 },
    { key: "current_state", label: "当前状态" },
    { key: "current_location", label: "当前位置" },
    { key: "power_level", label: "战力/等级" },
    { key: "relationships", label: "关系网", kind: "list" },
    { key: "arc", label: "成长曲线", kind: "textarea", rows: 4 }
  ],
  world_bible: [
    { key: "worldview_rules", label: "世界规则", kind: "list" },
    { key: "locations", label: "地点体系", kind: "list" },
    { key: "organizations", label: "组织势力", kind: "list" },
    { key: "power_system", label: "力量体系", kind: "textarea", rows: 4 },
    { key: "constraints", label: "不可违背设定", kind: "list" }
  ],
  continuity_bible: [
    { key: "timeline", label: "时间线", kind: "list" },
    { key: "entities", label: "Canon 实体", kind: "list" },
    { key: "open_threads", label: "未回收伏笔", kind: "list" },
    { key: "constraints", label: "连续性约束", kind: "list" }
  ],
  foreshadowing_thread: [
    { key: "thread_id", label: "伏笔 ID" },
    { key: "status", label: "状态 planned/seeded/developing/paid_off" },
    { key: "setup", label: "埋设方式", kind: "textarea", rows: 3 },
    { key: "payoff_plan", label: "回收计划", kind: "textarea", rows: 3 },
    { key: "related_chapters", label: "相关章节", kind: "list" }
  ],
  chapter_plan: [
    { key: "chapter", label: "章节号", kind: "number", defaultValue: 1 },
    { key: "objective", label: "章节目标", kind: "textarea", rows: 3 },
    { key: "beats", label: "节拍", kind: "list" },
    { key: "information_points", label: "信息点", kind: "list" },
    { key: "hook", label: "章末钩子", kind: "textarea", rows: 3 },
    { key: "word_budget", label: "字数预算", kind: "number", defaultValue: 2500 },
    { key: "feedback_constraints", label: "读者反馈约束", kind: "list" }
  ],
  review_report: [
    { key: "score", label: "总分", kind: "number", defaultValue: 0 },
    { key: "strengths", label: "优点", kind: "list" },
    { key: "issues", label: "问题清单", kind: "list" },
    { key: "revision_suggestions", label: "修订建议", kind: "list" },
    { key: "gate_decision", label: "门禁结论" }
  ],
  writing_template: [
    { key: "template_id", label: "模板 ID" },
    { key: "use_case", label: "使用场景" },
    { key: "structure", label: "结构", kind: "textarea", rows: 5 },
    { key: "constraints", label: "约束", kind: "list" },
    { key: "examples", label: "抽象示例", kind: "list" }
  ],
  craft_template: [
    { key: "template_id", label: "模板 ID" },
    { key: "craft_type", label: "技法类型" },
    { key: "steps", label: "步骤", kind: "list" },
    { key: "anti_patterns", label: "反模式", kind: "list" },
    { key: "review_checks", label: "审稿检查项", kind: "list" }
  ],
  review_rule_pack: [
    { key: "rule_pack_id", label: "规则包 ID" },
    { key: "dimensions", label: "评分维度", kind: "textarea", rows: 5 },
    { key: "blocking_rules", label: "阻断规则", kind: "list" },
    { key: "manual_gate_rules", label: "人工确认规则", kind: "list" }
  ]
};

function typedEditorFields(assetType: string) {
  return TYPE_EDITOR_FIELDS[assetType] ?? [];
}

function parseDraftContent(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function listToText(value: unknown) {
  if (Array.isArray(value)) {
    return value.map((item) => typeof item === "string" ? item : JSON.stringify(item)).join("\n");
  }
  return typeof value === "string" ? value : "";
}

function textToList(value: string) {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}
