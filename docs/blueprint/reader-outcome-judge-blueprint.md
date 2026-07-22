# Reader Outcome Judge Blueprint

Reader Outcome Judge（ROJ）的设计文档已拆分为可维护分册，并按当前单书闭环优先级完成架构收敛。

主入口：

- [Reader Outcome Judge（ROJ）完整设计蓝图](reader-outcome-judge/README.md)

分册：

1. [Authority 与生产链接入](reader-outcome-judge/01-authority-and-production-integration.md)
2. [Judge 契约、特征与校准](reader-outcome-judge/02-judge-contracts-and-calibration.md)
3. [读者反馈、实验与权威契约](reader-outcome-judge/03-feedback-experiments-and-authority-contracts.md)
4. [模型治理、测试、成熟度与实施路线](reader-outcome-judge/04-model-governance-testing-and-roadmap.md)

关键实施边界：

```text
ROJ-M0/M1：Shadow Sidecar，不进入 Chapter Completion Contract
ROJ-M2：Human Anchored，仍以 Advisory 为主
ROJ-M3：真实行为校准后才允许输出 calibrated probability
ROJ-M4：受控随机实验后才允许声称 causal validated
ROJ-M5：仅在明确平台、题材、Segment 和风险边界内有限自治
```

未校准 LLM 输出必须称为 `raw score` 或 `ordinal band`，不得称为真实概率。

文档状态：`ACTIVE TARGET DESIGN`。该状态不表示 ROJ 已实现、已接入真实读者行为、已完成因果实验或已通过生产验证。