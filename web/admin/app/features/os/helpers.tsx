import type { ReactNode } from "react";
import type { AssetDetail, AssetRow } from "../../shared/types";

export function splitLines(value: string): string[] {
  return value
    .split("\n")
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parseIndexList(value: string): number[] {
  return value
    .split(/[,\n]/)
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isInteger(item) && item >= 0);
}

export function compactJson(value: unknown, maxLength = 120): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value !== "object") return String(value);
  const text = JSON.stringify(value);
  return text.length > maxLength ? `${text.slice(0, maxLength)}...` : text;
}

export function pathCell(path?: string, key?: string): ReactNode {
  return <span className="pathText" key={key || path || "path"}>{path || "-"}</span>;
}

export function assetOptions(assets: AssetRow[], types: string[]): AssetRow[] {
  const wanted = new Set(types);
  return assets.filter((asset) => wanted.has(asset.type));
}

export function selectedWorkspace(projects: Array<{ project_id: string; path?: string }>, projectId: string): string | undefined {
  return projects.find((project) => project.project_id === projectId)?.path;
}

export function detailContent(detail: AssetDetail | null): Record<string, unknown> {
  const asset = detail?.asset as Record<string, unknown> | undefined;
  const content = asset?.content;
  return content && typeof content === "object" ? content as Record<string, unknown> : {};
}

export function formatMoney(value: unknown, currency = "USD"): string {
  const amount = Number(value ?? 0);
  return `${currency} ${amount.toFixed(4)}`;
}

export function durationLabel(span: Record<string, unknown>): string {
  const duration = Number(span.duration_ms ?? span.elapsed_ms ?? 0);
  if (duration > 0) return `${Math.round(duration)} ms`;
  const start = Date.parse(String(span.started_at || ""));
  const end = Date.parse(String(span.finished_at || ""));
  if (!Number.isNaN(start) && !Number.isNaN(end) && end >= start) return `${end - start} ms`;
  return "-";
}
