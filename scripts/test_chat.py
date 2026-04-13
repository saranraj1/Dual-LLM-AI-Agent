"""scripts/test_chat.py — verify chat content, diagram, and SSE token delivery."""
import requests
import json
import time
import sys

BASE = "http://localhost:8000"
ok = fail = 0

def chk(label, passed, detail=""):
    global ok, fail
    if passed:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label}  | {str(detail)[:120]}")

time.sleep(2)
print("=== SERVER ENDPOINT TESTS ===\n")

# ── Fast GETs ────────────────────────────────────────────────────────────────
for path, key in [("/health","status"), ("/stats","llm"), ("/memory","short_turns"), ("/backend","backend")]:
    with requests.Session() as s:
        r = s.get(f"{BASE}{path}", timeout=8)
        chk(f"GET {path}", r.status_code == 200 and key in r.json())

# ── Backend selector ─────────────────────────────────────────────────────────
for choice in ("groq", "local", "auto"):
    with requests.Session() as s:
        r = s.post(f"{BASE}/backend", json={"backend": choice}, timeout=8)
        b = r.json()
        if r.status_code == 503:
            chk(f"POST /backend {choice} (503=offline-ok)", True)
        else:
            chk(f"POST /backend {choice}", r.status_code == 200 and b.get("ok"), b)

with requests.Session() as s:
    r = s.post(f"{BASE}/backend", json={"backend": "INVALID"}, timeout=8)
    chk("POST /backend invalid → 400", r.status_code == 400)

# ── Commands ─────────────────────────────────────────────────────────────────
for cmd in ("/stats", "/memory", "/time", "/clear"):
    with requests.Session() as s:
        r = s.post(f"{BASE}/command", json={"command": cmd}, timeout=30)
        b = r.json()
        chk(f"POST /command {cmd}", r.status_code == 200 and b.get("ok"), b)

# ── /chat SSE — verify actual content arrives ────────────────────────────────
print("\n--- Chat content test ---")
with requests.Session() as s:
    r = s.post(
        f"{BASE}/chat",
        json={"message": "Reply with exactly one word: HELLO"},
        timeout=40,
        stream=True,
    )
    chk("POST /chat 200", r.status_code == 200)
    chk("POST /chat SSE content-type", "event-stream" in r.headers.get("content-type", ""))
    tokens = []
    for raw in r.iter_lines():
        if raw and raw.startswith(b"data: "):
            try:
                t = json.loads(raw[6:])
                if t:
                    tokens.append(t)
            except Exception:
                pass
    full = "".join(tokens)
    chk(f"POST /chat tokens received (got {len(tokens)})", len(tokens) > 0)
    chk(f"POST /chat content non-empty ({repr(full[:50])})", len(full.strip()) > 0)
    r.close()

# ── /chat SSE — concurrency: /health must respond while chat streams ──────────
import threading
health_ok = []
def poll_health():
    for _ in range(3):
        try:
            resp = requests.get(f"{BASE}/health", timeout=5)
            health_ok.append(resp.status_code == 200)
        except Exception:
            health_ok.append(False)
        time.sleep(0.5)

t = threading.Thread(target=poll_health)
t.start()
with requests.Session() as s:
    r = s.post(f"{BASE}/chat", json={"message": "hello"}, timeout=30, stream=True)
    for _ in r.iter_lines():
        pass
    r.close()
t.join()
chk(f"Concurrency: /health responsive during /chat ({sum(health_ok)}/{len(health_ok)} ok)", all(health_ok))

# ── /command /diagram — large output ─────────────────────────────────────────
print("\n--- Diagram command test ---")
with requests.Session() as s:
    r = s.post(f"{BASE}/command", json={"command": "/diagram"}, timeout=90)
    b = r.json()
    result = b.get("result", "")
    chk("POST /command /diagram 200", r.status_code == 200 and b.get("ok"), b.get("detail", ""))
    chk(f"POST /command /diagram content len={len(str(result))}", len(str(result)) > 100)
    has_code = "```" in str(result) or "#" in str(result) or "─" in str(result)
    chk("POST /command /diagram has diagram content", has_code, repr(str(result)[:100]))

print(f"\n=== {ok} PASSED / {fail} FAILED ===")
sys.exit(0 if fail == 0 else 1)
