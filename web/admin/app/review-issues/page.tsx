import { EditableAssetConsolePage } from "../features/os/EditableAssetConsolePage";

export default function ReviewIssuesRoutePage() {
  return (
    <EditableAssetConsolePage
      config={{
        title: "ReviewIssue Console",
        subtitle: "可阻断问题、审稿报告、修订任务和修订计划的可编辑控制台。",
        assetTypes: ["review_issue", "review_report", "revision_task", "revision_plan"],
        primaryLinks: [{ label: "Agent Center", href: "/agent-center" }, { label: "Review Rework", href: "/review-rework" }],
        guidance: "critical/high blocking issue 会阻断 canonical chapter 和 release package；不要只改状态而不保留修复证据。"
      }}
    />
  );
}
