# 在线 Demo 部署说明

本 Demo 使用 Gradio，并复用 `src/opinion_agent/` 中的 LangGraph、情感模型、检索器与复核路由。公开模式只读取 `examples/demo_event_cards.jsonl` 中的合成事件卡。

## 本地验收

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe app.py
```

访问 `http://127.0.0.1:7860`，点击“加载示例”和“运行研判”。页面必须同时出现：

- 检索证据及证据编号；
- 风险关注级别、摘要和建议动作；
- 复核状态、触发原因和策略版本；
- 完整审计 JSON。
- 可编辑的逐条人工复核表，以及复核后的 `human_completed` 状态。

没有 LLM Key 时，预置样例应同时展示 XGBoost 快速放行、页面明确标识的冻结验收回放和人工兜底；任何自由输入都不得冒充在线 Qwen 结果，低置信时进入“需要人工复核”。人工修改标签并提交后，应重新计算简报并显示“人工复核已完成”。

自由测试还需验收以下行为：

- 选择“现场自由测试（严格复核）”后，每条评论都包含 `strict_live_test` 升级原因；
- 即使仍选择稳定模式，只要修改评论、事件目标或背景，也会自动切换到 `strict_live_test_v1`；
- 有在线 Reviewer 时，只有 High 置信结果可以写回；Medium/Low 进入 `manual_required`；
- 无在线 Reviewer 时，陌生输入只能进入人工兜底，不能使用预置回放答案。

## Docker 验收

```powershell
docker build -t opinion-agent-demo .
docker run --rm -p 7860:7860 opinion-agent-demo
```

如需接入 OpenAI 兼容 Reviewer，在运行时传入环境变量：

```powershell
docker run --rm -p 7860:7860 `
  -e LLM_BASE_URL="https://your-provider.example/v1" `
  -e LLM_API_KEY="replace-me" `
  -e LLM_MODEL="your-model" `
  opinion-agent-demo
```

## 部署到 Hugging Face Spaces

1. 在 Hugging Face 新建 Space，Visibility 选择 Public，SDK 选择 Docker。
2. 将本仓库文件推送到 Space 仓库。README 顶部已包含 `sdk: docker` 与 `app_port: 7860` 元数据。
3. 默认不配置任何 Secret，等待镜像构建；模型在 Docker 构建阶段下载并缓存。
4. 构建完成后打开 Space，使用预置示例完成一次研判。
5. 若使用真实 Reviewer，在 Space 的 Settings → Variables and secrets 中添加：
   - `LLM_BASE_URL`
   - `LLM_API_KEY`（Secret）
   - `LLM_MODEL`
6. 将公开地址回填到根目录 README 的“在线 Demo”位置。

## 部署到魔搭创空间

1. 新建公开创空间并选择 Gradio 或 Docker 运行环境。
2. 上传/同步本仓库，启动命令使用 `python app.py`，服务端口设为 `7860`。
3. 默认不配置 Key 即可运行带明确标识的预置验收流程。
4. 为面试现场自由测试配置以下环境变量：
   - `LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1`
   - `LLM_MODEL=qwen-plus`
   - `LLM_API_KEY`：必须放在平台密钥管理中，不得作为普通明文变量或写入仓库
5. 保存配置后重新部署，使进程在启动时读取变量。
6. 选择“现场自由测试（严格复核）”，使用一条未预置评论验收：
   - 页面策略版本为 `strict_live_test_v1`；
   - Reviewer 显示 `在线 Reviewer：qwen-plus`；
   - High 置信结果路径为 `qwen_reviewed`；
   - Medium/Low 或调用失败路径为 `manual_required`。
7. 完成页面验收后，将公开地址回填到根目录 README。

当前公开实例：<https://modelscope.cn/studios/KristenYue/public-opinion-agent-demo>

## 发布前检查

- 仓库中不存在 API Key、Cookie、原始微博文本或用户标识。
- 无 Key 时预置样例可完整显示快速放行、离线验收、人工兜底、证据、结论和决策路径；自由输入不会被伪装成在线 Qwen 输出。
- 非预置输入会自动进入 `strict_live_test_v1`，不会仅因 XGBoost 和辅助模型一致而直接放行。
- 在线 Key 只存在于平台密钥管理中，仓库、日志、截图和审计 JSON 均不出现 Key。
- 页面中的合成来源使用 `example.com`，不应描述为真实新闻来源。
- `/` 可公开访问，冷启动完成后可运行一例。
- README 中的公开 URL 已回填，且使用无痕窗口验证无需登录。

## 当前状态

- 魔搭公开空间已创建并完成首次部署。
- README 已回填实际公开 URL。
