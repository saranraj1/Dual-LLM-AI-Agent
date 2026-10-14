"""
tests/test_preflight_tools.py — Unit tests for pre-flight compiler & static syntax checks.
"""

import tempfile
import shutil
from pathlib import Path
from tools.preflight_tools import (
    validate_python_syntax,
    auto_repair_syntax,
    preflight_check_file
)


class TestPreflightTools:

    def test_validate_python_syntax_valid(self):
        code = "def add(a: int, b: int) -> int:\n    return a + b\n"
        res = validate_python_syntax(code)
        assert res["valid"] is True
        assert res["error_type"] is None

    def test_validate_python_syntax_invalid(self):
        code = "def broken(\n    return 42\n"
        res = validate_python_syntax(code)
        assert res["valid"] is False
        assert res["error_type"] == "SyntaxError"
        assert res["lineno"] is not None

    def test_auto_repair_syntax_missing_colon(self):
        code = "def compute(x, y)\n    return x * y\n"
        syntax = validate_python_syntax(code)
        assert syntax["valid"] is False

        repaired = auto_repair_syntax(code, syntax)
        assert repaired is not None
        assert "def compute(x, y):" in repaired
        assert validate_python_syntax(repaired)["valid"] is True

    def test_preflight_check_file_python(self):
        tmp = tempfile.mkdtemp(prefix="test_pf_")
        try:
            f = Path(tmp) / "valid.py"
            f.write_text("class Model:\n    pass\n", encoding="utf-8")
            res = preflight_check_file(str(f))
            assert res["valid"] is True

            f_broken = Path(tmp) / "invalid.py"
            f_broken.write_text("class Model\n    pass\n", encoding="utf-8")
            res_broken = preflight_check_file(str(f_broken))
            assert res_broken["valid"] is False
            assert res_broken["auto_repaired_content"] is not None
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_preflight_check_file_json(self):
        tmp = tempfile.mkdtemp(prefix="test_pf_json_")
        try:
            f = Path(tmp) / "data.json"
            f.write_text('{"name": "test", "valid": true}', encoding="utf-8")
            res = preflight_check_file(str(f))
            assert res["valid"] is True

            f_bad = Path(tmp) / "bad.json"
            f_bad.write_text('{"name": "test", unquoted}', encoding="utf-8")
            res_bad = preflight_check_file(str(f_bad))
            assert res_bad["valid"] is False
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
