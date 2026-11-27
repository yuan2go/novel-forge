export type WorkbenchRow = {
  path: string;
  id: string;
  type: string;
  title: string;
  source: string;
  chapter: number | string;
  score?: number;
  risk_level: string;
  updated_at: string;
  summary: string;
  tags: string[];
};

export type DraftWorkbench = {
  chapter_plans: WorkbenchRow[];
  drafts: WorkbenchRow[];
  reviews: WorkbenchRow[];
  revision_plans: WorkbenchRow[];
  workspace: Array<{ path: string; title: string; project_id?: string }>;
};

export type DraftEditorState = {
  path: string;
  id: string;
  title: string;
  chapter: number | string;
  text: string;
  version_index: number;
  status: string;
};

export type ManuscriptTraceRow = WorkbenchRow & {
  status: string;
  content: Record<string, unknown>;
  metadata: Record<string, unknown>;
  references: string[];
};

export type ManuscriptWorkbench = {
  project_id: string;
  selected_draft_path: string;
  selected_draft: (DraftEditorState & {
    word_count: number;
    source: string;
    references: string[];
    context_bundle_path: string;
    context_bundle_id: string;
    generation_run_path: string;
    generation_run_id: string;
    agent_run_path: string;
    production_context: Record<string, unknown>;
    retrieved_context: Record<string, unknown>;
    copyright_boundary: string;
    updated_at: string;
  }) | null;
  chapters: Array<{
    chapter: number | string;
    latest_draft_path: string;
    latest_title: string;
    draft_count: number;
    review_count: number;
    latest_updated_at: string;
    status: string;
  }>;
  versions: ManuscriptTraceRow[];
  generation_runs: ManuscriptTraceRow[];
  context_bundles: ManuscriptTraceRow[];
  context_sources: Array<{
    id: string;
    path: string;
    type: string;
    title: string;
    rank: number | string;
    score: number | string;
    ranker: string;
    backend: string;
    risk_level: string;
    preview: string;
    source_bundle_path: string;
  }>;
  reviews: ManuscriptTraceRow[];
  revision_plans: ManuscriptTraceRow[];
  editor_artifacts: ManuscriptTraceRow[];
  agent_runs: ManuscriptTraceRow[];
  agent_events: ManuscriptTraceRow[];
  trace_summary: {
    has_selected_draft: boolean;
    context_source_count: number;
    generation_run_count: number;
    review_count: number;
    editor_artifact_count: number;
    agent_run_count: number;
    latest_review_score?: number | null;
    agent_statuses: Record<string, number>;
    ready_for_review: boolean;
  };
};

export type ProjectOption = {
  project_id: string;
  title: string;
  path: string;
  status?: string;
};

export type DraftSaveResult = {
  draft_path?: string;
  editor?: DraftEditorState;
};

export type ExportResult = {
  path?: string;
  format?: string;
  size_bytes?: number;
};

export function traceField(row: ManuscriptTraceRow, key: string): string {
  const value = row.content?.[key] ?? row.metadata?.[key] ?? (row as unknown as Record<string, unknown>)[key];
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return "";
}
