"""eval/__init__.py — SWE benchmark and evaluation harnesses."""
from eval.swe_benchmark import (
    SWEChallenge,
    BENCHMARK_CHALLENGES,
    run_swe_benchmark,
    run_comparative_benchmark,
    format_benchmark_report,
)

__all__ = [
    "SWEChallenge",
    "BENCHMARK_CHALLENGES",
    "run_swe_benchmark",
    "run_comparative_benchmark",
    "format_benchmark_report",
]
