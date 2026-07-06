"use client";

import { Boxes, BrainCircuit, CheckCircle2, FileText, GitCompare, Library, Network, Send, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { fetchJson, postJson } from "../../shared/api";
import { FeatureShell } from "../../shared/feature-shell";
import { DataTable, PanelHeader } from "../../shared/ui";

type RunResult = Record<string, unknown>;
type OperationContract = {
  operation?: string;
  agent_key?: string;
  output_types?: string[];
  aliases?: string[];
};

function primaryPath(result: RunResult | null) {
  return result ? String(result.path || result.run_path || result.acceptance_report_path || result.report_path || result.genre_strategy_pack_path || result.style_profile_path || "") : "";
}

function ResultPanel({ result }: { result: RunResult | null }) {
  const path = primaryPath(result);
  return (
    <div className="panel">
      <PanelHeader title="Run Result" icon={<CheckCircle2 size={18} />} />
      <p className="pathText">{path || "No run yet"}</p>
      <pre className="jsonPreview">{result ? JSON.stringify(result, null, 2).slice(0, 1600) : "{}"}</pre>
    </div>
  );
}

function ArtifactInspector({ seedPath }: { seedPath: string }) {
  const [leftPath, setLeftPath] = useState(seedPath);
  const [rightPath, setRightPath] = useState("");
  const [leftAsset, setLeftAsset] = useState<RunResult | null>(null);
  const [rightAsset, setRightAsset] = useState<RunResult | null>(null);
  const [message, setMessage] = useState("");
  const [repairNote, setRepairNote] = useState("Review required before any outline, chapter, or release mutation.");

  useEffect(() => {
    if (seedPath) setLeftPath(seedPath);
  }, [seedPath]);

  async function load(path: string, side: "left" | "right") {
    setMessage("");
    const asset = await fetchJson<RunResult>(`/product/assets/detail?path=${encodeURIComponent(path)}`);
    if (side === "left") setLeftAsset(asset);
    else setRightAsset(asset);
  }

  async function markNeedsReview() {
    if (!leftPath) return;
    const asset = await fetchJson<RunResult>("/product/assets/detail", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: leftPath, status: "needs_review", notes: repairNote })
    });
    setLeftAsset(asset);
    setMessage("Review marker saved. No story plan, chapter, or release package was changed.");
  }

  const leftContent = leftAsset?.content && typeof leftAsset.content === "object" ? leftAsset.content as Record<string, unknown> : {};
  const rightContent = rightAsset?.content && typeof rightAsset.content === "object" ? rightAsset.content as Record<string, unknown> : {};
  const comparison = leftAsset && rightAsset ? {
    left_type: leftAsset.type,
    right_type: rightAsset.type,
    shared_content_keys: Object.keys(leftContent).filter((key) => key in rightContent),
    left_only_keys: Object.keys(leftContent).filter((key) => !(key in rightContent)),
    right_only_keys: Object.keys(rightContent).filter((key) => !(key in leftContent))
  } : null;

  return (
    <section className="panel">
      <PanelHeader title="Artifact Inspector" icon={<GitCompare size={18} />} />
      <div className="repairBoundary">
        <strong>Review-only repair boundary</strong>
        <span>This action only updates asset review metadata. It never edits outlines, chapters, characters, release packages, or platform state.</span>
      </div>
      {message ? <div className="statusLine" role="status" aria-live="polite">{message}</div> : null}
      <div className="formGrid contentIntelligenceRepairGrid">
        <label className="inlineField">
          <span>Primary asset path</span>
          <input value={leftPath} onChange={(event) => setLeftPath(event.target.value)} placeholder="data/.../asset.json" />
        </label>
        <label className="inlineField">
          <span>Comparison asset path</span>
          <input value={rightPath} onChange={(event) => setRightPath(event.target.value)} placeholder="data/.../asset.json" />
        </label>
      </div>
      <label className="inlineField">
        <span>Review note</span>
        <textarea rows={3} value={repairNote} onChange={(event) => setRepairNote(event.target.value)} />
      </label>
      <div className="studioActions">
        <button className="secondaryButton" type="button" disabled={!leftPath} onClick={() => load(leftPath, "left")}>Load primary asset</button>
        <button className="secondaryButton" type="button" disabled={!rightPath} onClick={() => load(rightPath, "right")}>Load comparison asset</button>
        <button className="secondaryButton" type="button" disabled={!leftPath || !repairNote.trim()} onClick={markNeedsReview}>Save review marker</button>
      </div>
      <div className="artifactSummaryGrid" aria-label="Artifact review summary">
        <div>
          <span>Primary</span>
          <strong>{String(leftAsset?.type || "Not loaded")}</strong>
        </div>
        <div>
          <span>Comparison</span>
          <strong>{String(rightAsset?.type || "Not loaded")}</strong>
        </div>
        <div>
          <span>Shared keys</span>
          <strong>{comparison ? comparison.shared_content_keys.length : 0}</strong>
        </div>
        <div>
          <span>Review state</span>
          <strong>{String((leftAsset?.content && typeof leftAsset.content === "object" ? (leftAsset.content as Record<string, unknown>).status : "") || leftAsset?.status || "Unchanged")}</strong>
        </div>
      </div>
      <pre className="jsonPreview">{JSON.stringify({ left: leftAsset, right: rightAsset, comparison }, null, 2).slice(0, 2200)}</pre>
    </section>
  );
}

function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<RunResult | null>(null);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    try {
      setResult((await action()) as RunResult);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  return { busy, error, result, run };
}

export function GenreConsolePage() {
  const { busy, error, result, run } = useAction();
  const [genre, setGenre] = useState("mystery");
  const [subgenre, setSubgenre] = useState("police_procedural");
  const [strategyPath, setStrategyPath] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [catalog, setCatalog] = useState<RunResult | null>(null);

  useEffect(() => {
    fetchJson<RunResult>("/product/genre/catalog").then(setCatalog).catch(() => undefined);
  }, []);

  async function buildPack() {
    const payload = await postJson("/product/genre/strategy-pack", { genre, subgenre, project_id: "ui-local", platform_id: "local" }) as RunResult;
    setStrategyPath(String(payload.genre_strategy_pack_path || ""));
    return payload;
  }

  return (
    <FeatureShell title="Genre Console" subtitle="Genre OS strategy pack inspect/run console." eyebrow="Content Intelligence">
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Build / Gate" icon={<Library size={18} />} />
          <div className="formGrid">
            <input value={genre} onChange={(event) => setGenre(event.target.value)} placeholder="genre" />
            <input value={subgenre} onChange={(event) => setSubgenre(event.target.value)} placeholder="subgenre" />
            <input value={strategyPath} onChange={(event) => setStrategyPath(event.target.value)} placeholder="genre strategy pack path" />
            <input value={targetPath} onChange={(event) => setTargetPath(event.target.value)} placeholder="target asset path" />
          </div>
          <div className="studioActions">
            <button className="primaryButton" disabled={busy} onClick={() => run(buildPack)}>Build Strategy Pack</button>
            <button className="secondaryButton" disabled={busy || !strategyPath} onClick={() => run(() => postJson("/product/genre/risk-gate", { strategy_pack_path: strategyPath, target_path: targetPath || undefined, evidence: {} }))}>Run Risk Gate</button>
          </div>
        </div>
        <ResultPanel result={result} />
      </section>
      <section className="panel">
        <PanelHeader title="Catalog" icon={<Boxes size={18} />} />
        <pre className="jsonPreview">{JSON.stringify(catalog, null, 2).slice(0, 1800)}</pre>
      </section>
      <ArtifactInspector seedPath={primaryPath(result)} />
    </FeatureShell>
  );
}

export function StyleConsolePage() {
  const { busy, error, result, run } = useAction();
  const [sampleText, setSampleText] = useState("证据。行动。转折。代价。 ".repeat(40));
  const [samplePath, setSamplePath] = useState("");
  const [fingerprintPath, setFingerprintPath] = useState("");
  const [profilePath, setProfilePath] = useState("");
  const [targetPath, setTargetPath] = useState("");

  async function ingest() {
    const payload = await postJson("/product/style/sample", { sample_text: sampleText, project_id: "ui-local", rights: { license: "operator-authorized" } }) as RunResult;
    setSamplePath(String(payload.path || ""));
    return payload;
  }

  async function fingerprint() {
    const payload = await postJson("/product/style/fingerprint", { sample_path: samplePath }) as RunResult;
    setFingerprintPath(String(payload.path || ""));
    return payload;
  }

  async function profile() {
    const payload = await postJson("/product/style/profile", { fingerprint_path: fingerprintPath, style_name: "UI style profile" }) as RunResult;
    setProfilePath(String(payload.style_profile_path || ""));
    return payload;
  }

  return (
    <FeatureShell title="Style Console" subtitle="Style OS source-isolated sample, fingerprint, profile, and drift gate console." eyebrow="Content Intelligence">
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Ingest / Extract / Gate" icon={<FileText size={18} />} />
          <textarea rows={5} value={sampleText} onChange={(event) => setSampleText(event.target.value)} />
          <div className="formGrid">
            <input value={samplePath} onChange={(event) => setSamplePath(event.target.value)} placeholder="style sample path" />
            <input value={fingerprintPath} onChange={(event) => setFingerprintPath(event.target.value)} placeholder="fingerprint path" />
            <input value={profilePath} onChange={(event) => setProfilePath(event.target.value)} placeholder="style profile path" />
            <input value={targetPath} onChange={(event) => setTargetPath(event.target.value)} placeholder="draft target path" />
          </div>
          <div className="studioActions">
            <button className="primaryButton" disabled={busy} onClick={() => run(ingest)}>Ingest Sample</button>
            <button className="secondaryButton" disabled={busy || !samplePath} onClick={() => run(fingerprint)}>Extract Fingerprint</button>
            <button className="secondaryButton" disabled={busy || !fingerprintPath} onClick={() => run(profile)}>Build Profile</button>
            <button className="secondaryButton" disabled={busy || !profilePath || !targetPath} onClick={() => run(() => postJson("/product/style/drift-gate", { style_profile_path: profilePath, target_path: targetPath }))}>Run Drift Gate</button>
          </div>
        </div>
        <ResultPanel result={result} />
      </section>
      <ArtifactInspector seedPath={primaryPath(result)} />
    </FeatureShell>
  );
}

export function CanonGraphWorkbenchV2Page() {
  const { busy, error, result, run } = useAction();
  const [plugin, setPlugin] = useState("mystery_evidence_chain_engine");
  const [targetPath, setTargetPath] = useState("");
  const [artifactText, setArtifactText] = useState("稳定规则下的原创章节。");

  return (
    <FeatureShell title="Canon Graph Workbench 2.0" subtitle="Run schema-backed Canon Graph genre plugins against drafts, outlines, or release evidence." eyebrow="Content Intelligence">
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Plugin Gate" icon={<Network size={18} />} />
          <select value={plugin} onChange={(event) => setPlugin(event.target.value)}>
            {["fantasy_power_scale_engine", "mystery_evidence_chain_engine", "romance_relationship_state_engine", "historical_faction_network_engine", "sci_fi_rule_consistency_engine", "horror_rule_contamination_engine"].map((item) => <option key={item}>{item}</option>)}
          </select>
          <input value={targetPath} onChange={(event) => setTargetPath(event.target.value)} placeholder="target asset path, optional when artifact text is provided" />
          <textarea rows={5} value={artifactText} onChange={(event) => setArtifactText(event.target.value)} />
          <button className="primaryButton" disabled={busy} onClick={() => run(() => postJson("/product/canon-graph/plugin", { plugin, target_path: targetPath || undefined, artifact_text: artifactText }))}>Run Canon Plugin</button>
        </div>
        <ResultPanel result={result} />
      </section>
      <ArtifactInspector seedPath={primaryPath(result)} />
    </FeatureShell>
  );
}

export function QualityEvalV2Page() {
  const { busy, error, result, run } = useAction();
  const [rubricPath, setRubricPath] = useState("");
  const [targetPath, setTargetPath] = useState("");
  const [reportPath, setReportPath] = useState("");
  const [suiteType, setSuiteType] = useState("opening_3");
  const [providerMode, setProviderMode] = useState("fixture");
  const [providerName, setProviderName] = useState("fixture-provider");
  const [providerModel, setProviderModel] = useState("premium-judge-fixture");
  const [budgetCap, setBudgetCap] = useState("1.0");
  const [requireExternalProof, setRequireExternalProof] = useState(false);

  async function rubric() {
    const payload = await postJson("/product/quality/rubric-pack", { genre_id: "mystery", platform_id: "local" }) as RunResult;
    setRubricPath(String(payload.path || ""));
    return payload;
  }

  async function suite() {
    const payload = await postJson("/product/quality/suite", { suite_type: suiteType, target_paths: targetPath ? [targetPath] : [], rubric_path: rubricPath }) as RunResult;
    setReportPath(String(payload.path || ""));
    return payload;
  }

  async function providerJudge() {
    const fixture = {
      text: JSON.stringify({
        recommendation: "ready",
        scores: {
          genre_promise: 88,
          platform_rhythm: 86,
          style_adherence: 85,
          hook_strength: 87,
          conflict_density: 84,
          character_motivation: 86,
          canon_consistency: 90,
          ai_flavor_risk: 83
        },
        rationale: "fixture provider judge for local UI smoke"
      }),
      usage: { input_tokens: 800, output_tokens: 160, total_tokens: 960 },
      cost: { amount: 0.01, currency: "USD", source: "ui_fixture" },
      provider: providerName,
      model: providerModel
    };
    const payload = await postJson("/product/quality/provider-judge", {
      suite_type: suiteType,
      target_paths: targetPath ? [targetPath] : [],
      rubric_path: rubricPath,
      platform_id: "local",
      mode: providerMode,
      provider_config: { provider: providerName, model_name: providerModel, mode: providerMode },
      provider_route: {
        provider: providerName,
        model_name: providerModel,
        approval_status: "approved",
        approval_id: "ui-operator-approval",
        approved_by: "operator",
        production_provider_allowlist: [providerName]
      },
      operator_approval: { status: "approved", approval_id: "ui-operator-approval", approved_by: "operator", reason: "manual UI run" },
      budget_cap: Number(budgetCap || 0),
      allow_mock_fixture: providerMode === "fixture",
      fixture_judge_response: providerMode === "fixture" ? fixture : {},
      require_external_provider_proof: requireExternalProof,
      environment: providerMode === "real" ? "production" : ""
    }) as RunResult;
    setReportPath(String(payload.path || ""));
    return payload;
  }

  return (
    <FeatureShell title="Quality Eval Console 2.0" subtitle="Run rubric packs, quality suites, and hard gates for content intelligence evidence." eyebrow="Content Intelligence">
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Rubric / Suite / Gate" icon={<ShieldCheck size={18} />} />
          <select value={suiteType} onChange={(event) => setSuiteType(event.target.value)}>
            {["opening_3", "golden_10", "volume_30", "longform_100"].map((item) => <option key={item}>{item}</option>)}
          </select>
          <input value={rubricPath} onChange={(event) => setRubricPath(event.target.value)} placeholder="rubric path" />
          <input value={targetPath} onChange={(event) => setTargetPath(event.target.value)} placeholder="target asset path" />
          <input value={reportPath} onChange={(event) => setReportPath(event.target.value)} placeholder="quality report path" />
          <select value={providerMode} onChange={(event) => setProviderMode(event.target.value)}>
            <option value="fixture">fixture provider</option>
            <option value="real">real provider</option>
          </select>
          <input value={providerName} onChange={(event) => setProviderName(event.target.value)} placeholder="provider, e.g. claude-code" />
          <input value={providerModel} onChange={(event) => setProviderModel(event.target.value)} placeholder="provider model" />
          <input value={budgetCap} onChange={(event) => setBudgetCap(event.target.value)} placeholder="budget cap" />
          <label className="inlineCheckbox">
            <input type="checkbox" checked={requireExternalProof} onChange={(event) => setRequireExternalProof(event.target.checked)} />
            <span>Require external provider proof</span>
          </label>
          <div className="studioActions">
            <button className="primaryButton" disabled={busy} onClick={() => run(rubric)}>Build Rubric</button>
            <button className="secondaryButton" disabled={busy || !targetPath} onClick={() => run(suite)}>Run Suite</button>
            <button className="secondaryButton" disabled={busy || !targetPath || !rubricPath} onClick={() => run(providerJudge)}>Run Provider Judge</button>
            <button className="secondaryButton" disabled={busy || !reportPath} onClick={() => run(() => postJson("/product/quality/gate", { quality_report_path: reportPath }))}>Run Gate</button>
          </div>
        </div>
        <ResultPanel result={result} />
      </section>
      <ArtifactInspector seedPath={primaryPath(result)} />
    </FeatureShell>
  );
}

export function LongChainProofConsolePage() {
  const { busy, error, result, run } = useAction();
  const [mode, setMode] = useState("deterministic_50");
  return (
    <FeatureShell title="Long-chain Proof Console" subtitle="Deterministic 50, mock 100, state-only 300, and opt-in provider proof runs." eyebrow="Content Intelligence">
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Run Proof" icon={<GitCompare size={18} />} />
          <select value={mode} onChange={(event) => setMode(event.target.value)}>
            {["deterministic_50", "mock_100", "state_only_300"].map((item) => <option key={item}>{item}</option>)}
          </select>
          <button className="primaryButton" disabled={busy} onClick={() => run(() => postJson("/product/long-chain-proof/run", { project_id: "ui-local", mode }))}>Run Long-chain Proof</button>
        </div>
        <ResultPanel result={result} />
      </section>
      <ArtifactInspector seedPath={primaryPath(result)} />
    </FeatureShell>
  );
}

export function PublishingFeedbackV2Page() {
  const { busy, error, result, run } = useAction();
  const [releasePath, setReleasePath] = useState("");
  const [uploadPath, setUploadPath] = useState("");
  const [commentReportPath, setCommentReportPath] = useState("");
  const [platformEndpoint, setPlatformEndpoint] = useState("");
  const [tokenEnv, setTokenEnv] = useState("");
  const [platformId, setPlatformId] = useState("fanqie");
  const [receiptText, setReceiptText] = useState("作品ID：demo-book\n章节ID：demo-chapter\n审核状态：审核中");

  async function upload() {
    const payload = await postJson("/product/publishing-adapters/upload-package", { release_package_path: releasePath, platform_id: platformId }) as RunResult;
    setUploadPath(String(payload.path || ""));
    return payload;
  }

  async function comments() {
    const payload = await postJson("/product/feedback-adapters/comments/cluster", {
      platform_id: "manual",
      comments: [
        { text: "节奏太慢，看到这里想弃书", characters: ["主角"] },
        { text: "反转好看，期待下一章", characters: ["侦探"] }
      ]
    }) as RunResult;
    setCommentReportPath(String(payload.report_path || ""));
    return payload;
  }

  return (
    <FeatureShell title="Publishing Feedback Console 2.0" subtitle="Manual upload packages, receipts, metrics, comment clustering, and human-gated mutation proposals." eyebrow="Content Intelligence">
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="workspaceGrid">
        <div className="panel">
          <PanelHeader title="Publishing / Feedback" icon={<Send size={18} />} />
          <input value={releasePath} onChange={(event) => setReleasePath(event.target.value)} placeholder="release package path" />
          <select value={platformId} onChange={(event) => setPlatformId(event.target.value)}>
            <option value="fanqie">Fanqie manual adapter</option>
            <option value="qidian">Qidian manual adapter</option>
            <option value="manual">Generic manual adapter</option>
          </select>
          <input value={uploadPath} onChange={(event) => setUploadPath(event.target.value)} placeholder="upload package path" />
          <input value={commentReportPath} onChange={(event) => setCommentReportPath(event.target.value)} placeholder="comment cluster report path" />
          <input value={platformEndpoint} onChange={(event) => setPlatformEndpoint(event.target.value)} placeholder="platform API endpoint" />
          <input value={tokenEnv} onChange={(event) => setTokenEnv(event.target.value)} placeholder="token env var name" />
          <textarea rows={3} value={receiptText} onChange={(event) => setReceiptText(event.target.value)} placeholder="platform receipt text" />
          <div className="studioActions">
            <button className="primaryButton" disabled={busy || !releasePath} onClick={() => run(upload)}>Build Upload Package</button>
            <button className="secondaryButton" disabled={busy || !uploadPath} onClick={() => run(() => postJson("/product/publishing-adapters/platform-gate", { platform_id: platformId, upload_package_path: uploadPath }))}>Run Platform Gate</button>
            <button className="secondaryButton" disabled={busy || !uploadPath} onClick={() => run(() => postJson("/product/publishing-adapters/receipt/parse", { platform_id: platformId, receipt_text: receiptText, upload_package_path: uploadPath }))}>Parse Receipt</button>
            <button className="secondaryButton" disabled={busy || !uploadPath} onClick={() => run(() => postJson("/product/publishing-adapters/receipt", { platform_id: platformId, platform_book_id: `${platformId}-book`, upload_package_path: uploadPath }))}>Record Receipt</button>
            <button className="secondaryButton" disabled={busy || !uploadPath || !platformEndpoint} onClick={() => run(() => postJson("/product/publishing-adapters/publish", { upload_package_path: uploadPath, platform_config: { platform_id: "api-platform", endpoint: platformEndpoint, token_env: tokenEnv } }))}>Publish via API</button>
            <button className="secondaryButton" disabled={busy} onClick={() => run(() => postJson("/product/feedback-adapters/metrics", { platform_id: platformId, chapter_metrics: [{ chapter_no: 1, retention: 0.9 }, { chapter_no: 2, retention: 0.7 }] }))}>Import Metrics</button>
            <button className="secondaryButton" disabled={busy} onClick={() => run(comments)}>Cluster Comments</button>
            <button className="secondaryButton" disabled={busy || !commentReportPath} onClick={() => run(() => postJson("/product/feedback-adapters/mutation-proposal", { source_feedback_paths: [commentReportPath], target_assets: [{ asset_type: "outline", path: "manual" }], proposed_changes: [{ domain: "outline", action: "tighten_next_hook" }] }))}>Create Mutation Proposal</button>
          </div>
        </div>
        <ResultPanel result={result} />
      </section>
      <ArtifactInspector seedPath={primaryPath(result)} />
    </FeatureShell>
  );
}

export function AgentOperationCoveragePage() {
  const [contracts, setContracts] = useState<OperationContract[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    fetchJson<{ operations?: OperationContract[]; contracts?: OperationContract[] }>("/product/agents/operation-contracts")
      .then((payload) => setContracts(payload.operations || payload.contracts || []))
      .catch((caught) => setError(caught instanceof Error ? caught.message : String(caught)));
  }, []);

  const v7Operations = [
    "build-genre-strategy-pack",
    "run-genre-risk-gate",
    "ingest-style-sample",
    "extract-style-fingerprint",
    "build-style-profile",
    "run-style-drift-gate",
    "run-canon-graph-plugin",
    "run-quality-suite",
    "run-provider-quality-judge",
    "run-quality-gate",
    "run-long-chain-proof",
    "build-platform-upload-package",
    "record-platform-receipt",
    "publish-platform-upload-package",
    "import-platform-metrics",
    "cluster-platform-comments",
    "create-feedback-mutation-proposal"
  ];

  return (
    <FeatureShell title="Agent Operation Coverage" subtitle="Coverage view for V7 content intelligence Agent operations." eyebrow="Agent Runtime">
      {error ? <div className="errorLine">{error}</div> : null}
      <section className="panel">
        <PanelHeader title="V7 Operation Coverage" icon={<BrainCircuit size={18} />} />
        <DataTable
          columns={["Operation", "Registered", "Agent", "Outputs"]}
          rows={v7Operations.map((operation) => {
            const contract = contracts.find((item) => item.operation === operation || item.aliases?.includes(operation));
            return [
              operation,
              contract ? <span className="badge ok">yes</span> : <span className="badge warn">missing</span>,
              contract?.agent_key || "-",
              (contract?.output_types || []).join(", ")
            ];
          })}
        />
      </section>
    </FeatureShell>
  );
}
