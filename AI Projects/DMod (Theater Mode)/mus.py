"""
MouseUnSnag - DMod Backend Module
Fixes mouse getting stuck on corners/edges when moving between monitors on Windows.
"""

import math
import threading
import ctypes
import ctypes.wintypes
from dataclasses import dataclass, field
from typing import Optional

# ─── Win32 constants & structures ────────────────────────────────────────────

WH_MOUSE_LL   = 14
WM_MOUSEMOVE  = 0x0200
HC_ACTION     = 0

user32   = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

LRESULT  = ctypes.c_longlong
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)

kernel32.GetModuleHandleW.restype = ctypes.wintypes.HINSTANCE
kernel32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]

user32.CreateWindowExW.restype = LRESULT
user32.CreateWindowExW.argtypes = [
    ctypes.wintypes.DWORD,      # dwExStyle
    ctypes.wintypes.LPCWSTR,    # lpClassName
    ctypes.wintypes.LPCWSTR,    # lpWindowName
    ctypes.wintypes.DWORD,      # dwStyle
    ctypes.c_int,               # x
    ctypes.c_int,               # y
    ctypes.c_int,               # nWidth
    ctypes.c_int,               # nHeight
    ctypes.wintypes.HWND,       # hWndParent
    ctypes.wintypes.HMENU,      # hMenu
    ctypes.wintypes.HINSTANCE,  # hInstance
    ctypes.c_void_p,            # lpParam
]

user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [
    ctypes.wintypes.HWND, 
    ctypes.c_uint, 
    ctypes.wintypes.WPARAM, 
    ctypes.wintypes.LPARAM
]

user32.CallNextHookEx.restype  = LRESULT
user32.CallNextHookEx.argtypes = [
    ctypes.wintypes.HHOOK,
    ctypes.c_int,
    ctypes.wintypes.WPARAM,
    ctypes.wintypes.LPARAM,
]
user32.SetWindowsHookExW.restype  = ctypes.wintypes.HHOOK
user32.SetCursorPos.argtypes      = [ctypes.c_int, ctypes.c_int]

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]

class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt",        POINT),
        ("mouseData", ctypes.wintypes.DWORD),
        ("flags",     ctypes.wintypes.DWORD),
        ("time",      ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]

# ─── Geometry helpers ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self):  return self.right - self.left
    @property
    def height(self): return self.bottom - self.top

    def contains(self, x, y) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def overlap_x(self, other: "Rect") -> bool:
        return self.left < other.right and self.right > other.left

    def overlap_y(self, other: "Rect") -> bool:
        return self.top < other.bottom and self.bottom > other.top

    def outside_x_dist(self, x: int) -> int:
        return max(min(0, x - self.left), x - self.right + 1)

    def outside_y_dist(self, y: int) -> int:
        return max(min(0, y - self.top), y - self.bottom + 1)

    def outside_dist(self, x: int, y: int):
        return self.outside_x_dist(x), self.outside_y_dist(y)

    def outside_dir(self, x: int, y: int):
        dx, dy = self.outside_dist(x, y)
        return _sign(dx), _sign(dy)

    def outside_dir_rect(self, other: "Rect"):
        ox = not self.overlap_x(other)
        oy = not self.overlap_y(other)
        sx = _sign(other.left - self.left) if ox else 0
        sy = _sign(other.top  - self.top)  if oy else 0
        return sx, sy

    def closest_boundary(self, x: int, y: int):
        cx = max(self.left, min(x, self.right  - 1))
        cy = max(self.top,  min(y, self.bottom - 1))
        return cx, cy

    def magnitude_outside(self, x: int, y: int) -> float:
        dx, dy = self.outside_dist(x, y)
        return math.hypot(dx, dy)


def _sign(v: int) -> int:
    return (v > 0) - (v < 0)


# ─── Display / screen detection ───────────────────────────────────────────────

@dataclass
class Display:
    rect: Rect
    index: int
    to_left:  list = field(default_factory=list)
    to_right: list = field(default_factory=list)
    above:    list = field(default_factory=list)
    below:    list = field(default_factory=list)

    def link(self, other: "Display"):
        r, o = self.rect, other.rect
        if r.right  == o.left   and r.overlap_y(o): self.to_right.append(other)
        elif r.left == o.right  and r.overlap_y(o): self.to_left.append(other)
        elif r.top  == o.bottom and r.overlap_x(o): self.above.append(other)
        elif r.bottom == o.top  and r.overlap_x(o): self.below.append(other)


def _get_monitor_rects() -> list[Rect]:
    monitors = []

    def _cb(hmon, hdc, lprect, lparam):
        r = lprect.contents
        monitors.append(Rect(r.left, r.top, r.right, r.bottom))
        return 1

    MonitorEnumProc = ctypes.WINFUNCTYPE(
        ctypes.c_bool,
        ctypes.wintypes.HMONITOR,
        ctypes.wintypes.HDC,
        ctypes.POINTER(ctypes.wintypes.RECT),
        ctypes.wintypes.LPARAM,
    )
    cb = MonitorEnumProc(_cb)
    user32.EnumDisplayMonitors(None, None, cb, 0)
    return monitors


def build_display_list(rects: list[Rect]) -> list[Display]:
    displays = [Display(rect=r, index=i) for i, r in enumerate(rects)]
    for d in displays:
        for other in displays:
            if d is not other:
                d.link(other)
    return displays


# ─── Core logic ──────────────────────────────────────────────────────────────

class DisplayList:
    def __init__(self, displays: list[Display]):
        self.all       = displays
        self.left_most  = [d for d in displays if not d.to_left]
        self.right_most = [d for d in displays if not d.to_right]
        self.top_most   = [d for d in displays if not d.above]
        self.bottom_most= [d for d in displays if not d.below]

    def which_screen(self, x: int, y: int) -> Optional[Display]:
        for d in self.all:
            if d.rect.contains(x, y):
                return d
        return None

    def _screens_in_direction(self, dir_x: int, dir_y: int, cur_rect: Rect):
        for d in self.all:
            sx, sy = cur_rect.outside_dir_rect(d.rect)
            if (sx * dir_x == 1 and abs(sy - dir_y) <= 1) or \
               (sy * dir_y == 1 and abs(sx - dir_x) <= 1):
                yield d

    def jump_screen(self, mouse_x: int, mouse_y: int, cur_rect: Rect) -> Optional[Display]:
        dir_x, dir_y = cur_rect.outside_dir(mouse_x, mouse_y)
        best, best_dist = None, float("inf")
        for candidate in self._screens_in_direction(dir_x, dir_y, cur_rect):
            dist = candidate.rect.magnitude_outside(mouse_x, mouse_y)
            if dist < best_dist:
                best_dist = dist
                best = candidate
        return best

    def wrap_screen(self, dir_x: int, cursor_y: int) -> Optional[Display]:
        if dir_x == 0:
            return self.all[0] if self.all else None
        candidates = self.left_most if dir_x == 1 else self.right_most
        best, best_dist = (candidates[0] if candidates else self.all[0]), int(1e9)
        for s in candidates:
            dist = abs(s.rect.outside_y_dist(cursor_y))
            if dist < best_dist:
                best_dist = dist
                best = s
        return best


class MouseLogic:
    def __init__(self, options: "Options"):
        self.options = options
        self._display_list: Optional[DisplayList] = None
        self._updating = True
        self._last_mouse_x = 0
        self._last_mouse_y = 0
        self._lock = threading.Lock()
        self.on_wrap = None  # Setup an explicit placeholder for the sound trigger

    def begin_update(self):
        with self._lock:
            self._updating = True

    def end_update(self, display_list: DisplayList):
        with self._lock:
            self._display_list = display_list
            self._updating = False

    def handle_mouse(self, mouse_x: int, mouse_y: int, cursor_x: int, cursor_y: int):
        with self._lock:
            dl = self._display_list
            updating = self._updating

        if updating or dl is None:
            return None

        cursor_screen = dl.which_screen(cursor_x, cursor_y)
        mouse_screen  = dl.which_screen(mouse_x,  mouse_y)

        is_stuck = (cursor_x != self._last_mouse_x or cursor_y != self._last_mouse_y) \
                   and mouse_screen is not cursor_screen

        self._last_mouse_x, self._last_mouse_y = cursor_x, cursor_y

        if not is_stuck or cursor_screen is None:
            return None

        cur_rect = cursor_screen.rect
        stuck_dir_x, stuck_dir_y = cur_rect.outside_dir(mouse_x, mouse_y)

        if mouse_screen is not None:
            if not self.options.unstick:
                return None
            return mouse_x, mouse_y

        jump_screen = dl.jump_screen(mouse_x, mouse_y, cur_rect)
        if jump_screen is not None:
            if stuck_dir_x != 0 and stuck_dir_y != 0 and not self.options.unstick:
                return None
            if not self.options.jump:
                return None
            return jump_screen.rect.closest_boundary(cursor_x, cursor_y)

        if stuck_dir_x != 0:
            if not self.options.wrap:
                return None
            wrap = dl.wrap_screen(stuck_dir_x, cursor_y)
            if wrap is None:
                return None
            new_x = wrap.rect.left if stuck_dir_x == 1 else wrap.rect.right - 1
            new_y = cursor_y
            if not self.options.jump and not wrap.rect.contains(new_x, new_y):
                return None
                
            # Trigger the sound logic right before the cursor wrap takes effect
            if hasattr(self, 'on_wrap') and self.on_wrap:
                self.on_wrap()
                
            return wrap.rect.closest_boundary(new_x, new_y)

        return None


# ─── Options ──────────────────────────────────────────────────────────────────

class Options:
    def __init__(self):
        self.unsnag  = False
        self.unstick = False
        self.jump    = False
        self.wrap    = False

    def set_unsnag(self, v):
        self.unsnag = v
        self.unstick = v
        self.jump = v

    def set_wrap(self, v):
        self.wrap = v


# ─── Low-level mouse hook ─────────────────────────────────────────────────────

class MouseHook:
    def __init__(self, logic: MouseLogic):
        self._logic   = logic
        self._hook_id = None
        self._proc    = None

    def install(self):
        def _callback(ncode, wparam, lparam):
            if ncode == HC_ACTION and wparam == WM_MOUSEMOVE:
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                mouse_x, mouse_y = info.pt.x, info.pt.y

                cur = POINT()
                if user32.GetCursorPos(ctypes.byref(cur)):
                    result = self._logic.handle_mouse(mouse_x, mouse_y, cur.x, cur.y)
                    if result is not None:
                        nx, ny = result
                        user32.SetCursorPos(nx, ny)
                        return 1

            return user32.CallNextHookEx(self._hook_id, ncode, wparam, lparam)

        self._proc    = HOOKPROC(_callback)
        self._hook_id = user32.SetWindowsHookExW(WH_MOUSE_LL, self._proc, None, 0)
        if not self._hook_id:
            raise RuntimeError("Failed to install mouse hook")

    def uninstall(self):
        if self._hook_id:
            user32.UnhookWindowsHookEx(self._hook_id)
            self._hook_id = None

    def pump(self):
        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


# ─── Screen-change listener ───────────────────────────────────────────────────

def _rebuild_displays(logic: MouseLogic):
    logic.begin_update()
    rects    = _get_monitor_rects()
    displays = build_display_list(rects)
    logic.end_update(DisplayList(displays))


def _start_display_change_watcher(logic: MouseLogic):
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.wintypes.HWND,
                                  ctypes.c_uint, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
    WM_DISPLAYCHANGE = 0x007E
    WM_DESTROY       = 0x0002
    WS_OVERLAPPEDWINDOW = 0x00CF0000
    CW_USEDEFAULT    = 0x80000000

    def _wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_DISPLAYCHANGE:
            _rebuild_displays(logic)
        elif msg == WM_DESTROY:
            user32.PostQuitMessage(0)
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    proc = WNDPROC(_wndproc)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [
            ("style",         ctypes.c_uint),
            ("lpfnWndProc",   WNDPROC),
            ("cbClsExtra",    ctypes.c_int),
            ("cbWndExtra",    ctypes.c_int),
            ("hInstance",     ctypes.wintypes.HINSTANCE),
            ("hIcon",         ctypes.wintypes.HICON),
            ("hCursor",       ctypes.wintypes.HANDLE),
            ("hbrBackground", ctypes.wintypes.HBRUSH),
            ("lpszMenuName",  ctypes.wintypes.LPCWSTR),
            ("lpszClassName", ctypes.wintypes.LPCWSTR),
        ]

    cls = WNDCLASS()
    cls.lpfnWndProc  = proc
    cls.hInstance    = kernel32.GetModuleHandleW(None)
    cls.lpszClassName = "MouseUnSnagWatcher"
    user32.RegisterClassW(ctypes.byref(cls))

    hwnd = user32.CreateWindowExW(
        0, cls.lpszClassName, "MouseUnSnagWatcher",
        WS_OVERLAPPEDWINDOW, CW_USEDEFAULT, CW_USEDEFAULT,
        0, 0, None, None, cls.hInstance, None
    )

    msg = ctypes.wintypes.MSG()
    while user32.GetMessageW(ctypes.byref(msg), hwnd, 0, 0) != 0:
        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))