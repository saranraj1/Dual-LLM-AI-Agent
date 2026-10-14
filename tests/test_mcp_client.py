"""
tests/test_mcp_client.py — Unit tests for Native MCP Client & Tool Bridge.
"""

import os
import sys
import json
import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.mcp_client import MCPTool, MCPStdioClient, MCPBridge
from agent.react_harness import ToolRegistry


class TestMCPClient:

    def test_mcp_tool_naming(self):
        tool = MCPTool(name="read_resource", description="Reads URI", server_name="filesystem")
        assert tool.registered_name == "mcp_filesystem_read_resource"

    def test_mcp_stdio_client_not_running(self):
        client = MCPStdioClient(server_name="test", command="nonexistent_cmd_xyz")
        res = client.send_request("tools/list")
        assert "error" in res
        assert "not running" in res["error"]["message"]

    def test_mcp_stdio_client_mock_protocol(self):
        client = MCPStdioClient(server_name="mock_srv", command="python")
        client.process = MagicMock()
        client.process.stdin = MagicMock()

        # Test request formatting
        with patch.object(client, "send_request") as mock_send:
            mock_send.return_value = {
                "result": {
                    "tools": [
                        {
                            "name": "fetch_webpage",
                            "description": "Fetch URL content",
                            "inputSchema": {"type": "object", "properties": {"url": {"type": "string"}}}
                        }
                    ]
                }
            }
            tools = client.list_tools()
            assert len(tools) == 1
            assert tools[0].name == "fetch_webpage"
            assert tools[0].registered_name == "mcp_mock_srv_fetch_webpage"

    def test_mcp_call_tool_mock(self):
        client = MCPStdioClient(server_name="mock_srv", command="python")
        with patch.object(client, "send_request") as mock_send:
            mock_send.return_value = {
                "result": {
                    "content": [{"type": "text", "text": "<html>Sample page</html>"}],
                    "isError": False
                }
            }
            res = client.call_tool("fetch_webpage", {"url": "https://example.com"})
            assert res["ok"] is True
            assert "Sample page" in res["output"]

    def test_mcp_bridge_load_config_and_register(self, tmp_path):
        config_data = {
            "mcpServers": {
                "weather": {
                    "command": "python",
                    "args": ["-m", "weather_mcp"]
                }
            }
        }
        bridge = MCPBridge(workspace=str(tmp_path))
        bridge.load_config(config_dict=config_data)

        assert "weather" in bridge.clients
        client = bridge.clients["weather"]
        client.tools = [
            MCPTool(name="get_forecast", description="Get weather forecast", server_name="weather")
        ]

        registry = ToolRegistry(workspace=str(tmp_path))
        registered = bridge.register_tools(registry)
        assert registered == 1
        assert "mcp_weather_get_forecast" in registry.tools

        # Mock the tool call through the registry
        with patch.object(client, "call_tool") as mock_call:
            mock_call.return_value = {"ok": True, "output": "Sunny 25C"}
            result = registry.execute("mcp_weather_get_forecast", {"city": "Paris"})
            assert "Sunny 25C" in result

        bridge.close()
        assert len(bridge.clients) == 0
