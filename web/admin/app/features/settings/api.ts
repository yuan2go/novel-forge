import { fetchJson, postJson } from "../../shared/api";
import type { FeatureAssetRow, ProjectRow } from "../../shared/types";

export type SystemHealth = {
  configured_services: Record<string, boolean>;
  model_providers: Record<string, Record<string, unknown>>;
  embedding_provider: Record<string, unknown>;
  postgresql?: Record<string, unknown>;
};

export type PostgresStrict = {
  ready: boolean;
  strict: boolean;
  write_through: boolean;
  checks: Array<{ name: string; ok: boolean; message: string }>;
  errors: string[];
};

export function loadSettingsData(projectId?: string) {
  const settings = projectId
    ? `/product/settings/assets?project_id=${encodeURIComponent(projectId)}&limit=120`
    : "/product/settings/assets?limit=120";
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<FeatureAssetRow[]>(settings),
    fetchJson<SystemHealth>("/health"),
    fetchJson<PostgresStrict>("/product/system/postgres/strict-check")
  ]);
}

export function createSettingsProfile(body: {
  title: string;
  workspacePath?: string;
  provider: string;
  model: string;
  strict: boolean;
}) {
  return postJson("/product/settings/profile", {
    title: body.title,
    workspace_path: body.workspacePath || null,
    model_routing: { default_provider: body.provider, default_model: body.model },
    storage_config: {},
    agent_defaults: { permission_profiles_required: true, tool_allowlist_enforced: true },
    validation: {
      strict_local_prod: body.strict,
      schema_validation_required: true,
      project_scope_guard_required: true,
      copyright_boundary_required: true
    },
    status: "active"
  });
}

export function createPromptVersion(promptId: string, version: string, taskType: string, template: string) {
  return postJson("/product/evaluation/prompt-version", {
    prompt_id: promptId,
    version,
    task_type: taskType,
    template,
    status: "active"
  });
}
