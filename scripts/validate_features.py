import sys
sys.path.insert(0, ".")

print("Testing api_doc_scanner import...")
from tools.api_doc_scanner import generate_api_docs, scan_api_endpoints, _scan_file
print("  OK: generate_api_docs, scan_api_endpoints")

eps = _scan_file("server/api.py", ".")
print(f"  Scanned server/api.py — found {len(eps)} endpoints")
for ep in eps[:5]:
    print(f"    {ep}")

print()
print("Testing cmd_docs_api integration...")
from agent.commands.project import _cmd_docs_api
print("  OK: _cmd_docs_api importable")

print()
print("Testing VS Code extension package.json...")
import json
with open("vscode-extension/package.json") as f:
    pkg = json.load(f)
cmds = pkg["contributes"]["commands"]
print(f"  OK: package.json — {len(cmds)} commands defined")

ext_path = "vscode-extension/src/extension.js"
with open(ext_path) as f:
    src = f.read()
reg_count = src.count("registerCommand")
print(f"  extension.js: {len(src)} chars, {reg_count} commands registered")

print()
print("All checks PASSED")
