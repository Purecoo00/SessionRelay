"""OS-specific paths and process handling shared by the relay and its frontends."""
import os
import shlex
import subprocess
import sys
from pathlib import Path, PureWindowsPath
from time import sleep

WINDOWS = os.name == "nt"


def app_support():
    return Path(os.environ["APPDATA"]) if WINDOWS else Path.home() / "Library/Application Support"


def relay_support():
    return Path(os.environ.get("SESSION_RELAY_SUPPORT") or app_support() / "Session Relay")


def replace_record(source, destination):
    if WINDOWS:
        # Python's normal readers can deny FILE_SHARE_DELETE until they close the old record.
        for _ in range(20):
            try:
                os.replace(source, destination)
                return
            except PermissionError as exc:
                if exc.winerror not in (5, 32):
                    raise
                sleep(0.025)
    os.replace(source, destination)


def script_command(script, *args):
    """A frozen console worker dispatches the same scripts by filename."""
    if getattr(sys, "frozen", False):
        return [sys.executable, Path(script).name, *args]
    return [sys.executable, "-B", str(script), *args]


def git_bash_command(argv, path_args):
    # MSYS can rewrite arguments paths when spawning Win32 programs. Supply them ourselves.
    args = [PureWindowsPath(arg).as_posix() if i in path_args else arg
            for i, arg in enumerate(argv)]
    return "MSYS2_ARG_CONV_EXCL='*' " + shlex.join(args)


def claude_rule_path(path):
    if WINDOWS:
        path = PureWindowsPath(path)
        if path.drive.endswith(":"):
            return "//" + path.drive[0].lower() + "/" + "/".join(path.parts[1:])
        return "/" + path.as_posix()
    return "/" + str(path)


def process_group():
    if WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def terminate_tree(pid):
    subprocess.run(["taskkill.exe", "/PID", str(pid), "/T", "/F"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def pid_alive(pid):
    if WINDOWS:
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE
        if not handle:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: process exists.
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258  # WAIT_TIMEOUT: still running.
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
