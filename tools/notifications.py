"""
tools/notifications.py — Windows desktop toast notifications.

Uses PowerShell + Windows Forms — no extra packages required.
Falls back to a simple print if not on Windows or PowerShell unavailable.
"""

import sys
import subprocess
import threading


def _is_windows() -> bool:
    return sys.platform == "win32"


def notify(title: str, body: str, duration_ms: int = 6000):
    """
    Show a Windows 10/11 toast notification.
    Non-blocking — runs in a background thread.
    Falls back silently on non-Windows or missing PowerShell.
    """
    if not _is_windows():
        return

    def _send():
        # Escape double quotes
        t = title.replace('"', "'")
        b = body.replace('"', "'").replace("\n", " ")

        # Use Windows.UI.Notifications (modern toast) via PowerShell
        script = f"""
$app = 'AI Agent'
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

$template = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{t}</text>
      <text>{b}</text>
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
        except Exception:
            # Fallback: balloon notification via System.Windows.Forms
            try:
                fallback = f"""
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Application
$n.BalloonTipTitle = "{t}"
$n.BalloonTipText = "{b}"
$n.Visible = $True
$n.ShowBalloonTip({duration_ms})
Start-Sleep -Milliseconds {duration_ms + 500}
$n.Dispose()
"""
                subprocess.run(
                    ["powershell", "-WindowStyle", "Hidden", "-Command", fallback],
                    capture_output=True, timeout=10, creationflags=0x08000000
                )
            except Exception:
                pass

    threading.Thread(target=_send, daemon=True).start()


def notify_task_done(task: str, success: bool = True):
    """Notify that a long-running agent task completed."""
    icon  = "✅" if success else "❌"
    title = f"{icon} Task Complete"
    body  = task[:120] + ("..." if len(task) > 120 else "")
    notify(title, body)


def notify_info(msg: str):
    notify("🤖 AI Agent", msg)
