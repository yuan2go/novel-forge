"use client";

import { Activity, ListChecks, Play, RotateCcw, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { AgentEventRow, AgentRunRow, ProjectRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  dispatchAgentTaskFromIssue,
  dispatchAgentRun,
  createAgentDag,
  loadAgentCenterSnapshot,
  loadAgentDispatchData,
  recoverAgentDispatch,
  repairDeadLetterDispatch,
  rehearseAgentRollback,
  runAgentSchedulerTick,
  type AgentCenterSnapshot
} from "./api";
import { compactJson, pathCell, splitLines } from "./helpers";

const queueStatuses = ["", "queued", "claimed", "retry_scheduled", "waiting_human", "dead_letter", "acked"];

export function AgentDispatchCenterPage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [agentRuns, setAgentRuns] = useState<AgentRunRow[]>([]);
  const [agentEvents, setAgentEvents] = useState<AgentEventRow[]>([]);
  const [schedulerStatus, setSchedulerStatus] = useState<Record<string, unknown>>({});
  const [queue, setQueue] = useState<Array<Record<string, unknown>>>([]);
  const [contracts, setContracts] = useState<Array<Record<string, unknown>>>([]);
  const [agentCenter, setAgentCenter] = useState<AgentCenterSnapshot | null>(null);
  const [projectId, setProjectId] = useState("");
  const [status, setStatus] = useState("");
  const [agentRunPath, setAgentRunPath] = useState("");
  const [workflowRunId, setWorkflowRunId] = useState("");
  const [workflowNodeId, setWorkflowNodeId] = useState("");
  const [expectedOutputs, setExpectedOutputs] = useState("");
  const [reviewIssuePath, setReviewIssuePath] = useState("");
  const [schedulerResult, setSchedulerResult] = useState<Record<string, unknown> | null>(null);
  const [dispatchResult, setDispatchResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [governanceRepairQueuePath, setGovernanceRepairQueuePath] = useState("");
  const [governanceRepairNote, setGovernanceRepairNote] = useState("");
  const [governanceRepairConfirmed, setGovernanceRepairConfirmed] = useState(false);

  async function refresh(nextProjectId = projectId, nextStatus = status) {
    const [[projectRows, runRows, eventRows, schedulerState, queueRows, contractRows], centerSnapshot] = await Promise.all([
      loadAgentDispatchData(nextProjectId, nextStatus),
      loadAgentCenterSnapshot(nextProjectId)
    ]);
    setProjects(projectRows);
    setAgentRuns(runRows);
    setAgentEvents(eventRows);
    setSchedulerStatus(schedulerState);
    setQueue(queueRows);
    setContracts(contractRows.contracts || []);
    setAgentCenter(centerSnapshot);
    const resolvedProject = nextProjectId || projectRows[0]?.project_id || "";
    setProjectId(resolvedProject);
    setAgentRunPath((current) => current || runRows.find((run) => run.status === "prepared")?.path || runRows[0]?.path || "");
  }

  async function runAction(action: () => Promise<Record<string, unknown>>, message: string, setResult?: (result: Record<string, unknown>) => void) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await action();
      setResult?.(result);
      setNotice(message);
      await refresh(projectId, status);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const lease = (schedulerStatus.lease as Record<string, unknown> | undefined) || {};
  const byStatus = (schedulerStatus.by_status as Record<string, unknown> | undefined) || {};
  const preparedRuns = agentRuns.filter((run) => ["prepared", "waiting_human", "failed", "dead_letter"].includes(run.status));
  const failedQueue = queue.filter((row) => ["dead_letter", "waiting_human", "retry_scheduled"].includes(String(row.status || "")));
  const runGraphNodes = ((agentCenter?.run_graph as Record<string, unknown> | undefined)?.nodes as Array<Record<string, unknown>> | undefined) || [];
  const runGraphEdges = ((agentCenter?.run_graph as Record<string, unknown> | undefined)?.edges as Array<Record<string, unknown>> | undefined) || [];
  const agentTasks = agentCenter?.agent_tasks || [];
  const loopRuns = agentCenter?.loop_runs || [];
  const contextBundles = agentCenter?.context_bundles || [];
  const reviewIssues = agentCenter?.review_issues || [];
  const revisionTasks = agentCenter?.revision_tasks || [];
  const runtimeLinks = agentCenter?.runtime_links || {};
  const operationCoverageFull = (agentCenter?.operation_coverage_full || {}) as Record<string, unknown>;
  const hardStopDashboard = (agentCenter?.hard_stop_dashboard || {}) as Record<string, unknown>;
  const rollbackRehearsals = agentCenter?.rollback_rehearsals || [];
  const deadLetterRepairs = agentCenter?.dead_letter_repairs || [];
  const governanceDeadLetters = agentCenter?.governance_dead_letters || [];
  const governanceDeadLetterPaths = new Set(governanceDeadLetters.map((row) => String(row.queue_path || "")));
  const repairableDeadLetter = failedQueue.find((row) => String(row.status || "") === "dead_letter" && !governanceDeadLetterPaths.has(String(row.path || "")));
  const selectedGovernanceDeadLetter = governanceDeadLetters.find((row) => String(row.queue_path || "") === governanceRepairQueuePath);
  const selectedGovernanceGatePaths = Array.isArray(selectedGovernanceDeadLetter?.failed_gate_paths) ? selectedGovernanceDeadLetter.failed_gate_paths.map((item) => String(item)) : [];
  const selectedGovernanceCheckpointPaths = Array.isArray(selectedGovernanceDeadLetter?.failed_checkpoint_paths) ? selectedGovernanceDeadLetter.failed_checkpoint_paths.map((item) => String(item)) : [];
  const governanceRepairReady = Boolean(selectedGovernanceDeadLetter && governanceRepairConfirmed);
  const agentDags = agentCenter?.agent_dags || [];
  const coverageOps = ((operationCoverageFull.operations as Array<Record<string, unknown>> | undefined) || []);
  const hardStopSummary = (hardStopDashboard.summary || {}) as Record<string, unknown>;

  async function submitGovernanceDeadLetterRepair() {
    if (!selectedGovernanceDeadLetter) {
      throw new Error("Select a governance dead-letter before repair.");
    }
    const result = await repairDeadLetterDispatch(governanceRepairQueuePath, {
      reason: "os agent center reviewed governance dead-letter repair",
      confirm_governance_review: true,
      reviewed_failed_gate_paths: selectedGovernanceGatePaths,
      reviewed_failed_checkpoint_paths: selectedGovernanceCheckpointPaths,
      governance_review_note: governanceRepairNote || "operator reviewed failed gates and checkpoints in Agent Center UI"
    });
    setGovernanceRepairConfirmed(false);
    return result;
  }

  return (
    <FeatureShell title="Agent Dispatch Center" subtitle="让 prepared AgentRun 进入 queue，由 scheduler lease/claim/retry/recover 执行，并留下 checkpoint、gate、budget 和 trace 证据。" eyebrow="OS Runtime">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Runs" value={String(agentRuns.length)} />
        <Metric label="Queue" value={String(queue.length)} />
        <Metric label="Queued" value={String(byStatus.queued ?? 0)} />
        <Metric label="Acked" value={String(byStatus.acked ?? 0)} />
        <Metric label="Waiting" value={String(byStatus.waiting_human ?? 0)} />
        <Metric label="Lease" value={String(lease.status ?? "missing")} />
        <Metric label="Agent Tasks" value={String(agentTasks.length)} />
        <Metric label="Health" value={String(agentCenter?.health_score ?? 0)} />
        <Metric label="Center" value={String(agentCenter?.agent_center_version || "v1")} />
        <Metric label="Gov DL" value={String(agentCenter?.summary?.governance_dead_letter_count ?? governanceDeadLetters.length)} />
      </section>

      <section className="panel">
        <PanelHeader title="Agent Center v2 Control" icon={<ShieldCheck size={18} />} />
        <div className="studioActions">
          <button className="primaryButton" disabled={busy} onClick={() => runAction(() => createAgentDag(projectId), "Agent DAG 已创建", setDispatchResult)}><ListChecks size={16} />Create Review DAG</button>
          <button className="secondaryButton" disabled={busy || !failedQueue[0]?.path} onClick={() => runAction(() => rehearseAgentRollback(String(failedQueue[0]?.path || "")), "Rollback rehearsal 已生成", setDispatchResult)}>Rollback Rehearsal</button>
          <button className="secondaryButton" disabled={busy || !repairableDeadLetter?.path} onClick={() => runAction(() => repairDeadLetterDispatch(String(repairableDeadLetter?.path || "")), "Dead-letter repair 已执行", setDispatchResult)}>Repair Dead Letter</button>
        </div>
        <div className="summaryBand">
          <Metric label="Hard-stop" value={String(hardStopSummary.provider_status || hardStopDashboard.status || "-")} />
          <Metric label="Fail Closed" value={hardStopSummary.fail_closed === false ? "no" : "yes"} />
          <Metric label="Silent Fallback" value={hardStopSummary.silent_fallback_allowed === true ? "allowed" : "blocked"} />
          <Metric label="Full Coverage" value={String((operationCoverageFull.summary as Record<string, unknown> | undefined)?.registered_count ?? 0)} />
          <Metric label="DAGs" value={String(agentDags.length)} />
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Autonomy Readiness" icon={<ShieldCheck size={18} />} />
        <DataTable
          emptyText="暂无 Agent Center readiness evidence"
          columns={["Capability", "状态", "Evidence", "Fix"]}
          rows={(agentCenter?.readiness_checks || []).map((check) => [
            String(check.key || check.name || "-"),
            <span className={statusClass(String(check.status || ""))} key={`${String(check.key)}-status`}>{String(check.status || "-")}</span>,
            String(check.evidence || check.message || "-"),
            String(check.required_fix || check.recommendation || "-")
          ])}
        />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Scheduler Control" icon={<Activity size={18} />} />
          <div className="formGrid wide">
            <select value={projectId} onChange={(event) => refresh(event.target.value, status)}>
              <option value="">全局</option>
              {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
            </select>
            <select value={status} onChange={(event) => { setStatus(event.target.value); refresh(projectId, event.target.value).catch((caught) => setError(caught instanceof Error ? caught.message : String(caught))); }}>
              {queueStatuses.map((item) => <option value={item} key={item}>{item || "全部状态"}</option>)}
            </select>
            <button className="primaryButton" disabled={busy} onClick={() => runAction(() => runAgentSchedulerTick(projectId, 1), "Agent scheduler tick 已完成", setSchedulerResult)}><Play size={16} />Scheduler Tick</button>
            <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => runAgentSchedulerTick(projectId, 5), "Agent scheduler loop 已完成", setSchedulerResult)}><RotateCcw size={16} />Loop x5</button>
          </div>
          <div className="summaryBand">
            <Metric label="Owner" value={String(lease.owner ?? "-")} />
            <Metric label="Last Tick" value={String(schedulerStatus.last_tick ?? "-")} />
            <Metric label="Contracts" value={String(contracts.length)} />
            <Metric label="Recoverable" value={String(failedQueue.length)} />
          </div>
        </div>

        <div className="panel">
          <PanelHeader title="Manual Dispatch" icon={<ListChecks size={18} />} />
          <div className="formGrid">
            <select value={agentRunPath} onChange={(event) => setAgentRunPath(event.target.value)}>
              <option value="">选择 AgentRun</option>
              {preparedRuns.map((run) => <option value={run.path} key={run.path}>{run.status} · {run.agent_type} · {run.operation}</option>)}
            </select>
            <input value={workflowRunId} onChange={(event) => setWorkflowRunId(event.target.value)} placeholder="workflow_run_id，可选" />
            <input value={workflowNodeId} onChange={(event) => setWorkflowNodeId(event.target.value)} placeholder="workflow_node_id，可选" />
            <textarea rows={3} value={expectedOutputs} onChange={(event) => setExpectedOutputs(event.target.value)} placeholder="expected output assets，每行一个，可选" />
            <button
              className="primaryButton"
              disabled={busy || !agentRunPath}
              onClick={() => runAction(
                () => dispatchAgentRun({
                  agent_run_path: agentRunPath,
                  workflow_run_id: workflowRunId,
                  workflow_node_id: workflowNodeId,
                  expected_output_assets: splitLines(expectedOutputs)
                }),
                "AgentRun 已派发",
                setDispatchResult
              )}
            >
              <Play size={16} />Dispatch
            </button>
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Run Graph" icon={<Activity size={18} />} />
        <div className="assetGraphCanvas layered">
          {runGraphNodes.slice(0, 42).map((node) => (
            <button className="graphNode" key={String(node.id || node.path)} onClick={() => setAgentRunPath(String(node.path || agentRunPath))}>
              <strong>{String(node.operation || node.agent_type || node.id || "-")}</strong>
              <span>{String(node.status || "-")} / {String(node.duration_ms ?? "-")}ms</span>
              <small>{String(node.path || node.id || "-")}</small>
            </button>
          ))}
          {!runGraphNodes.length ? <div className="emptyCell">暂无 run graph 节点</div> : null}
        </div>
        <div className="pillRow">
          <span className="badge">nodes {runGraphNodes.length}</span>
          <span className="badge">edges {runGraphEdges.length}</span>
          <span className="badge">budget {String((agentCenter?.budget_burn || {}).total_cost ?? 0)}</span>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Agent Tasks" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 AgentTask"
            columns={["Agent", "Operation", "状态", "Run", "Issue", "RevisionTask"]}
            rows={agentTasks.slice(0, 60).map((row) => [
              String(row.agent_type || "-"),
              String(row.operation || "-"),
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-task-status`}>{String(row.status || "-")}</span>,
              pathCell(String(row.agent_run_path || "-"), `${String(row.path)}-task-run`),
              pathCell(String(row.linked_review_issue_path || "-"), `${String(row.path)}-task-issue`),
              pathCell(String(row.linked_revision_task_path || "-"), `${String(row.path)}-task-revision`)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Runtime Links" icon={<Activity size={18} />} />
          <pre className="jsonPreview">{compactJson(runtimeLinks, 1800)}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Loop / Context" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 LoopRun / ContextBundle"
            columns={["Loop", "状态", "Stop", "Context", "Budget"]}
            rows={loopRuns.slice(0, 40).map((row) => [
              String(row.loop_type || row.operation || "-"),
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-loop-status`}>{String(row.status || "-")}</span>,
              String(row.stop_condition || "-"),
              pathCell(String(row.context_bundle_path || "-"), `${String(row.path)}-loop-context`),
              compactJson(row.budget_used || {}, 100)
            ])}
          />
          <DataTable
            emptyText="暂无 ContextBundle"
            columns={["Bundle", "Task", "Target", "Token", "MKAOS"]}
            rows={contextBundles.slice(0, 20).map((row) => [
              pathCell(String(row.path || "-"), `${String(row.path)}-context`),
              String(row.task_type || "-"),
              `${String(row.target_asset_type || "-")} / ${String(row.target_asset_id || "-")}`,
              String(row.token_estimate ?? "-"),
              String(row.mkaos_pack_id || "-")
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Review Issues / Revision Tasks" icon={<ShieldCheck size={18} />} />
          <div className="formGrid">
            <input value={reviewIssuePath} onChange={(event) => setReviewIssuePath(event.target.value)} placeholder="review_issue path or issue_id" />
            <button className="primaryButton" disabled={busy || !reviewIssuePath} onClick={() => runAction(() => dispatchAgentTaskFromIssue(reviewIssuePath), "ReviewIssue 已派发为 AgentTask", setDispatchResult)}>
              <Play size={16} />Dispatch Issue
            </button>
          </div>
          <DataTable
            emptyText="暂无 ReviewIssue"
            columns={["类型", "严重级别", "Blocking", "Target", "Action"]}
            rows={reviewIssues.slice(0, 50).map((row) => [
              String(row.issue_type || "-"),
              <span className={statusClass(String(row.severity || ""))} key={`${String(row.path)}-issue-severity`}>{String(row.severity || "-")}</span>,
              String(row.blocking ?? false),
              String(row.target_asset_id || "-"),
              row.path ? (
                <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => dispatchAgentTaskFromIssue(String(row.path || "")), "ReviewIssue 已派发为 AgentTask", setDispatchResult)} key={`${String(row.path)}-dispatch-issue`}>
                  Dispatch
                </button>
              ) : "-"
            ])}
          />
          <DataTable
            emptyText="暂无 RevisionTask"
            columns={["Task", "Stage", "Issues", "Draft", "Path"]}
            rows={revisionTasks.slice(0, 30).map((row) => [
              String(row.task_id || "-"),
              String(row.stage || row.status || "-"),
              String(row.issue_count ?? 0),
              pathCell(String(row.source_draft_path || "-"), `${String(row.path)}-revision-draft`),
              pathCell(String(row.path || "-"), `${String(row.path)}-revision-path`)
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Gate Timeline" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 gate timeline"
            columns={["Gate", "状态", "Target", "Trace"]}
            rows={(agentCenter?.gate_timeline || []).slice(0, 60).map((row) => [
              String(row.gate_kind || row.kind || "-"),
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-gate-status`}>{String(row.status || "-")}</span>,
              String(row.target || row.target_paths || "-"),
              String(row.trace_id || "-")
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Checkpoint List" icon={<ShieldCheck size={18} />} />
          <DataTable
            emptyText="暂无 checkpoint"
            columns={["Stage", "Operation", "状态", "Path"]}
            rows={(agentCenter?.checkpoints || []).slice(0, 60).map((row) => [
              String(row.stage || "-"),
              String(row.operation || "-"),
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-checkpoint-status`}>{String(row.status || "-")}</span>,
              pathCell(String(row.path || "-"), `${String(row.path)}-checkpoint`)
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Budget Burn" icon={<Activity size={18} />} />
          <pre className="jsonPreview">{compactJson(agentCenter?.budget_burn || {}, 1600)}</pre>
        </div>
        <div className="panel">
          <PanelHeader title="Retry Controls" icon={<RotateCcw size={18} />} />
          <DataTable
            emptyText="暂无可恢复队列项"
            columns={["状态", "Operation", "Attempt", "Action"]}
            rows={(agentCenter?.retry_controls || []).slice(0, 50).map((row) => [
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-retry-status`}>{String(row.status || "-")}</span>,
              String(row.operation || "-"),
              `${String(row.attempt_count ?? 0)}/${String(row.max_attempts ?? 0)}`,
              governanceDeadLetterPaths.has(String(row.path || "")) ? (
                <span className="badge warn" key={`${String(row.path)}-retry-governance-review-required`}>Review required</span>
              ) : row.path ? (
                <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => recoverAgentDispatch(String(row.path || "")), "Dispatch 已恢复", setDispatchResult)} key={`${String(row.path)}-retry`}>
                  Recover
                </button>
              ) : "-"
            ])}
          />
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Governance Dead-letter Review" icon={<ShieldCheck size={18} />} />
        <DataTable
          emptyText="暂无治理 dead-letter"
          columns={["Operation", "失败证据", "Repair precondition", "Queue", "Payload"]}
          rows={governanceDeadLetters.slice(0, 50).map((row) => {
            const repair = (row.repair || {}) as Record<string, unknown>;
            const failedGateCount = Array.isArray(row.failed_gate_paths) ? row.failed_gate_paths.length : 0;
            const failedCheckpointCount = Array.isArray(row.failed_checkpoint_paths) ? row.failed_checkpoint_paths.length : 0;
            return [
              String(row.operation || "-"),
              `gates ${failedGateCount} / checkpoints ${failedCheckpointCount}`,
              String(repair.precondition || "inspect failed gates and checkpoints before retry"),
              pathCell(String(row.queue_path || "-"), `${String(row.queue_path)}-governance-dead-letter`),
              row.queue_path ? (
                <button
                  className="secondaryButton"
                  disabled={busy}
                  onClick={() => {
                    setGovernanceRepairQueuePath(String(row.queue_path || ""));
                    setGovernanceRepairNote("");
                    setGovernanceRepairConfirmed(false);
                  }}
                  key={`${String(row.queue_path)}-select-governance-payload`}
                >
                  Build reviewed payload
                </button>
              ) : "-"
            ];
          })}
        />
        <div className="formGrid wide">
          <select
            value={governanceRepairQueuePath}
            onChange={(event) => {
              setGovernanceRepairQueuePath(event.target.value);
              setGovernanceRepairConfirmed(false);
            }}
          >
            <option value="">选择治理 dead-letter</option>
            {governanceDeadLetters.map((row) => (
              <option value={String(row.queue_path || "")} key={String(row.queue_path || row.dispatch_id || row.operation)}>
                {String(row.operation || "-")} · gates {Array.isArray(row.failed_gate_paths) ? row.failed_gate_paths.length : 0} · checkpoints {Array.isArray(row.failed_checkpoint_paths) ? row.failed_checkpoint_paths.length : 0}
              </option>
            ))}
          </select>
          <textarea
            rows={3}
            value={governanceRepairNote}
            onChange={(event) => setGovernanceRepairNote(event.target.value)}
            placeholder="Reviewed Repair Payload note: explain what failed evidence was inspected before retry."
          />
          <label className="checkboxLine">
            <input
              type="checkbox"
              checked={governanceRepairConfirmed}
              disabled={!selectedGovernanceDeadLetter}
              onChange={(event) => setGovernanceRepairConfirmed(event.target.checked)}
            />
            confirm_governance_review: I inspected failed gate/checkpoint evidence; failed gates remain failed.
          </label>
          <button
            className="primaryButton"
            disabled={busy || !governanceRepairReady}
            onClick={() => runAction(() => submitGovernanceDeadLetterRepair(), "Governance dead-letter reviewed repair 已提交", setDispatchResult)}
          >
            Submit Reviewed Repair Payload
          </button>
        </div>
        <pre className="jsonPreview">{compactJson({
          queue_path: governanceRepairQueuePath || "-",
          confirm_governance_review: governanceRepairConfirmed,
          reviewed_failed_gate_paths: selectedGovernanceGatePaths,
          reviewed_failed_checkpoint_paths: selectedGovernanceCheckpointPaths,
          governance_review_note: governanceRepairNote || "operator reviewed failed gates and checkpoints in Agent Center UI"
        }, 1600)}</pre>
        <div className="pillRow">
          <span className="badge warn">Review required</span>
          <span className="badge">no automatic repair</span>
          <span className="badge">failed gates remain failed</span>
          <span className="badge">guarded repair endpoint only</span>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Dead-letter Queue / Repair" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 dead-letter"
            columns={["Operation", "错误", "Path", "Repair"]}
            rows={(agentCenter?.dead_letter_queue || []).slice(0, 50).map((row) => [
              String(row.operation || "-"),
              String(row.last_error || row.error || "-"),
              pathCell(String(row.path || "-"), `${String(row.path)}-dead-letter`),
              governanceDeadLetterPaths.has(String(row.path || "")) ? (
                <span className="badge warn" key={`${String(row.path)}-governance-review-required`}>Review required</span>
              ) : row.path ? (
                <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => repairDeadLetterDispatch(String(row.path || "")), "Dead-letter repair 已执行", setDispatchResult)} key={`${String(row.path)}-repair`}>
                  Repair
                </button>
              ) : "-"
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Rollback Preview / Rehearsal" icon={<RotateCcw size={18} />} />
          <DataTable
            emptyText="暂无 rollback preview"
            columns={["Operation", "Strategy", "状态", "Path", "Rehearse"]}
            rows={(agentCenter?.rollback_preview || []).slice(0, 50).map((row) => [
              String(row.operation || "-"),
              String(row.strategy || row.rollback_strategy || "-"),
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-rollback-status`}>{String(row.status || "-")}</span>,
              pathCell(String(row.path || "-"), `${String(row.path)}-rollback`),
              failedQueue[0]?.path ? (
                <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => rehearseAgentRollback(String(failedQueue[0]?.path || "")), "Rollback rehearsal 已生成", setDispatchResult)} key={`${String(row.path)}-rehearse`}>
                  Rehearse
                </button>
              ) : "-"
            ])}
          />
          <DataTable
            emptyText="暂无 rollback rehearsal"
            columns={["Status", "Operation", "Path"]}
            rows={rollbackRehearsals.slice(0, 20).map((row) => [
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-rehearsal-status`}>{String(row.status || "-")}</span>,
              String(row.operation || row.type || "-"),
              pathCell(String(row.path || "-"), `${String(row.path)}-rehearsal`)
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="SLA / Duration" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 SLA 证据"
            columns={["Operation", "Status", "Duration", "SLA"]}
            rows={(agentCenter?.sla_duration || []).slice(0, 60).map((row) => [
              String(row.operation || "-"),
              <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-sla-status`}>{String(row.status || "-")}</span>,
              String(row.duration_ms ?? "-"),
              String(row.sla_status || row.sla_seconds || "-")
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Operation Coverage Full" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 operation coverage"
            columns={["Operation", "Runner", "MKAOS", "Runs", "Dead Letters"]}
            rows={(coverageOps.length ? coverageOps : (agentCenter?.operation_coverage || [])).slice(0, 80).map((row) => [
              String(row.operation || "-"),
              String(row.runner_kind || row.runner || "-"),
              String(row.mkaos_context_policy || row.checkpoint_strategy || "-"),
              String(row.run_count ?? "-"),
              String(row.dead_letter_count ?? "-")
            ])}
          />
          <div className="pillRow">
            <span className="badge">missing required {String((operationCoverageFull.summary as Record<string, unknown> | undefined)?.missing_required_count ?? 0)}</span>
            <span className="badge">repairs {deadLetterRepairs.length}</span>
          </div>
        </div>
      </section>

      <section className="panel">
        <PanelHeader title="Evidence Drawer" icon={<ShieldCheck size={18} />} />
        <DataTable
          emptyText="暂无 evidence drawer"
          columns={["类型", "状态", "路径", "摘要"]}
          rows={(agentCenter?.evidence_drawer || []).slice(0, 80).map((row) => [
            String(row.type || "-"),
            <span className={statusClass(String(row.status || ""))} key={`${String(row.path)}-evidence-status`}>{String(row.status || "-")}</span>,
            pathCell(String(row.path || "-"), `${String(row.path)}-evidence`),
            String(row.summary || row.title || "-")
          ])}
        />
      </section>

      <section className="panel">
        <PanelHeader title="Agent Timeline" icon={<Activity size={18} />} />
        <DataTable
          emptyText="暂无 Agent queue 事件"
          columns={["Queue", "状态", "Operation", "Checkpoint", "Rollback"]}
          rows={queue.slice(0, 30).map((row) => {
            const contract = contracts.find((item) => String(item.operation || "") === String(row.operation || ""));
            return [
              String(row.dispatch_id || row.path || "-"),
              <span className={statusClass(String(row.status || ""))} key={`${row.path}-timeline-status`}>{String(row.status || "-")}</span>,
              String(row.operation || "-"),
              String(contract?.checkpoint_strategy || row.checkpoint_strategy || "-"),
              String(contract?.rollback_strategy || "-")
            ];
          })}
        />
      </section>

      <section className="panel">
        <PanelHeader title="Dispatch Queue" icon={<Activity size={18} />} />
        <DataTable
          emptyText="暂无 Agent dispatch queue"
          columns={["状态", "AgentRun", "Workflow", "尝试", "Lease", "Token/Cost", "恢复"]}
          rows={queue.slice(0, 80).map((row) => [
            <span className={statusClass(String(row.status || ""))} key={`${row.path}-status`}>{String(row.status || "-")}</span>,
            pathCell(String(row.agent_run_path || "-"), `${row.path}-agent`),
            `${String(row.workflow_node_id || "-")} · ${String(row.workflow_run_id || "-")}`,
            `${String(row.attempt_count ?? 0)}/${String(row.max_attempts ?? 0)}`,
            String(row.lease_owner || "-"),
            `${String(row.token_used ?? 0)} / ${String(row.cost_estimate ?? 0)}`,
            governanceDeadLetterPaths.has(String(row.path || "")) ? (
              <span className="badge warn" key={`${row.path}-governance-review-required`}>Review required</span>
            ) : ["dead_letter", "waiting_human", "retry_scheduled"].includes(String(row.status || "")) ? (
              <button className="secondaryButton" disabled={busy} onClick={() => runAction(() => recoverAgentDispatch(String(row.path || "")), "Dispatch 已恢复", setDispatchResult)} key={`${row.path}-recover`}>
                Recover
              </button>
            ) : String(row.last_error || "-")
          ])}
        />
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Agent Runs" icon={<ShieldCheck size={18} />} />
          <DataTable
            emptyText="暂无 AgentRun"
            columns={["Agent", "操作", "状态", "模型", "Token", "Checkpoint", "路径"]}
            rows={agentRuns.slice(0, 60).map((run) => [
              run.agent_type,
              run.operation,
              <span className={statusClass(run.status)} key={`${run.path}-status`}>{run.status}</span>,
              `${run.model_provider || "-"} / ${run.model_name || "-"}`,
              `${run.token_used ?? 0}/${run.token_budget ?? 0}`,
              compactJson(run.checkpoint, 80),
              pathCell(run.path, run.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Operation Contracts" icon={<ListChecks size={18} />} />
          <DataTable
            emptyText="暂无 operation contract"
            columns={["Operation", "Agent", "I/O", "Checkpoint", "Rollback"]}
            rows={contracts.slice(0, 50).map((contract) => [
              String(contract.operation || "-"),
              String(contract.agent_key || contract.agent_type || "-"),
              `${String((contract.input_types as unknown[] | undefined)?.join(", ") || "-")} -> ${String((contract.output_types as unknown[] | undefined)?.join(", ") || "-")}`,
              String(contract.checkpoint_strategy || "-"),
              String(contract.rollback_strategy || "-")
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Agent Events" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 Agent Event"
            columns={["事件", "状态", "消息", "时间", "Run"]}
            rows={agentEvents.slice(0, 80).map((event) => [
              event.event_type,
              <span className={statusClass(event.status)} key={`${event.path}-status`}>{event.status}</span>,
              event.message || "-",
              event.created_at || "-",
              pathCell(event.agent_run_path, event.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Scheduler Result" icon={<Activity size={18} />} />
          <pre className="jsonPreview">{JSON.stringify(schedulerResult || dispatchResult || schedulerStatus, null, 2)}</pre>
        </div>
      </section>
    </FeatureShell>
  );
}
