"""Minimal stdio MCP server exposing the opinion-analysis Agent."""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

from opinion_agent.api import get_default_graph


SERVER_INFO = {"name": "opinion-agent-mcp", "version": "0.1.0"}
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "event_id": {"type": "string"},
        "query": {"type": "string"},
        "comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "sample_id": {"type": "string"},
                    "text": {"type": "string"},
                    "context": {"type": "string"},
                    "source_url": {"type": "string"},
                },
                "required": ["sample_id", "text"],
            },
        },
    },
    "required": ["event_id", "query", "comments"],
}


def handle_request(request: dict[str, Any]) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if request_id is None:
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "analyze_event",
                        "description": "Analyze Chinese public-opinion comments with sentiment, evidence retrieval, review routing and a structured risk brief.",
                        "inputSchema": TOOL_SCHEMA,
                    }
                ]
            }
        elif method == "tools/call":
            result = call_tool(request.get("params", {}))
        else:
            return error_response(request_id, -32601, f"Unknown method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:  # pragma: no cover - defensive server boundary
        return error_response(request_id, -32000, f"{type(exc).__name__}: {exc}")


def call_tool(params: dict[str, Any]) -> dict[str, Any]:
    if params.get("name") != "analyze_event":
        raise ValueError("Unknown tool")
    arguments = params.get("arguments") or {}
    state = {
        "request_id": str(uuid.uuid4()),
        "event_id": arguments["event_id"],
        "query": arguments["query"],
        "comments": arguments["comments"],
        "tool_traces": [],
        "errors": [],
    }
    result = get_default_graph().invoke(state)
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False, indent=2),
            }
        ]
    }


def error_response(request_id: object, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        response = handle_request(json.loads(line))
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
