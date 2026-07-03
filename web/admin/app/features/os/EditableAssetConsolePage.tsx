"use client";

import { CheckSquare, Database, Edit3, GitPullRequest, Layers, Plus, Save, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { AssetDetail, AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import { fetchJson } from "../../shared/api";
import { FeatureShell } from "../../shared/feature-shell";
import { createCreativeAsset, loadAssetDetail, saveAssetContent } from "../assets/api";
import { updateReviewIssueAssetStatus } from "./api";
import { compactJson, pathCell } from "./helpers";

export type EditableConsoleConfig = {
  title: string;
  subtitle: string;
  eyebrow?: string;
  assetTypes: string[];
  createTypes?: string[];
  primaryLinks?: Array<{ label: string; href: string }>;
  guidance?: string;
};

export function EditableAssetConsolePage({ config }: { config: EditableConsoleConfig }) {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [selectedPath, setSelectedPath] = useState("");
  const [detail, setDetail] = useState<AssetDetail | null>(null);
  const [draftContent, setDraftContent] = useState("{}");
  const [newTitle, setNewTitle] = useState("");
  const [newType, setNewType] = useState(config.createTypes?.[0] || config.assetTypes[0] || "");
  const [bulkStatus, setBulkStatus] = useState("acknowledged");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const typeSet = useMemo(() => new Set(config.assetTypes), [config.assetTypes]);
  const filteredAssets = assets.filter((asset) => typeSet.has(asset.type));
  const selectedProject = projects.find((project) => project.project_id === projectId);
  const blockingCount = filteredAssets.filter((asset) => ["critical", "high", "blocked"].includes(String(asset.risk_level || asset.status || asset.asset_status || "").toLowerCase())).length;
  const recentAssets = [...filteredAssets].sort((left, right) => String(right.updated_at || "").localeCompare(String(left.updated_at || ""))).slice(0, 8);
  const selectedType = detail?.summary.type || "";
  const parsedContent = useMemo(() => parseJsonObject(draftContent), [draftContent]);
  const domainFields = useMemo(() => domainFieldsFor(selectedType), [selectedType]);
  const reviewIssueRows = filteredAssets.filter((asset) => asset.type === "review_issue");

  async function refresh(nextProjectId = projectId) {
    const assetPath = nextProjectId
      ? `/product/projects/${encodeURIComponent(nextProjectId)}/assets?limit=500`
      : "/assets?limit=500&rank=path";
    const [projectRows, assetRows] = await Promise.all([
      fetchJson<ProjectRow[]>("/product/projects"),
      fetchJson<AssetRow[]>(assetPath)
    ]);
    setProjects(projectRows);
    setAssets(assetRows);
    const nextSelection = selectedPath && assetRows.some((asset) => asset.path === selectedPath && typeSet.has(asset.type))
      ? selectedPath
      : assetRows.find((asset) => typeSet.has(asset.type))?.path || "";
    setSelectedPath(nextSelection);
    if (nextSelection) {
      await selectAsset(nextSelection);
    } else {
      setDetail(null);
      setDraftContent("{}");
    }
  }

  async function selectAsset(path: string) {
    setSelectedPath(path);
    const nextDetail = await loadAssetDetail(path);
    setDetail(nextDetail);
    const content = nextDetail.asset.content;
    setDraftContent(JSON.stringify(isRecord(content) ? content : {}, null, 2));
  }

  async function runAction(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      await action();
      setNotice(message);
      await refresh(projectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  function updateDomainField(field: DomainField, value: string | boolean) {
    const next = { ...parsedContent };
    if (field.kind === "list") {
      next[field.key] = linesToArray(String(value));
    } else if (field.kind === "number") {
      next[field.key] = Number(value) || 0;
    } else if (field.kind === "checkbox") {
      next[field.key] = Boolean(value);
    } else if (field.kind === "json") {
      next[field.key] = parseJsonValue(String(value));
    } else {
      next[field.key] = String(value);
    }
    setDraftContent(JSON.stringify(next, null, 2));
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  return (
    <FeatureShell title={config.title} subtitle={config.subtitle} eyebrow={config.eyebrow || "Novel OS Console"}>
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Assets" value={String(filteredAssets.length)} />
        <Metric label="Types" value={String(config.assetTypes.length)} />
        <Metric label="Blocking" value={String(blockingCount)} />
        <Metric label="Selected" value={detail?.summary.type || "-"} />
        <Metric label="Project" value={selectedProject?.title || "全局"} />
      </section>

      <section className="panel">
        <PanelHeader title="Console Scope" icon={<Database size={18} />} />
        <div className="formGrid wide">
          <select value={projectId} onChange={(event) => { setProjectId(event.target.value); refresh(event.target.value).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught))); }}>
            <option value="">全部项目</option>
            {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
          </select>
          <select value={selectedPath} onChange={(event) => selectAsset(event.target.value).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>
            <option value="">选择资产</option>
            {filteredAssets.map((asset) => <option value={asset.path} key={asset.path}>{asset.type} · {asset.title}</option>)}
          </select>
          {config.primaryLinks?.map((link) => <a className="linkButton" href={link.href} key={link.href}>{link.label}</a>)}
        </div>
        {config.guidance ? <p className="mutedText">{config.guidance}</p> : null}
      </section>

      {config.createTypes?.length ? (
        <section className="panel">
          <PanelHeader title="Create Asset" icon={<Plus size={18} />} />
          <div className="formGrid wide">
            <select value={newType} onChange={(event) => setNewType(event.target.value)}>
              {config.createTypes.map((type) => <option value={type} key={type}>{type}</option>)}
            </select>
            <input value={newTitle} onChange={(event) => setNewTitle(event.target.value)} placeholder="title" />
            <button className="primaryButton" disabled={busy || !newTitle.trim()} onClick={() => runAction(() => createCreativeAsset(newType, newTitle.trim(), projectId, selectedProject?.path), "资产已创建")}>
              <Plus size={16} />Create
            </button>
          </div>
        </section>
      ) : null}

      {domainFields.length ? (
        <section className="panel">
          <PanelHeader title="Domain Governance Editor" icon={<ShieldCheck size={18} />} />
          <div className="formGrid wide">
            {domainFields.map((field) => (
              <label className={field.kind === "textarea" || field.kind === "json" || field.kind === "list" ? "typedField wide" : "typedField"} key={field.key}>
                <span>{field.label}</span>
                {field.kind === "textarea" ? (
                  <textarea rows={field.rows || 3} value={String(parsedContent[field.key] || "")} onChange={(event) => updateDomainField(field, event.target.value)} />
                ) : field.kind === "json" ? (
                  <textarea rows={field.rows || 6} value={JSON.stringify(parsedContent[field.key] ?? field.defaultValue ?? {}, null, 2)} onChange={(event) => updateDomainField(field, event.target.value)} />
                ) : field.kind === "list" ? (
                  <textarea rows={field.rows || 3} value={arrayToLines(parsedContent[field.key])} onChange={(event) => updateDomainField(field, event.target.value)} />
                ) : field.kind === "checkbox" ? (
                  <select value={Boolean(parsedContent[field.key]) ? "true" : "false"} onChange={(event) => updateDomainField(field, event.target.value === "true")}>
                    <option value="true">true</option>
                    <option value="false">false</option>
                  </select>
                ) : (
                  <input type={field.kind === "number" ? "number" : "text"} value={String(parsedContent[field.key] ?? "")} onChange={(event) => updateDomainField(field, event.target.value)} />
                )}
              </label>
            ))}
          </div>
          <div className="buttonRow">
            <button className="primaryButton" disabled={busy || !selectedPath} onClick={() => runAction(() => saveAssetContent(selectedPath, parsedContent), "领域表单已保存")}>
              <Save size={16} />Save Domain Form
            </button>
          </div>
        </section>
      ) : null}

      {reviewIssueRows.length ? (
        <section className="panel">
          <PanelHeader title="Bulk Governance Tools" icon={<CheckSquare size={18} />} />
          <div className="formGrid wide">
            <select value={bulkStatus} onChange={(event) => setBulkStatus(event.target.value)}>
              <option value="acknowledged">acknowledged</option>
              <option value="in_revision">in_revision</option>
              <option value="resolved">resolved</option>
              <option value="waived">waived</option>
            </select>
            <button
              className="secondaryButton"
              disabled={busy || !reviewIssueRows.length}
              onClick={() => runAction(() => Promise.all(reviewIssueRows.slice(0, 50).map((asset) => updateReviewIssueAssetStatus(asset.path, bulkStatus, "bulk governance console"))), `已批量更新 ${Math.min(reviewIssueRows.length, 50)} 个 ReviewIssue`)}
            >
              <CheckSquare size={16} />Apply to Visible Issues
            </button>
            <button className="secondaryButton" disabled={busy || !reviewIssueRows.length} onClick={() => selectAsset(reviewIssueRows[0]?.path || selectedPath).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}>
              <Layers size={16} />Focus First Issue
            </button>
          </div>
        </section>
      ) : null}

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Asset List" icon={<GitPullRequest size={18} />} />
          <DataTable
            emptyText="暂无匹配资产"
            columns={["Type", "Title", "状态", "Updated", "Path"]}
            rows={filteredAssets.slice(0, 120).map((asset) => [
              asset.type,
              <button className="linkButton" onClick={() => selectAsset(asset.path).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))} key={`${asset.path}-select`}>{asset.title}</button>,
              <span className={statusClass(String(asset.status || asset.asset_status || asset.risk_level || ""))} key={`${asset.path}-status`}>{String(asset.status || asset.asset_status || asset.risk_level || "-")}</span>,
              asset.updated_at || "-",
              pathCell(asset.path, asset.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Recent Evidence" icon={<Database size={18} />} />
          <DataTable
            emptyText="暂无近期资产"
            columns={["Type", "Title", "Risk", "Path"]}
            rows={recentAssets.map((asset) => [
              asset.type,
              asset.title,
              String(asset.risk_level || asset.asset_status || "-"),
              pathCell(asset.path, `${asset.path}-recent`)
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Editable Content" icon={<Edit3 size={18} />} />
          <textarea className="editorArea" rows={22} value={draftContent} onChange={(event) => setDraftContent(event.target.value)} />
          <div className="buttonRow">
            <button className="primaryButton" disabled={busy || !selectedPath} onClick={() => runAction(() => saveAssetContent(selectedPath, JSON.parse(draftContent) as Record<string, unknown>), "资产内容已保存")}>
              <Save size={16} />Save Content
            </button>
          </div>
        </div>
        <div className="panel">
          <PanelHeader title="Asset Detail" icon={<Database size={18} />} />
          <pre className="jsonPreview">{compactJson(detail?.summary || {}, 1600)}</pre>
          <PanelHeader title="Lineage" icon={<GitPullRequest size={18} />} />
          <pre className="jsonPreview">{compactJson(detail?.lineage || {}, 1600)}</pre>
        </div>
      </section>
    </FeatureShell>
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

type DomainField = {
  key: string;
  label: string;
  kind?: "text" | "textarea" | "number" | "list" | "json" | "checkbox";
  rows?: number;
  defaultValue?: unknown;
};

function domainFieldsFor(type: string): DomainField[] {
  const fields: Record<string, DomainField[]> = {
    canon_database: [
      { key: "canon_id", label: "Canon ID" },
      { key: "entities", label: "Entities", kind: "json", rows: 10, defaultValue: [] },
      { key: "rules", label: "Rules / WorldRule", kind: "json", rows: 6, defaultValue: {} }
    ],
    character_state_ledger: [
      { key: "ledger_id", label: "Ledger ID" },
      { key: "chapter_no", label: "Chapter", kind: "number" },
      { key: "characters", label: "Characters / Debt Ledger", kind: "json", rows: 10, defaultValue: [] },
      { key: "debt_policy", label: "Debt Policy", kind: "json", rows: 5, defaultValue: {} }
    ],
    arc_plan: [
      { key: "arc_id", label: "Arc ID" },
      { key: "title", label: "Title" },
      { key: "chapter_range", label: "Chapter Range" },
      { key: "arc_question", label: "Arc Question", kind: "textarea", rows: 3 },
      { key: "protagonist_goal", label: "Protagonist Goal", kind: "textarea", rows: 3 },
      { key: "villain_goal", label: "Villain Goal", kind: "textarea", rows: 3 },
      { key: "required_payoffs", label: "Required Payoffs", kind: "list", rows: 4 },
      { key: "forbidden_expansion", label: "Forbidden Expansion", kind: "list", rows: 4 }
    ],
    foreshadowing_graph: [
      { key: "graph_id", label: "Graph ID" },
      { key: "chapter_no", label: "Chapter", kind: "number" },
      { key: "clues", label: "Clues", kind: "json", rows: 10, defaultValue: [] },
      { key: "edges", label: "Edges", kind: "json", rows: 5, defaultValue: [] },
      { key: "status", label: "Status" }
    ],
    review_issue: [
      { key: "issue_type", label: "Issue Type" },
      { key: "severity", label: "Severity" },
      { key: "blocking", label: "Blocking", kind: "checkbox" },
      { key: "status", label: "Status" },
      { key: "message", label: "Message", kind: "textarea", rows: 4 },
      { key: "fix_suggestion", label: "Fix Suggestion", kind: "textarea", rows: 4 },
      { key: "evidence_refs", label: "Evidence Refs", kind: "list", rows: 4 }
    ]
  };
  return fields[type] || [];
}

function parseJsonObject(value: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value);
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function parseJsonValue(value: string): unknown {
  try {
    return JSON.parse(value);
  } catch {
    return value;
  }
}

function linesToArray(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean);
}

function arrayToLines(value: unknown): string {
  return Array.isArray(value) ? value.map((item) => String(item)).join("\n") : "";
}
