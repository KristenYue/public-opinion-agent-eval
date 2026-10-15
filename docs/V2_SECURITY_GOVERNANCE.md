# V2 安全治理

## 1. 实际执行边界

安全策略由 `SecurityPolicy` 统一提供，并接入：

- `POST /v1/analyze`；
- `POST /v2/jobs` 进入持久化之前；
- Worker 结果写入 PostgreSQL 之前；
- MCP `analyze_event` 工具入口和返回出口。

这样可以避免 HTTP V2 安全、但同步 API 或 MCP 绕过策略的分裂状态。

## 2. 请求预算

`MAX_REQUEST_CHARS` 默认 100,000，按规范化 JSON 的总字符数计算，而不是只限制单条评论。超过预算：

- V1/V2 HTTP 返回 413；
- MCP 返回结构化工具错误；
- 请求不会进入 V2 数据库和队列。

Pydantic 的字段长度约束仍保留。两层限制解决的问题不同：字段约束限制单项，总预算限制大量合法小字段叠加后的整体成本。

## 3. 工具白名单与调用预算

生产白名单仅包含当前固定 LangGraph 节点：分类、聚合、检索、路由、复核、基线、人工复核和简报生成。`MAX_TOOL_CALLS` 默认 8。

Worker 在接受图结果时检查：

1. `tool_traces` 必须是数组；
2. 数量不得超过预算；
3. 每项必须是对象；
4. `node` 必须在白名单。

违反规则会记录 `security_policy_violation` 并失败关闭，不会重试未知工具。

当前图是代码静态编排，模型不能动态选择任意 Python 函数。白名单仍有价值，因为它把该架构事实变成运行时不变量，并防止未来扩展时静默放开工具。

## 4. 危险操作人工确认

策略支持将 allowlisted tool 同时标记为 `dangerous_tools`。未携带显式 `human_confirmed=True` 时抛出 `HumanConfirmationRequired`；确认后才授权。

当前生产白名单没有发送消息、删除数据、发布外部报告或转账等副作用工具，因此没有为了演示而伪造审批页面。未来新增副作用工具时，必须同时实现：

- 服务端身份和角色校验；
- 持久化审批记录；
- 参数摘要与幂等键；
- 审批过期时间；
- 执行后审计回执。

## 5. 敏感信息脱敏

入库前和输出持久化前都会递归处理：

- API Key、Bearer Token、password、cookie 等敏感字段名；
- 常见密钥文本；
- 电子邮箱；
- 中国大陆手机号；
- 文本中的 `api_key=...`、`token=...` 等形式。

`requested_by` 当前暂时保留，因为它承担审计主体字段；但它仍由客户端提供，不能视为真实身份。接入认证后必须由服务端 principal 覆盖，并建立访问控制和保留期限。

脱敏会牺牲部分原始文本信息，因此生产系统还需根据合规要求决定：只存脱敏副本、加密保存原文，或根本不保存原文。当前公开项目选择只让 Agent 和审计表接触脱敏后的自由文本。

## 6. 机器可读安全门禁

运行：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_security_governance.py
```

当前 10 个场景：

1. 请求总字符预算；
2. 未知工具拒绝；
3. 工具调用次数预算；
4. 危险工具缺少确认；
5. 危险工具带确认；
6. 敏感字段名脱敏；
7. 邮箱脱敏；
8. 手机号脱敏；
9. Bearer Token 脱敏；
10. 检索 Prompt Injection 检测。

机器报告位于 `data/evaluation/security_governance_v1.json`，必须 10/10 通过，总发布门禁才会通过。

## 7. 尚未完成

- 登录认证和 RBAC；
- Project 级数据隔离；
- 真正的审批 UI 与审批表状态机；
- Secret Manager；
- 加密字段与密钥轮换；
- 间接、编码混淆、多语言 Prompt Injection 红队集；
- 基于累计 Token、费用和墙钟时间的执行中预算中断。

因此当前可以表述为“有请求预算、静态工具白名单、输出失败关闭和敏感文本脱敏”，不能表述为“完成企业级零信任安全体系”。
