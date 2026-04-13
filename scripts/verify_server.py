"""scripts/verify_server.py — full endpoint verification including /backend selector."""
import requests
import sys
import time

BASE = "http://localhost:8000"
ok = fail = 0

def chk(label, status, condition=True, detail=""):
    global ok, fail
    if condition:
        ok += 1
        print(f"  PASS  {label}")
    else:
        fail += 1
        print(f"  FAIL  {label} [{status}] {detail[:100]}")

time.sleep(1)

# ── GET endpoints ──────────────────────────────────────────────────────────────
r = requests.get(f"{BASE}/health", timeout=8)
b = r.json()
chk("GET /health", r.status_code, r.status_code == 200 and b.get("status") == "ok")
ollama_up = b.get("ollama", False)
groq_up   = b.get("groq",   False)

r = requests.get(f"{BASE}/backend", timeout=8)
b = r.json()
chk("GET /backend", r.status_code,
    r.status_code == 200 and b.get("backend") in ("auto","local","groq"),
    str(b))
chk("GET /backend has ollama_up/groq_up", r.status_code,
    "ollama_up" in b and "groq_up" in b and "available" in b)

r = requests.get(f"{BASE}/stats",  timeout=8)
chk("GET /stats",  r.status_code, r.status_code==200 and "llm" in r.json())

r = requests.get(f"{BASE}/memory", timeout=8)
chk("GET /memory", r.status_code, r.status_code==200 and "short_turns" in r.json())

r = requests.get(f"{BASE}/files",  timeout=8)
chk("GET /files",  r.status_code, r.status_code==200 and "entries" in r.json())

r = requests.get(f"{BASE}/logs",   timeout=8)
chk("GET /logs",   r.status_code, r.status_code==200 and "lines" in r.json())

# ── POST /backend ──────────────────────────────────────────────────────────────
for choice in ("auto", "groq", "local", "auto"):
    r = requests.post(f"{BASE}/backend", json={"backend": choice}, timeout=8)
    b = r.json()
    # Groq/local may be blocked if offline, still expect ok=True or a 503
    if r.status_code == 503:
        chk(f"POST /backend {choice} (offline→503)", r.status_code, True)
    else:
        chk(f"POST /backend {choice}", r.status_code,
            r.status_code == 200 and b.get("ok") is True, str(b))

r = requests.post(f"{BASE}/backend", json={"backend": "invalid_xyz"}, timeout=8)
chk("POST /backend invalid → 400", r.status_code, r.status_code == 400)

# ── POST /command ──────────────────────────────────────────────────────────────
for cmd in ("/stats", "/memory", "/time", "/clear"):
    r = requests.post(f"{BASE}/command", json={"command": cmd}, timeout=25)
    b = r.json()
    chk(f"POST /command {cmd}", r.status_code,
        r.status_code == 200 and b.get("ok") is True, str(b)[:100])

# ── POST /chat (SSE) ───────────────────────────────────────────────────────────
r = requests.post(
    f"{BASE}/chat",
    json={"message": "say hi in one word"},
    timeout=30,
    stream=True,
)
chk("POST /chat status 200",         r.status_code, r.status_code == 200)
chk("POST /chat content-type = SSE", r.status_code,
    "text/event-stream" in r.headers.get("content-type",""))
tokens = []
for line in r.iter_lines():
    if line and line.startswith(b"data: "):
        import json as _json
        try:
            t = _json.loads(line[6:])
            if t: tokens.append(t)
        except Exception:
            pass
chk("POST /chat SSE yields tokens",  200, len(tokens) > 0, f"got {len(tokens)} tokens")

# ── POST /run (SSE) ───────────────────────────────────────────────────────────
r = requests.post(
    f"{BASE}/run",
    json={"task": "print hello world"},
    timeout=30,
    stream=True,
)
chk("POST /run status 200", r.status_code, r.status_code == 200)
lines = list(r.iter_lines())
chk("POST /run SSE non-empty", 200, len(lines) > 0)

print()
print(f"=== {ok} passed / {fail} failed ===")
sys.exit(0 if fail == 0 else 1)
