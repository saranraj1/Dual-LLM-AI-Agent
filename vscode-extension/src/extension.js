// vscode-extension/src/extension.js
// AI Agent VS Code Extension — Feature 11
// Calls the agent's REST API (http://localhost:8000) from inside VS Code.

const vscode = require("vscode");
const http   = require("http");
const https  = require("https");
const path   = require("path");

// ── Config helpers ────────────────────────────────────────────────────────────

function getServerUrl() {
  return vscode.workspace
    .getConfiguration("aiAgent")
    .get("serverUrl", "http://localhost:8000")
    .replace(/\/$/, "");
}

// ── HTTP helpers ──────────────────────────────────────────────────────────────

/**
 * POST JSON to the agent API, return the response body as a string.
 * Handles both streaming (SSE) and blocking endpoints.
 */
function agentPost(endpoint, body) {
  return new Promise((resolve, reject) => {
    const url     = new URL(getServerUrl() + endpoint);
    const payload = JSON.stringify(body);
    const lib     = url.protocol === "https:" ? https : http;

    const req = lib.request(
      { hostname: url.hostname, port: url.port || 8000, path: url.pathname, method: "POST",
        headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(payload) } },
      (res) => {
        let data = "";
        res.on("data", chunk => { data += chunk; });
        res.on("end", () => {
          // Strip SSE framing if present
          if (data.includes("event:")) {
            const tokens = [...data.matchAll(/^data: "(.*)"/gm)].map(m => {
              try { return JSON.parse(`"${m[1]}"`); } catch { return m[1]; }
            });
            resolve(tokens.join(""));
          } else {
            try { resolve(JSON.parse(data).result || data); }
            catch { resolve(data); }
          }
        });
      }
    );
    req.on("error", reject);
    req.write(payload);
    req.end();
  });
}

/**
 * GET from the agent API.
 */
function agentGet(endpoint) {
  return new Promise((resolve, reject) => {
    const url = new URL(getServerUrl() + endpoint);
    const lib = url.protocol === "https:" ? https : http;
    lib.get(url.href, (res) => {
      let data = "";
      res.on("data", chunk => { data += chunk; });
      res.on("end", () => { try { resolve(JSON.parse(data)); } catch { resolve(data); } });
    }).on("error", reject);
  });
}

// ── Shared utilities ──────────────────────────────────────────────────────────

function getRelativePath(uri) {
  const ws = vscode.workspace.workspaceFolders?.[0]?.uri?.fsPath;
  if (!ws) return path.basename(uri.fsPath);
  return path.relative(ws, uri.fsPath);
}

function getActiveFile() {
  return vscode.window.activeTextEditor?.document?.uri;
}

/**
 * Show streaming result in a new read-only Markdown document.
 */
async function showInDocument(title, content) {
  const doc = await vscode.workspace.openTextDocument({
    content: `# ${title}\n\n${content}`,
    language: "markdown",
  });
  vscode.window.showTextDocument(doc, { preview: true, preserveFocus: false });
}

/**
 * Run a slash command and show the result.
 */
async function runCommand(cmd, label) {
  const serverUrl = getServerUrl();
  return vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `AI Agent: ${label}…`, cancellable: false },
    async () => {
      try {
        const result = await agentPost("/command", { command: cmd });
        if (result && result.trim()) {
          showInDocument(label, result);
        } else {
          vscode.window.showInformationMessage(`AI Agent: ${label} complete.`);
        }
      } catch (err) {
        const msg = `Cannot reach agent server at ${serverUrl}. Start it with: ai --serve`;
        const action = await vscode.window.showErrorMessage(msg, "Copy Command");
        if (action === "Copy Command") {
          vscode.env.clipboard.writeText("ai --serve");
        }
      }
    }
  );
}

// ── Status bar ────────────────────────────────────────────────────────────────

let statusBarItem;

async function updateStatusBar() {
  if (!statusBarItem) return;
  try {
    const health = await agentGet("/health");
    const backend = health.backend || "auto";
    const ollama  = health.ollama ? "✓" : "✗";
    const groq    = health.groq   ? "✓" : "✗";
    statusBarItem.text        = `$(robot) AI Agent [Ollama:${ollama} Groq:${groq}]`;
    statusBarItem.tooltip     = `AI Agent — Backend: ${backend}\nClick to open chat`;
    statusBarItem.backgroundColor = undefined;
  } catch {
    statusBarItem.text            = `$(robot) AI Agent $(warning)`;
    statusBarItem.tooltip         = "AI Agent server offline — run: ai --serve";
    statusBarItem.backgroundColor = new vscode.ThemeColor("statusBarItem.warningBackground");
  }
}

// ── Extension activation ──────────────────────────────────────────────────────

function activate(context) {
  const config = vscode.workspace.getConfiguration("aiAgent");

  // ── Status bar ──────────────────────────────────────────────────────────────
  if (config.get("showStatusBar", true)) {
    statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBarItem.command = "aiAgent.openChat";
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);
    updateStatusBar();
    setInterval(updateStatusBar, 30_000);  // refresh every 30s
  }

  // ── Output channel for logs ─────────────────────────────────────────────────
  const output = vscode.window.createOutputChannel("AI Agent");
  context.subscriptions.push(output);

  // ── Register all commands ───────────────────────────────────────────────────

  // /review <file>
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.reviewFile", (uri) => {
      const file = uri || getActiveFile();
      if (!file) return vscode.window.showWarningMessage("AI Agent: No file selected.");
      const relPath = getRelativePath(file);
      output.appendLine(`[review] ${relPath}`);
      runCommand(`/review ${relPath}`, `Review: ${relPath}`);
    })
  );

  // /fix <file>
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.fixFile", (uri) => {
      const file = uri || getActiveFile();
      if (!file) return vscode.window.showWarningMessage("AI Agent: No file selected.");
      const relPath = getRelativePath(file);
      output.appendLine(`[fix] ${relPath}`);
      runCommand(`/fix ${relPath}`, `Fix: ${relPath}`);
    })
  );

  // /explain <file>
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.explainFile", (uri) => {
      const file = uri || getActiveFile();
      if (!file) return vscode.window.showWarningMessage("AI Agent: No file selected.");
      const relPath = getRelativePath(file);
      output.appendLine(`[explain] ${relPath}`);
      runCommand(`/explain ${relPath}`, `Explain: ${relPath}`);
    })
  );

  // /refactor <file>
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.refactorFile", (uri) => {
      const file = uri || getActiveFile();
      if (!file) return vscode.window.showWarningMessage("AI Agent: No file selected.");
      const relPath = getRelativePath(file);
      output.appendLine(`[refactor] ${relPath}`);
      runCommand(`/refactor ${relPath}`, `Refactor: ${relPath}`);
    })
  );

  // /security <file>
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.securityScan", (uri) => {
      const file = uri || getActiveFile();
      if (!file) return vscode.window.showWarningMessage("AI Agent: No file selected.");
      const relPath = getRelativePath(file);
      output.appendLine(`[security] ${relPath}`);
      runCommand(`/security ${relPath}`, `Security Scan: ${relPath}`);
    })
  );

  // /test <file>
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.generateTests", (uri) => {
      const file = uri || getActiveFile();
      if (!file) return vscode.window.showWarningMessage("AI Agent: No file selected.");
      const relPath = getRelativePath(file);
      output.appendLine(`[test] ${relPath}`);
      runCommand(`/test ${relPath}`, `Generate Tests: ${relPath}`);
    })
  );

  // /explain <selection> — explain selected code snippet
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.explainSelection", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const selection = editor.document.getText(editor.selection);
      if (!selection.trim()) return vscode.window.showWarningMessage("AI Agent: Select some code first.");
      output.appendLine(`[explain-selection] ${selection.length} chars`);
      return vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "AI Agent: Explaining selection…" },
        async () => {
          try {
            const result = await agentPost("/chat", {
              message: `Explain this code clearly:\n\`\`\`\n${selection.slice(0, 2000)}\n\`\`\``
            });
            showInDocument("Code Explanation", result);
          } catch (err) {
            vscode.window.showErrorMessage("AI Agent: Cannot reach server. Start with: ai --serve");
          }
        }
      );
    })
  );

  // /fix <selection> — fix a selected snippet inline
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.fixSelection", async () => {
      const editor = vscode.window.activeTextEditor;
      if (!editor) return;
      const sel  = editor.selection;
      const code = editor.document.getText(sel);
      if (!code.trim()) return vscode.window.showWarningMessage("AI Agent: Select some code first.");
      output.appendLine(`[fix-selection] ${code.length} chars`);
      return vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "AI Agent: Fixing selection…" },
        async () => {
          try {
            const result = await agentPost("/chat", {
              message: `Fix this code and return only the corrected code — no explanation:\n\`\`\`\n${code.slice(0, 2000)}\n\`\`\``
            });
            // Extract code block from response
            const codeMatch = result.match(/```[\w]*\n?([\s\S]+?)```/);
            const fixed = codeMatch ? codeMatch[1] : result;
            editor.edit(eb => eb.replace(sel, fixed.trim()));
            vscode.window.showInformationMessage("AI Agent: Selection fixed ✓");
          } catch (err) {
            vscode.window.showErrorMessage("AI Agent: Cannot reach server. Start with: ai --serve");
          }
        }
      );
    })
  );

  // Open Web Chat UI in browser
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.openChat", () => {
      const url = getServerUrl();
      vscode.env.openExternal(vscode.Uri.parse(url));
    })
  );

  // /run <task> — prompt user for a task description
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.runTask", async () => {
      const task = await vscode.window.showInputBox({
        prompt:      "Describe the task for the AI Agent",
        placeholder: "e.g. add input validation to all API routes",
        title:       "AI Agent — Run Task",
      });
      if (!task?.trim()) return;
      output.appendLine(`[run] ${task}`);
      return vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: `AI Agent: Running task…`, cancellable: false },
        async () => {
          try {
            const result = await agentPost("/run", { task });
            showInDocument(`Task Result: ${task.slice(0, 50)}`, result);
          } catch (err) {
            vscode.window.showErrorMessage("AI Agent: Cannot reach server. Start with: ai --serve");
          }
        }
      );
    })
  );

  // /docs api — generate API docs
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.generateApiDocs", () => {
      output.appendLine("[docs api]");
      runCommand("/docs api", "Generate API Docs");
    })
  );

  // /git — smart commit
  context.subscriptions.push(
    vscode.commands.registerCommand("aiAgent.gitCommit", () => {
      output.appendLine("[git]");
      runCommand("/git", "Smart Git Commit");
    })
  );

  // Auto-connect check
  if (config.get("autoConnect", true)) {
    agentGet("/health").then(health => {
      const backend = health.backend || "auto";
      vscode.window.showInformationMessage(
        `AI Agent connected (backend: ${backend}) — Ctrl+Shift+A to open chat`,
        "Open Chat"
      ).then(action => {
        if (action === "Open Chat") {
          vscode.commands.executeCommand("aiAgent.openChat");
        }
      });
    }).catch(() => {
      // Silent — don't nag if server isn't running
    });
  }

  output.appendLine("AI Agent extension activated.");
  output.appendLine(`Server URL: ${getServerUrl()}`);
}

function deactivate() {}

module.exports = { activate, deactivate };
