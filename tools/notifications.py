"""
tools/notifications.py — Cross-platform desktop notifications (Step 4).

Supports Windows, macOS, and Linux.
No extra packages required on any platform.
Falls back silently if the platform notification system is unavailable.
"""

import sys
import subprocess
import threading


def _platform() -> str:
    if sys.platform == "win32":
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def notify(title: str, body: str, duration_ms: int = 6000):
    """
    Show a desktop notification. Non-blocking — runs in a background thread.
    Supports Windows 10/11, macOS, and Linux (notify-send).
    Falls back silently on failure.
    """
    t = title.replace('"', "'")
    b = body.replace('"', "'").replace("\n", " ")
    platform = _platform()

    def _send():
        try:
            if platform == "windows":
                _notify_windows(t, b, duration_ms)
            elif platform == "macos":
                _notify_macos(t, b)
            else:
                _notify_linux(t, b)
        except Exception:
            pass  # Always fail silently — notifications are best-effort

    threading.Thread(target=_send, daemon=True).start()


# ── Platform implementations ──────────────────────────────────────────────────

def _notify_windows(title: str, body: str, duration_ms: int):
    """Windows 10/11 toast via PowerShell Windows.UI.Notifications."""
    script = f"""
$app = 'AI Agent'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title}</text>
      <text>{body}</text>
    </binding>
  </visual>
</toast>
"@

$xml = New-Object Windows.Data.Xml.Dom.XmlDocument
$xml.LoadXml($template)
$toast = [Windows.UI.Notifications.ToastNotification]::new($xml)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($app)
$notifier.Show($toast)
"""
    try:
        subprocess.run(
            ["powershell", "-WindowStyle", "Hidden", "-Command", script],
            capture_output=True, timeout=5, creationflags=0x08000000
        )
        return
    except Exception:
        pass

    # Fallback: Windows Forms balloon tip
    fallback = f"""
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Application
$n.BalloonTipTitle = "{title}"
$n.BalloonTipText = "{body}"
$n.Visible = $True
$n.ShowBalloonTip({duration_ms})
Start-Sleep -Milliseconds {duration_ms + 500}
$n.Dispose()
"""
    subprocess.run(
        ["powershell", "-WindowStyle", "Hidden", "-Command", fallback],
        capture_output=True, timeout=10, creationflags=0x08000000
    )


def _notify_macos(title: str, body: str):
    """macOS notification via osascript."""
    script = f'display notification "{body}" with title "{title}"'
    subprocess.run(["osascript", "-e", script], capture_output=True, timeout=5)


def _notify_linux(title: str, body: str):
    """Linux notification via notify-send (libnotify)."""
    subprocess.run(["notify-send", title, body], capture_output=True, timeout=5)


# ── Convenience helpers ───────────────────────────────────────────────────────

def notify_task_done(task: str, success: bool = True):
    """Notify that a long-running agent task completed."""
    icon  = "✅" if success else "❌"
    title = f"{icon} Task Complete"
    body  = task[:120] + ("..." if len(task) > 120 else "")
    notify(title, body)


def notify_info(msg: str):
    notify("🤖 AI Agent", msg)
