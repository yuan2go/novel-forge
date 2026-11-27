import { EditableAssetConsolePage } from "../features/os/EditableAssetConsolePage";

export default function CanonConsoleRoutePage() {
  return (
    <EditableAssetConsolePage
      config={{
        title: "Canon Console",
        subtitle: "正典、设定规则、事实账本和 Canon patch 的本地可编辑控制台。",
        assetTypes: ["canon_database", "canon_patch", "canon_graph_snapshot", "continuity_bible", "chapter_state", "fact_ledger", "world_bible", "power_scale_rule"],
        createTypes: ["world_bible", "continuity_bible", "power_scale_rule"],
        primaryLinks: [{ label: "Novel KG", href: "/novel-kg" }, { label: "Longform Stability", href: "/longform-stability" }],
        guidance: "Canon 资产保存后仍需通过 KG/Longform gate 验证；不要在这里绕过 ReviewIssue 阻断。"
      }}
    />
  );
}
