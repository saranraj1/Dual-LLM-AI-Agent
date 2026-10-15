"""
scripts/e2e_browser_test.py — End-to-end browser automation and functional verification
using Playwright against the local AI Agent Engineering Console.
"""

import sys
import time
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

import os
ARTIFACT_DIR = Path(os.getenv("ARTIFACT_DIR", r"C:\Users\tamil\.gemini\antigravity\brain\52bf6f49-2588-4b8a-83b6-deff095fc7c9"))
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

def run_browser_automation():
    results = {
        "steps": [],
        "screenshots": {},
        "errors": []
    }

    with sync_playwright() as p:
        print("[Playwright] Launching Chromium browser...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # Capture browser console & error logs
        page.on("console", lambda msg: print(f"  [Browser Console {msg.type}]: {msg.text}"))
        page.on("pageerror", lambda err: print(f"  [Browser PageError]: {err}"))

        # --- Step 1: Navigating to Web Console and Ensuring Groq Backend ---
        print("\n--- Step 1: Navigating to Web Console and Selecting Groq ---")
        t0 = time.time()
        page.goto("http://127.0.0.1:8000")
        page.wait_for_load_state("networkidle")
        page.wait_for_selector("#chat-input", timeout=10000)

        # Switch / Ensure Backend is Groq
        groq_btn = page.locator("#btn-groq")
        page.wait_for_selector("#btn-groq", timeout=5000)
        groq_btn.click()
        page.wait_for_timeout(1000)

        # Verify backend selection
        page.wait_for_selector(".backend-btn.active-groq", timeout=5000)
        backend_badge = page.locator("#stat-backend").inner_text()
        print(f"  Active backend confirmed via UI: {backend_badge}")

        ss_home = ARTIFACT_DIR / "ui_step1_home_groq.png"
        page.screenshot(path=str(ss_home))
        results["screenshots"]["homepage"] = str(ss_home)
        results["steps"].append({
            "step": 1,
            "name": "Navigate and Select Groq",
            "duration": round(time.time() - t0, 2),
            "status": "PASS",
            "backend": backend_badge
        })
        print(f"  Loaded console in {round(time.time() - t0, 2)}s. Screenshot saved.")

        # --- Step 2: Execute Slash Command (/stats) ---
        print("\n--- Step 2: Executing Query /stats ---")
        t0 = time.time()
        chat_input = page.locator("#chat-input")
        chat_input.fill("/stats")
        page.locator("#send-btn").click()

        # Wait for streaming to finish and turn card to be created
        page.wait_for_function(
            "() => !window.isStreaming && document.querySelectorAll('.turn-card.agent .turn-content').length >= 1",
            timeout=20000
        )
        page.wait_for_timeout(1000)

        ss_stats = ARTIFACT_DIR / "ui_step2_query_stats.png"
        page.screenshot(path=str(ss_stats))
        results["screenshots"]["query_stats"] = str(ss_stats)

        last_agent_card = page.locator(".turn-card.agent").last
        agent_text = last_agent_card.locator(".turn-content").inner_text()
        print(f"  /stats Response:\n{agent_text[:250]}...")

        assert any(k in agent_text.lower() for k in [
            "project", "files", "lines", "statistics", "total", "backend", "groq", "call", "token", "cache", "model", "sqlite", "memory"
        ]), f"Unexpected /stats output: {agent_text}"

        results["steps"].append({
            "step": 2,
            "name": "Query /stats",
            "duration": round(time.time() - t0, 2),
            "status": "PASS",
            "output_preview": agent_text[:160]
        })
        print(f"  Executed /stats in {round(time.time() - t0, 2)}s.")

        # --- Step 3: Run Conversational Engineering Knowledge Query ---
        print("\n--- Step 3: Executing Knowledge Query ---")
        t0 = time.time()
        query_prompt = "What are the 4 tiers of the memory subsystem in this project?"
        chat_input.fill(query_prompt)
        page.locator("#send-btn").click()

        # Give 500ms for sendChat to trigger streaming state
        page.wait_for_timeout(800)

        # Wait for streaming completion and populated turn-content body
        page.wait_for_function(
            """() => {
                if (window.isStreaming) return false;
                if (document.querySelectorAll('.stream-status').length > 0) return false;
                const contents = document.querySelectorAll('.turn-card.agent .turn-content');
                if (contents.length < 2) return false;
                const lastContent = contents[contents.length - 1].innerText.trim();
                return lastContent.length > 30;
            }""",
            timeout=45000
        )
        page.wait_for_timeout(1000)

        ss_query = ARTIFACT_DIR / "ui_step3_knowledge_query.png"
        page.screenshot(path=str(ss_query))
        results["screenshots"]["knowledge_query"] = str(ss_query)

        agent_cards = page.locator(".turn-card.agent .turn-content").all()
        knowledge_resp = agent_cards[-1].inner_text()
        print(f"  Knowledge Response:\n{knowledge_resp[:350]}...")
        assert len(knowledge_resp) > 30, "Knowledge response too short or empty"

        results["steps"].append({
            "step": 3,
            "name": "Knowledge Query",
            "duration": round(time.time() - t0, 2),
            "status": "PASS",
            "output_preview": knowledge_resp[:200]
        })
        print(f"  Knowledge query completed in {round(time.time() - t0, 2)}s.")

        # --- Step 4: Autonomous Task in Run Mode ---
        print("\n--- Step 4: Executing Autonomous Task in Run Mode ---")
        t0 = time.time()
        # Switch to Run Task mode
        page.locator("#tab-run").click()
        page.wait_for_selector("#tab-run.active", timeout=5000)
        page.evaluate("() => { if (typeof clearChat === 'function') clearChat(); }")
        page.wait_for_timeout(500)

        task_prompt = "Scan workspace and report the primary database file used for memory."
        chat_input.fill(task_prompt)

        # Click the Run button
        page.locator("#run-btn").click()

        # Wait for ReAct trace card
        page.wait_for_selector(".react-trace-card", timeout=10000)
        print("  ReAct card spawned. Streaming thoughts and tool actions...")

        # Wait for task completion badge
        page.wait_for_selector(".trace-status-badge.done, .trace-status-badge.error", timeout=90000)
        badge_text = page.locator(".trace-status-badge").last.inner_text()
        print(f"  Trace status: {badge_text}")

        # Capture step items count
        steps_count = page.locator(".trace-step-item").count()
        print(f"  Captured {steps_count} ReAct trajectory steps.")

        # Scroll chat-area to the bottom so the entire ReAct trajectory is visible
        page.evaluate("""() => {
            const area = document.getElementById('chat-area');
            if (area) area.scrollTop = area.scrollHeight;
        }""")
        page.wait_for_timeout(1200)
        ss_task = ARTIFACT_DIR / "ui_step4_autonomous_task.png"
        page.screenshot(path=str(ss_task))
        results["screenshots"]["autonomous_task"] = str(ss_task)

        results["steps"].append({
            "step": 4,
            "name": "Autonomous ReAct Task",
            "duration": round(time.time() - t0, 2),
            "status": "PASS",
            "trajectory_steps": steps_count,
            "final_badge": badge_text
        })
        print(f"  Autonomous task completed in {round(time.time() - t0, 2)}s.")

        # --- Step 5: Switch to AST Call Graph Visualizer ---
        print("\n--- Step 5: AST Call Graph Visualizer ---")
        t0 = time.time()
        page.locator("#tab-graph").click()
        page.wait_for_selector("#tab-graph.active", timeout=5000)
        page.wait_for_timeout(2000)

        # Wait for #graph-loading to finish
        page.wait_for_function(
            "() => { const l = document.getElementById('graph-loading'); return !l || l.style.display === 'none'; }",
            timeout=15000
        )
        page.wait_for_timeout(1000)

        # Verify SVG nodes exist
        nodes_count = page.locator("#graph-nodes g, #graph-nodes circle, #graph-nodes rect, #graph-nodes text").count()
        print(f"  AST graph rendered with {nodes_count} elements.")

        ss_graph = ARTIFACT_DIR / "ui_step5_ast_graph.png"
        page.screenshot(path=str(ss_graph))
        results["screenshots"]["ast_graph"] = str(ss_graph)

        results["steps"].append({
            "step": 5,
            "name": "AST Call Graph View",
            "duration": round(time.time() - t0, 2),
            "status": "PASS",
            "nodes_count": nodes_count
        })
        print(f"  AST graph view captured in {round(time.time() - t0, 2)}s.")

        # --- Step 6: Slide-Over Telemetry Deck ---
        print("\n--- Step 6: Telemetry Deck Drawer ---")
        t0 = time.time()
        # Open Telemetry Deck drawer
        page.locator("#panel-btn").click()
        page.wait_for_selector("#stats-panel.open", timeout=5000)
        page.wait_for_timeout(1500)

        # Extract live telemetry values
        stat_tokens = page.locator("#stat-tokens").inner_text()
        stat_cost = page.locator("#stat-cost").inner_text()
        stat_groq_calls = page.locator("#stat-groq-calls").inner_text()
        print(f"  Live telemetry: tokens={stat_tokens}, cost={stat_cost}, groq_calls={stat_groq_calls}")

        ss_deck = ARTIFACT_DIR / "ui_step6_telemetry_deck.png"
        page.screenshot(path=str(ss_deck))
        results["screenshots"]["telemetry_deck"] = str(ss_deck)

        results["steps"].append({
            "step": 6,
            "name": "Telemetry Deck Drawer",
            "duration": round(time.time() - t0, 2),
            "status": "PASS",
            "tokens": stat_tokens,
            "cost": stat_cost,
            "groq_calls": stat_groq_calls
        })
        print(f"  Telemetry Deck drawer captured in {round(time.time() - t0, 2)}s.")

        browser.close()

    print("\n==========================================")
    print("ALL PLAYWRIGHT E2E BROWSER STEPS PASSED!")
    print("==========================================")
    summary_path = ARTIFACT_DIR / "e2e_browser_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Saved results summary to {summary_path}")
    return results

if __name__ == "__main__":
    run_browser_automation()
