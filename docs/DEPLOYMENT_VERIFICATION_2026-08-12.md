# 公开部署验收记录（2026-08-12）

## 结论

魔搭公开实例完成一次真实冷启动后进入“运行中”，无需登录即可访问。预置合成样例和陌生合成输入均完成端到端研判；严格复核、合成证据和审计边界符合项目契约。本次状态为 **通过但有局限**，不构成可用性 SLA。

验收地址：<https://modelscope.cn/studios/KristenYue/public-opinion-agent-demo>

## 预置样例

5 条合成评论产生三种预期路径：

| 路径 | 数量 |
|---|---:|
| `fast_path` | 2 |
| `qwen_reviewed` | 2 |
| `manual_required` | 1 |

页面显示了合成证据提示、风险结论、路由原因、策略版本、Reviewer 状态、人工复核表和审计 JSON。Medium 置信结果没有自动写回，正确进入人工流程。

## 陌生输入严格复核

使用完全合成的新事件和评论进行测试。虽然 XGBoost 与辅助模型均给出 Positive，系统仍因输入不属于预置样例而自动切换：

- `review_policy=strict_live_test`
- `policy_version=strict_live_test_v1`
- `prompt_version=event_stance_v2`
- 最终路径为 `qwen_reviewed`
- 审计结果 `errors=[]`

检索证据全部来自 `https://example.com/synthetic/`，没有读取或展示真实微博语料。

## 隐私扫描

对严格模式展开后的可见审计 JSON 检查以下模式，未发现命中：

- API Key
- Cookie
- 本机用户路径
- `data/raw_private` / `data/annotations`
- `uid`、`user_id`、`username`、`screen_name`

## 局限

- 浏览器客户端阻止直接访问 `ms.show/health`，因此未独立验证公开 `/health` 响应；应用页面本身已完成两次端到端运行。
- 线上实例配置了 `qwen-plus` Reviewer；无 Key 降级由本地自动化测试覆盖，不属于本次线上快照。
- 本记录只证明 2026-08-12 的一次部署快照，不代表持续在线率、并发能力或供应商 SLA。

机器可读证据：`data/evaluation/deployment_verification_2026-08-12.json`。
