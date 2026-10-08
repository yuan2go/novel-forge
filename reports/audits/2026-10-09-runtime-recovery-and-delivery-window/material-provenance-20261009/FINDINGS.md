# 青岚问道资料生成来源核对

读取时间：2026-10-08T17:40:22.375123+00:00。北京时间以下均指 2026-10-08。

当前读取的是原数据库端点上的备份恢复点，备份时间为 2026-10-08 20:18:23 +08:00；没有证明备份之后原安装的全部最新状态。只读入口为 AuthorityAssetQuery、AuthorityExecutionRecoveryStore.read_evidence、inspect_runtime 和 creation_status；本次没有模型调用或业务状态写入。

结论：不能把一次 Codex 请求中途断流扩大为 Codex 全部无法访问。当前资料由登记输入、原生配置与初始化、此前成功的 Codex 调用、参考资料导入及拆解共同形成。当前 API alive，provider_dispatch_suspended=true。

## 本书模型生成资料

下列六项均从当前 BookDesign 的精确绑定读取，并重新校验内容哈希；均匹配。实际路线为 codex-cli / gpt-6.1-sol / high，会员 ACCOUNT_ENTITLEMENT，金额不可观测。

| 资料 | 成功完成时间 | 实测总 token | Operation |
|---|---|---:|---|
| 创作基础 | 17:41:07 | 24367 | `528eabd8-ae1b-4629-8137-b1b86a11bf8c` |
| 主题 | 17:47:34 | 26690 | `01d50954-728c-47bb-85fb-06fd785130e0` |
| 结局意图 | 17:48:48 | 25536 | `847cd4f1-7763-473d-8c46-0785ffa7b1f3` |
| 读者承诺 | 17:50:39 | 26596 | `6b3fab3d-e978-45b0-a1d6-97df7254d134` |
| 世界设定 | 18:49:39 | 54396 | `bd11fa76-a76e-4b65-8e32-093f8f6e6bac` |
| 人物组 | 19:02:14 | 56161 | `c59b05b5-a51c-4d41-a97c-b5d47e841472` |

冻结输入形成明确依赖：作者简报 → 创作基础 → 主题/结局意图/读者承诺 → 世界设定 → 人物组 → BookDesign 与全书规划候选。六项绑定均保留精确 AssetVersion、内容哈希、选择回执和模型用量回执；这不等于正文或文学质量已完成。

全书规划候选：

- `f624f36c-5c9f-4506-9420-8a3ab1b0e9b9`：19:02:55—19:11:18，SUCCEEDED，实测总 token 73823。
- `d74c587d-7dc2-468f-8e11-34f9db4a0195`：19:11:19—19:18:42，SUCCEEDED，实测总 token 72464。
- `bf6e1d58-97ec-412d-bf91-19d4687d3f24`：19:18:44—19:22:58，UNKNOWN，实测总 token UNKNOWN。

前两个全书方案有候选 AssetVersion；第三个原 Effect `30421df5-8e89-46ab-8aff-ebb9cf3077c7` 没有成功完成回执与实测用量，仍为 UNKNOWN。当前 creation_status 为 RECONCILIATION_REQUIRED，BookProduction 记录为空。这是当前已核实恢复点的状态，不能外推为任何地方都没有正文。

## 非模型登记与研究资料

- creative_brief 的来源回执登记为 CURRENT_AUTHOR_INPUT，由 author-first-native-operator 经原生选择入口保存。保存/读回该输入不需要调用模型；来源标签不等于额外的作者亲自确认。
- reader_contract、production_profile 明确标记 operator_authored=true、provider_generated=false；初始 Canon 为 OPERATOR_AUTHORED_GENESIS、accepted_through_chapter=0。这些是配置或初始状态，不是模型写出的章节，也不能证明作者反馈或正式接纳。
- 研究侧保存了 `qid-reading-notes-original-20261008`、`qid-preferred-gou-original-methods-20261008` 两个导入材料记录；采集完整性字段为 UNKNOWN。导入记录本身不证明已取得完整参考小说原文。
- 项目内另有 12 次 source / deconstruction 成功执行，均为 codex-cli / gpt-6.1-sol / high，服务于 source-corpus:qid-learning-prose-01，不能算作本书已交付章节。

其中以下 6 次在原规划请求失败之后完成，足以反驳“从此所有 Codex 请求均访问不了”：

| 完成时间 | 类型 | Operation |
|---|---|---|
| 19:26:01 | deconstruction | `e025230a-f7a0-4d29-ad13-a5f2317f4cad` |
| 19:44:21 | source | `a4779a66-f392-4ef7-9a3c-9d7bfadd2ea2` |
| 19:48:02 | deconstruction | `4a052562-cfbe-41b6-8fd6-2b135e7717f8` |
| 19:56:18 | deconstruction | `ea6718f6-04d4-4832-8f1e-26adcffb6e10` |
| 19:59:53 | deconstruction | `cc2731f7-59af-45cc-a703-8fe30febfb1b` |
| 20:01:19 | deconstruction | `31a136f9-ea49-4ccf-a0cc-19d2ae4019ac` |

研究调用的成功不替代失败的全书规划原请求，也不自动代表研究结果已纳入本书冻结输入。

## 故障与证据边界

- 23 个保留的执行会话中，22 个成功、1 个 UNKNOWN；10 个成功属于本书创作/规划链，12 个属于参考资料分类/拆解链。另有 22 份 ModelCallLog，provider_id 全部为 codex-cli、model_id 全部为 gpt-6.1-sol。本次检查的记录中没有 DeepSeek 接管。
- 原失败请求的本地事件是 `stream disconnected before completion: Transport error: network error: error decoding response body`，随后 turn.failed。缺完整结果和实测用量，不能判成远端未执行或费用为零。
- 当前暂停派发与旧请求 UNKNOWN 是两件事：前者是当前运行控制；后者是原执行结果仍无法确定。两者均不阻止读回已保存资产。
- 23 是执行会话数量，不是所有 ExternalEffect 总数；导入/抓取等另有 Effect。总数不能混加成模型调用数。
- 本次未运行新的推理或生成测试，未修改应用代码、选择记录或业务数据。脚本首次命名 inspect.py 遮蔽 Python 标准库，已改名 material_provenance_readback.py 后完成原生只读查询；这不是数据库或模型故障。

精确身份、Route/Prompt/Skill/Schema、输入版本、回执及用量见同目录 [provenance.json](provenance.json)。
