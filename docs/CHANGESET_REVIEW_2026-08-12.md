# 变更集审查（2026-08-12）

## 结论

当前工作树是一批相互关联的项目可靠性与发布治理变更。公开候选树共 217 个现存文件，自动范围审计无失败项；全量测试、依赖检查、发布门禁和差异格式检查均通过。本记录只定义提交范围，不代表已经执行 Git 提交或推送。

## 建议提交范围

### 1. 输入与接口契约

- API `sample_id` 非空与长度校验
- 对应回归测试
- ADR `0013-validate-comment-sample-id.md`

### 2. 可复现评测证据

- 离线性能测量代码、脚本、测试、报告和 JSON
- Reviewer 置信度诊断代码、脚本、测试、报告和 JSON
- Prompt 回归门禁、基线、状态与测试
- 公开部署验收报告与机器可读快照

### 3. 发布与供应链安全

- 旧模型资产大小和 SHA-256 清单
- 模型资产完整性门禁
- 未知许可词典阻断门禁
- Git 公开候选树范围审计
- wheel 内容泄漏检查
- CI 的 `pip check`、wheel 构建、回装和导入冒烟

### 4. 数据与文档治理

- `ANNOTATION_GUIDE.md`
- 更新后的 `DATA_CARD.md` 与 `docs/EVALUATION.md`
- 第三方来源说明、发布清单和安全规则
- 项目完成计划和部署验收记录

### 5. 有意删除

以下五个词典没有被运行时、评测或测试引用，且缺少可验证的再分发许可，当前版本有意删除：

- `dictionaries/BosonNLP_sentiment_score.txt`
- `dictionaries/hownet/pos_emotion.txt`
- `dictionaries/hownet/neg_emotion.txt`
- `dictionaries/stopwords.txt`
- `dictionaries/否定词_融合版.txt`

## 明确排除

- `.idea/`
- `.venv/`、缓存、构建目录和 wheel 输出目录
- `data/raw_private/`、`data/annotations/`、人工标注明细和 Qwen 原始响应
- Transformer 权重、优化器状态和本地候选模型
- `legacy/`、`references/`、`docs/_local/`、`outputs/`、`tmp/`

## 提交前仍需人工确认

1. 是否接受五个旧词典从当前版本删除；文件仍可从 Git 历史恢复。
2. 是否将本批变更作为一个可靠性/发布治理提交，或拆分为代码、证据、文档三个提交。
3. 根许可证尚未选择，不应在提交时自动补充未经版权所有者确认的许可证。

## 已执行验证

```text
pytest: 104 passed
pip check: passed
release readiness: passed with repository_license and docker_runtime_available warnings
public tree audit: 217 files, 0 failures
git diff --check: passed
```
