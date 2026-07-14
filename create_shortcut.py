"""Create a "Michigan Pesticide Map" .lnk shortcut on the user's Desktop.

Uses PowerShell's WScript.Shell COM object so it works on any Windows
install without needing pywin32 / winshell.

Run from project root:
    py create_shortcut.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
TARGET      = PROJECT_ROOT / "launch_app.bat"
ICON        = PROJECT_ROOT / "app_icon.ico"
SHORTCUT_NAME = "Michigan Pesticide Map.lnk"


def _desktop_dir() -> Path:
    # USERPROFILE on Windows is the canonical home; OneDrive sometimes
    # re-homes the Desktop folder. Try the canonical path first, fall back
    # to OneDrive if it doesn't exist.
    candidates = []
    if "USERPROFILE" in os.environ:
        candidates.append(Path(os.environ["USERPROFILE"]) / "Desktop")
    if "OneDrive" in os.environ:
        candidates.append(Path(os.environ["OneDrive"]) / "Desktop")
    candidates.append(Path.home() / "Desktop")
    for p in candidates:
        if p.is_dir():
            return p
    raise SystemExit(f"Could not locate Desktop. Tried: {candidates}")


def make_shortcut() -> Path:
    if not TARGET.exists():
        raise SystemExit(f"Launcher not found: {TARGET}")
    if not ICON.exists():
        print(f"[warn] {ICON.name} not found — shortcut will use default icon.")
        icon_arg = ""
    else:
        icon_arg = str(ICON)

    desktop = _desktop_dir()
    shortcut_path = desktop / SHORTCUT_NAME

    # Build the PowerShell script. Escape single quotes for safety.
    def esc(p: str) -> str:
        return str(p).replace("'", "''")

    ps_script = f"""
$ws  = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut('{esc(shortcut_path)}')
$lnk.TargetPath       = '{esc(TARGET)}'
$lnk.WorkingDirectory = '{esc(PROJECT_ROOT)}'
$lnk.Description      = 'Michigan Pesticide Application Heat Map — launches the local server and opens the browser.'
$lnk.WindowStyle      = 1
"""
    if icon_arg:
        ps_script += f"$lnk.IconLocation = '{esc(icon_arg)},0'\n"
    ps_script += "$lnk.Save()\nWrite-Host 'shortcut written'\n"

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print("[error] PowerShell failed:")
        print(result.stdout)
        print(result.stderr)
        sys.exit(result.returncode)

    print(f"[ok] Created shortcut: {shortcut_path}")
    return shortcut_path


if __name__ == "__main__":
    path = make_shortcut()
    print()
    print("=" * 60)
    print(" Setup complete.")
    print("=" * 60)
    print()
    print(f"  Double-click 'Michigan Pesticide Map' on your desktop")
    print(f"  to launch the app. The browser will open automatically")
    print(f"  at http://localhost:8080.")
    print()
    print(f"  Shortcut location: {path}")
