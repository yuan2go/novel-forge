# 位置敏感性评测的研究依据

核查日期：2026-10-06。Novel Forge 实验基线：`9bd1d34f24ebe302533ffc26c72bda97336c4152`。邮件仅作为问题来源；本文件不转载邮件正文，也不以邮件推断本项目模型已经发生中段遗忘。

## 原始研究支持的结论

[Lost in the Middle, v3](https://arxiv.org/html/2307.03172v3)，§2.1–2.3：固定问题、含答案文档与干扰文档集合，通过重排文档改变证据位置；用 greedy decoding 比较回答准确率。研究观察到部分受测历史模型的中段性能下降。§3 的随机 UUID 键值检索进一步减少自然语言语义混淆。§4.2 表明查询前后重复对简单检索与多文档 QA 的效果不同，因此检索通过不能替代复杂任务表现。[作者代码与数据](https://github.com/nelson-liu/lost-in-the-middle/tree/29b8a6d042ce29abccee3db1a73171a107d7e6af)。

[RULER, v3](https://arxiv.org/html/2404.06654v3)，§3、§4：通过检索、多跳追踪、聚合和 QA 检查长度增加后的行为。§8 明确说明论文按长度报告单一指标，没有提供深度分层表现；合成代理任务与真实长上下文任务的相关性亦未验证。因此长度分数不能回答本项目同一关键证据移动后的差异，不能作为 Chapter/Draft 质量的替代证据。

这个论文限制不能直接泛化为现版 RULER 代码完全没有位置逻辑。核查到的 [NVIDIA/RULER 固定源码](https://github.com/NVIDIA/RULER/blob/c3f5e3b4f87f97e048793bb510a3a6b19a46bf3a/scripts/data/synthetic/niah.py) 已定义 40 个 `DEPTHS`、随机采样插入点，并输出 `token_position_answer`。该生成器仍没有构造同一问题、同一证据和同一背景的前／中／后三元组；仅运行默认随机样本并聚合不足以识别配对位置效应。该仓库 SHA 由官方 GitHub API 核查，提交日期为 2026-07-22。

## 对本实验的适用边界

- 论文支持“位置需要独立控制”的实验动机；不证明当前 Provider/model/profile 必然出现 U 型曲线。
- QA 或合成召回成功不证明人物知识边界、因果义务执行或正文一致性成功；四个维度需分别记分。
- 本实验的冻结构造、阈值和统计方案是项目设计建议，属于 `CONFIGURABLE_POLICY`，不是论文给出的运行时不变量。
- 局部 fixture、receipt 与序列化检查通过，最多说明实验输入可执行；真实模型表现仍需独立调用与输出证据。未调用时保持 `NOT_RUN`。

## 建议的配对设计

每个实验单元是 `case × model/profile × length × replicate` 的前／中／后三元组。保留 message role、system 内容、工具定义、任务指令、生成参数、背景块相对顺序、证据块原始字节及目标输出 schema；只改变关键证据块位置。不要把证据从 user 移到 system，也不要添加首尾摘要、查询重复或强化指令。

在最终 Provider 输入上记录证据起止偏移、角色及序列化 hash。字节长度相同不保证 tokenizer 的边界分词相同，必须复核实际模型 tokenizer 的总 token 数与证据位置；没有实际 tokenizer 时明确标记估计，不能声称精确 token 控制。目标深度与实测深度分开保存；无法达到指定区间的三元组不参与那个位置结论。

每个维度分别报告前、中、末的通过率和以下配对差值：

`middle_deficit = (front_score + end_score) / 2 - middle_score`

同时报告 `front - middle`、`end - middle` 与 `best - worst`。预注册主维度和失败阈值，不能事后选择最有利的位置作唯一对照。人物知识泄漏、due obligation 跳过与因果顺序破坏应保留逐条反例，不被总平均分抵消。

调用顺序用固定种子的轮换或随机化平衡，并记录 seed；相同 seed 若 Provider 不支持，记录 `UNSUPPORTED`。重复是同一 case 下的嵌套观测，不能当成新的独立故事样本。跨 case 推断以 case 为聚类单位，整组三位置一起 bootstrap 或配对置换；二值前／中及末／中比较可用 exact McNemar，对预注册多重比较作 Holm 校正。小样本 smoke 只用于发现反例，置信区间过宽时结论为证据不足，不能写“没有位置效应”。

正式推广需增加独立故事 case，覆盖实际长度与难度分层；每个层单独报告，避免把长度、模型差异或重复次数混作位置效应。盲评正文时隐藏位置标签，按冻结 rubric 评估并保存引用文本；召回回答与正文执行分开评估，避免额外答题指令改变正式 draft 行为。
