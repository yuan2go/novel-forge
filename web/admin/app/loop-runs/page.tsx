import { EditableAssetConsolePage } from "../features/os/EditableAssetConsolePage";

export default function LoopRunsRoutePage() {
  return (
    <EditableAssetConsolePage
      config={{
        title: "LoopRun Monitor",
        subtitle: "LoopRun、LoopStep、Checkpoint 和 Report 的运行监控台。",
        assetTypes: ["loop_run", "loop_step", "loop_checkpoint", "loop_report"],
        primaryLinks: [{ label: "Agent Center", href: "/agent-center" }, { label: "Context Builder", href: "/context" }],
        guidance: "Loop 资产是 runtime evidence，默认禁止进入 generation RAG；失败 loop 应保留 stop condition 和 checkpoint。"
      }}
    />
  );
}
