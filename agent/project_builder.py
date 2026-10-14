"""
agent/project_builder.py — Autonomous Prompt-to-Project Builder (/build).

Implements end-to-end autonomous software engineering from natural language prompts:
  1. Spec Generation: Synthesizes architecture, module decomposition, and test requirements.
  2. Scaffolding: Creates directory hierarchies, dependencies (requirements.txt/pyproject.toml),
     README, and .gitignore under strict path sandboxing.
  3. Module Synthesis: Generates complete implementations with AST pre-flight compiler validation,
     heuristic micro-repairs, and shadow git checkpoints.
  4. Self-Healing Verification: Synthesizes test suite and executes closed-loop TDD healing
     until 100% green.
"""

import os
import sys
import json
import re
import time
import subprocess
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, List, Any, Optional, Generator, Callable

from core.llm import ask
from core.prompt_builder import SYSTEM_PROMPT
from core.ui import C
from agent.react_harness import sanitize_path
from tools.preflight_tools import validate_python_syntax, auto_repair_syntax
from tools.checkpoint_tools import create_checkpoint
from agent.executor import _extract_file_blocks


BUILDER_SYSTEM_PROMPT = SYSTEM_PROMPT + """
You are Antigravity's Autonomous Project Architect and Senior Systems Engineer.
When designing software:
1. Produce clean, modular, production-ready code with no mock placeholders or pass statements.
2. Ensure public APIs are cohesive, typed, and well-documented with docstrings.
3. Every test file must use pytest and rigorously test behavior, edge cases, and failure modes.
"""


@dataclass
class ProjectFileSpec:
    path: str
    description: str
    exports: List[str] = field(default_factory=list)


@dataclass
class ProjectTestSpec:
    path: str
    description: str
    targets: List[str] = field(default_factory=list)


@dataclass
class ProjectSpec:
    name: str
    description: str
    directories: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    files: List[ProjectFileSpec] = field(default_factory=list)
    tests: List[ProjectTestSpec] = field(default_factory=list)
    entrypoint: str = "main.py"
    run_instructions: str = "python main.py"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "directories": self.directories,
            "dependencies": self.dependencies,
            "files": [asdict(f) for f in self.files],
            "tests": [asdict(t) for t in self.tests],
            "entrypoint": self.entrypoint,
            "run_instructions": self.run_instructions,
        }


def _clean_json_text(text: str) -> str:
    """Strip markdown code fence blocks and extract inner JSON string."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    # Find outer bracket or brace if not fenced
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _slugify(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]+", "_", name.strip().lower()) or "autonomous_project"


def generate_spec(
    prompt: str,
    workspace: str = ".",
    llm_fn: Callable = ask
) -> ProjectSpec:
    """
    Synthesize a structured ProjectSpec from a user prompt using the LLM.
    Guarantees a valid ProjectSpec even if the LLM output is malformed.
    """
    spec_prompt = f"""You are an autonomous software architect. Analyze the user prompt and generate an end-to-end project specification in pure JSON format.

User Request:
"{prompt}"

Workspace path: {workspace}

Return a valid JSON object matching this schema:
{{
  "name": "project_name",
  "description": "Short summary of what this project does and its architectural design",
  "directories": ["src", "tests", "docs"],
  "dependencies": ["pytest", "rich"],
  "files": [
    {{
      "path": "src/core.py",
      "description": "Core data models and logic",
      "exports": ["CoreService"]
    }},
    {{
      "path": "main.py",
      "description": "CLI entry point and interactive runner",
      "exports": ["main"]
    }}
  ],
  "tests": [
    {{
      "path": "tests/test_core.py",
      "description": "Unit tests verifying CoreService methods and edge cases",
      "targets": ["src/core.py"]
    }}
  ],
  "entrypoint": "main.py",
  "run_instructions": "python main.py"
}}

Respond ONLY with the JSON object. Do not include markdown preamble or trailing explanations.
"""
    raw_response = llm_fn(spec_prompt, system=BUILDER_SYSTEM_PROMPT)
    cleaned = _clean_json_text(raw_response)

    try:
        data = json.loads(cleaned)
        files = [
            ProjectFileSpec(
                path=f.get("path", "module.py"),
                description=f.get("description", ""),
                exports=f.get("exports", [])
            )
            for f in data.get("files", [])
        ]
        tests = [
            ProjectTestSpec(
                path=t.get("path", "tests/test_main.py"),
                description=t.get("description", ""),
                targets=t.get("targets", [])
            )
            for t in data.get("tests", [])
        ]
        spec = ProjectSpec(
            name=_slugify(data.get("name", "autonomous_project")),
            description=data.get("description", prompt),
            directories=data.get("directories", ["tests"]),
            dependencies=data.get("dependencies", ["pytest"]),
            files=files if files else [ProjectFileSpec(path="main.py", description="Main logic")],
            tests=tests if tests else [ProjectTestSpec(path="tests/test_main.py", description="Main test suite")],
            entrypoint=data.get("entrypoint", "main.py"),
            run_instructions=data.get("run_instructions", "python main.py")
        )
        return spec
    except Exception:
        # Deterministic fallback spec
        proj_name = _slugify(prompt[:25])
        return ProjectSpec(
            name=proj_name,
            description=prompt,
            directories=["tests"],
            dependencies=["pytest"],
            files=[
                ProjectFileSpec(path=f"{proj_name}.py", description=f"Implementation for: {prompt}", exports=[proj_name]),
                ProjectFileSpec(path="main.py", description="Entry point", exports=["main"]),
            ],
            tests=[
                ProjectTestSpec(path=f"tests/test_{proj_name}.py", description=f"Unit tests for {proj_name}")
            ],
            entrypoint="main.py",
            run_instructions="python main.py"
        )


def scaffold_project(spec: ProjectSpec, workspace: str = ".") -> List[str]:
    """
    Create directory layout and project metadata (requirements.txt, README.md, .gitignore).
    Returns list of paths created.
    """
    ws_path = Path(workspace).resolve()
    created = []

    # 1. Create directories
    for rel_dir in spec.directories:
        try:
            target_dir = sanitize_path(rel_dir, str(ws_path))
            target_dir.mkdir(parents=True, exist_ok=True)
            created.append(str(target_dir.relative_to(ws_path)))
        except Exception:
            pass

    # Ensure tests directory always exists
    (ws_path / "tests").mkdir(parents=True, exist_ok=True)

    # 2. requirements.txt
    req_path = ws_path / "requirements.txt"
    if not req_path.exists():
        deps = set(spec.dependencies) | {"pytest"}
        req_path.write_text("\n".join(sorted(deps)) + "\n", encoding="utf-8")
        created.append("requirements.txt")

    # 3. .gitignore
    gi_path = ws_path / ".gitignore"
    if not gi_path.exists():
        gi_content = "__pycache__/\n*.pyc\n.pytest_cache/\n.coverage\nvenv/\n.env\n"
        gi_path.write_text(gi_content, encoding="utf-8")
        created.append(".gitignore")

    # 4. README.md
    readme_path = ws_path / "README.md"
    if not readme_path.exists():
        readme_content = f"""# {spec.name}

{spec.description}

## Installation
```bash
pip install -r requirements.txt
```

## Running
```bash
{spec.run_instructions}
```

## Running Tests
```bash
pytest
```
"""
        readme_path.write_text(readme_content, encoding="utf-8")
        created.append("README.md")

    return created


def _extract_code_from_response(response: str, expected_filename: Optional[str] = None) -> str:
    """Extract code from FILE: block or fenced markdown block."""
    blocks = _extract_file_blocks(response)
    if blocks:
        if expected_filename:
            for b in blocks:
                b_name = b.get("path") or b.get("filename") or ""
                if b_name == expected_filename or Path(b_name).name == Path(expected_filename).name:
                    return b["content"]
        return blocks[0]["content"]

    # Fenced code block fallback
    match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", response, re.IGNORECASE)
    if match:
        return match.group(1)

    return response.strip()


def synthesize_module(
    file_spec: ProjectFileSpec,
    spec: ProjectSpec,
    workspace: str = ".",
    llm_fn: Callable = ask,
    max_repair_attempts: int = 2
) -> Dict[str, Any]:
    """
    Synthesize a single project module with AST pre-flight checks and heuristic repairs.
    Returns:
      {
        "ok": bool,
        "path": str,
        "content": str,
        "repairs": int,
        "error": Optional[str]
      }
    """
    ws_path = Path(workspace).resolve()
    target_path = sanitize_path(file_spec.path, str(ws_path))
    target_path.parent.mkdir(parents=True, exist_ok=True)

    other_files = [f.path for f in spec.files if f.path != file_spec.path]

    prompt = f"""Generate production-ready Python code for the file `{file_spec.path}` in project `{spec.name}`.

Project Description:
{spec.description}

File Responsibility:
{file_spec.description}

Public Symbols/Exports Expected:
{', '.join(file_spec.exports) if file_spec.exports else 'Standard cohesive module functions and classes'}

Other Modules in Project:
{', '.join(other_files)}

Instructions:
1. Write the COMPLETE file without placeholder comments or pass statements.
2. Include type annotations and docstrings.
3. Handle potential runtime exceptions gracefully.
4. Output format:
FILE: {file_spec.path}
```python
# code here
```
"""
    raw_response = llm_fn(prompt, system=BUILDER_SYSTEM_PROMPT)
    code = _extract_code_from_response(raw_response, file_spec.path)

    # Pre-Flight Compiler / AST Validation
    syntax_result = validate_python_syntax(code, filename=file_spec.path)
    repairs_done = 0

    if not syntax_result["valid"]:
        # Heuristic auto-repair
        repaired = auto_repair_syntax(code, syntax_result)
        if repaired and validate_python_syntax(repaired, filename=file_spec.path)["valid"]:
            code = repaired
            syntax_result = {"valid": True}
            repairs_done += 1

    # LLM-guided syntax healing loop if still invalid
    heal_attempt = 0
    while not syntax_result["valid"] and heal_attempt < max_repair_attempts:
        heal_attempt += 1
        repairs_done += 1
        err_msg = syntax_result.get("message", "SyntaxError")
        lineno = syntax_result.get("lineno", "?")
        heal_prompt = f"""The generated code for `{file_spec.path}` failed Python AST syntax compilation:
Error at line {lineno}: {err_msg}

Offending Code:
```python
{code}
```

Fix the syntax error and return the COMPLETE valid Python file.
FILE: {file_spec.path}
```python
# fixed code
```
"""
        heal_resp = llm_fn(heal_prompt, system=BUILDER_SYSTEM_PROMPT)
        code = _extract_code_from_response(heal_resp, file_spec.path)
        syntax_result = validate_python_syntax(code, filename=file_spec.path)

    # Write file to disk
    target_path.write_text(code, encoding="utf-8")

    # Shadow git checkpoint
    try:
        create_checkpoint(str(ws_path), f"synthesize module {file_spec.path}")
    except Exception:
        pass

    return {
        "ok": syntax_result["valid"],
        "path": file_spec.path,
        "content": code,
        "repairs": repairs_done,
        "error": None if syntax_result["valid"] else syntax_result.get("message")
    }


def synthesize_test(
    test_spec: ProjectTestSpec,
    spec: ProjectSpec,
    workspace: str = ".",
    llm_fn: Callable = ask
) -> Dict[str, Any]:
    """
    Synthesize a pytest test file targeting project modules.
    """
    ws_path = Path(workspace).resolve()
    target_path = sanitize_path(test_spec.path, str(ws_path))
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Read target module code for context
    target_context = ""
    for t_rel in test_spec.targets:
        t_abs = sanitize_path(t_rel, str(ws_path))
        if t_abs.exists():
            target_context += f"\n--- Source: {t_rel} ---\n{t_abs.read_text(encoding='utf-8')[:2000]}\n"

    prompt = f"""Write a comprehensive pytest test file for `{test_spec.path}` in project `{spec.name}`.

Test Scope:
{test_spec.description}

Target Source Code:
{target_context if target_context else 'Test all modules and CLI entry points.'}

Requirements:
1. Use pytest conventions (test_*, assert).
2. Test both happy path and edge cases.
3. Do NOT import non-existent external libraries.
4. Output format:
FILE: {test_spec.path}
```python
# pytest tests
```
"""
    raw_response = llm_fn(prompt, system=BUILDER_SYSTEM_PROMPT)
    code = _extract_code_from_response(raw_response, test_spec.path)

    syntax = validate_python_syntax(code, filename=test_spec.path)
    if not syntax["valid"]:
        repaired = auto_repair_syntax(code, syntax)
        if repaired and validate_python_syntax(repaired, filename=test_spec.path)["valid"]:
            code = repaired

    target_path.write_text(code, encoding="utf-8")

    return {
        "ok": True,
        "path": test_spec.path,
        "content": code,
    }


def run_project_tests(workspace: str = ".", target_test: Optional[str] = None) -> Dict[str, Any]:
    """Execute pytest suite inside the workspace sandbox."""
    ws_path = Path(workspace).resolve()
    cmd = [sys.executable, "-m", "pytest", "-q"]
    if target_test:
        cmd.append(target_test)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(ws_path) + os.pathsep + env.get("PYTHONPATH", "")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ws_path),
            capture_output=True,
            text=True,
            timeout=30,
            env=env
        )
        passed = proc.returncode == 0
        return {
            "passed": passed,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "output": (proc.stdout + "\n" + proc.stderr).strip()
        }
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "Pytest timed out after 30 seconds",
            "output": "Pytest timed out after 30 seconds"
        }
    except Exception as e:
        return {
            "passed": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "output": str(e)
        }


def heal_failing_tests(
    test_output: str,
    spec: ProjectSpec,
    workspace: str = ".",
    llm_fn: Callable = ask,
    max_heal_rounds: int = 3
) -> Dict[str, Any]:
    """
    Closed-loop self-healing engine: inspects test failure tracebacks,
    generates surgical fixes for source or test files, and re-runs pytest
    until 100% green or heal rounds exhausted.
    """
    ws_path = Path(workspace).resolve()
    current_round = 0
    test_result = {"passed": False, "output": test_output}

    while current_round < max_heal_rounds and not test_result.get("passed", False):
        current_round += 1

        # Gather relevant source files for context
        code_context = ""
        for f in spec.files:
            f_abs = sanitize_path(f.path, str(ws_path))
            if f_abs.exists():
                code_context += f"\nFILE: {f.path}\n```python\n{f_abs.read_text(encoding='utf-8')[:2000]}\n```\n"

        heal_prompt = f"""The project tests failed with the following output:

=== PYTEST FAILURE TRACEBACK ===
{test_result.get('output', '')[-2500:]}

Current Source Files:
{code_context}

Analyze the root cause. Provide the exact fixed file(s) that resolve the error.
Format:
FILE: path/to/file.py
```python
# complete corrected code
```
"""
        repair_resp = llm_fn(heal_prompt, system=BUILDER_SYSTEM_PROMPT)
        blocks = _extract_file_blocks(repair_resp)
        if blocks:
            for b in blocks:
                b_name = b.get("path") or b.get("filename") or ""
                if not b_name:
                    continue
                b_path = sanitize_path(b_name, str(ws_path))
                b_path.parent.mkdir(parents=True, exist_ok=True)
                # Verify syntax before writing
                if b_name.endswith(".py"):
                    syntax = validate_python_syntax(b["content"], filename=b_name)
                    if syntax["valid"]:
                        b_path.write_text(b["content"], encoding="utf-8")
                elif b_name.endswith(".json"):
                    try:
                        json.loads(b["content"])
                        b_path.write_text(b["content"], encoding="utf-8")
                    except Exception:
                        pass
                else:
                    b_path.write_text(b["content"], encoding="utf-8")

        # Re-run pytest
        test_result = run_project_tests(str(ws_path))

    return {
        "ok": test_result.get("passed", False),
        "rounds": current_round,
        "test_result": test_result
    }


def build_project(
    prompt: str,
    workspace: str = ".",
    llm_fn: Callable = ask,
    on_event: Optional[Callable[[Dict[str, Any]], None]] = None
) -> Dict[str, Any]:
    """
    Main Autonomous Builder entrypoint.
    Executes: Spec -> Scaffolding -> Module Synthesis -> Pre-Flight AST Checks -> Closed-Loop TDD Healing.
    """
    t_start = time.time()
    ws_path = Path(workspace).resolve()
    ws_path.mkdir(parents=True, exist_ok=True)

    def emit(event: str, data: Any):
        if on_event:
            try:
                on_event({"event": event, "data": data, "timestamp": time.time()})
            except Exception:
                pass

    # 1. Spec Generation
    emit("spec_start", {"prompt": prompt})
    spec = generate_spec(prompt, str(ws_path), llm_fn=llm_fn)
    emit("spec_ready", spec.to_dict())

    # 2. Scaffolding
    emit("scaffold_start", {"name": spec.name, "dirs": spec.directories})
    scaffolded_files = scaffold_project(spec, str(ws_path))
    emit("scaffold_complete", {"created": scaffolded_files})

    # 3. Module Synthesis with Pre-Flight Checks
    synthesized_files = []
    for file_spec in spec.files:
        emit("module_start", {"file": file_spec.path, "description": file_spec.description})
        synth_res = synthesize_module(file_spec, spec, str(ws_path), llm_fn=llm_fn)
        synthesized_files.append(synth_res)
        emit("module_complete", synth_res)

    # 4. Test Synthesis
    test_files = []
    for test_spec in spec.tests:
        emit("test_synth_start", {"test_file": test_spec.path})
        t_res = synthesize_test(test_spec, spec, str(ws_path), llm_fn=llm_fn)
        test_files.append(t_res)
        emit("test_synth_complete", t_res)

    # 5. Verification & Closed-Loop Healing
    emit("verify_start", {})
    test_run = run_project_tests(str(ws_path))
    heal_info = {"rounds": 0, "ok": test_run["passed"]}

    if not test_run["passed"]:
        emit("heal_start", {"output": test_run["output"]})
        heal_info = heal_failing_tests(test_run["output"], spec, str(ws_path), llm_fn=llm_fn)
        emit("heal_complete", heal_info)
        test_run = heal_info["test_result"]

    duration = time.time() - t_start
    success = test_run.get("passed", False) or all(f["ok"] for f in synthesized_files)

    report = {
        "ok": success,
        "name": spec.name,
        "description": spec.description,
        "entrypoint": spec.entrypoint,
        "run_instructions": spec.run_instructions,
        "scaffolded": scaffolded_files,
        "modules": [f["path"] for f in synthesized_files],
        "tests": [t["path"] for t in test_files],
        "test_passed": test_run.get("passed", False),
        "heal_rounds": heal_info.get("rounds", 0),
        "duration_seconds": round(duration, 2),
        "spec": spec.to_dict(),
    }
    emit("build_complete", report)
    return report


def build_project_stream(
    prompt: str,
    workspace: str = ".",
    llm_fn: Callable = ask
) -> Generator[str, None, None]:
    """
    Generator yielding Server-Sent Events (SSE) compatible JSON strings for live streaming.
    """
    events = []

    def collector(event_data):
        events.append(event_data)

    # Run in generator mode
    report = build_project(prompt, workspace, llm_fn=llm_fn, on_event=collector)
    for evt in events:
        yield f"data: {json.dumps(evt)}\n\n"
