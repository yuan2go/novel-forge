"use client";

import { BookOpen, CheckCircle2, FileSearch, GitBranch, ShieldAlert, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  analyzeMkaosAssetImpact,
  approveMkaosModelExtractionCandidate,
  applyMkaosWeightGovernance,
  attributeMkaosFeedback,
  buildMkaosGateCoverage,
  buildMkaosLineageIndex,
  checkMkaosLeakage,
  convertMkaosCreativeAssets,
  createMkaosRepository,
  createMkaosModelExtractionJob,
  diffMkaosLineageIndexes,
  dryRunMkaosWeightGovernance,
  evaluateMkaosExtraction,
  exportMkaosLineageGraph,
  gateMkaosKnowledgePack,
  importMkaosRepository,
  loadMkaosBooks,
  loadMkaosIngestionJobs,
  loadMkaosLineageIndex,
  loadMkaosModelExtractionJobs,
  loadMkaosModelExtractionPrompts,
  loadMkaosModelExtractionReviewQueue,
  loadMkaosOverview,
  loadMkaosParallelPairs,
  loadMkaosGateCoverage,
  loadMkaosProductionGateReports,
  loadMkaosRepositories,
  cancelMkaosIngestionJob,
  queryMkaosLineagePath,
  rejectMkaosModelExtractionCandidate,
  resumeMkaosIngestionJob,
  runMkaosExtractionJob,
  runMkaosModelExtractionBenchmark,
  runMkaosModelExtractionJob,
  runMkaosModelExtractionRegression,
  runMkaosProductionGate,
  scanMkaosRepository,
  type MkaosRow
} from "./api";

type Mode =
  | "import"
  | "repositories"
  | "books"
  | "extraction-jobs"
  | "creative-assets"
  | "quality"
  | "model-extraction"
  | "model-extraction-jobs"
  | "model-extraction-review"
  | "model-extraction-benchmarks"
  | "model-extraction-prompts"
  | "production-gate"
  | "production-gate-reports"
  | "knowledge-graph"
  | "lineage"
  | "impact"
  | "feedback-attribution";

export function MkaosIngestionPage({ mode }: { mode: Mode }) {
  const [repositories, setRepositories] = useState<MkaosRow[]>([]);
  const [books, setBooks] = useState<MkaosRow[]>([]);
  const [pairs, setPairs] = useState<MkaosRow[]>([]);
  const [jobs, setJobs] = useState<MkaosRow[]>([]);
  const [modelJobs, setModelJobs] = useState<MkaosRow[]>([]);
  const [modelReviews, setModelReviews] = useState<MkaosRow[]>([]);
  const [modelPrompts, setModelPrompts] = useState<MkaosRow[]>([]);
  const [gateReports, setGateReports] = useState<MkaosRow[]>([]);
  const [gateCoverage, setGateCoverage] = useState<Record<string, any> | null>(null);
  const [lineageIndex, setLineageIndex] = useState<Record<string, any> | null>(null);
  const [knowledge, setKnowledge] = useState<MkaosRow[]>([]);
  const [name, setName] = useState("Classical-Modern local corpus");
  const [localPath, setLocalPath] = useState("");
  const [sourceType, setSourceType] = useState("classical_text");
  const [modelSummary, setModelSummary] = useState("制度、资源和风险约束如何转成角色行动、冲突与代价。");
  const [lineageAssetId, setLineageAssetId] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, any> | null>(null);

  async function refresh() {
    const [repoRows, bookRows, pairRows, jobRows, overview, mxJobs, mxReviews, mxPrompts, gateRows, coverage, lineage] = await Promise.all([
      loadMkaosRepositories(),
      loadMkaosBooks(),
      loadMkaosParallelPairs(),
      loadMkaosIngestionJobs(),
      loadMkaosOverview(),
      loadMkaosModelExtractionJobs(),
      loadMkaosModelExtractionReviewQueue(),
      loadMkaosModelExtractionPrompts(),
      loadMkaosProductionGateReports(),
      loadMkaosGateCoverage().catch(() => null),
      loadMkaosLineageIndex().catch(() => null)
    ]);
    setRepositories(repoRows);
    setBooks(bookRows);
    setPairs(pairRows);
    setJobs(jobRows);
    setKnowledge(overview.knowledge ?? []);
    setModelJobs(mxJobs);
    setModelReviews(mxReviews);
    setModelPrompts(mxPrompts);
    setGateReports(gateRows);
    setGateCoverage(coverage);
    setLineageIndex(lineage);
  }

  async function runAction(action: () => Promise<any>, message: string) {
    setNotice("");
    setError("");
    try {
      const next = await action();
      setResult(next);
      setNotice(message);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    }
  }

  useEffect(() => {
    refresh().catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const selectedRepo = repositories[0];
  const selectedBook = books[0];
  const selectedModelJob = modelJobs[0];
  const selectedReview = modelReviews[0];
  const selectedAssetId = lineageAssetId || knowledge[0]?.id || "";
  const creativeCards = useMemo(() => knowledge.filter((row) => row.metadata?.knowledge_subtype === "creative_knowledge_card" || row.content?.knowledge_subtype === "creative_knowledge_card"), [knowledge]);

  return (
    <FeatureShell title={`MKAOS ${titleForMode(mode)}`} subtitle="多类型文本资产导入、创作机制抽取、创作资产转换和质量门禁。">
      {notice ? <div className="noticeLine">{notice}</div> : null}
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="summaryBand manuscriptSummary">
        <Metric label="Repositories" value={String(repositories.length)} />
        <Metric label="Books" value={String(books.length)} />
        <Metric label="Pairs" value={String(pairs.length)} />
        <Metric label="Jobs" value={String(jobs.length)} />
        <Metric label="Creative Cards" value={String(creativeCards.length)} />
        <Metric label="Model Jobs" value={String(modelJobs.length)} />
        <Metric label="Gate Reports" value={String(gateReports.length)} />
        <Metric label="Gate Coverage" value={`${String(gateCoverage?.covered_count ?? 0)}/${String(gateCoverage?.operation_count ?? 0)}`} />
        <Metric label="Lineage Nodes" value={String(lineageIndex?.node_count ?? 0)} />
      </section>

      {mode === "import" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Ingestion Import" icon={<FileSearch size={18} />} />
            <div className="formGrid">
              <input value={name} onChange={(event) => setName(event.target.value)} placeholder="repository name" />
              <select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
                {["classical_text", "professional_book", "webnovel_analysis", "mystery"].map((item) => <option key={item}>{item}</option>)}
              </select>
            </div>
            <input value={localPath} onChange={(event) => setLocalPath(event.target.value)} placeholder="/local/path/to/corpus" />
            <div className="buttonRow">
              <button className="primaryButton" onClick={() => runAction(() => createMkaosRepository({ name, localPath, sourceType }), "Repository registered")}>Register</button>
              <button onClick={() => selectedRepo && runAction(() => scanMkaosRepository(selectedRepo.id), "Repository scanned")}>Scan First Repository</button>
              <button onClick={() => selectedRepo && runAction(() => importMkaosRepository(selectedRepo.id), "Repository imported")}>Import First Repository</button>
            </div>
            <p className="mutedText">GitHub URL 在 P0 只登记来源；真实 clone 由 operator 本地完成。raw source text 只进入 evidence layer。</p>
          </div>
          <RepositoryTable rows={repositories} />
        </section>
      ) : null}

      {mode === "repositories" ? <RepositoryTable rows={repositories} /> : null}
      {mode === "books" ? <BooksPanel books={books} pairs={pairs} /> : null}
      {mode === "extraction-jobs" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Extraction Jobs" icon={<Sparkles size={18} />} />
            <div className="buttonRow">
              <button className="primaryButton" onClick={() => runAction(() => runMkaosExtractionJob({ sourceType, bookId: selectedBook?.id }), "Extraction job completed")}>Run extraction</button>
              <button onClick={() => jobs[0] && runAction(() => resumeMkaosIngestionJob(jobs[0].id, true), "Resume Job requested")}>Resume Job</button>
              <button onClick={() => jobs[0] && runAction(() => cancelMkaosIngestionJob(jobs[0].id, true), "Cancel Job requested")}>Cancel Job</button>
            </div>
            <DataTable emptyText="No extraction jobs" columns={["Job", "Status", "Operation", "Resume"]} rows={jobs.map((row) => [row.title, <span key={row.id} className={statusClass(String(row.content.status || ""))}>{String(row.content.status || "-")}</span>, String(row.content.operation || "-"), String(row.content.resume_allowed ?? "-")])} />
          </div>
        </section>
      ) : null}

      {mode === "creative-assets" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Creative Assets" icon={<GitBranch size={18} />} />
            <button className="primaryButton" onClick={() => runAction(() => convertMkaosCreativeAssets(creativeCards.slice(0, 3).map((row) => row.id), true), "Creative asset dry-run completed")}>Dry-run convert</button>
            <DataTable emptyText="No CreativeKnowledgeCard" columns={["Card", "Source Type", "Flows", "Quality"]} rows={creativeCards.map((row) => [row.title, String(row.content.source_type || "-"), String(row.content.applicable_flows || "-"), String(row.content.overall_quality_score ?? row.content.quality_score ?? "-")])} />
          </div>
        </section>
      ) : null}

      {mode === "quality" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Extraction Quality Gate" icon={<ShieldAlert size={18} />} />
            <div className="buttonRow">
              <button className="primaryButton" onClick={() => runAction(() => evaluateMkaosExtraction(), "Extraction quality evaluated")}>Evaluate extraction</button>
              <button onClick={() => runAction(() => checkMkaosLeakage("人物在族规压力下必须做选择", "子曰：学而时习之，不亦说乎？"), "Leakage checked")}>Check leakage</button>
              <button onClick={() => runAction(() => gateMkaosKnowledgePack({ content: { pack_items: [{ knowledge_id: "demo" }] } }), "Knowledge pack gated")}>Gate pack</button>
            </div>
            <DataTable emptyText="No weak cards" columns={["Card", "Risk", "Status"]} rows={creativeCards.map((row) => [row.title, String(row.risk_level || row.content.risk_level || "low"), String(row.status || row.content.status || "-")])} />
          </div>
        </section>
      ) : null}

      {mode === "model-extraction" || mode === "model-extraction-jobs" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Model Extraction Jobs" icon={<Sparkles size={18} />} />
            <div className="formGrid">
              <select value={sourceType} onChange={(event) => setSourceType(event.target.value)}>
                {["classical_text", "professional_book", "webnovel_analysis", "mystery", "platform_rule", "training"].map((item) => <option key={item}>{item}</option>)}
              </select>
              <input value={modelSummary} onChange={(event) => setModelSummary(event.target.value)} placeholder="safe abstract input summary" />
            </div>
            <div className="buttonRow">
              <button className="primaryButton" onClick={() => runAction(() => createMkaosModelExtractionJob({ sourceType, inputSummary: modelSummary, providerMode: "disabled" }), "Model extraction job created")}>Create Job</button>
              <button onClick={() => selectedModelJob && runAction(() => runMkaosModelExtractionJob(selectedModelJob.id), "Model extraction job ran")}>Run First Job</button>
            </div>
            <DataTable emptyText="No model extraction jobs" columns={["Job", "Source", "Provider", "Status", "Candidates"]} rows={modelJobs.map((row) => [row.title, String(row.content.source_type || "-"), String(row.content.provider_mode || "-"), <span key={row.id} className={statusClass(String(row.content.status || ""))}>{String(row.content.status || "-")}</span>, String(row.content.candidate_count ?? "-")])} />
          </div>
        </section>
      ) : null}

      {mode === "model-extraction-review" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Extraction Review Queue" icon={<ShieldAlert size={18} />} />
            <div className="buttonRow">
              <button className="primaryButton" onClick={() => selectedReview && runAction(() => approveMkaosModelExtractionCandidate(String(selectedReview.content.candidate_id || selectedReview.references?.[0] || selectedReview.id)), "Candidate approved")}>Approve First</button>
              <button onClick={() => selectedReview && runAction(() => rejectMkaosModelExtractionCandidate(String(selectedReview.content.candidate_id || selectedReview.references?.[0] || selectedReview.id)), "Candidate rejected")}>Reject First</button>
            </div>
            <DataTable emptyText="No review queue items" columns={["Candidate", "Status", "Confidence", "Recommendation", "Forbidden"]} rows={modelReviews.map((row) => [String(row.content.candidate_id || row.title), <span key={row.id} className={statusClass(String(row.content.status || ""))}>{String(row.content.status || "-")}</span>, String(row.content.confidence ?? "-"), String(row.content.approval_recommendation || "-"), String(row.content.sanitizer?.forbidden_field_count ?? 0)])} />
          </div>
        </section>
      ) : null}

      {mode === "model-extraction-benchmarks" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Extraction Benchmarks" icon={<CheckCircle2 size={18} />} />
            <div className="buttonRow">
              <button className="primaryButton" onClick={() => runAction(() => runMkaosModelExtractionBenchmark(), "Benchmark completed")}>Run Benchmark</button>
              <button onClick={() => runAction(() => runMkaosModelExtractionRegression(), "Regression completed")}>Run Regression</button>
            </div>
            <p className="mutedText">默认使用 disabled provider + deterministic fixture，不调用真实外部模型。</p>
          </div>
        </section>
      ) : null}

      {mode === "model-extraction-prompts" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Extraction Prompt Versions" icon={<FileSearch size={18} />} />
            <DataTable emptyText="No prompt versions" columns={["Prompt", "Source Type", "Status", "Benchmark"]} rows={modelPrompts.map((row) => [row.title, String(row.content.source_type || "-"), String(row.content.status || "-"), String(row.content.benchmark_score ?? "-")])} />
          </div>
        </section>
      ) : null}

      {mode === "production-gate" || mode === "production-gate-reports" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="MKAOS Production Gate" icon={<ShieldAlert size={18} />} />
            <div className="buttonRow">
              <button className="primaryButton" onClick={() => runAction(() => runMkaosProductionGate("prose"), "Production gate preview ran")}>Run Prose Gate Preview</button>
              <button onClick={() => runAction(() => runMkaosProductionGate("publish"), "Publish gate preview ran")}>Run Publish Gate Preview</button>
              <button onClick={() => runAction(() => buildMkaosGateCoverage(), "Gate coverage report built")}>Build Coverage Report</button>
            </div>
            <section className="summaryBand manuscriptSummary">
              <Metric label="Covered Operations" value={String(gateCoverage?.covered_count ?? 0)} />
              <Metric label="Compat Gaps" value={String(gateCoverage?.compat_gap_count ?? 0)} />
              <Metric label="Forbidden Bypass" value={String(gateCoverage?.forbidden_bypass_operations?.length ?? 0)} />
            </section>
            <DataTable emptyText="No coverage data" columns={["Operation", "Flow", "Status", "Bypass"]} rows={(Array.isArray(gateCoverage?.operations) ? gateCoverage.operations.slice(0, 16) : []).map((row: any) => [String(row.operation || "-"), String(row.flow || "-"), <span key={row.operation} className={statusClass(String(row.status || ""))}>{String(row.status || "-")}</span>, String(row.bypass_allowed)])} />
            <DataTable emptyText="No gate reports" columns={["Flow", "Passed", "Blocking", "Recommendation", "Path"]} rows={gateReports.map((row) => [String(row.content.flow || "-"), String(row.content.passed), String(row.content.blocking_issue_count ?? 0), String(row.content.recommendation || "-"), <span className="pathText" key={row.id}>{row.path}</span>])} />
          </div>
        </section>
      ) : null}

      {mode === "knowledge-graph" || mode === "lineage" ? (
        <LineagePanel
          lineageIndex={lineageIndex}
          assetId={lineageAssetId}
          setAssetId={setLineageAssetId}
          selectedAssetId={selectedAssetId}
          runAction={runAction}
        />
      ) : null}

      {mode === "impact" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Asset Impact" icon={<GitBranch size={18} />} />
            <input value={lineageAssetId} onChange={(event) => setLineageAssetId(event.target.value)} placeholder="asset id" />
            <div className="buttonRow">
              <button className="primaryButton" onClick={() => selectedAssetId && runAction(() => analyzeMkaosAssetImpact(selectedAssetId), "Impact analysis completed")}>Analyze Impact</button>
              <button onClick={() => selectedAssetId && runAction(() => dryRunMkaosWeightGovernance(selectedAssetId), "Weight governance dry-run completed")}>Dry-run Weight Governance</button>
              <button onClick={() => selectedAssetId && runAction(() => applyMkaosWeightGovernance(selectedAssetId), "Explicit weight governance apply completed")}>Explicit Apply</button>
            </div>
            <p className="mutedText">Impact 只显示 id、类型、风险、建议动作，不展示 source raw text。自动写权重需要 explicit apply policy。</p>
          </div>
        </section>
      ) : null}

      {mode === "feedback-attribution" ? (
        <section className="workspaceGrid">
          <div className="panel">
            <PanelHeader title="Feedback Attribution" icon={<GitBranch size={18} />} />
            <input value={lineageAssetId} onChange={(event) => setLineageAssetId(event.target.value)} placeholder="generated asset id" />
            <div className="buttonRow">
              <button className="primaryButton" onClick={() => selectedAssetId && runAction(() => attributeMkaosFeedback(selectedAssetId), "Feedback attributed")}>Attribute Feedback</button>
              <button onClick={() => runAction(() => dryRunMkaosWeightGovernance(), "Global weight governance dry-run completed")}>Global Dry-run</button>
              <button onClick={() => runAction(() => applyMkaosWeightGovernance(), "Global explicit weight governance apply completed")}>Global Explicit Apply</button>
            </div>
            <p className="mutedText">反馈先生成 attribution 和调权建议，默认不直接改权重；显式 apply 会写 mutation/version/audit。</p>
          </div>
        </section>
      ) : null}

      {result ? (
        <section className="panel">
          <PanelHeader title="Last Result" icon={<CheckCircle2 size={18} />} />
          <pre className="jsonBlock">{JSON.stringify(result, null, 2)}</pre>
        </section>
      ) : null}
    </FeatureShell>
  );
}

function RepositoryTable({ rows }: { rows: MkaosRow[] }) {
  return (
    <div className="panel">
      <PanelHeader title="Repositories" icon={<BookOpen size={18} />} />
      <DataTable
        emptyText="No repositories"
        columns={["Name", "Status", "Corpus", "Path"]}
        rows={rows.map((row) => [
          row.title,
          <span key={row.id} className={statusClass(String(row.content.import_status || ""))}>{String(row.content.import_status || "-")}</span>,
          String(row.content.detected_corpus_type || "-"),
          <span className="pathText" key={`${row.id}-path`}>{String(row.content.local_path || row.content.source_uri || "-")}</span>
        ])}
      />
    </div>
  );
}

function BooksPanel({ books, pairs }: { books: MkaosRow[]; pairs: MkaosRow[] }) {
  return (
    <section className="workspaceGrid">
      <div className="panel">
        <PanelHeader title="Books" icon={<BookOpen size={18} />} />
        <DataTable emptyText="No books" columns={["Book", "Type", "Risk", "Chapters", "Parser", "Sections"]} rows={books.map((row) => [row.title, String(row.content.source_type || "-"), String(row.content.risk_level || "-"), String(row.content.chapter_count ?? "-"), String(row.content.parser_quality || row.content.parser_metadata?.parser_quality || "-"), String(row.content.section_manifest?.length ?? row.content.stats?.section_count ?? "-")])} />
      </div>
      <div className="panel">
        <PanelHeader title="Parallel Pairs" icon={<GitBranch size={18} />} />
        <DataTable emptyText="No parallel pairs" columns={["Pair", "Evidence Only", "Prose Allowed", "Hash"]} rows={pairs.slice(0, 50).map((row) => [row.title || row.id, String(row.content.evidence_layer_only), String(row.content.raw_text_allowed_for_prose), String(row.content.content_hash || "").slice(0, 12)])} />
      </div>
    </section>
  );
}

function LineagePanel({
  lineageIndex,
  assetId,
  setAssetId,
  selectedAssetId,
  runAction
}: {
  lineageIndex: Record<string, any> | null;
  assetId: string;
  setAssetId: (value: string) => void;
  selectedAssetId: string;
  runAction: (action: () => Promise<any>, message: string) => Promise<void>;
}) {
  const nodes = Array.isArray(lineageIndex?.nodes) ? lineageIndex.nodes.slice(0, 50) : [];
  const edges = Array.isArray(lineageIndex?.edges) ? lineageIndex.edges.slice(0, 50) : [];
  return (
    <section className="workspaceGrid">
      <div className="panel">
        <PanelHeader title="Knowledge Graph / Lineage" icon={<GitBranch size={18} />} />
        <div className="buttonRow">
          <button className="primaryButton" onClick={() => runAction(() => buildMkaosLineageIndex(), "Lineage index rebuilt")}>Build Index</button>
          <button onClick={() => selectedAssetId && runAction(() => queryMkaosLineagePath(selectedAssetId), "Lineage path queried")}>Query Path</button>
          <button onClick={() => runAction(() => diffMkaosLineageIndexes(), "Lineage diff report generated")}>Diff Latest</button>
          <button onClick={() => runAction(() => exportMkaosLineageGraph(), "Lineage graph export generated")}>Export Graph</button>
        </div>
        <input value={assetId} onChange={(event) => setAssetId(event.target.value)} placeholder="asset id for lineage query" />
        <section className="summaryBand manuscriptSummary">
          <Metric label="Nodes" value={String(lineageIndex?.node_count ?? 0)} />
          <Metric label="Edges" value={String(lineageIndex?.edge_count ?? 0)} />
          <Metric label="Sources" value={String(lineageIndex?.source_asset_ids?.length ?? 0)} />
        </section>
      </div>
      <div className="panel">
        <PanelHeader title="Nodes" icon={<BookOpen size={18} />} />
        <DataTable emptyText="No lineage nodes" columns={["Asset", "Type", "Flow", "Risk"]} rows={nodes.map((node: any) => [String(node.title || node.asset_id), String(node.asset_type || "-"), String(node.flow || "-"), String(node.risk_level || "-")])} />
      </div>
      <div className="panel">
        <PanelHeader title="Edges" icon={<GitBranch size={18} />} />
        <DataTable emptyText="No lineage edges" columns={["Source", "Relation", "Target"]} rows={edges.map((edge: any) => [String(edge.source || "-"), String(edge.relation_type || "-"), String(edge.target || "-")])} />
        <p className="mutedText">Graph export includes deterministic cluster layout and semantic edge weights for LocalStorage-scale exploration.</p>
      </div>
    </section>
  );
}

function titleForMode(mode: Mode) {
  const labels: Record<Mode, string> = {
    import: "Import",
    repositories: "Repositories",
    books: "Books",
    "extraction-jobs": "Extraction Jobs",
    "creative-assets": "Creative Assets",
    quality: "Quality",
    "model-extraction": "Model Extraction",
    "model-extraction-jobs": "Model Extraction Jobs",
    "model-extraction-review": "Model Extraction Review",
    "model-extraction-benchmarks": "Model Extraction Benchmarks",
    "model-extraction-prompts": "Model Extraction Prompts",
    "production-gate": "Production Gate",
    "production-gate-reports": "Production Gate Reports",
    "knowledge-graph": "Knowledge Graph",
    lineage: "Lineage",
    impact: "Impact",
    "feedback-attribution": "Feedback Attribution"
  };
  return labels[mode];
}
