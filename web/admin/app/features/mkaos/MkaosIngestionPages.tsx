"use client";

import { BookOpen, CheckCircle2, FileSearch, GitBranch, ShieldAlert, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { FeatureShell } from "../../shared/feature-shell";
import { DataTable, Metric, PanelHeader, statusClass } from "../../shared/ui";
import {
  checkMkaosLeakage,
  convertMkaosCreativeAssets,
  createMkaosRepository,
  evaluateMkaosExtraction,
  gateMkaosKnowledgePack,
  importMkaosRepository,
  loadMkaosBooks,
  loadMkaosIngestionJobs,
  loadMkaosOverview,
  loadMkaosParallelPairs,
  loadMkaosRepositories,
  runMkaosExtractionJob,
  scanMkaosRepository,
  type MkaosRow
} from "./api";

type Mode = "import" | "repositories" | "books" | "extraction-jobs" | "creative-assets" | "quality";

export function MkaosIngestionPage({ mode }: { mode: Mode }) {
  const [repositories, setRepositories] = useState<MkaosRow[]>([]);
  const [books, setBooks] = useState<MkaosRow[]>([]);
  const [pairs, setPairs] = useState<MkaosRow[]>([]);
  const [jobs, setJobs] = useState<MkaosRow[]>([]);
  const [knowledge, setKnowledge] = useState<MkaosRow[]>([]);
  const [name, setName] = useState("Classical-Modern local corpus");
  const [localPath, setLocalPath] = useState("");
  const [sourceType, setSourceType] = useState("classical_text");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Record<string, any> | null>(null);

  async function refresh() {
    const [repoRows, bookRows, pairRows, jobRows, overview] = await Promise.all([
      loadMkaosRepositories(),
      loadMkaosBooks(),
      loadMkaosParallelPairs(),
      loadMkaosIngestionJobs(),
      loadMkaosOverview()
    ]);
    setRepositories(repoRows);
    setBooks(bookRows);
    setPairs(pairRows);
    setJobs(jobRows);
    setKnowledge(overview.knowledge ?? []);
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
            </div>
            <DataTable emptyText="No extraction jobs" columns={["Job", "Status", "Operation"]} rows={jobs.map((row) => [row.title, <span key={row.id} className={statusClass(String(row.content.status || ""))}>{String(row.content.status || "-")}</span>, String(row.content.operation || "-")])} />
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
        <DataTable emptyText="No books" columns={["Book", "Type", "Risk", "Chapters"]} rows={books.map((row) => [row.title, String(row.content.source_type || "-"), String(row.content.risk_level || "-"), String(row.content.chapter_count ?? "-")])} />
      </div>
      <div className="panel">
        <PanelHeader title="Parallel Pairs" icon={<GitBranch size={18} />} />
        <DataTable emptyText="No parallel pairs" columns={["Pair", "Evidence Only", "Prose Allowed", "Hash"]} rows={pairs.slice(0, 50).map((row) => [row.title || row.id, String(row.content.evidence_layer_only), String(row.content.raw_text_allowed_for_prose), String(row.content.content_hash || "").slice(0, 12)])} />
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
    quality: "Quality"
  };
  return labels[mode];
}
