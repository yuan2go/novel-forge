import { EditableAssetConsolePage } from "../features/os/EditableAssetConsolePage";

export default function LongformRecapRoutePage() {
  return (
    <EditableAssetConsolePage
      config={{
        title: "Longform Recap Reports",
        subtitle: "长篇复盘报告、写回包、人物漂移和伏笔状态的可编辑查看台。",
        assetTypes: ["longform_recap_report", "chapter_state", "arc_plan", "character_state_ledger", "foreshadowing_graph"],
        primaryLinks: [{ label: "Run Recap", href: "/longform-stability" }, { label: "Loop Runs", href: "/loop-runs" }],
        guidance: "Recap 报告是治理证据，不是正文素材；后续章节应通过 Context Builder 读取压缩状态。"
      }}
    />
  );
}
