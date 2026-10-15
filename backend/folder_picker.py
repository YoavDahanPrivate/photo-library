"""Native directory selection, available only to a direct local browser."""
import ipaddress
import json
import os
import subprocess
import threading
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/databases/folders", tags=["Databases"])
_dialog_lock = threading.Lock()


def local_browser(request: Request):
    # Ignore proxy/client-supplied address claims. Never open a server desktop
    # dialog on behalf of a remote browser or through a reverse proxy.
    if any(name in request.headers for name in ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto")):
        return False
    try:
        if not request.client or not ipaddress.ip_address(request.client.host).is_loopback:
            return False
    except ValueError:
        return False
    if request.url.hostname not in ("localhost", "127.0.0.1", "::1"):
        return False
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in ("http", "https") or parsed.hostname not in ("localhost", "127.0.0.1", "::1"):
            return False
    return True


def supported(request):
    return os.name == "nt" and local_browser(request)


@router.get("/capabilities")
def capabilities(request: Request):
    available = supported(request)
    return {"available": available, "reason": None if available else "To browse, open this app through localhost on the Windows server computer. You can enter a server folder path from any computer."}


class PickFolder(BaseModel):
    initial: str = Field(default="", max_length=4096)


def native_directory(initial):
    # The script is constant; user paths travel in an environment variable,
    # never as executable PowerShell text. No console window accompanies it.
    script = r"""
    $ErrorActionPreference = 'Stop'
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
    Add-Type -AssemblyName System.Windows.Forms
    $dialog = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialog.Description = 'Choose a Database folder for Dahan'
    $dialog.ShowNewFolderButton = $false
    if ($env:DAHAN_PICKER_INITIAL -and (Test-Path -LiteralPath $env:DAHAN_PICKER_INITIAL -PathType Container)) {
        $dialog.SelectedPath = $env:DAHAN_PICKER_INITIAL
    }
    try {
        if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
            @{ root=$dialog.SelectedPath; cancelled=$false } | ConvertTo-Json -Compress
        } else {
            @{ root=$null; cancelled=$true } | ConvertTo-Json -Compress
        }
    } finally { $dialog.Dispose() }
    """
    env = os.environ.copy()
    env["DAHAN_PICKER_INITIAL"] = initial
    executable = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    result = subprocess.run([executable, "-NoProfile", "-STA", "-Command", script], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("The Windows directory dialog could not open. Enter the folder path instead.")
    return json.loads(result.stdout.strip().lstrip("\ufeff"))


@router.post("/pick")
def pick(request: Request, body: PickFolder):
    if not supported(request):
        raise HTTPException(403, "Folder browsing is only available from a direct local browser on the Windows backend host")
    if not _dialog_lock.acquire(blocking=False):
        raise HTTPException(409, "A folder dialog is already open on this computer")
    try:
        try:
            result = native_directory(body.initial)
        except subprocess.TimeoutExpired:
            raise HTTPException(408, "Folder selection timed out. Try Browse again or enter a path.")
        except (OSError, RuntimeError, ValueError):
            raise HTTPException(503, "The Windows directory dialog could not open. Enter the folder path instead.")
        if not result.get("cancelled"):
            # A real server path is returned, not a browser File object.
            from .source_management import root_path
            path = root_path(result.get("root", ""))
            if not path.is_dir():
                raise HTTPException(409, "Selected folder is no longer available")
            return {"root": str(path), "cancelled": False}
        return {"root": None, "cancelled": True}
    finally:
        _dialog_lock.release()
