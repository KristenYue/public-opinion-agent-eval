# 版本基线记录（2026-09-11）

## 维护范围

该版本作为可复现基线保存。后续变更以影响复现、事实准确性、安全性和依赖兼容性的问题为主；新增架构能力应单独记录验证范围。

本记录对应的基线提交为 `d69b5c6`。未创建 Git tag；正式发布前仍需完成仓库所有者复核。

## 本机核验

| 项目 | 命令 | 结果 |
|---|---|---|
| 安装 | `python -m pip install -e ".[demo,dev]"` | 成功 |
| 依赖一致性 | `python -m pip check` | 无损坏依赖 |
| 全量测试 | `python -m pytest -q` | 104 passed；4 个第三方弃用/模型版本警告 |
| Reviewer 门禁演示 | `python scripts/demo_reviewer_gate.py` | APPLY 与 REJECT 两条路径均成功 |
| 发布检查 | `python scripts/check_release_readiness.py` | `ready_with_warnings`；无失败项 |
| GitHub Actions | `CI` | [最近一次公开运行成功](https://github.com/KristenYue/public-opinion-agent-eval/actions/runs/30498183351) |

## 剩余警告与边界

- 发布检查仍提示仓库未提供 `LICENSE`：在第三方模型、词典和数据条款完成复核前保留该警告，不擅自声明统一许可证。
- 当前机器未提供 Docker 可执行程序，因此本轮没有本机重跑容器；Dockerfile 与 CI 资料仍保留。
- 公开 Demo 使用合成事件卡；真实语料、Cookie、API Key 和用户标识不进入仓库。
- 评测结果只适用于冻结数据与测试条件，不代表生产 SLA。

## 公开材料

- README：架构图、核心结果、贡献边界、失败案例、术语解释和指标局限。
- `docs/舆情研判Agent_3分钟离线演示.mp4`：网络异常时的本地播放备份。
