"""Ask for a local desktop decision. Command arguments cannot supply the answer."""
import base64
import os
import subprocess
import sys
from pathlib import Path

MAC_DIALOG = """
ObjC.import('AppKit');
function run(argv) {
    const app = $.NSApplication.sharedApplication;
    app.setActivationPolicy($.NSApplicationActivationPolicyAccessory);
    const alert = $.NSAlert.alloc.init;
    alert.messageText = '外贸单证管线 · 确认正式出单';
    alert.informativeText = argv[0];
    alert.alertStyle = $.NSAlertStyleWarning;
    alert.addButtonWithTitle('取消');
    alert.addButtonWithTitle('确认出单');
    app.activateIgnoringOtherApps(true);
    return Number(alert.runModal) === Number($.NSAlertSecondButtonReturn) ? 'approved' : 'cancelled';
}
"""
WINDOWS_DIALOG = """
Add-Type -AssemblyName System.Windows.Forms
$result = [System.Windows.Forms.MessageBox]::Show(
    $env:WORKBUDDY_ORDER_APPROVAL_TEXT, '外贸单证管线 · 确认正式出单',
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    [System.Windows.Forms.MessageBoxIcon]::Warning,
    [System.Windows.Forms.MessageBoxDefaultButton]::Button2)
if ($result -eq [System.Windows.Forms.DialogResult]::Yes) { 'approved' }
"""


class ApprovalUnavailable(Exception):
    pass


def approve_on_desktop(message, *, verifying_actuals=False):
    env = None
    if sys.platform == "darwin":
        script = MAC_DIALOG
        if verifying_actuals:
            script = script.replace("确认正式出单", "核对实际资料").replace("确认出单", "确认资料")
        command = ["/usr/bin/osascript", "-l", "JavaScript", "-e", script, message]
    elif sys.platform == "win32":
        windows = Path(os.environ.get("SystemRoot", r"C:\Windows"))
        powershell = windows / "System32/WindowsPowerShell/v1.0/powershell.exe"
        script = WINDOWS_DIALOG.replace("确认正式出单", "核对实际资料") if verifying_actuals else WINDOWS_DIALOG
        encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
        command = [str(powershell), "-NoProfile", "-NonInteractive", "-STA",
                   "-EncodedCommand", encoded]
        env = {**os.environ, "WORKBUDDY_ORDER_APPROVAL_TEXT": message}
    else:
        raise ApprovalUnavailable("这个环境无法显示桌面确认窗口。可以先保留内部草稿。")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=95, env=env)
    except subprocess.TimeoutExpired as exc:
        raise ApprovalUnavailable("桌面确认超时，请重新核对后再打开确认。") from exc
    except OSError as exc:
        raise ApprovalUnavailable("无法打开桌面确认窗口。可以先保留内部草稿。") from exc
    if result.returncode:
        raise ApprovalUnavailable("桌面确认窗口未能完成。可以先保留内部草稿。")
    return result.returncode == 0 and result.stdout.strip() == "approved"
