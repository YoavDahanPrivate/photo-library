"""SMB access under the backend's Windows account; secrets stay in its vault."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field, SecretStr, ValidationError
from . import core
from .folder_picker import local_browser

router = APIRouter(prefix="/api/databases/access", tags=["Network folder access"])
_lock = threading.RLock()
_connections = {}
_failures = {}


def scope(value):
    raw = str(value).strip().replace("/", "\\")
    if not raw.startswith("\\\\"):
        return None
    parts = raw[2:].rstrip("\\").split("\\")
    if (len(parts) < 2 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", parts[0])
            or any(not p or p in (".", "..") or any(c in p for c in '\x00:*?"<>|') for p in parts[1:])):
        raise ValueError("Use a network folder path such as \\\\server\\share\\Photos; device paths and '..' are not supported")
    return dict(server=parts[0].casefold(), share="\\\\"+parts[0]+"\\"+parts[1], root="\\\\"+"\\".join(parts))


def target(server):
    namespace = hashlib.sha256(str(core.database_dir().resolve()).casefold().encode()).hexdigest()[:24]
    return "DahanPhotoLibrary/"+namespace+"/SMB/"+server.casefold()


class Credential(ctypes.Structure):
    _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]


class Resource(ctypes.Structure):
    _fields_ = [("dwScope", wintypes.DWORD), ("dwType", wintypes.DWORD),
                ("dwDisplayType", wintypes.DWORD), ("dwUsage", wintypes.DWORD),
                ("lpLocalName", wintypes.LPWSTR), ("lpRemoteName", wintypes.LPWSTR),
                ("lpComment", wintypes.LPWSTR), ("lpProvider", wintypes.LPWSTR)]


def vault_api():
    if os.name != "nt":
        raise RuntimeError("Saved network access requires a Windows backend")
    dll = ctypes.WinDLL("advapi32", use_last_error=True)
    dll.CredWriteW.argtypes = [ctypes.POINTER(Credential), wintypes.DWORD]
    dll.CredWriteW.restype = wintypes.BOOL
    dll.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(Credential))]
    dll.CredReadW.restype = wintypes.BOOL
    dll.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    dll.CredDeleteW.restype = wintypes.BOOL
    dll.CredFree.argtypes = [ctypes.c_void_p]
    return dll


def read_secret(server):
    dll = vault_api()
    pointer = ctypes.POINTER(Credential)()
    if not dll.CredReadW(target(server), 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:
            return None
        raise RuntimeError("Windows Credential Manager is unavailable for the backend account")
    try:
        value = pointer.contents
        raw = ctypes.string_at(value.CredentialBlob, value.CredentialBlobSize)
        return value.UserName, raw.decode("utf-16-le")
    finally:
        if pointer.contents.CredentialBlobSize:
            ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
        dll.CredFree(pointer)


def write_secret(server, username, password):
    dll = vault_api()
    raw = password.encode("utf-16-le")
    if not raw or len(raw) > 2560:
        raise RuntimeError("Password must contain 1 to 1280 UTF-16 characters")
    buffer = ctypes.create_string_buffer(raw)
    value = Credential(Type=1, TargetName=target(server), Comment="Dahan network folder access",
                       CredentialBlobSize=len(raw), CredentialBlob=ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)),
                       Persist=2, UserName=username)
    try:
        if not dll.CredWriteW(ctypes.byref(value), 0):
            raise RuntimeError("Windows could not save credentials for the backend account")
    finally:
        ctypes.memset(buffer, 0, len(buffer))


def delete_secret(server):
    dll = vault_api()
    if not dll.CredDeleteW(target(server), 1, 0) and ctypes.get_last_error() != 1168:
        raise RuntimeError("Windows could not forget these credentials")
    # Do not disconnect shares used by other apps or delete their credentials.
    with _lock:
        _connections.clear()
        _failures.clear()


def native_connect(share, username, password):
    dll = ctypes.WinDLL("mpr", use_last_error=True)
    dll.WNetAddConnection2W.argtypes = [ctypes.POINTER(Resource), wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    dll.WNetAddConnection2W.restype = wintypes.DWORD
    resource = Resource(dwType=1, lpRemoteName=share)
    return int(dll.WNetAddConnection2W(ctypes.byref(resource), password, username, 4))


class CredentialConflict(RuntimeError):
    """Windows error 1219: another account already owns this server session."""


def existing_folder_readable(root):
    # Bound even an unavailable NAS. This only tests Windows' current access;
    # it neither reads the Dahan vault nor submits or saves a new password.
    try:
        result=subprocess.run([sys.executable,'-B','-m','backend.network_access','--check-existing'],
            input=json.dumps({'root':str(root)}),text=True,encoding='utf-8',capture_output=True,
            timeout=20,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,
            cwd=Path(__file__).resolve().parents[1])
        return not result.returncode and json.loads(result.stdout).get('readable') is True
    except (subprocess.TimeoutExpired,OSError,ValueError):return False


def mark_connected(info):
    key=(target(info['server']),info['share'].casefold())
    _failures.pop(key,None)
    _connections[key]=time.monotonic()+60


def connect_share(share, username, password):
    # The password goes through a private stdin pipe, never command arguments,
    # environment variables, logs or catalogue JSON. A stalled NAS is bounded.
    try:
        result = subprocess.run([sys.executable, "-B", "-m", "backend.network_access", "--connect"],
                                input=json.dumps(dict(share=share, username=username, password=password)),
                                text=True, encoding="utf-8", capture_output=True, timeout=20,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                                cwd=Path(__file__).resolve().parents[1])
        code = json.loads(result.stdout)["code"] if not result.returncode else -1
    except subprocess.TimeoutExpired:
        raise RuntimeError("Network connection timed out. Check that the server is available") from None
    except (OSError, ValueError, KeyError):
        raise RuntimeError("Windows could not establish network access") from None
    if code == 1219:
        raise CredentialConflict("Windows already has a connection to this server with different credentials. Its current account cannot read this folder. Change the connection account in Windows, then retry. The submitted credentials were not saved")
    if code in (5, 86, 1326, 1330, 1909):
        raise RuntimeError("Access denied. Check the username, password and share permissions")
    if code:
        raise RuntimeError("Network server or share unavailable (Windows code "+str(code)+")")


def ensure_access(root):
    info = scope(root)
    if not info or os.name != "nt":
        return
    with _lock:
        key = (target(info["server"]), info["share"].casefold())
        if _connections.get(key, 0) > time.monotonic():
            return
        failure = _failures.get(key)
        if failure and failure[0] > time.monotonic():
            raise RuntimeError(failure[1])
        try:
            credentials = read_secret(info["server"])
            if credentials:
                try:
                    connect_share(info["share"], *credentials)
                except CredentialConflict:
                    if not existing_folder_readable(info['root']):raise
                _connections[key] = time.monotonic()+60
                _failures.pop(key, None)
        except RuntimeError as error:
            _failures[key] = (time.monotonic()+30, str(error))
            raise


def guard(request):
    if os.name != "nt" or not local_browser(request):
        raise HTTPException(403, "Manage network credentials through localhost on the Windows backend computer; passwords cannot be submitted over the LAN")


class Folder(BaseModel):
    root: str = Field(min_length=1, max_length=4096)


class Login(Folder):
    username: str = Field(min_length=1, max_length=256)
    password: SecretStr
    remember: bool = False


async def checked_body(request, model):
    # Normal validation errors can echo the submitted body. This endpoint never
    # includes raw inputs (particularly a password) in error responses.
    try:
        return model.model_validate(await request.json())
    except (ValidationError, ValueError):
        raise HTTPException(422, "Enter a network folder, username and password with valid lengths") from None


def network_folder(root):
    try:
        info = scope(root)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    if not info:
        raise HTTPException(422, "Use a UNC network path such as \\\\server\\share\\Photos. Local and mapped-drive folders use the backend Windows account")
    return info


@router.get("/capabilities")
def capabilities(request: Request):
    available = os.name == "nt" and local_browser(request)
    return dict(available=available, reason=None if available else "To set or forget saved access, open this app through localhost on the Windows backend computer. Saved access still works for automatic syncs and remote browsing.")


@router.post("/status")
async def status(request: Request):
    guard(request)
    body = await checked_body(request, Folder)
    info = network_folder(body.root)
    try:
        saved = read_secret(info["server"])
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from None
    return dict(server=info["server"], saved=bool(saved), username=saved[0] if saved else "")


def connect_folder(info, username, password, remember):
    with _lock:
        try:
            connect_share(info["share"], username, password)
        except CredentialConflict:
            if not existing_folder_readable(info['root']):raise
            mark_connected(info)
            # Never save unverified submitted credentials just because another
            # Windows account can already read the selected folder.
            return dict(saved=False,used_existing=True,credentials_verified=False)
        # Full media readability is checked by assignment analysis afterwards.
        with os.scandir(info["root"]) as entries:
            next(entries, None)
        if remember:
            write_secret(info["server"], username, password)
        # Testing without Remember never erases an existing saved credential.
        _failures.clear()
        _connections[(target(info["server"]), info["share"].casefold())] = time.monotonic()+60
        return dict(saved=remember,used_existing=False,credentials_verified=True)


@router.post("/use-existing")
async def use_existing(request:Request):
    guard(request)
    body=await checked_body(request,Folder)
    info=network_folder(body.root)
    readable=await run_in_threadpool(existing_folder_readable,info['root'])
    if not readable:
        raise HTTPException(409,'The current Windows connection cannot read this folder. Check the folder path and permissions, or change the connection account in Windows and retry')
    with _lock:mark_connected(info)
    return dict(server=info['server'],connected=True,saved=False,used_existing=True,credentials_verified=False)


@router.post("/connect")
async def connect(request: Request):
    guard(request)
    body = await checked_body(request, Login)
    info = network_folder(body.root)
    username = body.username.strip()
    password = body.password.get_secret_value()
    try:
        valid_password = bool(password) and len(password.encode("utf-16-le")) <= 2560
    except UnicodeEncodeError:
        valid_password = False
    if not username or "\x00" in username or "\x00" in password or not valid_password:
        raise HTTPException(422, "Enter a non-empty username and password with valid lengths")
    try:
        outcome=await run_in_threadpool(connect_folder, info, username, password, body.remember)
    except CredentialConflict as error:
        raise HTTPException(409,dict(code='credential_conflict',message=str(error))) from None
    except (RuntimeError, OSError) as error:
        detail = str(error) if isinstance(error, RuntimeError) else "Share connected, but the folder is unavailable or cannot be read. Credentials were not saved"
        raise HTTPException(409, detail) from None
    return dict(server=info["server"], connected=True, username=username if outcome['credentials_verified'] else '', **outcome)


@router.post("/forget")
async def forget(request: Request):
    guard(request)
    body = await checked_body(request, Folder)
    info = network_folder(body.root)
    try:
        delete_secret(info["server"])
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from None
    return dict(forgotten=True, server=info["server"])


if __name__ == "__main__" and sys.argv[1:] == ["--connect"]:
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(dict(code=native_connect(payload["share"], payload["username"], payload["password"]))))
    except Exception:
        # The helper never emits request contents, exceptions or tracebacks.
        print(json.dumps(dict(code=-1)))

elif __name__ == '__main__' and sys.argv[1:]==['--check-existing']:
    try:
        body=json.load(sys.stdin)
        info=scope(body['root'])
        if not info:raise ValueError('UNC path required')
        with os.scandir(info['root']) as entries:next(entries,None)
        print(json.dumps({'readable':True}))
    except Exception:
        print(json.dumps({'readable':False}))
