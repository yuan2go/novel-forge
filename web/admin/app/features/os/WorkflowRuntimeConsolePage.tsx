"use client";

import { Activity, GitBranch, Pause, Play, RotateCcw, Square, Workflow } from "lucide-react";
import { useEffect, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import type { NodeRunRow, ProjectRow, TaskControl, WorkflowDefinitionRow, WorkflowRunRow } from "../../shared/types";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  controlWorkflowRun,
  executeWorkflow,
  loadWorkflowRuntimeConsole,
  loadWorkflowRuntimeData,
  resumeWorkflow,
  runWorkflowSchedulerTick
} from "./api";
import { compactJson, pathCell, selectedWorkspace, splitLines } from "./helpers";

export function WorkflowRuntimeConsolePage() {
  const [projects, setProjects] = useState<ProjectRow[]>([]);
  const [taskControl, setTaskControl] = useState<TaskControl | null>(null);
  const [definitions, setDefinitions] = useState<WorkflowDefinitionRow[]>([]);
  const [runs, setRuns] = useState<WorkflowRunRow[]>([]);
  const [nodeRuns, setNodeRuns] = useState<NodeRunRow[]>([]);
  const [projectId, setProjectId] = useState("");
  const [selectedDefinition, setSelectedDefinition] = useState("");
  const [selectedRun, setSelectedRun] = useState("");
  const [inputText, setInputText] = useState("");
  const [outputText, setOutputText] = useState("");
  const [runtime, setRuntime] = useState<Record<string, unknown> | null>(null);
  const [actionResult, setActionResult] = useState<Record<string, unknown> | null>(null);
  const [schedulerResult, setSchedulerResult] = useState<Record<string, unknown> | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function refresh(nextProjectId = projectId) {
    const [projectRows, control, definitionRows, runRows, nodeRunRows] = await loadWorkflowRuntimeData(nextProjectId);
    setProjects(projectRows);
    setTaskControl(control);
    setDefinitions(definitionRows);
    setRuns(runRows);
    setNodeRuns(nodeRunRows);
    const resolvedProject = nextProjectId || projectRows[0]?.project_id || "";
    setProjectId(resolvedProject);
    setSelectedDefinition((current) => current || definitionRows[0]?.path || "");
    setSelectedRun((current) => current || runRows.find((run) => ["blocked", "failed", "paused", "running"].includes(run.status))?.path || runRows[0]?.path || "");
  }

  async function reloadRuntime(definitionPath = selectedDefinition, runPath = selectedRun) {
    if (!definitionPath && !runPath) return;
    const result = await loadWorkflowRuntimeConsole({
      workflow_path_or_id: definitionPath || undefined,
      workflow_run_path_or_id: runPath || undefined,
      input_assets: splitLines(inputText)
    });
    setRuntime(result);
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
      await reloadRuntime();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  async function executeSelected() {
    if (!selectedDefinition) {
      setError("请选择 workflow definition");
      return;
    }
    await runAction(
      () => executeWorkflow({
        workflow_path_or_id: selectedDefinition,
        input_assets: splitLines(inputText),
        workspace_path: selectedWorkspace(projects, projectId)
      }),
      "Workflow 已执行"
    );
  }

  async function resumeSelected() {
    if (!selectedRun) {
      setError("请选择 workflow run");
      return;
    }
    const run = runs.find((item) => item.path === selectedRun);
    await runAction(
      () => resumeWorkflow({
        workflow_run_path_or_id: selectedRun,
        resume_node_id: run?.blocked_node_id || undefined,
        output_assets: splitLines(outputText)
      }),
      "Workflow 已恢复"
    );
  }

  async function controlSelected(action: "pause" | "retry" | "cancel" | "resume") {
    if (!selectedRun) {
      setError("请选择 workflow run");
      return;
    }
    const run = runs.find((item) => item.path === selectedRun);
    await runAction(
      () => controlWorkflowRun({
        workflow_run_path_or_id: selectedRun,
        action,
        resume_node_id: run?.blocked_node_id || undefined,
        output_assets: splitLines(outputText)
      }),
      `Workflow ${action} 已提交`
    );
  }

  async function tickScheduler(iterations = 1) {
    setBusy(true);
    setNotice("");
    setError("");
    try {
      const result = await runWorkflowSchedulerTick(projectId, iterations);
      setSchedulerResult(result);
      setNotice("Workflow scheduler tick 已完成");
      await refresh(projectId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const dagNodes = (((runtime?.dag as Record<string, unknown> | undefined)?.nodes as Array<Record<string, unknown>> | undefined) || []);
  const readyQueue = (((runtime?.ready_queue as Record<string, unknown> | undefined)?.queue as Array<Record<string, unknown>> | undefined) || []);
  const processorContracts = ((runtime?.processor_contracts as Array<Record<string, unknown>> | undefined) || []);
  const stateMachine = ((runtime?.state_machine as Record<string, unknown> | undefined) || {});
  const selectedRunRow = runs.find((run) => run.path === selectedRun);
  const blockedRuns = runs.filter((run) => run.blocked_node_id || ["blocked", "failed", "paused", "waiting_human"].includes(run.status));

  return (
    <FeatureShell title="Workflow Runtime Console" subtitle="DAG 解析、ready node queue、processor contract、execute/resume/control/scheduler 的正式运行台。" eyebrow="OS Runtime">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}

      <section className="summaryBand manuscriptSummary">
        <Metric label="Definitions" value={String(definitions.length)} />
        <Metric label="Runs" value={String(runs.length)} />
        <Metric label="Ready Nodes" value={String(readyQueue.length)} />
        <Metric label="Blocked Runs" value={String(blockedRuns.length)} />
        <Metric label="Scheduler" value={String(taskControl?.scheduler?.status ?? "missing")} />
        <Metric label="Action" value={String(actionResult?.status ?? "-")} />
      </section>

      <section className="panel">
        <PanelHeader title="Run Control" icon={<Play size={18} />} />
        <div className="formGrid wide">
          <select value={projectId} onChange={(event) => refresh(event.target.value)}>
            <option value="">全局</option>
            {projects.map((project) => <option value={project.project_id} key={project.project_id}>{project.title}</option>)}
          </select>
          <select value={selectedDefinition} onChange={(event) => setSelectedDefinition(event.target.value)}>
            <option value="">选择 Definition</option>
            {definitions.map((definition) => <option value={definition.path} key={definition.path}>{definition.name || definition.workflow_id}</option>)}
          </select>
          <select value={selectedRun} onChange={(event) => setSelectedRun(event.target.value)}>
            <option value="">选择 Run</option>
            {runs.map((run) => <option value={run.path} key={run.path}>{run.status} · {run.blocked_node_id || run.run_id}</option>)}
          </select>
          <textarea rows={3} value={inputText} onChange={(event) => setInputText(event.target.value)} placeholder="输入资产路径，每行一个" />
          <textarea rows={3} value={outputText} onChange={(event) => setOutputText(event.target.value)} placeholder="resume 输出资产路径，每行一个" />
          <button className="primaryButton" disabled={busy || !selectedDefinition} onClick={executeSelected}><Play size={16} />执行</button>
          <button className="secondaryButton" disabled={busy || !selectedRun} onClick={resumeSelected}><RotateCcw size={16} />Resume</button>
          <button className="secondaryButton" disabled={busy || (!selectedDefinition && !selectedRun)} onClick={() => reloadRuntime().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)))}><GitBranch size={16} />刷新 Runtime</button>
          <button className="secondaryButton" disabled={busy || !selectedRun} onClick={() => controlSelected("pause")}><Pause size={16} />Pause</button>
          <button className="secondaryButton" disabled={busy || !selectedRun} onClick={() => controlSelected("retry")}><RotateCcw size={16} />Retry</button>
          <button className="secondaryButton dangerButton" disabled={busy || !selectedRun} onClick={() => controlSelected("cancel")}><Square size={16} />Cancel</button>
          <button className="primaryButton" disabled={busy} onClick={() => tickScheduler(1)}><Workflow size={16} />Scheduler Tick</button>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="DAG Nodes" icon={<Workflow size={18} />} />
          <DataTable
            emptyText="选择 definition/run 后刷新 Runtime"
            columns={["节点", "处理器", "输入", "输出", "Checkpoint"]}
            rows={dagNodes.slice(0, 40).map((node) => {
              const contract = node.processor_contract as Record<string, unknown> | undefined;
              return [
                String(node.node_id || "-"),
                `${String(node.processor_kind || "-")} · ${String(node.processor_operation || node.operation || "-")}`,
                String((node.input_types as unknown[] | undefined)?.join(", ") || "-"),
                String((node.output_types as unknown[] | undefined)?.join(", ") || "-"),
                String(contract?.checkpoint_strategy || "-")
              ];
            })}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Ready Node Queue" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 ready node"
            columns={["节点", "状态", "处理器", "输入", "Lease/恢复"]}
            rows={readyQueue.slice(0, 30).map((row) => [
              String(row.node_id || "-"),
              <span className={statusClass(String(row.blocked_status || row.workflow_run_status || ""))} key={`ready-${row.node_id}`}>{String(row.blocked_status || row.workflow_run_status || "-")}</span>,
              `${String(row.processor_kind || "-")} · ${String(row.processor_operation || row.operation || "-")}`,
              String((row.input_assets as unknown[] | undefined)?.length ?? 0),
              `${row.lease_owner || "-"} / ${row.resume_supported ? "resume" : "rerun"}`
            ])}
          />
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Workflow Runs" icon={<GitBranch size={18} />} />
          <DataTable
            emptyText="暂无 workflow run"
            columns={["Run", "状态", "Blocked", "Node/Agent", "Trace", "路径"]}
            rows={runs.slice(0, 50).map((run) => [
              run.run_id,
              <span className={statusClass(run.status)} key={`${run.path}-status`}>{run.status}</span>,
              run.blocked_node_id ? `${run.blocked_node_id} · ${run.blocked_status}` : "-",
              `${run.node_run_count}/${run.agent_run_count}`,
              run.trace_id || "-",
              pathCell(run.path, run.path)
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Scheduler Evidence" icon={<Workflow size={18} />} />
          <div className="summaryBand">
            <Metric label="Candidate" value={String(schedulerResult?.candidate_count ?? "-")} />
            <Metric label="Resumed" value={String(schedulerResult?.resumed_count ?? "-")} />
            <Metric label="Skipped" value={String(schedulerResult?.skipped_count ?? "-")} />
            <Metric label="Errors" value={String(schedulerResult?.error_count ?? "-")} />
          </div>
          <pre className="jsonPreview">{JSON.stringify(schedulerResult || selectedRunRow || {}, null, 2)}</pre>
        </div>
      </section>

      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Processor Contracts" icon={<Activity size={18} />} />
          <DataTable
            emptyText="暂无 processor contract"
            columns={["Operation", "Kind", "类别", "Checkpoint", "Gate"]}
            rows={processorContracts.slice(0, 60).map((contract) => [
              String(contract.operation || "-"),
              String(contract.kind || "-"),
              String(contract.category || "-"),
              String(contract.checkpoint_strategy || "-"),
              `${contract.pre_gates ? "pre" : "-"} / ${contract.post_gates ? "post" : "-"}`
            ])}
          />
        </div>
        <div className="panel">
          <PanelHeader title="Node Runs / State Machine" icon={<Workflow size={18} />} />
          <DataTable
            emptyText="暂无 node run"
            columns={["节点", "操作", "状态", "I/O", "错误"]}
            rows={nodeRuns.slice(0, 35).map((run) => [
              `${run.node_type}/${run.node_id}`,
              run.operation,
              <span className={statusClass(run.status)} key={`${run.path}-status`}>{run.status}</span>,
              `${run.input_count} -> ${run.output_count}`,
              run.error || "-"
            ])}
          />
          <p className="previewText">State machine: {compactJson(stateMachine, 260)}</p>
        </div>
      </section>
    </FeatureShell>
  );
}
