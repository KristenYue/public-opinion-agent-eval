from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from opinion_agent import mcp_server  # noqa: E402
from opinion_agent.mcp_server import handle_request  # noqa: E402


def test_mcp_initialize_exposes_server_info() -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    assert response is not None
    assert response["result"]["serverInfo"]["name"] == "opinion-agent-mcp"
    assert "tools" in response["result"]["capabilities"]


def test_mcp_tools_list_exposes_analyze_event() -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert response is not None
    tool = response["result"]["tools"][0]
    assert tool["name"] == "analyze_event"
    assert "comments" in tool["inputSchema"]["required"]


def test_mcp_unknown_method_returns_jsonrpc_error() -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 3, "method": "missing"})

    assert response is not None
    assert response["error"]["code"] == -32601


def test_mcp_tools_call_invokes_agent_graph(monkeypatch) -> None:
    class FakeGraph:
        def invoke(self, state):
            return {"event_id": state["event_id"], "final_report": "ok"}

    monkeypatch.setattr(mcp_server, "get_default_graph", lambda: FakeGraph())

    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "analyze_event",
                "arguments": {
                    "event_id": "event-a",
                    "query": "analyze",
                    "comments": [{"sample_id": "c1", "text": "hello"}],
                },
            },
        }
    )

    assert response is not None
    text = response["result"]["content"][0]["text"]
    assert '"event_id": "event-a"' in text
    assert '"final_report": "ok"' in text
