"""
tests/test_project_builder.py — Unit tests for Autonomous Prompt-to-Project Builder.
"""

import os
import sys
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent.project_builder import (
    ProjectSpec,
    ProjectFileSpec,
    ProjectTestSpec,
    generate_spec,
    scaffold_project,
    synthesize_module,
    synthesize_test,
    build_project,
    build_project_stream,
    _clean_json_text,
)


class TestProjectBuilder:

    def test_clean_json_text(self):
        fenced = "```json\n{\"name\": \"test_app\"}\n```"
        assert _clean_json_text(fenced) == "{\"name\": \"test_app\"}"

        with_preamble = "Here is the spec:\n{\"name\": \"my_proj\"}\nHope this helps!"
        assert _clean_json_text(with_preamble) == "{\"name\": \"my_proj\"}"

    def test_generate_spec_valid_json(self):
        sample_json = """```json
{
  "name": "fast_cache",
  "description": "High performance LRU cache",
  "directories": ["src", "tests"],
  "dependencies": ["pytest"],
  "files": [
    {"path": "src/cache.py", "description": "LRU cache implementation", "exports": ["LRUCache"]}
  ],
  "tests": [
    {"path": "tests/test_cache.py", "description": "Cache tests", "targets": ["src/cache.py"]}
  ],
  "entrypoint": "src/cache.py",
  "run_instructions": "python src/cache.py"
}
```"""
        spec = generate_spec("Build an LRU cache", llm_fn=lambda p, system=None: sample_json)
        assert spec.name == "fast_cache"
        assert len(spec.files) == 1
        assert spec.files[0].path == "src/cache.py"
        assert len(spec.tests) == 1
        assert "pytest" in spec.dependencies

    def test_generate_spec_fallback_on_malformed_json(self):
        malformed = "I cannot generate valid JSON sorry!"
        spec = generate_spec("Create custom tool", llm_fn=lambda p, system=None: malformed)
        assert spec is not None
        assert spec.name is not None
        assert len(spec.files) >= 1
        assert len(spec.tests) >= 1

    def test_scaffold_project(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = ProjectSpec(
                name="demo_proj",
                description="Demo app",
                directories=["src", "tests"],
                dependencies=["requests", "pytest"],
                files=[ProjectFileSpec(path="src/app.py", description="app logic")],
                tests=[ProjectTestSpec(path="tests/test_app.py", description="tests")],
                entrypoint="src/app.py",
                run_instructions="python src/app.py"
            )

            created = scaffold_project(spec, workspace=tmpdir)
            assert (Path(tmpdir) / "src").is_dir()
            assert (Path(tmpdir) / "tests").is_dir()
            assert (Path(tmpdir) / "requirements.txt").is_file()
            assert (Path(tmpdir) / "README.md").is_file()
            assert (Path(tmpdir) / ".gitignore").is_file()

            req_content = (Path(tmpdir) / "requirements.txt").read_text(encoding="utf-8")
            assert "requests" in req_content
            assert "pytest" in req_content

    def test_synthesize_module_valid_syntax(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = ProjectSpec(
                name="math_service",
                description="Math utils",
                files=[ProjectFileSpec(path="calculator.py", description="calc logic", exports=["add"])],
            )
            file_spec = spec.files[0]

            llm_response = """FILE: calculator.py
```python
def add(a: int, b: int) -> int:
    \"\"\"Add two numbers.\"\"\"
    return a + b
```"""
            res = synthesize_module(file_spec, spec, workspace=tmpdir, llm_fn=lambda p, system=None: llm_response)
            assert res["ok"] is True
            assert res["path"] == "calculator.py"
            written_file = Path(tmpdir) / "calculator.py"
            assert written_file.is_file()
            assert "def add(a: int, b: int) -> int:" in written_file.read_text(encoding="utf-8")

    def test_synthesize_module_auto_repairs_missing_colon(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec = ProjectSpec(
                name="syntax_test",
                description="Test syntax repair",
                files=[ProjectFileSpec(path="sub.py", description="subtractor", exports=["sub"])],
            )
            file_spec = spec.files[0]

            # Missing colon in def
            buggy_code = """FILE: sub.py
```python
def sub(a, b)
    return a - b
```"""
            res = synthesize_module(file_spec, spec, workspace=tmpdir, llm_fn=lambda p, system=None: buggy_code)
            assert res["ok"] is True
            assert res["repairs"] >= 1
            written = (Path(tmpdir) / "sub.py").read_text(encoding="utf-8")
            assert "def sub(a, b):" in written

    def test_full_build_project_flow(self, monkeypatch):
        with tempfile.TemporaryDirectory() as tmpdir:
            responses = {
                "spec": """```json
{
  "name": "greeter_app",
  "description": "Friendly greeter CLI",
  "directories": ["tests"],
  "dependencies": ["pytest"],
  "files": [
    {"path": "greeter.py", "description": "Greeting generator", "exports": ["greet"]}
  ],
  "tests": [
    {"path": "tests/test_greeter.py", "description": "Greeter tests", "targets": ["greeter.py"]}
  ],
  "entrypoint": "greeter.py",
  "run_instructions": "python greeter.py"
}
```""",
                "module": """FILE: greeter.py
```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```""",
                "test": """FILE: tests/test_greeter.py
```python
from greeter import greet

def test_greet():
    assert greet("Alice") == "Hello, Alice!"
```"""
            }

            def mock_llm(prompt, system=None):
                if "generate an end-to-end project specification" in prompt:
                    return responses["spec"]
                elif "greeter.py" in prompt and "test" not in prompt:
                    return responses["module"]
                else:
                    return responses["test"]

            # Mock pytest execution to succeed
            monkeypatch.setattr(
                "agent.project_builder.run_project_tests",
                lambda ws, target=None: {"passed": True, "output": "1 passed in 0.05s", "returncode": 0}
            )

            events_logged = []
            report = build_project(
                "Build a greeter CLI",
                workspace=tmpdir,
                llm_fn=mock_llm,
                on_event=lambda e: events_logged.append(e["event"])
            )

            assert report["ok"] is True
            assert report["name"] == "greeter_app"
            assert "greeter.py" in report["modules"]
            assert "tests/test_greeter.py" in report["tests"]
            assert report["test_passed"] is True
            assert "spec_ready" in events_logged
            assert "build_complete" in events_logged

            # Test streaming generator
            stream_events = list(build_project_stream("Build a greeter CLI", workspace=tmpdir, llm_fn=mock_llm))
            assert len(stream_events) > 0
            assert "data: " in stream_events[0]
