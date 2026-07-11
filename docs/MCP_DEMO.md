# MCP Demo

本项目提供一个最小 stdio MCP server，将同一套 LangGraph 舆情研判工作流暴露为 `analyze_event` 工具。MCP 在本项目中是工程化入口，不是核心算法创新。

## 启动

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe -m opinion_agent.mcp_server
```

## 可展示请求

- `examples/mcp_initialize.json`
- `examples/mcp_tools_list.json`
- `examples/mcp_analyze_event_call.json`

这些样例使用合成公开评论，不依赖私有微博语料。

## 设计说明

实现要点：

> 我把同一套 LangGraph workflow 同时暴露给 FastAPI、Console 和 MCP stdio tool。这样 Agent 不只停留在页面 Demo，也可以作为工具被其他 Agent 宿主调用。MCP 入口复用 `/v1/analyze` 背后的工作流，所以 API、Console 和工具调用的行为保持一致。

不要这样说：

- 不要说 MCP 是项目核心创新；
- 不要说它已经接入生产环境；
- 不要说它替代了完整平台权限、监控和审计系统。
