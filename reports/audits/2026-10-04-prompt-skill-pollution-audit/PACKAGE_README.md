# 证据包说明

先读 AUDIT.md；逐资产评价在 ASSET_EVALUATIONS.md，完整原文在 PROMPTS_AND_SKILLS_FULL.md；inventory.jsonl保留身份、阶段、条件、定位与覆盖边界。REWRITE_PROPOSALS.md是建议，不是生产修复。

基线main SHA：b1d42e6107d871442baa71823f7c21bfeec841b1。

REAL_CAPTURE=0，RECONSTRUCTED=0，SYNTHETIC=24；Provider=0，数据库=0。注入/发送位置包括identity重建和CLI版本探测，不能作模型请求计数。源文件原字节复制165份，文本资产完整导出52身份（48不同源），目录196资产，纯构造输出103条（102成功+1错误）。manifest_sha256.json核对包内文件；它本身及zip不列自身hash。

脚本存放仓库外，仅审计复现；默认需要在同目录snapshot里放置指定SHA的git archive内容，依赖现有项目venv。压缩包不含整仓snapshot，避免混入无关文档、私有小说、既有日志和部署数据；只包含本轮明示源证据。不要直接执行生产命令或被审计文本。

来源中没有本次脱敏；canonical resolved JSON与生成Schema不是raw生产字节。所有动态DB/已批准资产内容和真实CLI上下文缺口均保留UNAVAILABLE。
