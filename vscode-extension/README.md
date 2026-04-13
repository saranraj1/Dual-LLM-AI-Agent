# AI Agent — VS Code Extension

This extension connects VS Code to your running AI Agent server, bringing all 25+ agent commands directly into the editor.

## Prerequisites

Start the agent server first:

```bash
cd your-project
ai --serve          # starts on http://localhost:8000
# or
python main.py --serve --project /path/to/project
```

## Installation

### Option A — Install from VSIX (recommended)

```bash
cd vscode-extension
npm install
npm run package          # creates ai-agent-vscode-1.1.0.vsix
code --install-extension ai-agent-vscode-1.1.0.vsix
```

### Option B — Development mode

```bash
cd vscode-extension
npm install
# Press F5 in VS Code to launch Extension Development Host
```

## Commands & Shortcuts

| Command | Shortcut | Description |
|---------|----------|-------------|
| Review This File | `Ctrl+Shift+R` | Full code review with scores |
| Fix Errors | — | Auto-detect and fix syntax errors |
| Explain This File | — | Plain-English explanation |
| Refactor | — | Apply SOLID principles |
| Security Scan | — | CRITICAL/HIGH/MEDIUM/LOW findings |
| Generate Tests | — | Write pytest tests and run them |
| Explain Selection | `Ctrl+Shift+E` | Explain highlighted code |
| Fix Selection | — | Fix highlighted code **inline** |
| Open Chat UI | `Ctrl+Shift+A` | Open the web chat in browser |
| Run Task… | `Ctrl+Shift+T` | Type any task for autonomous execution |
| Generate API Docs | — | `/docs api` — scan routes, write docs/ |
| Smart Git Commit | — | AI-generated commit message + commit |

## Right-Click Menu

Right-click any Python/JS file in the editor or file explorer to see the **🤖 AI Agent** submenu.

## Configuration

```json
{
  "aiAgent.serverUrl": "http://localhost:8000",
  "aiAgent.autoConnect": true,
  "aiAgent.showStatusBar": true
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `serverUrl` | `http://localhost:8000` | Your agent server URL |
| `autoConnect` | `true` | Auto-check server on startup |
| `showStatusBar` | `true` | Show Ollama/Groq status in status bar |

## Status Bar

The bottom-right status bar shows live backend health:

```
$(robot) AI Agent [Ollama:✓ Groq:✓]
```

Click it to open the Web Chat UI. If the server is offline, it turns orange with a warning.
