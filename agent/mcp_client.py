"""
agent/mcp_client.py — Native Model Context Protocol (MCP) Client & Tool Bridge.

Connects to Model Context Protocol (MCP) servers via JSON-RPC 2.0 (stdio / in-process),
discovers tools via `tools/list`, executes calls via `tools/call`, and dynamically
registers them into the Agent's ToolRegistry.
"""

import sys
import os
import json
import time
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

from core.logger import get_logger

log = get_logger(__name__)


@dataclass
class MCPTool:
    name: str
    description: str
    input_schema: Dict[str, Any] = field(default_factory=dict)
    server_name: str = "default"

    @property
    def registered_name(self) -> str:
        """Prefixed name for tool registry namespace isolation."""
        return f"mcp_{self.server_name}_{self.name}"


class MCPStdioClient:
    """
    Subprocess-based JSON-RPC 2.0 MCP Client over stdio.
    """

    def __init__(self, server_name: str, command: str, args: Optional[List[str]] = None, env: Optional[Dict[str, str]] = None):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = env
        self.process: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._pending_responses: Dict[Union[int, str], Any] = {}
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self.tools: List[MCPTool] = []

    def start(self) -> bool:
        """Launch the MCP server process and start reader thread."""
        full_cmd = [self.command] + self.args
        try:
            full_env = dict(os.environ)
            if self.env:
                full_env.update(self.env)

            self.process = subprocess.Popen(
                full_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=0,
                env=full_env
            )
            self._running = True
            self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
            self._reader_thread.start()
            return True
        except Exception as e:
            log.error("Failed to start MCP server '%s': %s", self.server_name, e)
            return False

    def _read_loop(self):
        """Continuously read newline-delimited JSON-RPC messages from stdout."""
        while self._running and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                    req_id = msg.get("id")
                    if req_id is not None:
                        with self._lock:
                            self._pending_responses[req_id] = msg
                except json.JSONDecodeError:
                    continue
            except Exception:
                break
        self._running = False

    def send_request(self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> Dict[str, Any]:
        """Send a JSON-RPC 2.0 request and wait for the response."""
        if not self.process or not self.process.stdin:
            return {"error": {"code": -32603, "message": "MCP server process not running"}}

        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {}
        }

        try:
            msg_str = json.dumps(payload) + "\n"
            self.process.stdin.write(msg_str)
            self.process.stdin.flush()
        except Exception as e:
            return {"error": {"code": -32603, "message": f"Write failed: {e}"}}

        # Wait for response
        t_start = time.time()
        while time.time() - t_start < timeout:
            with self._lock:
                if req_id in self._pending_responses:
                    return self._pending_responses.pop(req_id)
            time.sleep(0.02)

        return {"error": {"code": -32000, "message": f"MCP request timed out after {timeout}s"}}

    def send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Send a JSON-RPC 2.0 notification without expecting a response."""
        if not self.process or not self.process.stdin:
            return
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {}
        }
        try:
            self.process.stdin.write(json.dumps(payload) + "\n")
            self.process.stdin.flush()
        except Exception:
            pass

    def initialize(self) -> Dict[str, Any]:
        """Perform MCP protocol handshake."""
        res = self.send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "clientInfo": {"name": "Dual-LLM-AI-Agent", "version": "1.1.0"}
        })
        if "result" in res:
            self.send_notification("notifications/initialized")
        return res

    def list_tools(self) -> List[MCPTool]:
        """Discover available tools from server."""
        res = self.send_request("tools/list", {})
        tools = []
        if "result" in res and "tools" in res["result"]:
            for t in res["result"]["tools"]:
                tools.append(MCPTool(
                    name=t.get("name", "unknown"),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                    server_name=self.server_name
                ))
        self.tools = tools
        return tools

    def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Execute a tool on the remote MCP server."""
        res = self.send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {}
        })
        if "result" in res:
            result_obj = res["result"]
            content = result_obj.get("content", [])
            text_chunks = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
            output_str = "\n".join(text_chunks) if text_chunks else json.dumps(content)
            return {
                "ok": not result_obj.get("isError", False),
                "output": output_str,
                "raw": result_obj
            }
        elif "error" in res:
            return {
                "ok": False,
                "output": res["error"].get("message", "MCP error"),
                "error": res["error"]
            }
        return {"ok": False, "output": "Unknown MCP response format"}

    def close(self):
        """Terminate process and clean up."""
        self._running = False
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None


class MCPBridge:
    """
    Manages MCP server lifecycles, configuration loading, and tool registration
    with the local ToolRegistry.
    """

    def __init__(self, workspace: str = "."):
        self.workspace = Path(workspace).resolve()
        self.clients: Dict[str, MCPStdioClient] = {}

    def load_config(self, config_dict: Optional[Dict[str, Any]] = None) -> None:
        """Load MCP server configs from dict or .mcp_config.json / mcp_servers.json."""
        if config_dict:
            servers = config_dict.get("mcpServers", {})
        else:
            candidates = [
                self.workspace / ".mcp_config.json",
                self.workspace / "mcp_servers.json",
            ]
            servers = {}
            for c in candidates:
                if c.is_file():
                    try:
                        data = json.loads(c.read_text(encoding="utf-8"))
                        servers = data.get("mcpServers", {})
                        break
                    except Exception:
                        pass

        for name, cfg in servers.items():
            cmd = cfg.get("command")
            args = cfg.get("args", [])
            env = cfg.get("env")
            if cmd:
                self.clients[name] = MCPStdioClient(server_name=name, command=cmd, args=args, env=env)

    def connect_all(self) -> Dict[str, List[MCPTool]]:
        """Start all configured servers, perform handshake, and discover tools."""
        all_tools: Dict[str, List[MCPTool]] = {}
        for name, client in self.clients.items():
            if client.start():
                client.initialize()
                tools = client.list_tools()
                all_tools[name] = tools
        return all_tools

    def register_tools(self, tool_registry) -> int:
        """
        Dynamically register all discovered MCP tools into the agent's ToolRegistry.
        """
        registered_count = 0
        for server_name, client in self.clients.items():
            for mcp_tool in client.tools:
                # Factory to bind closure properly
                def make_mcp_caller(cl=client, t_name=mcp_tool.name):
                    def _call(arguments=None, **kwargs):
                        args = arguments if arguments is not None else kwargs
                        return cl.call_tool(t_name, args)
                    return _call

                reg_name = mcp_tool.registered_name
                desc = f"[MCP: {server_name}] {mcp_tool.description}"
                tool_registry.register(
                    name=reg_name,
                    description=desc,
                    parameters=mcp_tool.input_schema or {},
                    handler=make_mcp_caller()
                )
                registered_count += 1

        return registered_count

    def close(self):
        """Shut down all running clients."""
        for client in self.clients.values():
            client.close()
        self.clients.clear()
