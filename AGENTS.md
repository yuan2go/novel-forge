# AGENTS.md

本文件定义 Codex / Claude Code / 其他代码代理在 `novel-forge` 仓库中的工作规则。

## 1. 项目定位

`novel-forge` 是一个小说宇宙工厂项目，目标是构建一套文件项目制的工业化小说生产系统。

核心流程：

```text
Reader Attraction Gate
  → Project Differentiation Gate
  → Knowledge Compiler
  → Project Constitution
  → Novel Workspace
  → Claude Code / Codex / DeepSeek 执行生产
  → Review System
  → Feedback Control
```

## 2. 当前阶段

当前阶段是 V1：文件项目制。

允许使用：

- Markdown
- JSON
- Python 标准库
- Git
- Codex / Claude Code 审查与执行

暂不引入：

- Web 平台
- 数据库
- Qdrant
- Neo4j
- Redis
- Celery
- 复杂多 Agent 平台

## 3. 工作优先级

所有代理必须遵守以下优先级：

1. 原创风险与安全边界
2. 读者吸引力
3. 项目差异化
4. 多学科可信度
5. 哲学方向
6. 世界观完整性
7. 生产效率
8. 自动化程度

不能为了世界观完整牺牲读者吸引力；不能为了多学科合理性把小说写成论文；不能为了自动化破坏项目宪法。

## 4. 代理职责

### Codex

适合处理：

- 审查项目结构
- 生成脚本
- 维护模板
- 编写测试
- 重构文档组织
- 生成工程化脚手架

### Claude Code

适合处理：

- 单本小说 workspace 接管
- 按任务卡执行
- 维护 project memory
- 组织章节、审稿、反馈文件

### DeepSeek

适合处理：

- 批量拆解
- 正文 v0
- 评论分类
- 知识卡初稿

### ChatGPT / Codex 高质量审稿

适合处理：

- Reader Attraction Gate
- Project Differentiation Gate
- Knowledge Compiler
- Project Constitution
- 多维审稿
- 架构判断

## 5. 文件修改规则

### 允许修改

- `docs/`
- `templates/`
- `scripts/`
- `tests/`
- `ROADMAP.md`
- `CHANGELOG.md`

### 谨慎修改

- `README.md`
- `AGENTS.md`
- `pyproject.toml`
- `Makefile`

### 禁止无任务卡修改

- 单本小说项目中的 `*_final.md`
- `project_constitution.md`
- `world_constitution.md`
- 任何包含真实密钥或私有素材的文件

## 6. 代码规则

Python 脚本要求：

- 使用 Python 3.11+
- 优先使用标准库
- 不依赖外部 API
- 不读取真实密钥
- 不写入敏感内容
- 提供清晰命令行参数
- 出错时给出明确提示

## 7. 文档规则

新增文档必须包含：

1. 模块目标
2. 输入
3. 输出
4. 文件路径
5. 执行流程
6. 验收标准
7. 风险与边界

## 8. 测试规则

当前阶段至少维护：

- 文档结构校验
- 模板文件存在性校验
- 脚本 dry-run 校验

运行：

```bash
make check
make test
```

## 9. 重大变更规则

以下修改必须先输出审查报告，再执行：

- 改变项目总架构
- 合并或删除核心文档
- 修改 project constitution 模板
- 引入数据库或外部服务
- 增加复杂依赖
- 改变 V1 路线

## 10. 最终判断标准

本项目不是为了生成最多文本，而是为了稳定生产：

```text
有吸引力
有可信度
有项目边界
有审稿闭环
有反馈控制
可长期维护
```
