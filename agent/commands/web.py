"""agent/commands/web.py — /ask /search"""

import re
import json
import urllib.request
import urllib.parse
from core.llm import ask, ask_stream
from core.prompt_builder import SYSTEM_PROMPT


# ── /ask <url> ────────────────────────────────────────────────────────────────

def cmd_ask_url(agent, args: str) -> str:
    parts = args.strip().split(" ", 1)
    url = parts[0]
    question = parts[1] if len(parts) > 1 else "Summarize this page and extract the key information."

    if not url.startswith("http"):
        return "Usage: /ask <url> [optional question]"

    print(f"\n🌐 Fetching: {url}")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        return f"❌ Could not fetch URL: {e}"

    clean = re.sub(r'<[^>]+>', ' ', raw)
    clean = re.sub(r'\s+', ' ', clean).strip()[:3000]

    prompt = f"""{question}

Page content from {url}:
{clean}"""

    print("Agent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    return full


# ── /search <query> ───────────────────────────────────────────────────────────

def cmd_search(agent, args: str) -> str:
    query = args.strip()
    if not query:
        return "Usage: /search <your question>"

    print(f"\n🔎 Searching: {query}")
    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            abstract = data.get("Abstract", "")
            answer = data.get("Answer", "")
            related = [r["Text"] for r in data.get("RelatedTopics", [])[:5] if "Text" in r]
    except Exception as e:
        return f"❌ Search failed: {e}"

    context = f"Query: {query}\n"
    if answer:
        context += f"Answer: {answer}\n"
    if abstract:
        context += f"Summary: {abstract}\n"
    if related:
        context += "Related:\n" + "\n".join(f"- {r}" for r in related)
    if not (answer or abstract or related):
        context += "(No direct results found)\n"

    prompt = f"""Based on this web search result, help the user with their question in the context of their codebase.

{context}

Workspace context:
{agent.code_context[:800]}"""

    print(f"\nAgent › ", end="", flush=True)
    full = ""
    for token in ask_stream(prompt, system=SYSTEM_PROMPT):
        print(token, end="", flush=True)
        full += token
    print()
    return full
