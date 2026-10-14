"""
agent/react_harness.py — Unified ReAct Execution Harness & Sandboxed Tool Loop.

Implements native function/tool execution (Pillar 1) with:
- Standardized tool schemas and JSON/block parameter parsing.
- 3-tiered security sandboxing:
    * Tier 0 (Safe Read): auto-approved
    * Tier 1 (Safe Mutation): auto-approved with shadow git checkpointing + pre-flight AST validation
    * Tier 2 (Destructive/System): intercepted with user confirmation / interactive QA prompt
- Thought → Action → Observation iterative loop.
"""

import re
import json
import os
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable


class SecurityTier(str, Enum):
    SAFE_READ = "safe_read"
    SAFE_MUTATION = "safe_mutation"
    DESTRUCTIVE = "destructive"


# Commands classified as dangerous / destructive (Tier 2)
DESTRUCTIVE_COMMAND_PATTERNS = [
    r"\brm\s+-[rf]{1,2}\b",
    r"\bdel\s+/[sfq]\b",
    r"\brd\s+/[sq]\b",
    r"\brmdir\s+/[sq]\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+push\b",
    r"\bgit\s+clean\s+-[fdx]{1,3}\b",
    r"\bformat\s+[a-z]:\b",
    r"\bmkfs\b",
    r"\bcurl\b.*\|\s*(?:bash|sh|powershell|pwsh)",
]


def classify_command_security(command: str) -> SecurityTier:
    """Classify shell command into Tier 0 (Safe Read), Tier 1 (Safe Mutation), or Tier 2 (Destructive)."""
    cmd_lower = command.strip().lower()

    # Check Tier 2 (Destructive)
    for pat in DESTRUCTIVE_COMMAND_PATTERNS:
        if re.search(pat, cmd_lower):
            return SecurityTier.DESTRUCTIVE

    # Check Tier 0 (Safe Read)
    safe_read_prefixes = (
        "git status", "git diff", "git log", "git branch", "git show",
        "dir", "ls", "cat", "type ", "head ", "tail ", "echo ", "pwd",
        "where ", "which ", "whoami", "python --version", "node --version",
        "findstr ", "grep ",
    )
    if any(cmd_lower.startswith(p) for p in safe_read_prefixes):
        return SecurityTier.SAFE_READ

    # Everything else defaults to Tier 1 (Safe Mutation / Execution)
    return SecurityTier.SAFE_MUTATION


class ToolRegistry:
    """Registry of tools available to the autonomous agent harness."""

    def __init__(self, workspace: str = "."):
        self.workspace = os.path.abspath(workspace)
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._register_default_tools()

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        handler: Callable[..., Any],
        tier: SecurityTier = SecurityTier.SAFE_READ
    ):
        self.tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "handler": handler,
            "tier": tier,
        }

    def _register_default_tools(self):
        # 1. read_file
        def _read_file_tool(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
            from tools.file_tools import read_file
            abs_p = (Path(self.workspace) / path).resolve()
            r = read_file(str(abs_p))
            if not r["ok"]:
                return f"Error: {r['error']}"
            content = r["content"]
            lines = content.splitlines()
            if start_line is not None or end_line is not None:
                s = max(1, start_line or 1) - 1
                e = end_line or len(lines)
                sliced = lines[s:e]
                return "\n".join(f"{s+idx+1}: {line}" for idx, line in enumerate(sliced))
            return content

        self.register(
            name="read_file",
            description="Read content of a file with optional line range slice.",
            parameters={"path": "string", "start_line": "integer (optional)", "end_line": "integer (optional)"},
            handler=_read_file_tool,
            tier=SecurityTier.SAFE_READ
        )

        # 2. write_file
        def _write_file_tool(path: str, content: str) -> str:
            from tools.file_tools import write_file
            from tools.checkpoint_tools import create_checkpoint
            from tools.preflight_tools import preflight_check_file

            # Checkpoint before mutation
            create_checkpoint(description=f"Auto-checkpoint before writing {path}", root_dir=self.workspace)

            abs_p = (Path(self.workspace) / path).resolve()
            r = write_file(str(abs_p), content)
            if not r["ok"]:
                return f"Error: {r['error']}"

            # Preflight check
            pf = preflight_check_file(str(abs_p))
            if not pf.get("valid", True):
                if pf.get("auto_repaired_content"):
                    abs_p.write_text(pf["auto_repaired_content"], encoding="utf-8")
                    return f"Successfully wrote {path} (auto-repaired syntax error)"
                return f"Wrote {path} with warning: {pf.get('error')}"

            return f"Successfully wrote {path} ({len(content)} characters)"

        self.register(
            name="write_file",
            description="Write full content to a file. Auto-checkpoints and runs pre-flight syntax check.",
            parameters={"path": "string", "content": "string"},
            handler=_write_file_tool,
            tier=SecurityTier.SAFE_MUTATION
        )

        # 3. edit_file
        def _edit_file_tool(path: str, target: str, replacement: str) -> str:
            from tools.file_tools import replace_in_file
            from tools.checkpoint_tools import create_checkpoint
            from tools.preflight_tools import preflight_check_file

            # Checkpoint before mutation
            create_checkpoint(description=f"Auto-checkpoint before editing {path}", root_dir=self.workspace)

            abs_p = (Path(self.workspace) / path).resolve()
            r = replace_in_file(str(abs_p), target, replacement)
            if not r["ok"]:
                return f"Error: {r['error']}"

            # Preflight check
            pf = preflight_check_file(str(abs_p))
            if not pf.get("valid", True):
                if pf.get("auto_repaired_content"):
                    abs_p.write_text(pf["auto_repaired_content"], encoding="utf-8")
                    return f"Successfully edited {path} (auto-repaired syntax error)"
                return f"Edited {path} with warning: {pf.get('error')}"

            return f"Successfully replaced target in {path}"

        self.register(
            name="edit_file",
            description="Surgically replace exact target content with replacement in an existing file.",
            parameters={"path": "string", "target": "string", "replacement": "string"},
            handler=_edit_file_tool,
            tier=SecurityTier.SAFE_MUTATION
        )

        # 4. shell_command
        def _shell_tool(command: str) -> str:
            from tools.terminal_tools import run_command
            tier = classify_command_security(command)
            if tier == SecurityTier.DESTRUCTIVE:
                return f"BLOCKED: Command '{command}' is classified as DESTRUCTIVE (Tier 2). Explicit user authorization required."

            r = run_command(command, cwd=self.workspace)
            out = r.get("stdout", "").strip()
            err = r.get("stderr", "").strip()
            if r.get("ok"):
                return out or "(Command succeeded with no output)"
            return f"Command failed (exit {r.get('exit')}):\n{err}\n{out}"

        self.register(
            name="shell_command",
            description="Execute a safe shell command in the workspace directory.",
            parameters={"command": "string"},
            handler=_shell_tool,
            tier=SecurityTier.SAFE_MUTATION
        )

        # 5. grep_search
        def _grep_tool(query: str, path: Optional[str] = None) -> str:
            from tools.file_tools import scan_codebase
            res = scan_codebase(self.workspace)
            if not res["ok"]:
                return f"Scan error: {res.get('error')}"
            hits = []
            q_low = query.lower()
            for f in res.get("files", []):
                rel = f.get("path", "")
                if path and path not in rel:
                    continue
                abs_f = Path(self.workspace) / rel
                try:
                    text = abs_f.read_text(encoding="utf-8", errors="ignore")
                    for idx, line in enumerate(text.splitlines(), 1):
                        if q_low in line.lower():
                            hits.append(f"{rel}:{idx}: {line.strip()}")
                            if len(hits) >= 30:
                                break
                except Exception:
                    pass
                if len(hits) >= 30:
                    break
            if not hits:
                return f"No matches found for '{query}'"
            return "\n".join(hits[:30])

        self.register(
            name="grep_search",
            description="Search codebase for text or symbol matches.",
            parameters={"query": "string", "path": "string (optional)"},
            handler=_grep_tool,
            tier=SecurityTier.SAFE_READ
        )

        # 6. ast_blast
        def _ast_blast_tool(symbol: str, target_file: Optional[str] = None) -> str:
            from tools.graph_tools import compute_blast_radius
            blast = compute_blast_radius(symbol, target_file=target_file, root_dir=self.workspace)
            callers = [f"{c['file']}:{c.get('line', '?')}" for c in blast.get("callers", [])]
            tests = blast.get("affected_tests", [])
            return (
                f"Symbol '{symbol}' Blast Radius [{blast['severity']}]:\n"
                f"- Callers ({blast['caller_count']}): {', '.join(callers[:5]) or 'None'}\n"
                f"- Affected Tests: {', '.join(tests) or 'None'}"
            )

        self.register(
            name="ast_blast",
            description="Analyze AST blast radius for a symbol before modifying it.",
            parameters={"symbol": "string", "target_file": "string (optional)"},
            handler=_ast_blast_tool,
            tier=SecurityTier.SAFE_READ
        )

        # 7. undo
        def _undo_tool(target: Optional[str] = None) -> str:
            from tools.checkpoint_tools import restore_checkpoint
            res = restore_checkpoint(checkpoint_id_or_index=target, root_dir=self.workspace)
            if res.get("ok"):
                return res.get("message", "Reverted successfully.")
            return f"Undo failed: {res.get('error')}"

        self.register(
            name="undo",
            description="Restore workspace or file to previous turn checkpoint.",
            parameters={"target": "string (checkpoint id, turn number, or filename)"},
            handler=_undo_tool,
            tier=SecurityTier.SAFE_MUTATION
        )

        # 8. delegate
        def _delegate_tool(role: str, task: str) -> str:
            from agent.subagent_pool import run_subagent
            r = run_subagent(role, task, workspace=self.workspace)
            if not r.get("ok", False) and "error" in r:
                return f"Subagent error: {r['error']}"
            return r.get("summary", "Subagent task complete.")

        self.register(
            name="delegate",
            description="Delegate exploratory task (researcher, test_runner, reviewer) to an isolated subagent worker.",
            parameters={"role": "string ('researcher', 'test_runner', 'reviewer')", "task": "string"},
            handler=_delegate_tool,
            tier=SecurityTier.SAFE_READ
        )

        # 9. compact
        def _compact_tool() -> str:
            return "Context compaction requested. Working state preserved."

        self.register(
            name="compact",
            description="Trigger working memory compaction to reduce token overhead.",
            parameters={},
            handler=_compact_tool,
            tier=SecurityTier.SAFE_READ
        )

    def execute(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute a registered tool with given arguments."""
        tool = self.tools.get(tool_name)
        if not tool:
            return f"Error: Tool '{tool_name}' not found. Available tools: {', '.join(self.tools.keys())}"
        handler = tool["handler"]
        try:
            return str(handler(**arguments))
        except TypeError as e:
            return f"Argument Error for tool '{tool_name}': {e}"
        except Exception as e:
            return f"Execution Error in tool '{tool_name}': {e}"

    def get_tool_prompt_specs(self) -> str:
        """Format available tool definitions for system prompt."""
        specs = ["Available Tools:"]
        for name, t in self.tools.items():
            params = json.dumps(t["parameters"])
            specs.append(f"- {name}({params}): {t['description']}")
        return "\n".join(specs)


# ── ReAct Parser ──────────────────────────────────────────────────────────────

def parse_react_step(llm_response: str) -> Optional[Dict[str, Any]]:
    """
    Parse a ReAct step from LLM output.
    Looks for:
      Action: <tool_name>
      Action Input: <json or string>
    Or JSON format:
      ```json {"action": "...", "input": {...}} ```
    """
    text = llm_response.strip()

    # 1. JSON block match
    json_match = re.search(r'```(?:json)?\s*(\{\s*"action".*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            if "action" in data:
                inp = data.get("input", {})
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except Exception:
                        pass
                return {"action": data["action"], "input": inp if isinstance(inp, dict) else {"arg": inp}}
        except Exception:
            pass

    # 2. ReAct text match
    action_match = re.search(r'Action:\s*([a-zA-Z0-9_]+)', text)
    if action_match:
        action = action_match.group(1).strip()
        input_match = re.search(r'Action Input:\s*(.*?)(?=\n\s*(?:Observation:|Thought:|Action:|Final Answer:)|$)', text, re.DOTALL)
        raw_input = input_match.group(1).strip() if input_match else "{}"

        # Try parsing raw_input as JSON
        try:
            parsed_args = json.loads(raw_input)
            if not isinstance(parsed_args, dict):
                parsed_args = {"arg": parsed_args}
        except Exception:
            # Fallback to key-value or raw string
            parsed_args = {"arg": raw_input.strip("\"'")}

        return {"action": action, "input": parsed_args}

    # 3. Qwen XML tool_call match
    from agent.tool_interceptor import extract_qwen_tool_calls
    qwen_calls = extract_qwen_tool_calls(text)
    if qwen_calls:
        first = qwen_calls[0]
        action_map = {
            "list_files": "file_search",
            "ls": "file_search",
            "dir": "file_search",
            "cat": "read_file",
            "view_file": "read_file",
            "bash": "shell_command",
            "terminal": "shell_command",
            "run_command": "shell_command",
            "replace_in_file": "edit_file",
            "create_file": "write_file",
        }
        action = action_map.get(first["function"].lower(), first["function"])
        return {"action": action, "input": first["parameters"]}

    return None


def run_react_loop(
    task: str,
    registry: ToolRegistry,
    system_prompt: Optional[str] = None,
    max_turns: int = 5,
    llm_ask: Optional[Callable[[str, str], str]] = None
) -> Dict[str, Any]:
    """
    Execute a closed-loop ReAct cycle (Thought -> Action -> Observation).
    """
    from core.llm import ask
    _ask = llm_ask or (lambda p, s: ask(p, system=s))

    base_system = system_prompt or "You are an autonomous engineering agent with tool-calling capabilities."
    tools_spec = registry.get_tool_prompt_specs()
    react_system = (
        f"{base_system}\n\n"
        f"{tools_spec}\n\n"
        "To use a tool, respond in this exact format:\n"
        "Thought: reason about what to do next\n"
        "Action: tool_name\n"
        "Action Input: {\"param\": \"value\"}\n\n"
        "When your task is complete or answered, output:\n"
        "Final Answer: your final comprehensive response"
    )

    history = [f"Task: {task}"]
    turns_taken = 0

    while turns_taken < max_turns:
        turns_taken += 1
        prompt = "\n\n".join(history)
        resp = _ask(prompt, react_system)

        if "Final Answer:" in resp:
            final_part = resp.split("Final Answer:", 1)[1].strip()
            history.append(resp)
            return {"ok": True, "answer": final_part, "turns": turns_taken, "history": history}

        parsed = parse_react_step(resp)
        if not parsed:
            # Model gave direct text answer without explicit tool or final answer
            history.append(resp)
            return {"ok": True, "answer": resp, "turns": turns_taken, "history": history}

        action = parsed["action"]
        args = parsed["input"]
        obs = registry.execute(action, args)
        history.append(f"{resp}\nObservation: {obs}")

    return {
        "ok": False,
        "answer": "Maximum ReAct turns exceeded before Final Answer was reached.",
        "turns": turns_taken,
        "history": history
    }
