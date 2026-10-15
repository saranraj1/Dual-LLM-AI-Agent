"""
agent/react_harness.py — Unified ReAct Execution Harness & Sandboxed Tool Loop.

Implements native function/tool execution (Pillar 1) with:
- Standardized tool schemas and JSON/block parameter parsing.
- 3-tiered security sandboxing:
    * Tier 0 (Safe Read): auto-approved
    * Tier 1 (Safe Mutation): auto-approved with shadow git checkpointing + pre-flight AST validation
    * Tier 2 (Destructive/System): intercepted with user confirmation / interactive QA prompt
- Strict Workspace Path Sandboxing (blocks ../ traversal outside workspace root).
- Automatic Secret Redaction across all tool outputs.
- 3-Phase Self-Healing Fuzzy Edit Engine (exact -> whitespace-normalized -> SequenceMatcher).
- Unified Tool Registry with AST symbol search, test runner, git diagnostics, and parameter alias mapping.
- Thought → Action → Observation iterative loop with synchronous and streaming generators.
"""

import ast
import difflib
import json
import os
import re
import subprocess
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Generator, Tuple


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
    r"\bremove-item\b.*-(?:recurse|force)",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+push\b",
    r"\bgit\s+clean\s+-[fdx]{1,3}\b",
    r"\bformat\s+[a-z]:\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bcurl\b.*\|\s*(?:bash|sh|powershell|pwsh)",
    r"\bwget\b.*\|\s*(?:bash|sh|powershell|pwsh)",
    r"\biex\b.*(?:irm|iwr|downloadstring)",
    r"\bdrop\s+(?:database|table)\b",
    r"\btruncate\s+table\b",
]


def classify_command_security(command: str) -> SecurityTier:
    """Classify shell command into Tier 0 (Safe Read), Tier 1 (Safe Mutation), or Tier 2 (Destructive)."""
    # Check Tier 2 (Destructive)
    for pat in DESTRUCTIVE_COMMAND_PATTERNS:
        if re.search(pat, command, re.IGNORECASE):
            return SecurityTier.DESTRUCTIVE

    cmd_lower = command.strip().lower()

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


# ── Sandboxing & Security Helpers ─────────────────────────────────────────────

def sanitize_path(path: str, workspace: str) -> Path:
    """
    Ensure path resolves strictly within the workspace directory.
    Delegates to core.security.sanitize_path.
    """
    from core.security import sanitize_path as _sanitize
    return _sanitize(path, workspace)


def mask_secrets(text: str) -> str:
    """
    Mask known sensitive token patterns in tool outputs and logs.
    Delegates to core.security.mask_secrets.
    """
    from core.security import mask_secrets as _mask
    return _mask(text)


# ── Self-Healing Edit Engine ──────────────────────────────────────────────────

def fuzzy_replace_in_content(
    content: str,
    target: str,
    replacement: str,
    similarity_threshold: float = 0.88
) -> Tuple[bool, str, str]:
    """
    3-phase self-healing string replacement.
    Phase 1: Exact substring match.
    Phase 2: Whitespace-normalized line matching (handles indentation / newline variances).
    Phase 3: Sliding window SequenceMatcher at similarity >= similarity_threshold.

    Returns: (success: bool, new_content: str, diagnostic_message: str)
    """
    if not target:
        return False, content, "Target string cannot be empty."

    # Phase 1: Exact match
    if target in content:
        count = content.count(target)
        new_content = content.replace(target, replacement, 1)
        return True, new_content, f"Exact match replaced ({count} occurrence(s) found)."

    # Prepare lines
    c_lines = content.replace("\r\n", "\n").splitlines(keepends=True)
    t_lines = target.replace("\r\n", "\n").splitlines()
    window_size = len(t_lines)

    # Phase 2: Whitespace-normalized line matching
    def norm_line(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip())

    target_norm = [norm_line(l) for l in t_lines if l.strip()]

    if target_norm and len(c_lines) >= len(target_norm):
        for i in range(len(c_lines) - len(target_norm) + 1):
            slice_lines = [norm_line(l) for l in c_lines[i:i + len(target_norm)] if l.strip()]
            if slice_lines == target_norm:
                before = "".join(c_lines[:i])
                after = "".join(c_lines[i + len(target_norm):])
                sep = "" if replacement.endswith("\n") or not after else "\n"
                new_content = before + replacement + sep + after
                return True, new_content, "Whitespace-normalized match replaced."

    # Phase 3: Sliding window SequenceMatcher
    best_ratio = 0.0
    best_window = None
    best_idx = -1
    best_len = 0

    if window_size > 0 and len(c_lines) >= window_size:
        min_w = max(1, window_size - 2)
        max_w = min(len(c_lines), window_size + 2)
        for w in range(min_w, max_w + 1):
            for i in range(len(c_lines) - w + 1):
                window_slice = "".join(c_lines[i:i + w])
                ratio = difflib.SequenceMatcher(None, target, window_slice).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_window = window_slice
                    best_idx = i
                    best_len = w

    if best_ratio >= similarity_threshold and best_idx != -1:
        before = "".join(c_lines[:best_idx])
        after = "".join(c_lines[best_idx + best_len:])
        sep = "" if replacement.endswith("\n") or not after else "\n"
        new_content = before + replacement + sep + after
        return True, new_content, f"Fuzzy match (similarity {best_ratio:.2f}) replaced."

    closest_snippet = f" Closest candidate (similarity {best_ratio:.2f}):\n{best_window[:200]}" if best_window else ""
    return False, content, f"Target content not found.{closest_snippet}"


# ── AST & Code Tools Helpers ──────────────────────────────────────────────────

def find_symbol_in_workspace(symbol: str, workspace: str, max_results: int = 30) -> List[str]:
    """Find function, class, and variable definitions in the workspace."""
    results = []
    ws = Path(workspace).resolve()
    skip_dirs = {".git", ".agent_backups", "__pycache__", ".venv", "venv", "node_modules"}

    for root, dirs, files in os.walk(ws):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]
        for file in sorted(files):
            if not file.endswith((".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".json")):
                continue
            abs_f = Path(root) / file
            try:
                rel_f = str(abs_f.relative_to(ws))
            except ValueError:
                rel_f = str(abs_f)

            try:
                content = abs_f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            # Python AST parsing
            if file.endswith(".py"):
                try:
                    tree = ast.parse(content, filename=rel_f)
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if symbol.lower() in node.name.lower():
                                results.append(f"{rel_f}:{node.lineno}: def {node.name}()")
                        elif isinstance(node, ast.ClassDef):
                            if symbol.lower() in node.name.lower():
                                results.append(f"{rel_f}:{node.lineno}: class {node.name}")
                except Exception:
                    pass

            # Regex search for symbols
            pattern = re.compile(
                rf"(?:def|class|function|var|let|const|type|interface)\s+([a-zA-Z0-9_]*{re.escape(symbol)}[a-zA-Z0-9_]*)",
                re.IGNORECASE
            )
            for lineno, line in enumerate(content.splitlines(), 1):
                if pattern.search(line):
                    entry = f"{rel_f}:{lineno}: {line.strip()}"
                    if entry not in results:
                        results.append(entry)
                if len(results) >= max_results:
                    break
        if len(results) >= max_results:
            break

    return results[:max_results]


def run_tests_tool(target: Optional[str] = None, timeout: int = 30, workspace: str = ".") -> str:
    """Execute pytest suite safely inside the workspace."""
    cmd = ["pytest"]
    if target:
        cmd.append(target.strip())
    cmd.extend(["-q", "--no-header"])
    try:
        proc = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        code = proc.returncode
        status = "PASSED" if code == 0 else f"FAILED (exit {code})"
        combined = f"Pytest {status}:\n{out}"
        if err:
            combined += f"\nStderr:\n{err}"
        return combined
    except subprocess.TimeoutExpired:
        return f"Test Execution Error: Timed out after {timeout}s"
    except Exception as exc:
        return f"Test Execution Error: {exc}"


def git_status_tool(workspace: str = ".") -> str:
    """Get concise git status for the workspace."""
    from tools.terminal_tools import run_command
    res = run_command("git status --short", cwd=workspace)
    if res.get("ok"):
        return res.get("stdout", "").strip() or "(Clean working tree)"
    return f"Git Error: {res.get('stderr', '')}"


def git_diff_tool(path: Optional[str] = None, workspace: str = ".") -> str:
    """Get current git diff for the workspace or a specific path."""
    from tools.terminal_tools import run_command
    cmd = "git diff"
    if path:
        cmd += f" -- {path}"
    res = run_command(cmd, cwd=workspace)
    if res.get("ok"):
        return res.get("stdout", "").strip() or "(No changes in git diff)"
    return f"Git Error: {res.get('stderr', '')}"


# ── Tool Registry ─────────────────────────────────────────────────────────────

class ToolRegistry:
    """Registry of tools available to the autonomous agent harness."""

    def __init__(self, workspace: str = "."):
        self.workspace = os.path.abspath(workspace)
        self.tools: Dict[str, Dict[str, Any]] = {}
        self.aliases: Dict[str, str] = {
            "list_files": "list_dir",
            "ls": "list_dir",
            "dir": "list_dir",
            "get_files": "list_dir",
            "view_file": "read_file",
            "cat": "read_file",
            "get_file": "read_file",
            "create_file": "write_file",
            "replace_in_file": "edit_file",
            "search_files": "grep_search",
            "find_in_files": "grep_search",
            "search": "grep_search",
            "bash": "shell_command",
            "terminal": "shell_command",
            "run_command": "shell_command",
            "locate_symbol": "find_symbol",
            "pytest": "run_tests",
            "test": "run_tests",
        }
        self.stats: Dict[str, Any] = {
            "invocations": 0,
            "failures": 0,
            "tool_usage": {},
        }
        self._register_default_tools()
        self._mcp_bridge = None
        self._attach_mcp_servers()

    def _attach_mcp_servers(self):
        try:
            from agent.mcp_client import MCPBridge
            bridge = MCPBridge(self.workspace)
            bridge.load_config()
            if bridge.clients:
                bridge.connect_all()
                bridge.register_tools(self)
                self._mcp_bridge = bridge
        except Exception:
            pass

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
        def _read_file_tool(
            path: Optional[str] = None,
            file: Optional[str] = None,
            filepath: Optional[str] = None,
            target_file: Optional[str] = None,
            start_line: Optional[int] = None,
            end_line: Optional[int] = None,
            offset: Optional[int] = None,
            limit: Optional[int] = None,
            **kwargs
        ) -> str:
            from tools.file_tools import read_file
            rel_path = path or file or filepath or target_file or ""
            if not rel_path:
                return "Error: File path is required."

            abs_p = sanitize_path(rel_path, self.workspace)
            r = read_file(str(abs_p))
            if not r.get("ok"):
                return f"Error: {r.get('error', 'File not found')}"

            content = r.get("content", "")
            lines = content.splitlines()

            has_slice = (start_line is not None) or (end_line is not None) or (offset is not None) or (limit is not None)
            if not has_slice:
                return content or "(empty file)"

            start_num = max(1, int(offset or start_line or 1))
            start_idx = start_num - 1
            if limit is not None:
                end_idx = start_idx + int(limit)
            elif end_line is not None:
                end_idx = int(end_line)
            else:
                end_idx = len(lines)

            sliced = lines[start_idx:end_idx]
            if not sliced:
                return "(empty file)"
            return "\n".join(f"{start_num + idx}: {line}" for idx, line in enumerate(sliced))

        self.register(
            name="read_file",
            description="Read content of a file with optional line range slice or offset/limit.",
            parameters={
                "path": "string",
                "start_line": "integer (optional)",
                "end_line": "integer (optional)",
                "offset": "integer (optional, 1-based start line)",
                "limit": "integer (optional, max lines to return)",
            },
            handler=_read_file_tool,
            tier=SecurityTier.SAFE_READ
        )

        # 2. write_file
        def _write_file_tool(
            path: Optional[str] = None,
            file: Optional[str] = None,
            filepath: Optional[str] = None,
            content: Optional[str] = "",
            **kwargs
        ) -> str:
            from tools.file_tools import write_file
            from tools.checkpoint_tools import create_checkpoint
            from tools.preflight_tools import preflight_check_file

            rel_path = path or file or filepath or ""
            if not rel_path:
                return "Error: File path is required."

            abs_p = sanitize_path(rel_path, self.workspace)

            # Checkpoint before mutation
            create_checkpoint(description=f"Auto-checkpoint before writing {rel_path}", root_dir=self.workspace)

            r = write_file(str(abs_p), content or "")
            if not r.get("ok"):
                return f"Error: {r.get('error')}"

            # Preflight check
            pf = preflight_check_file(str(abs_p))
            if not pf.get("valid", True):
                if pf.get("auto_repaired_content"):
                    abs_p.write_text(pf["auto_repaired_content"], encoding="utf-8")
                    return f"Successfully wrote {rel_path} (auto-repaired syntax error)"
                return f"Wrote {rel_path} with warning: {pf.get('error')}"

            return f"Successfully wrote {rel_path} ({len(content or '')} characters)"

        self.register(
            name="write_file",
            description="Write full content to a file. Auto-checkpoints and runs pre-flight syntax check.",
            parameters={"path": "string", "content": "string"},
            handler=_write_file_tool,
            tier=SecurityTier.SAFE_MUTATION
        )

        # 3. edit_file
        def _edit_file_tool(
            path: Optional[str] = None,
            file: Optional[str] = None,
            filepath: Optional[str] = None,
            target: Optional[str] = None,
            old_str: Optional[str] = None,
            find: Optional[str] = None,
            replacement: Optional[str] = None,
            new_str: Optional[str] = None,
            replace: Optional[str] = None,
            **kwargs
        ) -> str:
            from tools.checkpoint_tools import create_checkpoint
            from tools.preflight_tools import preflight_check_file

            rel_path = path or file or filepath or ""
            if not rel_path:
                return "Error: File path is required."

            tgt = target if target is not None else (old_str if old_str is not None else find)
            rep = replacement if replacement is not None else (new_str if new_str is not None else replace)
            if tgt is None or rep is None:
                return "Error: Both target and replacement strings are required."

            abs_p = sanitize_path(rel_path, self.workspace)
            if not abs_p.exists():
                return f"Error: File '{rel_path}' does not exist."

            # Checkpoint before mutation
            create_checkpoint(description=f"Auto-checkpoint before editing {rel_path}", root_dir=self.workspace)

            try:
                content = abs_p.read_text(encoding="utf-8")
            except Exception as e:
                return f"Error reading file '{rel_path}': {e}"

            success, new_content, diag = fuzzy_replace_in_content(content, tgt, rep)
            if not success:
                return f"Error: {diag}"

            try:
                abs_p.write_text(new_content, encoding="utf-8")
            except Exception as e:
                return f"Error writing file '{rel_path}': {e}"

            # Preflight check
            pf = preflight_check_file(str(abs_p))
            if not pf.get("valid", True):
                if pf.get("auto_repaired_content"):
                    abs_p.write_text(pf["auto_repaired_content"], encoding="utf-8")
                    return f"Successfully replaced target in {rel_path} (auto-repaired syntax error)"
                return f"Successfully replaced target in {rel_path} with warning: {pf.get('error')}"

            return f"Successfully replaced target in {rel_path}"

        self.register(
            name="edit_file",
            description="Surgically replace target content with replacement in an existing file using self-healing 3-phase matching.",
            parameters={"path": "string", "target": "string", "replacement": "string"},
            handler=_edit_file_tool,
            tier=SecurityTier.SAFE_MUTATION
        )

        # 4. patch_file (alias to edit_file)
        self.register(
            name="patch_file",
            description="Apply surgical replacement patch to a file with fuzzy fallback.",
            parameters={"path": "string", "target": "string", "replacement": "string"},
            handler=_edit_file_tool,
            tier=SecurityTier.SAFE_MUTATION
        )

        # 5. list_dir
        def _list_dir_tool(path: Optional[str] = ".", depth: int = 2, **kwargs) -> str:
            from tools.file_tools import list_dir
            safe_p = sanitize_path(path or ".", self.workspace)
            res = list_dir(str(safe_p), depth=int(depth))
            if not res.get("ok"):
                return f"Error: {res.get('error', 'Could not list directory')}"
            entries = res.get("entries", [])
            lines = [f"{e['path']} ({e['type']})" for e in entries[:40]]
            if len(entries) > 40:
                lines.append(f"... (+{len(entries)-40} more)")
            return "\n".join(lines) or "(empty directory)"

        self.register(
            name="list_dir",
            description="List directory entries recursively up to given depth within workspace sandbox.",
            parameters={"path": "string (optional, default '.')", "depth": "integer (optional, default 2)"},
            handler=_list_dir_tool,
            tier=SecurityTier.SAFE_READ
        )

        # 6. shell_command
        def _shell_tool(command: Optional[str] = None, cmd: Optional[str] = None, **kwargs) -> str:
            from tools.terminal_tools import run_command
            c = command or cmd or ""
            if not c:
                return "Error: command parameter required"

            tier = classify_command_security(c)
            if tier == SecurityTier.DESTRUCTIVE:
                return f"BLOCKED: Command '{c}' is classified as DESTRUCTIVE (Tier 2). Explicit user authorization required."

            r = run_command(c, cwd=self.workspace)
            out = r.get("stdout", "").strip()
            err = r.get("stderr", "").strip()
            if r.get("ok"):
                return out or "(Command succeeded with no output)"
            return f"Command exit {r.get('exit')}: {err}\n{out}".strip()

        self.register(
            name="shell_command",
            description="Execute a safe shell command inside the workspace directory.",
            parameters={"command": "string"},
            handler=_shell_tool,
            tier=SecurityTier.SAFE_MUTATION
        )

        # 7. grep_search
        def _grep_tool(query: Optional[str] = "", path: Optional[str] = None, **kwargs) -> str:
            if not query:
                return "Error: query parameter required"
            from tools.file_tools import search_in_files
            search_root = str(sanitize_path(path, self.workspace)) if path else self.workspace
            res = search_in_files(search_root, query, max_results=30)
            if not res.get("ok"):
                return f"Scan error: {res.get('error')}"
            matches = res.get("matches", [])
            if not matches:
                return f"No matches found for '{query}'"
            return "\n".join(f"{m['file']}:{m['line_no']}: {m['content']}" for m in matches[:30])

        self.register(
            name="grep_search",
            description="Search codebase for text or symbol matches across workspace files.",
            parameters={"query": "string", "path": "string (optional)"},
            handler=_grep_tool,
            tier=SecurityTier.SAFE_READ
        )

        # 8. find_symbol
        def _find_symbol_tool(symbol: Optional[str] = None, **kwargs) -> str:
            if not symbol:
                return "Error: symbol parameter required"
            matches = find_symbol_in_workspace(symbol, self.workspace)
            if not matches:
                return f"Symbol '{symbol}' not found in workspace."
            return "\n".join(matches)

        self.register(
            name="find_symbol",
            description="Locate function, class, and method definitions in workspace files via AST and syntax analysis.",
            parameters={"symbol": "string"},
            handler=_find_symbol_tool,
            tier=SecurityTier.SAFE_READ
        )

        # 9. run_tests
        def _run_tests_handler(target: Optional[str] = None, timeout: int = 30, **kwargs) -> str:
            return run_tests_tool(target=target, timeout=int(timeout), workspace=self.workspace)

        self.register(
            name="run_tests",
            description="Run pytest suite on target file/directory or full workspace with timeout.",
            parameters={"target": "string (optional test path)", "timeout": "integer (optional, default 30)"},
            handler=_run_tests_handler,
            tier=SecurityTier.SAFE_MUTATION
        )

        # 10. git_status
        self.register(
            name="git_status",
            description="Get current git status for the workspace.",
            parameters={},
            handler=lambda **kw: git_status_tool(workspace=self.workspace),
            tier=SecurityTier.SAFE_READ
        )

        # 11. git_diff
        self.register(
            name="git_diff",
            description="Get uncommitted git diff for the workspace or target file.",
            parameters={"path": "string (optional file path)"},
            handler=lambda path=None, **kw: git_diff_tool(path=path, workspace=self.workspace),
            tier=SecurityTier.SAFE_READ
        )

        # 12. ast_blast
        def _ast_blast_tool(symbol: str, target_file: Optional[str] = None, **kwargs) -> str:
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

        # 13. undo
        def _undo_tool(target: Optional[str] = None, **kwargs) -> str:
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

        # 14. delegate
        def _delegate_tool(role: str, task: str, **kwargs) -> str:
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

        # 15. compact
        def _compact_tool(**kwargs) -> str:
            return "Context compaction requested. Working state preserved."

        self.register(
            name="compact",
            description="Trigger working memory compaction to reduce token overhead.",
            parameters={},
            handler=_compact_tool,
            tier=SecurityTier.SAFE_READ
        )

    def execute(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> str:
        """Execute a registered tool with given arguments, sandboxing, and secret masking."""
        self.stats["invocations"] += 1
        raw_name = (tool_name or "").strip().lower().replace("-", "_")
        resolved_name = self.aliases.get(raw_name, raw_name)

        tool = self.tools.get(resolved_name)
        if not tool:
            self.stats["failures"] += 1
            return f"Error: Tool '{tool_name}' is not supported. Available tools: {', '.join(sorted(self.tools.keys()))}"

        self.stats["tool_usage"][resolved_name] = self.stats["tool_usage"].get(resolved_name, 0) + 1
        handler = tool["handler"]
        args = arguments or {}

        try:
            raw_out = handler(**args)
            return mask_secrets(str(raw_out))
        except PermissionError as pe:
            self.stats["failures"] += 1
            return f"Security Error: {pe}"
        except TypeError as te:
            self.stats["failures"] += 1
            return f"Argument Error for tool '{tool_name}': {te}"
        except Exception as exc:
            self.stats["failures"] += 1
            return f"Execution Error in tool '{tool_name}': {exc}"

    def get_stats(self) -> Dict[str, Any]:
        """Return runtime execution statistics and telemetry."""
        return {
            "invocations": self.stats["invocations"],
            "failures": self.stats["failures"],
            "tool_usage": dict(self.stats["tool_usage"]),
            "registered_tools": len(self.tools)
        }

    def get_tool_prompt_specs(self) -> str:
        """Format available tool definitions for system prompt."""
        specs = ["Available Tools:"]
        for name in sorted(self.tools.keys()):
            t = self.tools[name]
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
    action_match = re.search(r'Action:\s*([a-zA-Z0-9_\-]+)', text)
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
            parsed_args = {"arg": raw_input.strip("\"'")}

        return {"action": action, "input": parsed_args}

    # 3. Qwen XML tool_call match
    from agent.tool_interceptor import extract_qwen_tool_calls
    qwen_calls = extract_qwen_tool_calls(text)
    if qwen_calls:
        first = qwen_calls[0]
        return {"action": first["function"], "input": first["parameters"]}

    return None


# ── Streaming & Synchronous ReAct Loops ───────────────────────────────────────

def run_react_loop_stream(
    task: str,
    registry: ToolRegistry,
    system_prompt: Optional[str] = None,
    max_turns: int = 5,
    llm_ask: Optional[Callable[[str, str], str]] = None
) -> Generator[Dict[str, Any], None, None]:
    """
    Execute a closed-loop ReAct cycle yielding real-time event updates:
      {"type": "thought", "turn": turn, "content": ...}
      {"type": "action", "turn": turn, "tool": ..., "input": ...}
      {"type": "observation", "turn": turn, "content": ...}
      {"type": "final_answer", "turn": turn, "content": ...}
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

        # Extract thought if present
        thought_match = re.search(r"Thought:\s*(.*?)(?=\n\s*(?:Action:|Final Answer:)|$)", resp, re.DOTALL)
        if thought_match:
            thought_text = thought_match.group(1).strip()
            if thought_text:
                yield {"type": "thought", "turn": turns_taken, "content": thought_text}

        if "Final Answer:" in resp:
            final_part = resp.split("Final Answer:", 1)[1].strip()
            history.append(resp)
            yield {"type": "final_answer", "turn": turns_taken, "content": final_part}
            return

        parsed = parse_react_step(resp)
        if not parsed:
            # Model gave direct text answer without explicit tool or final answer
            history.append(resp)
            yield {"type": "final_answer", "turn": turns_taken, "content": resp}
            return

        action = parsed["action"]
        args = parsed["input"]
        yield {"type": "action", "turn": turns_taken, "tool": action, "input": args}

        obs = registry.execute(action, args)
        yield {"type": "observation", "turn": turns_taken, "content": obs}

        history.append(f"{resp}\nObservation: {obs}")

    yield {
        "type": "error",
        "turn": turns_taken,
        "content": "Maximum ReAct turns exceeded before Final Answer was reached."
    }


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
    events = []
    final_answer = None
    is_ok = False
    turns = 0
    history = [f"Task: {task}"]

    for ev in run_react_loop_stream(
        task=task,
        registry=registry,
        system_prompt=system_prompt,
        max_turns=max_turns,
        llm_ask=llm_ask
    ):
        events.append(ev)
        turns = max(turns, ev.get("turn", 0))
        ev_type = ev.get("type")
        if ev_type == "thought":
            history.append(f"Thought: {ev.get('content')}")
        elif ev_type == "action":
            history.append(f"Action: {ev.get('tool')}({ev.get('input')})")
        elif ev_type == "observation":
            history.append(f"Observation: {ev.get('content')}")
        elif ev_type == "final_answer":
            final_answer = ev["content"]
            history.append(f"Final Answer: {final_answer}")
            is_ok = True
        elif ev_type == "error":
            final_answer = ev["content"]
    try:
        from memory.episodic_memory import EpisodicMemory, Episode
        ep = Episode(
            task_goal=task,
            workspace=getattr(registry, "workspace", ""),
            trajectory=events,
            status="SUCCESS" if is_ok else "FAILED",
            error_summary=None if is_ok else (final_answer or "Incomplete loop")
        )
        EpisodicMemory(workspace=getattr(registry, "workspace", "")).record_episode(ep)
    except Exception:
        pass

    return {
        "ok": is_ok,
        "answer": final_answer or "No answer generated.",
        "turns": turns,
        "events": events,
        "history": history
    }
