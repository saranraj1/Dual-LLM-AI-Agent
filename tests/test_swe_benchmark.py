"""
tests/test_swe_benchmark.py — Unit tests for Automated SWE Benchmark Suite.
"""

import sys
import os
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from eval.swe_benchmark import (
    SWEChallenge,
    BENCHMARK_CHALLENGES,
    run_swe_benchmark,
    run_comparative_benchmark,
    format_benchmark_report,
)


class TestSWEBenchmark:

    def test_benchmark_challenges_structure(self):
        assert len(BENCHMARK_CHALLENGES) >= 3
        for ch in BENCHMARK_CHALLENGES:
            assert ch.id
            assert ch.title
            assert ch.prompt
            assert "test_" in ch.test_code

    def test_format_benchmark_report(self):
        sample_report = {
            "backend": "groq",
            "total": 2,
            "passed": 2,
            "failed": 0,
            "pass_rate_percent": 100.0,
            "total_duration": 4.5,
            "avg_latency_seconds": 2.25,
            "challenges": [
                {
                    "title": "O(1) LRU Cache",
                    "category": "algorithm",
                    "latency": 2.1,
                    "passed": True,
                    "error": None
                },
                {
                    "title": "Nested Key Path Extractor",
                    "category": "data",
                    "latency": 2.4,
                    "passed": True,
                    "error": None
                }
            ]
        }
        text = format_benchmark_report(sample_report)
        assert "SWE Benchmark & Evaluation Report" in text
        assert "GROQ" in text
        assert "100.0%" in text
        assert "PASS" in text

    def test_run_swe_benchmark_mock_success(self):
        test_challenge = SWEChallenge(
            id="test_calc",
            title="Calculator Function",
            category="algorithm",
            prompt="Write add(a, b)",
            test_code="from solution import add\ndef test_add(): assert add(2, 3) == 5\n"
        )

        mock_solution = """FILE: solution.py
```python
def add(a: int, b: int) -> int:
    return a + b
```"""
        report = run_swe_benchmark(
            challenges=[test_challenge],
            llm_fn=lambda p, **kw: mock_solution
        )
        assert report["total"] == 1
        assert report["passed"] == 1
        assert report["pass_rate_percent"] == 100.0
        assert report["challenges"][0]["passed"] is True

    def test_run_comparative_benchmark_mock(self, monkeypatch):
        mock_rep_local = {
            "backend": "local",
            "total": 1,
            "passed": 1,
            "pass_rate_percent": 100.0,
            "avg_latency_seconds": 4.0,
            "total_duration": 4.0,
            "challenges": []
        }
        mock_rep_groq = {
            "backend": "groq",
            "total": 1,
            "passed": 1,
            "pass_rate_percent": 100.0,
            "avg_latency_seconds": 1.0,
            "total_duration": 1.0,
            "challenges": []
        }

        monkeypatch.setattr("core.llm.is_running", lambda: True)
        monkeypatch.setattr("core.llm.is_groq_available", lambda: True)
        monkeypatch.setattr("eval.swe_benchmark.run_swe_benchmark", lambda backend=None, **kw: mock_rep_groq if backend == "groq" else mock_rep_local)

        comp = run_comparative_benchmark()
        assert comp["local"] is not None
        assert comp["groq"] is not None
        assert comp["speedup_factor"] == 4.0
