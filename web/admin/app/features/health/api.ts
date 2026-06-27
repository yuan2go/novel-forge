import { fetchJson, postJson } from "../../shared/api";
import type { BackupRow, MinioStatus, ProjectHealthReport, ProjectRow, QdrantSearchResult } from "../../shared/types";

export function loadHealthData(projectId?: string) {
  return Promise.all([
    fetchJson<ProjectRow[]>("/product/projects"),
    fetchJson<ProjectHealthReport>(projectId ? `/product/system/health?project_id=${encodeURIComponent(projectId)}` : "/product/system/health"),
    fetchJson<BackupRow[]>("/product/system/backups?limit=40"),
    fetchJson<MinioStatus>("/product/minio/objects?limit=80")
  ]);
}

export function createBackup() {
  return postJson("/product/system/backups", {});
}

export function restoreBackup(backupPath: string) {
  return postJson("/product/system/restore", { backup_path: backupPath, confirm: true });
}

export function archiveEvents() {
  return postJson("/product/system/events/archive", { keep_latest: 500, confirm: true });
}

export function rebuildQdrantIndex() {
  return postJson("/product/qdrant/index", { batch_size: 32 });
}

export function qdrantSearch(query: string, projectId?: string): Promise<QdrantSearchResult> {
  return postJson("/product/qdrant/search", {
    query,
    project_id: projectId || null,
    limit: 12
  }) as Promise<QdrantSearchResult>;
}

export function syncMinio() {
  return postJson("/product/minio/sync", {});
}
