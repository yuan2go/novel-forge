"use client";

import { BookOpenCheck, Database, FileText, GitPullRequest, ListChecks, ShieldAlert, ShieldCheck, Workflow } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  buildKnowledgePack,
  createKnowledgeCard,
  createUsageBinding,
  importMkaosSource,
  loadMkaosOverview,
  loadPackPreview,
  patchKnowledge,
  patchUsageBinding,
  runMinimalAcceptance,
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
  const [acceptance, setAcceptance] = useState<Record<string, boolean> | null>(null);
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
                setPackPreview(preview.preview);
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
          <PanelHeader title="P0 验收样例" icon={<BookOpenCheck size={18} />} />
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
        </div>
      </section>
    </FeatureShell>
  );
}
