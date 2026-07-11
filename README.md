# 面向突发事件的可评测舆情研判 Agent

[![CI](https://github.com/KristenYue/public-opinion-agent-eval/actions/workflows/ci.yml/badge.svg)](https://github.com/KristenYue/public-opinion-agent-eval/actions/workflows/ci.yml)

一个强调**受控工具调用、证据拒绝、人工接管和可复现评测**的中文舆情风险研判 Agent。项目从本科情感分析系统出发，针对短文本漏检和高置信误判构建可追溯工作流；它不是开放式 Autonomous Agent，也不把 LLM 建议直接当作最终结论。

## 关键证据

| 证据 | 结果 |
|---|---:|
| 冻结策略独立验证 | 24 条不重叠样本，10/10 批次成功 |
| Reviewer 安全门禁 | Accuracy 54.2% → 58.3% |
| 受控覆盖 | 3 次覆盖，纠正 1 条，harmful override 0 条 |
| 工作流契约 | 36 个任务 × 8 类检查，288/288 通过 |
| 故障恢复 | 7/7 类受控故障进入预期恢复或人工接管路径 |
| 自动化回归 | 59 tests passed |

> 独立验证规模仍小，尤其只有 3 次门禁覆盖；这些结果是工程证据，不代表统计显著性、生产 SLA 或线上业务收益。

## 两分钟运行

要求 Python 3.11 或 3.12。公开 Demo 只读取合成事件卡；未配置外部 LLM 时明确降级为人工复核，不消耗 API 额度。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe scripts\run_public_demo.py --port 8000
```

浏览器访问 `http://127.0.0.1:8000/console`。运行完整回归与发布检查：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
```

## 系统工作流

```text
评论输入
  -> XGBoost情感分类 + SnowNLP第二信号
  -> 情绪聚合
  -> Hybrid历史事件检索
  -> 多信号复核路由
       ├─ 无触发：输出带局限说明的基线结果
       └─ 有触发：结构化LLM复核 / 人工复核降级
  -> 研判报告编排（证据引用、风险信号、复核状态、行动建议）
```

API、Console 和 MCP stdio 复用同一条 LangGraph 工作流。详细设计见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)，Reviewer 冻结门禁见 [验证结果](docs/REVIEWER_POLICY_VALIDATION_RESULTS.md)，两分钟演示见 [Reviewer Gate Demo](docs/REVIEWER_GATE_DEMO.md)。

## 完整评测结果

当前使用242条评论，按事件划分为169/35/38。其中107条高风险样本已完成聚焦二次裁决，24条标签发生修改；其余135条仍保留单人暂定标签。该数据集不是独立双人标注金标准，因此以下数字不得描述成最终生产效果。

| 指标 | 结果 |
|---|---:|
| XGBoost测试集Accuracy | 44.7%（95%区间28.9%–60.5%） |
| XGBoost测试集Macro-F1 | 0.312 |
| SnowNLP测试集Accuracy | 47.4%（95%区间31.6%–63.2%） |
| 36个Agent任务工具执行成功率 | 100% |
| 结构化研判报告生成成功率 | 100% |
| Agent工作流契约通过率 | 100%（36个任务 × 8类检查） |
| Agent故障恢复场景通过率 | 100%（7类离线注入场景） |
| 不含外部 LLM 的本地批次中位延迟 | 约50ms |
| Agent原始情感准确率 | 46.7% |
| 模型分歧路由的错误捕获率 | 86.9% |
| 一致路径覆盖率 | 24.8% |
| 一致路径准确率 | 71.7% |

结果说明“模型一致”只能作为复核信号，不能作为直接采信依据。完整指标与限制见 [docs/EVALUATION.md](docs/EVALUATION.md)。

## 本地运行

要求Python 3.11或3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m pytest -q
```

首次使用语义检索时会下载 `BAAI/bge-small-zh-v1.5`。之后可离线运行：

```powershell
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe scripts\run_mvp.py --event-id "关税" --limit 10
```

只使用合成公开事件卡启动可展示的 Console：

```powershell
.\.venv\Scripts\python.exe scripts\run_public_demo.py --port 8000
```

启动后访问 `http://127.0.0.1:8000/console`。发布前检查可通过以下命令复现：

```powershell
.\.venv\Scripts\python.exe scripts\check_release_readiness.py
```

## FastAPI

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m uvicorn opinion_agent.api:app --host 0.0.0.0 --port 8000
```

启动后访问 `http://127.0.0.1:8000/console` 打开 Agent Console。控制台可直接提交事件、上下文和评论样本，并展示结构化研判摘要、人工复核队列、历史证据及逐节点工具轨迹；无需单独安装前端依赖。

本地私有事件卡存在时默认使用 `data/processed/event_cards.jsonl`；干净克隆或 Docker
镜像使用 `examples/demo_event_cards.jsonl` 中明确标注的合成事件。也可通过
`EVENT_CARDS_PATH` 指定其他事件卡文件。公开 Demo 不需要提交原始微博语料。

请求示例：

```json
POST /v1/analyze
{
  "event_id": "关税",
  "query": "分析关税事件评论，并检索可信的历史相似事件",
  "comments": [
    {"sample_id": "demo-1", "text": "这个政策让普通消费者压力更大", "context": "原帖或事件背景"},
    {"sample_id": "demo-2", "text": "先看看后续具体实施细则"}
  ]
}
```

健康检查：`GET /health`。交互式文档：`http://127.0.0.1:8000/docs`。

## 可选LLM复核

项目不绑定具体供应商，使用OpenAI兼容的 `/chat/completions` 接口：

```powershell
$env:LLM_BASE_URL="https://your-provider.example/v1"
$env:LLM_API_KEY="replace-me"
$env:LLM_MODEL="your-model"
$env:LLM_TIMEOUT_SECONDS="30"
$env:LLM_MAX_ATTEMPTS="3"
$env:LLM_MAX_INPUT_CHARS="50000"
```

任何Key都不得写入仓库。未配置上述变量时，系统不会伪造LLM结果，而是返回明确的人工复核状态。复核器对超时、传输错误、429和5xx执行有上限的指数退避重试；请求携带稳定幂等键，并校验返回ID完整性。Token用量进入评测报告，价格由实际供应商配置计算，不在代码中猜测。

## Docker

```powershell
docker build -t opinion-agent .
docker run --rm -p 8000:8000 opinion-agent
```

若需要LLM复核，通过运行时环境变量传入，不要写入镜像：

```powershell
docker run --rm -p 8000:8000 `
  -e LLM_BASE_URL="https://your-provider.example/v1" `
  -e LLM_API_KEY="replace-me" `
  -e LLM_MODEL="your-model" `
  opinion-agent
```

## 复现评测

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_baselines.py
.\.venv\Scripts\python.exe scripts\build_agent_eval_tasks.py
$env:HF_HUB_OFFLINE="1"
.\.venv\Scripts\python.exe scripts\evaluate_agent_mvp.py
.\.venv\Scripts\python.exe scripts\evaluate_retrieval.py
.\.venv\Scripts\python.exe scripts\evaluate_reliability.py
.\.venv\Scripts\python.exe scripts\evaluate_failure_recovery.py
.\.venv\Scripts\python.exe scripts\build_reviewer_eval_cases.py
.\.venv\Scripts\python.exe scripts\evaluate_llm_reviewer.py
```

## 目录结构

```text
src/opinion_agent/
  agent/          State、Nodes、Graph、结构化复核器
  sentiment/      XGBoost封装与SnowNLP第二信号
  retrieval/      事件卡构建、稀疏/语义/Hybrid检索
  evaluation/     分类器与路由评测
  static/         Agent Console静态前端
  api.py          FastAPI入口
data/
  processed/      脱敏、去重数据与事件卡
  evaluation/     暂定标签、任务与指标
docs/             架构、决策和评测报告
tests/            单元与接口测试
```

## 已知限制

- 107条高风险标签已完成同一项目内的聚焦二次裁决，但不是独立标注者一致性实验。
- 其余135条仍是单人暂定标签。
- 测试集只有38条，统计区间较宽。
- 12个历史事件不足以证明通用RAG能力。
- 已完成 DeepSeek `deepseek-v4-flash` 的12条探索实验和24条不重叠冻结策略验证。独立验证中10/10批次成功、24/24覆盖；安全门禁将准确率由54.2%提升至58.3%，3次受控覆盖纠正1条且 harmful override 为0。样本规模较小，不宣称生产泛化。
- 本科XGBoost模型使用旧版序列化资产，加载时会出现兼容性警告，后续应导出为XGBoost原生格式。
- 主仓库代码许可证仍需在核对词典和模型资产条款后确定；不能直接套用伴生评测扩展的MIT许可证。

## 数据和安全

原始微博数据、Cookie、API Key和用户标识不得进入公开仓库。公开前请再次执行敏感信息扫描，详见 [SECURITY.md](SECURITY.md)。

完整评论文本、事件卡和人工标注JSONL默认被 `.gitignore` 排除。公开版本应提供经过许可或重新脱敏的小型样例数据，不能为了让Demo方便运行而直接提交整份抓取语料。数据说明见 [DATA_CARD.md](DATA_CARD.md)。
## Review Policy Controls

The default router is deliberately conservative. It routes model disagreements,
unscorable text, short context-dependent comments and missing evidence to review.
For threshold experiments or demos that need a visible auto-release path:

```powershell
$env:REVIEW_DISAGREEMENT_THRESHOLD="0.8"
$env:REVIEW_ROUTE_ON_NO_EVIDENCE="0"
```

These settings should be reported as policy experiments, not production safety
defaults. Use `scripts/tune_review_policy.py` to inspect the current
review-rate/error-recall trade-off.

## Agent Evaluation

The project includes a single-run audit layer that combines workflow contracts,
tool trajectory, evidence grounding, review status, recoverable errors and
risk flags into one JSON report.

```powershell
.\.venv\Scripts\python.exe scripts\audit_agent_run.py `
  --request path\to\request.json `
  --result path\to\result.json `
  --output artifacts\audits\run_audit.json
```

See [docs/AGENT_EVALUATION.md](docs/AGENT_EVALUATION.md) for the evaluation
layers, evidence paths, and measurement limitations.

The Reviewer override gate has a two-case offline demo:

```powershell
.\.venv\Scripts\python.exe scripts\demo_reviewer_gate.py
```

See [docs/REVIEWER_GATE_DEMO.md](docs/REVIEWER_GATE_DEMO.md) for the design walkthrough and limitations.

## Why this is an Agent workflow

This project deliberately uses bounded autonomy. It does not claim to be an
open-ended planning agent: the graph topology, available tools and escalation
rules are predefined because a high-risk analysis system should not freely
invent execution paths. Runtime signals still control retrieval acceptance,
review routing, LLM/manual fallback and whether an LLM suggestion may override
the baseline. The engineering focus is governed tool use, state transitions,
failure recovery and auditable decisions.

## MCP Server

The Agent can also be exposed as a minimal stdio MCP server with one tool,
`analyze_event`:

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m opinion_agent.mcp_server
```

The MCP tool reuses the same LangGraph workflow as the FastAPI endpoint, so MCP,
API and console behavior stay aligned.

Example JSON-RPC requests are provided for reproducible demo walkthroughs:

- `examples/mcp_initialize.json`
- `examples/mcp_tools_list.json`
- `examples/mcp_analyze_event_call.json`

See [docs/MCP_DEMO.md](docs/MCP_DEMO.md) for the recommended demo wording and
limitations.
