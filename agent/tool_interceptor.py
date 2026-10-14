"""
agent/tool_interceptor.py — Intercepts and executes model-native tool calls (e.g. Qwen XML format).

Handles models (like Qwen 3.8 27B / Qwen 2.5 Coder) that emit:
<tool_call>
<function=list_files>
<parameter=path>
.
</parameter>
</function>
</tool_call>

Executes the requested tools in the workspace and feeds the observation back to the model
so that the model completes its generation rather than halting on raw XML.
"""

import re
import os
import json
from typing import List, Dict, Any, Generator, Optional
from tools.file_tools import list_dir, read_file, write_file, replace_in_file, scan_codebase
from tools.terminal_tools import run_command
from core.logger import get_logger

log = get_logger(__name__)


def extract_qwen_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Extract XML and JSON tool calls emitted by models."""
    calls = []
    if not text or ("<tool_call>" not in text and '"action"' not in text):
        return calls

    # Pattern 1: <tool_call><function=name><parameter=key>val</parameter></function></tool_call>
    for m in re.finditer(r'<tool_call>\s*<function=([a-zA-Z0-9_\-]+)>(.*?)</function>\s*</tool_call>', text, re.DOTALL):
        func = m.group(1).strip()
        body = m.group(2)
        params = {}
        for pm in re.finditer(r'<parameter=([a-zA-Z0-9_\-]+)>\s*(.*?)\s*</parameter>', body, re.DOTALL):
            key = pm.group(1).strip()
            val = pm.group(2).strip()
            try:
                val = json.loads(val)
            except Exception:
                pass
            params[key] = val
        calls.append({"function": func, "parameters": params})

    # Pattern 2: <tool_call>{"name": "...", "arguments": {...}}</tool_call>
    for m in re.finditer(r'<tool_call>\s*(\{\s*"name".*?\})\s*</tool_call>', text, re.DOTALL):
        try:
            data = json.loads(m.group(1))
            calls.append({"function": data.get("name", ""), "parameters": data.get("arguments", {})})
        except Exception:
            pass

    return calls


def execute_tool_call(func: str, params: Dict[str, Any], workspace: str = ".") -> str:
    """Execute a single tool call safely inside the workspace via ToolRegistry."""
    from agent.react_harness import ToolRegistry
    registry = ToolRegistry(workspace=workspace)
    return registry.execute(func, params)


def resolve_tool_calls_text(
    prompt: str,
    system: Optional[str] = None,
    workspace: str = ".",
    backend: Optional[str] = None,
    max_turns: int = 3
) -> str:
    """
    Run LLM turn and iteratively resolve any tool calls until a final answer is produced.
    """
    from core.llm import ask
    curr_prompt = prompt

    for turn in range(max_turns):
        resp = ask(curr_prompt, system=system, backend=backend)
        calls = extract_qwen_tool_calls(resp)
        if not calls:
            return resp

        # Execute tools
        obs = []
        for c in calls:
            out = execute_tool_call(c["function"], c["parameters"], workspace=workspace)
            obs.append(f"<tool_response>\n<function={c['function']}>\n{out}\n</function>\n</tool_response>")

        curr_prompt = (
            f"{curr_prompt}\n\n"
            f"Assistant: {resp}\n\n"
            f"Observation:\n" + "\n".join(obs) + "\n\n"
            f"All requested tool outputs are provided above. Now generate the complete response directly without further tool calls."
        )

    return resp


def resolve_tool_calls_stream(
    prompt: str,
    system: Optional[str] = None,
    workspace: str = ".",
    backend: Optional[str] = None,
    max_turns: int = 3
) -> Generator[str, None, None]:
    """
    Stream tokens from LLM. If a turn produces <tool_call>, intercept it, execute the tools,
    yield execution notifications, and stream the final resolution.
    """
    from core.llm import ask_stream
    curr_prompt = prompt

    for turn in range(max_turns):
        buf = ""
        has_tool_call_tag = False

        for token in ask_stream(curr_prompt, system=system, backend=backend):
            buf += token
            if "<tool_call>" in buf:
                has_tool_call_tag = True
            else:
                yield token

        calls = extract_qwen_tool_calls(buf)
        if not calls:
            # No tool calls; stream complete
            break

        # Tool calls detected: notify user in stream
        obs = []
        for c in calls:
            fname = c["function"]
            params_str = ", ".join(f"{k}='{v}'" for k, v in c["parameters"].items())
            yield f"\n\n⚙️ *[Executing tool]* `{fname}({params_str})`...\n"
            out = execute_tool_call(fname, c["parameters"], workspace=workspace)
            obs.append(f"<tool_response>\n<function={fname}>\n{out}\n</function>\n</tool_response>")

        yield "\n---\n\n"

        curr_prompt = (
            f"{curr_prompt}\n\n"
            f"Assistant: {buf}\n\n"
            f"Observation:\n" + "\n".join(obs) + "\n\n"
            f"All requested tool outputs are provided above. Now produce your complete final response directly without further tool calls."
        )
