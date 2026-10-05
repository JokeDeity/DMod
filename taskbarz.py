import sys
import time
import os
import json
import ctypes
import tempfile
import threading
import subprocess
import atexit
from ctypes import wintypes as wt

import win32gui
import win32con
import win32api

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QSlider, QPushButton, QCheckBox, QGroupBox, QApplication
)
from PyQt5.QtCore import Qt, QThread, QSettings

# Attempt high DPI awareness
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Optional UIA import handling
try:
    import uiautomation as auto
except ImportError:
    auto = None

# ---- Win32 API Bindings ----
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

HWND = wt.HWND
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = HWND
user32.FindWindowExW.argtypes = [HWND, HWND, wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowExW.restype = HWND
user32.GetParent.argtypes = [HWND]
user32.GetParent.restype = HWND
user32.IsWindow.argtypes = [HWND]
user32.IsWindow.restype = wt.BOOL
user32.IsWindowVisible.argtypes = [HWND]
user32.IsWindowVisible.restype = wt.BOOL
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wt.RECT)]
user32.GetClassNameW.argtypes = [HWND, wt.LPWSTR, ctypes.c_int]
user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wt.UINT]
user32.SendMessageTimeoutW.argtypes = [HWND, wt.UINT, wt.WPARAM, wt.LPCWSTR,
                                       wt.UINT, wt.UINT, ctypes.POINTER(wt.DWORD)]
user32.SendMessageTimeoutW.restype = wt.LPARAM
gdi32.CreateRectRgn.argtypes = [ctypes.c_int] * 4
gdi32.CreateRectRgn.restype = wt.HANDLE
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi32.CreateRoundRectRgn.restype = wt.HANDLE
user32.SetWindowRgn.argtypes = [HWND, wt.HANDLE, wt.BOOL]

SWP_BASE = 0x0004 | 0x0010   # NOZORDER | NOACTIVATE
SWP_NOSENDCHANGING = 0x0400

LEFT_ORDER = ["Start", "TrayDummySearchControl"]
RIGHT_ORDER = ["TrayNotifyWnd", "TrayInputIndicatorWClass", "TrayClockWClass",
               "ClockButton", "TrayShowDesktopButtonWClass"]

PROFILES = {
    "main": dict(
        slack=2,
        swp=SWP_BASE,
        enforce=True,
        tasklist_order=("MSTaskListWClass", "MSTaskSwWClass"),
        visible_only=False,
    ),
    "secondary": dict(
        slack=6,
        swp=SWP_BASE | SWP_NOSENDCHANGING,
        enforce=True,
        tasklist_order=("MSTaskSwWClass", "MSTaskListWClass"),
        visible_only=True,
    ),
}

# ---- Helper Functions ----
def rect(h):
    r = wt.RECT()
    user32.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom

def cls(h):
    b = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(h, b, 256)
    return b.value

def children(parent):
    out, h = [], None
    while True:
        h = user32.FindWindowExW(parent, h, None, None)
        if not h:
            return out
        out.append(h)

def visible_children(parent):
    return [c for c in children(parent) if user32.IsWindowVisible(c)]

def find_desc(parent, name, visible_only=False):
    for c in (visible_children(parent) if visible_only else children(parent)):
        if cls(c) == name:
            return c
        r = find_desc(c, name, visible_only)
        if r:
            return r
    return None

def taskbars():
    out = []
    h = user32.FindWindowW("Shell_TrayWnd", None)
    if h:
        out.append(h)
    h = None
    while True:
        h = user32.FindWindowExW(None, h, "Shell_SecondaryTrayWnd", None)
        if not h:
            return out
        out.append(h)

def force_relayout(tb):
    res = wt.DWORD()
    user32.SendMessageTimeoutW(tb, 0x001A, 0, "TraySettings", 2, 1000, ctypes.byref(res))

def restart_explorer():
    flags = 0x08000000
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], creationflags=flags,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(0.1)
        if user32.FindWindowW("Shell_TrayWnd", None):
            return
    subprocess.Popen(["explorer.exe"])

def restore_data(data):
    """Put every child back where it was, remove our clip, then verify the taskbar really
    is back to its original extents; if explorer refuses, restart it as a last resort."""
    for tb, kids in data.items():
        if not user32.IsWindow(tb):
            continue
        user32.SetWindowRgn(tb, None, True)
        for c, (x, y, w, h) in kids.items():
            if user32.IsWindow(c):
                user32.SetWindowPos(c, None, x, y, w, h, SWP_BASE | SWP_NOSENDCHANGING)
    for tb in data:
        if user32.IsWindow(tb):
            force_relayout(tb)
    if not data:
        return
    time.sleep(0.15)
    for tb, kids in data.items():
        if not user32.IsWindow(tb) or not kids:
            continue
        tl = rect(tb)[0]
        cur = [rect(c) for c in visible_children(tb)]
        if not cur:
            continue
        o_left = min(x for x, _, _, _ in kids.values())
        o_right = max(x + w for x, _, w, _ in kids.values())
        if abs(min(l - tl for l, _, _, _ in cur) - o_left) > 4 or \
                abs(max(r - tl for _, _, r, _ in cur) - o_right) > 4:
            restart_explorer()
            return

def order_key(name, order, x):
    return (order.index(name) if name in order else len(order), x)


def looks_natural(tb, snap):
    """True if the children span the taskbar edge to edge, as explorer lays them out."""
    if not snap:
        return False
    l, t, r, b = rect(tb)
    W = r - l
    if b - t > W:
        return True   # vertical taskbar: not checked
    return (min(x for x, _, _, _ in snap.values()) <= 24 and
            max(x + w for x, _, w, _ in snap.values()) >= W - 24)


# Detached helper: if the host app dies without cleaning up (crash / killed), it puts the
# taskbars back. It waits for the host process, then applies the layout saved in a JSON file.
WATCHDOG = True
WATCHDOG_SRC = r'''
import ctypes, json, os, sys
from ctypes import wintypes as wt
pid, path = int(sys.argv[1]), sys.argv[2]
k32 = ctypes.WinDLL("kernel32")
u32 = ctypes.WinDLL("user32")
k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
k32.OpenProcess.restype = ctypes.c_void_p
k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, wt.DWORD]
u32.IsWindow.argtypes = [ctypes.c_void_p]
u32.SetWindowRgn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wt.BOOL]
u32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 4 + [wt.UINT]
u32.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, wt.UINT, wt.WPARAM, wt.LPCWSTR,
                                    wt.UINT, wt.UINT, ctypes.POINTER(wt.DWORD)]
h = k32.OpenProcess(0x00100000, False, pid)
if h:
    k32.WaitForSingleObject(h, 0xFFFFFFFF)
try:
    with open(path) as f:
        data = json.load(f)
except Exception:
    data = {}
for tb, kids in data.items():
    tb = int(tb)
    if not u32.IsWindow(tb):
        continue
    u32.SetWindowRgn(tb, None, True)
    for c, (x, y, w, hh) in kids.items():
        if u32.IsWindow(int(c)):
            u32.SetWindowPos(int(c), None, x, y, w, hh, 0x0414)
    u32.SendMessageTimeoutW(tb, 0x001A, 0, "TraySettings", 2, 1000, ctypes.byref(wt.DWORD()))
try:
    os.remove(path)
except OSError:
    pass
'''


# ---- Taskbar Instance Logic ----
class Taskbar:
    def __init__(self, hwnd, backend):
        self.h = hwnd
        self.backend = backend
        self.kind = "secondary" if cls(hwnd) == "Shell_SecondaryTrayWnd" else "main"
        self.p = PROFILES[self.kind]
        self.tasklists = []
        self.ctls = {}
        self.reading = None
        self.reading_seen = 0.0
        self.moved_ts = 0.0
        self.cw = None
        self.count = -1
        self.sig = None
        self.unit = None
        self.lead = 0
        self.hold_until = 0.0
        self.prev_measured = None
        self.clip_box = None
        self.clip_time = 0.0
        self.last_tray_check = 0.0
        self.last_heal = 0.0

    def snapshot(self):
        tl, tt, _, _ = rect(self.h)
        out = {}
        for c in visible_children(self.h):
            l, t, r, b = rect(c)
            out[c] = (l - tl, t - tt, r - l, b - t)
        return out

    def read_sig(self):
        tl, tt, tr, tb = rect(self.h)
        sig = [(tl, tt, tr, tb)]
        for c in visible_children(self.h):
            l, t, r, b = rect(c)
            sig.append((c, l - tl, t - tt, r - l, b - t))
        return tuple(sig)

    def structure(self):
        if not (self.tasklists and all(user32.IsWindow(t) for t in self.tasklists)):
            found = [find_desc(self.h, n, self.p["visible_only"])
                     for n in self.p["tasklist_order"]]
            self.tasklists = [t for t in found if t]
        if not self.tasklists:
            return None
        elastic, p = None, self.tasklists[0]
        while p:
            par = user32.GetParent(p)
            if par == self.h:
                elastic = p
                break
            p = par
        if not elastic:
            return None
        el, _, er, _ = rect(elastic)
        ecx = (el + er) / 2
        left, right = [], []
        for c in visible_children(self.h):
            if c == elastic:
                continue
            l, _, r, _ = rect(c)
            if r - l <= 0:
                continue
            name = cls(c)
            if name in RIGHT_ORDER:
                right.append((order_key(name, RIGHT_ORDER, l), c))
            elif name in LEFT_ORDER:
                left.append((order_key(name, LEFT_ORDER, l), c))
            elif (l + r) / 2 < ecx:
                left.append((order_key(name, LEFT_ORDER, l), c))
            else:
                right.append((order_key(name, RIGHT_ORDER, l), c))
        return elastic, [c for _, c in sorted(left)], [c for _, c in sorted(right)]

    def tray_misordered(self):
        for c in visible_children(self.h):
            if cls(c) == "TrayNotifyWnd":
                kids = {cls(k): k for k in visible_children(c)}
                pager, clock = kids.get("SysPager"), kids.get("TrayClockWClass")
                if pager and clock:
                    return rect(clock)[0] < rect(pager)[2] - 2
        return False

    def uia_rects(self):
        if not auto:
            return []
        reached = False
        for t in list(self.tasklists):
            try:
                ctl = self.ctls.get(t) or auto.ControlFromHandle(t)
                self.ctls[t] = ctl
                kids = [(k, k.BoundingRectangle) for k in ctl.GetChildren()]
                reached = True
                btns = [br for k, br in kids if k.ControlTypeName == "ButtonControl"]
                if not btns:
                    tl_, _, tr_, _ = rect(t)
                    btns = [br for _, br in kids
                            if 0 < br.right - br.left < (tr_ - tl_) * 0.9]
                out = [(br.left, br.right) for br in btns if br.right - br.left > 0]
                if out:
                    return out
            except Exception:
                self.ctls.pop(t, None)
        return [] if reached else None

    def width(self, c):
        l, _, r, _ = rect(c)
        return r - l

    def place(self, c, x, w, tl, tt):
        l, t, r, b = rect(c)
        if (l - tl, r - l) != (x, w):
            user32.SetWindowPos(c, None, x, t - tt, w, b - t, self.p["swp"])
            self.moved_ts = time.time()

    def apply_clip(self, x0, x1, H):
        radius = self.backend.corner_radius
        margin = min(self.backend.margin, H // 4)
        pad = self.backend.clip_pad
        box = (max(0, x0 - pad), x1 + pad, H, radius, margin)
        now = time.time()
        if box == self.clip_box and now - self.clip_time < 1.0:
            return
        changed = box != self.clip_box
        self.clip_box, self.clip_time = box, now
        l, r = box[0], box[1]
        if radius > 0:
            rgn = gdi32.CreateRoundRectRgn(l, margin, r, H - margin, radius, radius)
        else:
            rgn = gdi32.CreateRectRgn(l, margin, r, H - margin)
        user32.SetWindowRgn(self.h, rgn, changed)

    def layout(self, elastic, left, right):
        tl, tt, tr, tb = rect(self.h)
        W, H = tr - tl, tb - tt
        if H > W:
            return
        gap = self.backend.gap if right else 0
        lw = sum(self.width(c) for c in left)
        rw = sum(self.width(c) for c in right)
        x = (W - (lw + self.cw + gap + rw)) // 2
        x0 = x
        for c in left:
            w = self.width(c)
            self.place(c, x, w, tl, tt)
            x += w
        self.place(elastic, x, self.cw, tl, tt)
        x += self.cw + gap
        for c in right:
            w = self.width(c)
            self.place(c, x, w, tl, tt)
            x += w
        self.apply_clip(x0, x, H)
        self.sig = self.read_sig()

    def update(self, now):
        parts = self.structure()
        if not parts:
            return
        elastic, left, right = parts

        if now - self.last_tray_check >= 0.1:
            self.last_tray_check = now
            if now - self.last_heal > 1.0 and self.tray_misordered():
                self.last_heal = now
                force_relayout(self.h)
                self.sig = None

        moved = self.read_sig() != self.sig
        if moved:
            self.moved_ts = now
        relayout = moved

        reading = self.reading
        if reading and reading[0] > self.reading_seen:
            self.reading_seen = reading[0]
            rs = reading[1]
            if rs is not None:
                coherent = reading[0] > self.moved_ts
                count = len(rs)
                tl, tt, tr, _ = rect(self.h)
                lw = sum(self.width(c) for c in left)
                rw = sum(self.width(c) for c in right)
                avail = max(4, (tr - tl) - lw - rw - (self.backend.gap if right else 0))
                slack = self.p["slack"]
                grew = self.cw is not None and count > self.count >= 0
                shrank = self.cw is not None and 0 <= count < self.count
                if rs:
                    mn = min(l for l, _ in rs)
                    mx = max(r for _, r in rs)
                    ext = mx - mn
                    lead = self.lead
                    if coherent:
                        lead = mn - rect(elastic)[0]
                        if not 0 <= lead <= 6:
                            lead = 0
                    measured = ext + lead + slack
                else:
                    ext, lead, measured = 0, self.lead, 4

                if count and self.unit and (grew or shrank):
                    new_cw = min(int(round(self.unit * count)) + self.lead + slack, avail)
                    self.hold_until = now + 0.45
                elif grew and not self.unit:
                    new_cw = avail
                    self.hold_until = now + 0.15
                elif now < self.hold_until:
                    new_cw = max(self.cw or 0, measured)
                else:
                    new_cw = measured
                    stable = measured == self.prev_measured
                    if stable and coherent and count and ext > 0:
                        self.unit = ext / count
                        self.lead = lead
                self.prev_measured = measured

                self.count = count
                if new_cw != self.cw:
                    self.cw = new_cw
                    relayout = True

        if self.cw is None:
            return
        if relayout or self.p["enforce"]:
            self.layout(elastic, left, right)


# ---- PyQt Thread Backend ----
class TaskbarZBackend(QThread):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("TheaterMode", "Settings")
        self.enabled = self.settings.value("taskbarz_enabled", True, type=bool)
        self.corner_radius = self.settings.value("taskbar_radius", 16, type=int)
        self.margin = self.settings.value("taskbar_margin", 2, type=int)
        self.clip_pad = self.settings.value("taskbar_clip_pad", 6, type=int)
        self.gap = self.settings.value("taskbar_gap", 0, type=int)
        
        self.running = True
        self.lock = threading.RLock()
        self.originals = {}
        self.tbs = {}
        self.pending = {}   # taskbars waiting for explorer to finish building them
        self.json_path = None

    def uia_worker(self):
        if not auto:
            return
        init = getattr(auto, "UIAutomationInitializerInThread", None)
        ctx = init() if init else threading.Lock() # dummy context if not available
        with ctx:
            while self.running:
                if not self.enabled:
                    time.sleep(0.1)  # stay alive while disabled so re-enabling works
                    continue
                try:
                    with self.lock:
                        tb_list = list(self.tbs.values())
                    for t in tb_list:
                        if t.tasklists:
                            ts = time.time()
                            t.reading = (ts, t.uia_rects())
                except Exception:
                    pass
                time.sleep(0.02)

    def write_json(self):
        """Save the natural layouts for the watchdog."""
        if not self.json_path:
            return
        try:
            blob = {str(tb): {str(c): list(v) for c, v in kids.items()}
                    for tb, kids in self.originals.items()}
            with open(self.json_path, "w") as f:
                json.dump(blob, f)
        except Exception:
            pass

    def spawn_watchdog(self):
        exe = sys.executable or ""
        if getattr(sys, "frozen", False) or not os.path.basename(exe).lower().startswith("python"):
            return   # never relaunch a host exe by accident
        self.json_path = os.path.join(tempfile.gettempdir(), f"taskbarz_{os.getpid()}.json")
        self.write_json()
        try:
            subprocess.Popen(
                [exe, "-c", WATCHDOG_SRC, str(os.getpid()), self.json_path],
                creationflags=0x00000008 | 0x00000200,   # DETACHED_PROCESS | NEW_PROCESS_GROUP
                close_fds=True, stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            self.json_path = None

    def admit(self, h, now):
        """Start managing a taskbar only once explorer has finished building it and its
        layout is natural, so the saved 'original' layout is the real one. (Right after an
        explorer restart the main taskbar is populated over several seconds.)"""
        p = self.pending.get(h)
        if p is None:
            p = self.pending[h] = {"tb": Taskbar(h, self), "sig": None,
                                   "since": now, "born": now, "tries": 0}
        tb = p["tb"]
        sig = tb.read_sig()
        if sig != p["sig"]:
            p["sig"], p["since"] = sig, now     # still changing: wait
            return
        if (now - p["since"] < 0.4 and now - p["born"] < 5.0) or tb.structure() is None:
            return
        snap = tb.snapshot()
        if not looks_natural(h, snap) and p["tries"] < 3:
            p["tries"] += 1                     # left displaced: ask explorer to relayout
            force_relayout(h)
            p["since"] = now
            return
        self.tbs[h] = tb
        self.originals[h] = snap
        del self.pending[h]
        self.write_json()

    def run(self):
        ole32 = ctypes.windll.ole32
        ole32.CoInitialize(None)

        for h in taskbars():
            force_relayout(h)   # start from explorer's natural layout
        time.sleep(0.3)

        if WATCHDOG:
            self.spawn_watchdog()
        threading.Thread(target=self.uia_worker, daemon=True).start()

        active = False
        while self.running:
            if self.enabled:
                if not active:
                    # (re)enabled: start from explorer's natural layout, like first launch
                    active = True
                    for h in taskbars():
                        force_relayout(h)
                    time.sleep(0.3)
                with self.lock:
                    if not (self.enabled and self.running):   # toggled off / closing
                        continue
                    now = time.time()
                    current = taskbars()
                    for h in current:
                        if h not in self.tbs:
                            self.admit(h, now)
                    for h in list(self.pending):
                        if h not in current:
                            del self.pending[h]
                    for h in list(self.tbs):
                        if h not in current:
                            del self.tbs[h]
                            self.originals.pop(h, None)
                            self.write_json()
                    for t in self.tbs.values():
                        try:
                            t.update(now)
                        except Exception:
                            pass
            else:
                active = False
                time.sleep(0.05)
            time.sleep(0.005)

        self.cleanup()

    def set_enabled(self, enabled):
        self.enabled = enabled
        self.settings.setValue("taskbarz_enabled", enabled)
        if not enabled:
            self.cleanup()

    def update_settings(self, radius, margin, clip_pad, gap):
        self.corner_radius = radius
        self.margin = margin
        self.clip_pad = clip_pad
        self.gap = gap

        self.settings.setValue("taskbar_radius", radius)
        self.settings.setValue("taskbar_margin", margin)
        self.settings.setValue("taskbar_clip_pad", clip_pad)
        self.settings.setValue("taskbar_gap", gap)

    def cleanup(self):
        """Restore the default taskbars. Safe to call more than once."""
        with self.lock:
            restore_data(self.originals)
            self.originals.clear()
            self.tbs.clear()
            self.pending.clear()
            self.write_json()

    def shutdown(self):
        """Stop managing taskbars and restore the defaults (does not change saved settings)."""
        self.running = False
        self.cleanup()

    def stop(self):
        self.shutdown()
        if self.isRunning() and QThread.currentThread() is not self:
            self.wait(3000)


# Global Singleton instance
taskbar_z_backend = TaskbarZBackend()
taskbar_z_backend.start()
atexit.register(taskbar_z_backend.shutdown)    # restore on normal interpreter exit


def hook_qt_quit():
    """Restore the taskbars when the host Qt application quits."""
    app = QApplication.instance()
    if app is not None and not getattr(app, "_taskbarz_quit_hooked", False):
        app.aboutToQuit.connect(taskbar_z_backend.stop)
        app._taskbarz_quit_hooked = True


hook_qt_quit()

# Alias for backwards compatibility with DMod imports
TaskbarRounderBackend = TaskbarZBackend
taskbar_rounder_backend = taskbar_z_backend


# ---- PyQt Settings Tab UI ----
class TaskbarZTab(QWidget):
    def __init__(self, backend_thread=None):
        super().__init__()
        self.backend = backend_thread or taskbar_z_backend
        self.settings = QSettings("TheaterMode", "Settings")
        hook_qt_quit()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignTop)

        # Main Enable Checkbox
        self.enable_chk = QCheckBox("Enable TaskbarZ")
        self.enable_chk.setChecked(self.backend.enabled)
        self.enable_chk.toggled.connect(self.update_settings)
        layout.addWidget(self.enable_chk)
        layout.addSpacing(10)

        # Rounding & Geometry Group Box
        geom_group = QGroupBox("Geometry and Margins")
        geom_layout = QVBoxLayout()

        self.radius_label = QLabel(f"Corner Radius: {self.backend.corner_radius} px")
        geom_layout.addWidget(self.radius_label)
        self.radius_slider = QSlider(Qt.Horizontal)
        self.radius_slider.setRange(0, 50)
        self.radius_slider.setValue(self.backend.corner_radius)
        self.radius_slider.valueChanged.connect(self.update_settings)
        geom_layout.addWidget(self.radius_slider)

        self.margin_label = QLabel(f"Vertical Margin: {self.backend.margin} px")
        geom_layout.addWidget(self.margin_label)
        self.margin_slider = QSlider(Qt.Horizontal)
        self.margin_slider.setRange(0, 20)
        self.margin_slider.setValue(self.backend.margin)
        self.margin_slider.valueChanged.connect(self.update_settings)
        geom_layout.addWidget(self.margin_slider)

        self.pad_label = QLabel(f"Clip Padding: {self.backend.clip_pad} px")
        geom_layout.addWidget(self.pad_label)
        self.pad_slider = QSlider(Qt.Horizontal)
        self.pad_slider.setRange(0, 30)
        self.pad_slider.setValue(self.backend.clip_pad)
        self.pad_slider.valueChanged.connect(self.update_settings)
        geom_layout.addWidget(self.pad_slider)

        self.gap_label = QLabel(f"Button to Tray Gap: {self.backend.gap} px")
        geom_layout.addWidget(self.gap_label)
        self.gap_slider = QSlider(Qt.Horizontal)
        self.gap_slider.setRange(0, 50)
        self.gap_slider.setValue(self.backend.gap)
        self.gap_slider.valueChanged.connect(self.update_settings)
        geom_layout.addWidget(self.gap_slider)

        geom_group.setLayout(geom_layout)
        layout.addWidget(geom_group)
        layout.addSpacing(10)

        layout.addSpacing(5)

        # Utilities
        self.restart_btn = QPushButton("Restart Windows Explorer")
        self.restart_btn.clicked.connect(restart_explorer)
        layout.addWidget(self.restart_btn)

        self.setLayout(layout)

    def update_settings(self):
        enabled = self.enable_chk.isChecked()
        radius = self.radius_slider.value()
        margin = self.margin_slider.value()
        pad = self.pad_slider.value()
        gap = self.gap_slider.value()

        self.radius_label.setText(f"Corner Radius: {radius} px")
        self.margin_label.setText(f"Vertical Margin: {margin} px")
        self.pad_label.setText(f"Clip Padding: {pad} px")
        self.gap_label.setText(f"Button to Tray Gap: {gap} px")

        self.backend.update_settings(radius, margin, pad, gap)
        self.backend.set_enabled(enabled)


# Alias for backwards compatibility with DMod imports
TaskbarRounderTab = TaskbarZTab