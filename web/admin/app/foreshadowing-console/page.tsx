import { EditableAssetConsolePage } from "../features/os/EditableAssetConsolePage";

export default function ForeshadowingConsoleRoutePage() {
  return (
    <EditableAssetConsolePage
      config={{
        title: "Foreshadowing Console",
        subtitle: "伏笔线程、伏笔图谱、回收状态和长篇稳定性证据。",
        assetTypes: ["foreshadowing_thread", "foreshadowing_graph"],
        createTypes: ["foreshadowing_thread"],
        primaryLinks: [{ label: "Novel KG", href: "/novel-kg" }, { label: "Longform Stability", href: "/longform-stability" }],
        guidance: "伏笔变更需要同步检查 open/payoff 状态，避免后续 recap 和 publish gate 产生阻断。"
      }}
    />
  );
}
