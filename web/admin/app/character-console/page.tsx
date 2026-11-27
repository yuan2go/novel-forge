import { EditableAssetConsolePage } from "../features/os/EditableAssetConsolePage";

export default function CharacterConsoleRoutePage() {
  return (
    <EditableAssetConsolePage
      config={{
        title: "Character Console",
        subtitle: "人物卡、人物状态账本和漂移证据的可编辑控制台。",
        assetTypes: ["character_card", "character_state_ledger"],
        createTypes: ["character_card"],
        primaryLinks: [{ label: "Assets", href: "/assets?library=bible" }, { label: "Longform Stability", href: "/longform-stability" }],
        guidance: "人物状态变化应由 ReviewIssue、Recap 或明确编辑动作驱动；保存后检查后续章节上下文。"
      }}
    />
  );
}
