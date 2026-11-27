import { EditableAssetConsolePage } from "../features/os/EditableAssetConsolePage";

export default function PublishGateRoutePage() {
  return (
    <EditableAssetConsolePage
      config={{
        title: "Publish Gate Console",
        subtitle: "发布门禁、Release Package、发布计划和发布日志的可编辑控制台。",
        assetTypes: ["publish_gate_report", "release_package", "publishing_plan", "publishing_log"],
        primaryLinks: [{ label: "Publishing Center", href: "/quality?tab=publishing" }, { label: "Review Issues", href: "/review-issues" }],
        guidance: "Publish Gate 必须尊重 blocking ReviewIssue、Longform Stability Gate、MKAOS risk 和 source isolation。"
      }}
    />
  );
}
