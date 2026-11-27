import type { ReactNode } from "react";

export function PanelHeader({ title, icon }: { title: string; icon: ReactNode }) {
  return (
    <div className="panelHeader">
      <h2>{title}</h2>
      {icon}
    </div>
  );
}

export function DataTable({ columns, rows, emptyText = "Empty" }: { columns: string[]; rows: ReactNode[][]; emptyText?: string }) {
  return (
    <div className="tableWrap">
      <table>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex}>{cell}</td>
              ))}
            </tr>
          ))}
          {!rows.length ? (
            <tr>
              <td colSpan={columns.length} className="emptyCell">
                {emptyText}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}

export function Metric({ label, value, code = false }: { label: string; value: string; code?: boolean }) {
  return (
    <div>
      <span className="metricLabel">{label}</span>
      <strong className={code ? "pathText" : undefined}>{value}</strong>
    </div>
  );
}

export function statusClass(status: string): string {
  if (["completed", "succeeded", "recovered", "passed", "ready", "active"].includes(status)) return "badge ok";
  if (["failed", "dead_letter", "needs_revision", "cancelled", "blocked", "high"].includes(status)) return "badge warn";
  return "badge muted";
}
