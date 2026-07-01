"""
winutils.py – Small Win32 helpers backing the cursor-lock and
always-on-top hotkey features. Windows-only; pure ctypes, no extra
dependencies required.
"""

import ctypes
import sys
import winreg
import os
from ctypes import wintypes

user32 = ctypes.windll.user32
user32.GetForegroundWindow.restype = wintypes.HWND
user32.ClipCursor.argtypes = [ctypes.POINTER(wintypes.RECT)]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    ctypes.c_uint
]

GWL_EXSTYLE    = -20
WS_EX_TOPMOST  = 0x00000008
HWND_TOPMOST   = -1
HWND_NOTOPMOST = -2
SWP_NOMOVE     = 0x0002
SWP_NOSIZE     = 0x0001
SWP_NOACTIVATE = 0x0010


def get_foreground_window():
    """Returns the HWND of the currently active window."""
    return user32.GetForegroundWindow()


def lock_cursor_to_window(hwnd):
    """Clips the cursor to the bounds of the given window. Returns True on success."""
    if not hwnd:
        return False
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    return bool(user32.ClipCursor(ctypes.byref(rect)))


def release_cursor_lock():
    """Removes any active cursor clip. Safe to call even if nothing is locked."""
    user32.ClipCursor(None)


def toggle_always_on_top(hwnd=None):
    """
    Toggles the topmost (always-on-top) state of a window, mirroring
    AutoHotkey's `WinSet, AlwaysOnTop, Toggle, A`. Defaults to the
    current foreground window. Returns the new state (True = now on top).
    """
    if hwnd is None:
        hwnd = get_foreground_window()
    if not hwnd:
        return False

    ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    is_topmost = bool(ex_style & WS_EX_TOPMOST)
    target = HWND_NOTOPMOST if is_topmost else HWND_TOPMOST

    user32.SetWindowPos(
        hwnd, target, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE
    )
    return not is_topmost

def toggle_desktop_icons():
    """
    Toggles desktop icon visibility by searching both Progman and WorkerW
    branches for the SysListView32 component.
    """
    # Required Windows API definitions for this specific function
    # Using c_wchar_p (pointer to wide-character string) for string arguments
    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_wchar_p, ctypes.c_wchar_p]
    user32.FindWindowExW.restype  = wintypes.HWND
    user32.GetWindow.argtypes     = [wintypes.HWND, ctypes.c_uint]
    user32.GetWindow.restype      = wintypes.HWND
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype  = wintypes.BOOL
    user32.ShowWindow.argtypes    = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype     = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetClassNameW.restype  = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
    user32.GetWindowTextW.restype  = ctypes.c_int

    GW_CHILD = 5
    SW_HIDE  = 0
    SW_SHOW  = 5

    def _get_class(hwnd):
        b = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, b, 256)
        return b.value

    def _get_title(hwnd):
        b = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, b, 256)
        return b.value

    # Check both potential parent shell windows
    parent_classes = ["WorkerW", "Progman"]
    
    for parent_class in parent_classes:
        hwnd = 0
        while True:
            hwnd = user32.FindWindowExW(0, hwnd, parent_class, None)
            if not hwnd:
                break
                
            h_def = user32.GetWindow(hwnd, GW_CHILD)
            if not h_def:
                continue
            
            # Look for the SHELLDLL_DefView container
            if _get_class(h_def) != "SHELLDLL_DefView":
                continue
                
            # Look for the actual icon list
            h_lv = user32.GetWindow(h_def, GW_CHILD)
            if h_lv and _get_class(h_lv) == "SysListView32" and _get_title(h_lv) == "FolderView":
                if user32.IsWindowVisible(h_lv):
                    user32.ShowWindow(h_lv, SW_HIDE)
                else:
                    user32.ShowWindow(h_lv, SW_SHOW)
                return
                
                
def set_autostart(enable=True):
    """Adds or removes the application from the Windows Startup registry key."""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "DMod"
    exe_path = sys.executable
    
    # Handle both PyInstaller executable and raw script execution
    if getattr(sys, 'frozen', False):
        target = f'"{exe_path}"'
    else:
        target = f'"{exe_path}" "{os.path.abspath(sys.argv[0])}"'
        
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
        if enable:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, target)
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception:
        return False
        
def is_autostart_enabled():
    """Checks if the app is currently in the Windows Startup registry."""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "DMod"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ)
        winreg.QueryValueEx(key, app_name)
        winreg.CloseKey(key)
        return True
    except FileNotFoundError:
        return False


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False

def relaunch_as_admin():
    """Relaunches this program elevated via the UAC prompt. Caller should quit right after."""
    exe = sys.executable
    if getattr(sys, "frozen", False):
        # Compiled exe (PyInstaller) — sys.argv[0] is the exe itself, skip it
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, None, 1)