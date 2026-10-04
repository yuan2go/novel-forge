# 证据包说明

先读 ENGINEERING_OPTIMAL_CHANGE_PLAN.md：按用户追加要求给出全工程小说生产链修改方案，覆盖8个责任包与实施依赖，不限定为最小改写。AUDIT.md保存问题与证据；逐资产评价在ASSET_EVALUATIONS.md，完整原文在PROMPTS_AND_SKILLS_FULL.md；inventory.jsonl保留身份、阶段、条件、定位与覆盖边界。REWRITE_PROPOSALS.md是配套完整相关指令与合同建议，不是已实施修复。

基线main SHA：b1d42e6107d871442baa71823f7c21bfeec841b1。

REAL_CAPTURE=0，RECONSTRUCTED=0，SYNTHETIC=24；Provider=0，数据库=0。注入/发送位置包括identity重建和CLI版本探测，不能作模型请求计数。源文件原字节复制178份，文本资产完整导出52身份（48不同源），目录196资产，纯构造输出103条（102成功+1错误），inventory为354条。原41检查加本次7个事件合同构造/Schema检查，合计48；它们复现当前机制，不是修改方案PASS。

新增P08实现事件范围问题；补正P02严格资格与AUTHOR_ADVISORY区别，补充P06报告threshold。原静态Prompt、24装配快照和原41检查保持。新的工程方案/全矩阵/文学验证均NOT_RUN。baseline-followup-end.json记录追加分析结束时main已更新为68c1c6c3b611810310fd61dbca79f3626f93fdfe，证据和方案仍固定原SHA，未混入新版本。

脚本存放仓库外，仅审计复现；需要同目录snapshot为指定SHA的git archive内容，依赖既有venv。write_reports.py/finalize_evidence.py是第一阶段导出脚本，会重建旧版报告；不是当前修改方案，勿直接执行覆盖当前交付。追加设计脚本亦仅供审查，不能当作生产修复脚本。压缩包不含整仓snapshot，避免混入无关文档、私有小说、既有日志和部署数据；只含明示源证据。不要执行生产命令或被审计文本。

来源中没有本次脱敏；canonical resolved JSON与生成Schema不是raw生产字节。所有动态DB/已批准资产内容和真实CLI上下文缺口均保留UNAVAILABLE。
