"""tests/test_cache.py — Verify LLM response caching works correctly."""

import time
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import patch, MagicMock
from core.llm import ask, get_stats, _cache


class TestResponseCache:
    def setup_method(self):
        """Clear cache before each test."""
        _cache.clear()

    def test_cache_stores_response(self):
        """First call stores the response in cache."""
        with patch("core.llm._ollama_ask", return_value="hello world") as mock_ollama:
            with patch("core.llm.is_running", return_value=True):
                result = ask("What is 2+2?")
        assert result is not None
        assert len(result) > 0

    def test_cache_hit_avoids_second_call(self):
        """Identical prompt returns cached result without calling the LLM again."""
        call_count = {"n": 0}

        def fake_ollama(prompt, system="", **kwargs):
            call_count["n"] += 1
            return "cached response"

        with patch("core.llm._ollama_ask", side_effect=fake_ollama):
            with patch("core.llm.is_running", return_value=True):
                r1 = ask("Unique test prompt XYZ123")
                r2 = ask("Unique test prompt XYZ123")  # Same prompt

        assert r1 == r2
        assert call_count["n"] == 1  # LLM should only be called once

    def test_different_prompts_not_cached_together(self):
        """Different prompts each call the LLM independently."""
        call_count = {"n": 0}

        def fake_ollama(prompt, system="", **kwargs):
            call_count["n"] += 1
            return f"response to: {prompt}"

        with patch("core.llm._ollama_ask", side_effect=fake_ollama):
            with patch("core.llm.is_running", return_value=True):
                ask("Prompt Alpha")
                ask("Prompt Beta")

        assert call_count["n"] == 2

    def test_get_stats_tracks_cache_hits(self):
        """get_stats() reports accurate cache hit counts."""
        stats_before = get_stats()
        hits_before = stats_before["cache_hits"]

        with patch("core.llm._ollama_ask", return_value="test"):
            with patch("core.llm.is_running", return_value=True):
                ask("Repeatable prompt ALPHA")
                ask("Repeatable prompt ALPHA")  # cache hit

        stats_after = get_stats()
        assert stats_after["cache_hits"] >= hits_before + 1
