"""
tests/test_terminal_tui.py — Unit tests for Rich Terminal TUI & Live Steerability.
"""

import sys
import os
import pytest
from io import StringIO
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rich.console import Console
from cli.terminal_tui import (
    SteerController,
    render_diff,
    render_banner,
    stream_markdown,
)


class TestTerminalTUI:

    def test_steer_controller_lifecycle(self):
        test_console = Console(file=StringIO(), force_terminal=True)
        with SteerController(test_console) as steer:
            assert steer.was_interrupted is False
            assert steer.steering_feedback is None

    def test_steer_controller_sigint_steering(self):
        test_console = Console(file=StringIO(), force_terminal=True)
        controller = SteerController(test_console)
        with patch("cli.terminal_tui.Prompt.ask", side_effect=["s", "Use SQLite instead of JSON"]):
            # Trigger handler directly
            controller._handle_sigint(2, None)
            assert controller.steering_feedback == "Use SQLite instead of JSON"
            assert controller.was_interrupted is False

    def test_steer_controller_sigint_abort(self):
        test_console = Console(file=StringIO(), force_terminal=True)
        controller = SteerController(test_console)
        with patch("cli.terminal_tui.Prompt.ask", return_value="a"):
            with pytest.raises(KeyboardInterrupt, match="Task aborted by user"):
                controller._handle_sigint(2, None)

    def test_render_diff(self):
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True)
        sample_diff = """--- a/calculator.py
+++ b/calculator.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
        render_diff(sample_diff, console_instance=test_console)
        output = buf.getvalue()
        assert "calculator.py" in output

    def test_render_empty_diff(self):
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True)
        render_diff("", console_instance=test_console)
        output = buf.getvalue()
        assert "No diff changes" in output

    def test_stream_markdown(self):
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True)

        def token_gen():
            yield "Hello "
            yield "**World**"

        accum = stream_markdown(token_gen(), console_instance=test_console)
        assert accum == "Hello **World**"

    def test_render_banner(self):
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True)
        render_banner(console_instance=test_console)
        output = buf.getvalue()
        assert "Autonomous AI Agent" in output
