import { EditableAssetConsolePage } from "../features/os/EditableAssetConsolePage";

export default function ArcConsoleRoutePage() {
  return (
    <EditableAssetConsolePage
      config={{
        title: "Arc Console",
        subtitle: "长篇主线、阶段弧线、章节状态和节奏治理资产。",
        assetTypes: ["arc_plan", "long_form_macro_plan", "chapter_state"],
        primaryLinks: [{ label: "Longform Stability", href: "/longform-stability" }, { label: "Impact", href: "/impact" }],
        guidance: "Arc 修改会影响 Context Builder、Longform Recap 和发布门禁；保存前确认章节范围和回滚点。"
      }}
    />
  );
}
