"use client";

import { BookOpenCheck, BrainCircuit, CheckCircle2, GitBranch, ListChecks, Send, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AssetRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  createPublishGate,
  calibrateLongformExtraction,
  loadLongformStabilityData,
  runLongformAcceptance,
  runLongformExtraction,
  upsertLongformControlAsset,
  type LongformControlAssetPayload,
  type LongformStabilityDashboard
} from "./api";
import { assetOptions, compactJson, pathCell, selectedWorkspace } from "./helpers";

export function LongformStabilityPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [assets, setAssets] = useState<AssetRow[]>([]);
  const [dashboard, setDashboard] = useState<LongformStabilityDashboard | null>(null);
  const [projectId, setProjectId] = useState("");
  const [draftPath, setDraftPath] = useState("");
  const [useModel, setUseModel] = useState(true);
  const [controlAssetType, setControlAssetType] = useState<LongformControlAssetPayload["asset_type"]>("canon_database");
  const [controlAssetTitle, setControlAssetTitle] = useState("");
  const [controlAssetJson, setControlAssetJson] = useState("{\n  \"entities\": []\n}");
  const [calibrationExpectedJson, setCalibrationExpectedJson] = useState("{\n  \"characters\": [],\n  \"organizations\": [],\n  \"locations\": [],\n  \"clues\": [],\n  \"motifs\": []\n}");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [actionResult, setActionResult] = useState<Record<string, unknown> | null>(null);

  async function refresh(nextProjectId = projectId) {
    const [projectRows, assetRows, dashboardData] = await loadLongformStabilityData(nextProjectId);
    setProjects(projectRows);
    setAssets(assetRows);
    setDashboard(dashboardData);
    const resolvedProject = nextProjectId || projectRows[0]?.project_id || "";
    setProjectId(resolvedProject);
    setDraftPath((current) => current || assetRows.find((asset) => ["draft_chapter", "draft_version"].includes(asset.type))?.path || "");
  }

  async function runAction(action: () => Promise<Record<string, unknown>>, message: string) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action();
      setActionResult(result);
      setNotice(message);
      await refresh(projectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function submitControlAsset() {
    const content = parseJsonObject(controlAssetJson, "control asset JSON");
    return upsertLongformControlAsset({
      asset_type: controlAssetType,
      title: controlAssetTitle,
      project_id: projectId || undefined,
      workspace_path: workspacePath || undefined,
      content
    });
  }

  async function submitCalibration() {
    const expected = parseJsonObject(calibrationExpectedJson, "expected extraction JSON");
    return calibrateLongformExtraction(draftPath, workspacePath, expected, useModel, true);
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const workspacePath = selectedWorkspace(projects, projectId);
  const drafts = assetOptions(assets, ["draft_chapter", "draft_version"]);
  const summary = dashboard?.summary || {};
  const acceptance = dashboard?.acceptance;
  const arc = dashboard?.arc_visualization;
  const lanes = arc?.lanes || [];
  const chapters = dashboard?.chapters || [];
  const latestAssets = Object.values(dashboard?.latest_assets || {});

  return (
    <FeatureShell title="Longform Stability Console" subtitle="正典、章节状态、结构去重、卷级推进、模型辅助抽取和 OS 级验收的长篇稳定性总控页。" eyebrow="OS Runtime">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Drafts" value={String(summary.draft_count ?? 0)} />
        <Metric label="Chapter States" value={String(summary.chapter_state_count ?? 0)} />
        <Metric label="Acceptance" value={String(summary.acceptance_status ?? "-")} />
        <Metric label="Score" value={String(summary.acceptance_score ?? 0)} />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Extraction Controls" icon={<BrainCircuit size={18} />} />
          <div className="formGrid wide longformControls">
            <select value={projectId} onChange={(event) => refresh(event.target.value)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={draftPath} onChange={(event) => setDraftPath(event.target.value)}>
              <option value="">选择 Draft</option>
              {drafts.map((draft) => <option value={draft.path} key={draft.path}>{draft.type}: {draft.title}</option>)}
            </select>
            <label className="checkboxLine">
              <input type="checkbox" checked={useModel} onChange={(event) => setUseModel(event.target.checked)} />
              Model assisted
            </label>
            <button className="primaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => runLongformExtraction(draftPath, workspacePath, useModel), "longform extraction 已运行")}>
              <BrainCircuit size={16} />Extract
            </button>
            <button className="secondaryButton" disabled={busy || !projectId} onClick={() => runAction(() => runLongformAcceptance(projectId, workspacePath, true), "OS acceptance gate 已持久化")}>
              <ShieldCheck size={16} />Acceptance
            </button>
            <button className="primaryButton" disabled={busy || !draftPath} onClick={() => runAction(() => createPublishGate(draftPath, workspacePath), "publish gate 已运行")}>
              <Send size={16} />Publish Gate
            </button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="Gate Summary" icon={<CheckCircle2 size={18} />} />
          <div className="summaryBand">
            <Metric label="Canon DB" value={String(summary.canon_database_count ?? 0)} />
            <Metric label="Arc Plans" value={String(summary.arc_plan_count ?? 0)} />
            <Metric label="Gate Fails" value={String(summary.publish_gate_failure_count ?? 0)} />
            <Metric label="Revision Tasks" value={String(summary.revision_task_count ?? 0)} />
          </div>
          <pre className="jsonPreview">{compactJson(actionResult || acceptance?.summary || {}, 1800)}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Editable OS Control Assets" icon={<ShieldCheck size={18} />} />
          <div className="formGrid wide longformControls">
            <select
              value={controlAssetType}
              onChange={(event) => {
                const nextType = event.target.value as LongformControlAssetPayload["asset_type"];
                setControlAssetType(nextType);
                setControlAssetJson(defaultControlAssetJson(nextType));
              }}
            >
              <option value="canon_database">Canon Database</option>
              <option value="arc_plan">Arc Planner</option>
              <option value="foreshadowing_graph">Foreshadowing Graph</option>
              <option value="character_state_ledger">Character State / Debt Ledger</option>
              <option value="villain_operation_plan">Villain Operation Model</option>
            </select>
            <input value={controlAssetTitle} onChange={(event) => setControlAssetTitle(event.target.value)} placeholder="控制资产标题，可选" />
            <textarea rows={10} value={controlAssetJson} onChange={(event) => setControlAssetJson(event.target.value)} />
            <button className="primaryButton" disabled={busy} onClick={() => runAction(submitControlAsset, "OS control asset 已写入")}>
              <ShieldCheck size={16} />Save Control Asset
            </button>
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="Extraction Calibration" icon={<BrainCircuit size={18} />} />
          <div className="formGrid wide longformControls">
            <textarea rows={10} value={calibrationExpectedJson} onChange={(event) => setCalibrationExpectedJson(event.target.value)} />
            <button className="secondaryButton" disabled={busy || !draftPath} onClick={() => runAction(submitCalibration, "extraction calibration 已记录")}>
              <BrainCircuit size={16} />Calibrate Draft
            </button>
          </div>
          <p className="mutedText">Calibration records confidence, precision/recall and evidence spans as a semantic extraction regression asset.</p>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Arc Visualization" icon={<GitBranch size={18} />} />
        <div className="longformArcHeader">
          <strong>{arc?.title || "No active arc"}</strong>
          <span>{arc?.chapter_range || "-"}</span>
          <span>{String(arc?.nodes?.length ?? 0)} nodes / {String(arc?.edges?.length ?? 0)} edges</span>
        </div>
        <div className="longformArcLane" role="list">
          {lanes.map((lane) => (
            <div className={`longformArcNode ${arcNodeClass(lane)}`} role="listitem" key={String(lane.chapter_no)}>
              <strong>Ch {String(lane.chapter_no)}</strong>
              <span>state {String(lane.state || "-")}</span>
              <span>pattern {String(lane.pattern || "-")}</span>
              <span>motif {String(lane.motif || "-")}</span>
              <span>{String(lane.villain || "no visible agent")}</span>
            </div>
          ))}
          {!lanes.length ? <div className="emptyCell">暂无卷级章节证据</div> : null}
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Chapter Stability" icon={<BookOpenCheck size={18} />} />
          <DataTable
            emptyText="暂无章节稳定性证据"
            columns={["章节", "State", "Pattern", "Motif", "Villain", "Gate", "证据"]}
            rows={chapters.slice(0, 80).map((chapter) => [
              String(chapter.chapter_no ?? "-"),
              chapter.chapter_state_path ? <span className="badge ok" key={`state-${String(chapter.chapter_no)}`}>present</span> : <span className="badge warn" key={`state-${String(chapter.chapter_no)}`}>missing</span>,
              <span className={statusClass(String(chapter.pattern_status || ""))} key={`pattern-${String(chapter.chapter_no)}`}>{String(chapter.pattern_status || "-")}</span>,
              <span className={statusClass(String(chapter.motif_status || ""))} key={`motif-${String(chapter.chapter_no)}`}>{String(chapter.motif_status || "-")}</span>,
              String(chapter.visible_agent || "-"),
              <span className={statusClass(String(chapter.publish_decision || ""))} key={`gate-${String(chapter.chapter_no)}`}>{String(chapter.publish_decision || "-")}</span>,
              pathCell(String(chapter.chapter_state_path || chapter.pattern_path || chapter.draft_path || ""), `evidence-${String(chapter.chapter_no)}`)
            ])}
          />
        </div>

        <div className="panel">
          <PanelHeader title="Acceptance Checks" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 OS acceptance checks"
            columns={["Check", "状态", "Blocking", "建议"]}
            rows={(acceptance?.checks || []).map((check) => [
              String(check.key || "-"),
              <span className={statusClass(String(check.status || ""))} key={`${String(check.key)}-status`}>{String(check.status || "-")}</span>,
              check.blocking ? "yes" : "no",
              String(check.recommendation || check.message || "-")
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Latest Longform Assets" icon={<BookOpenCheck size={18} />} />
          <DataTable
            emptyText="暂无长篇稳定性资产"
            columns={["类型", "标题", "状态", "章节", "路径"]}
            rows={latestAssets.map((asset) => [
              String(asset.type || "-"),
              String(asset.title || "-"),
              <span className={statusClass(String(asset.status || asset.decision || ""))} key={`${String(asset.path)}-status`}>{String(asset.status || asset.decision || "-")}</span>,
              String(asset.chapter || "-"),
              pathCell(String(asset.path || "-"), String(asset.path || "-"))
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Evidence JSON" icon={<ShieldCheck size={18} />} />
          <pre className="jsonPreview">{JSON.stringify({ actionResult, acceptance, counts_by_type: dashboard?.counts_by_type }, null, 2)}</pre>
        </div>
      </section>
    </FeatureShell>
  );
}

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON object`);
  }
  return parsed as Record<string, unknown>;
}

function defaultControlAssetJson(assetType: LongformControlAssetPayload["asset_type"]): string {
  const defaults: Record<LongformControlAssetPayload["asset_type"], Record<string, unknown>> = {
    canon_database: {
      entities: [
        {
          entity_id: "azhao",
          entity_type: "character",
          canonical_name: "阿照",
          aliases: [],
          forbidden_aliases: ["江砚", "沈砚"],
          role: "protagonist",
          status: "active"
        }
      ]
    },
    arc_plan: {
      arc_id: "arc_01",
      title: "长篇稳定性测试卷",
      chapter_range: "1-12",
      arc_question: "本卷必须回答的阶段问题",
      protagonist_goal: "推进主线而非扩张线索",
      required_payoffs: [],
      forbidden_expansion: []
    },
    foreshadowing_graph: {
      clues: [
        {
          clue_id: "clue_01",
          name: "待校准伏笔",
          source_chapter: 1,
          target_truth: "卷级真相",
          planned_payoff_chapter: 10,
          status: "active"
        }
      ],
      edges: []
    },
    character_state_ledger: {
      characters: [
        {
          character_id: "azhao",
          authority: "夜档司巡遗人",
          reputation: {},
          active_burdens: [],
          risks: [],
          debt_ledger: { inherited_total: 100, cleared: 0, remaining: 100, new_liabilities: [] }
        }
      ]
    },
    villain_operation_plan: {
      arc_id: "arc_01",
      visible_agent: "稳定反派代理人",
      public_identity: "公开身份",
      hidden_goal: "卷级反派目标",
      signatures: [],
      current_wins: [],
      operations: []
    }
  };
  return JSON.stringify(defaults[assetType], null, 2);
}

function arcNodeClass(lane: Record<string, unknown>): string {
  if (String(lane.gate || "") === "blocked") return "warn";
  if (String(lane.state || "") === "missing") return "warn";
  if (String(lane.pattern || "") === "block" || String(lane.motif || "") === "block") return "warn";
  return "ok";
}
