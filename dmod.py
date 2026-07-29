import sys
import os
import time
import ctypes
import ctypes.wintypes
import threading
import subprocess
from PyQt5.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu, QOpenGLWidget
from PyQt5.QtCore import Qt, QRect, QPropertyAnimation, pyqtProperty, pyqtSignal, QObject, QSettings, QEasingCurve, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QIcon, QPixmap, QSurfaceFormat
from pynput import keyboard
from os import environ
environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import pygame
from veil import get_veil, VEIL_LABELS
from gui import SettingsWindow
from shapes import clear_selection_holes, draw_selection_outlines
import winutils
import mus

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_cache = {}

# ── Sound setup ────────────────────────────────────────────────────────────
pygame.mixer.init()

_sound_cache: dict = {}

def _get_sound(filename: str):
    path = os.path.join(SCRIPT_DIR, filename)
    if path not in _sound_cache:
        _sound_cache[path] = (
            pygame.mixer.Sound(path) if os.path.exists(path) else None
        )
    return _sound_cache[path]

def play_sound(filename: str):
    if QSettings("TheaterMode", "Settings").value(
            f"mute_{filename}", False, type=bool):
        return
    try:
        snd = _get_sound(filename)
        if snd is not None:
            snd.play()
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────────────

class HotkeyManager(QObject):
    primary_pressed = pyqtSignal()
    primary_released = pyqtSignal()
    secondary_triggered = pyqtSignal()
    cursorlock_triggered = pyqtSignal()
    aot_triggered = pyqtSignal()
    network_triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = QSettings("TheaterMode", "Settings")
        self.listener = None
        self.primary_str = self.settings.value("primary_hotkey", "<ctrl>+<f3>")
        self.secondary_str = self.settings.value("secondary_hotkey", "<shift>+<ctrl>+<f3>")
        self.cursorlock_str = self.settings.value("cursorlock_hotkey", "<f7>")
        self.aot_str = self.settings.value("aot_hotkey", "<f8>")
        self.network_str = self.settings.value("network_hotkey", "<f10>")
        
        self.primary_active = False
        self._held_keys = set()
        self.start_listener()

    def reset_state(self):
        """Flushes stale orphan key states from pynput matchers after long idle times."""
        self._held_keys.clear()
        self.primary_active = False
        for hk in (self.primary_hk, self.secondary_hk, self.cursorlock_hk, self.aot_hk, self.network_hk):
            if hk and hasattr(hk, '_state'):
                try:
                    hk._state.clear()
                except Exception:
                    pass

    def start_listener(self):
        if self.listener:
            try:
                self.listener.stop()
            except Exception:
                pass

        self._held_keys = set()

        def is_valid(hk_str):
            return bool(hk_str and hk_str.strip() and hk_str.upper() != "NONE")

        self.primary_keys = set(keyboard.HotKey.parse(self.primary_str)) if is_valid(self.primary_str) else set()
        
        def on_primary_activate():
            self.primary_active = True
            self.primary_pressed.emit()

        def on_secondary_activate():
            self.secondary_triggered.emit()

        def on_cursorlock_activate():
            self.cursorlock_triggered.emit()

        def on_aot_activate():
            self.aot_triggered.emit()

        def on_network_activate():
            self.network_triggered.emit()

        self.primary_hk = keyboard.HotKey(keyboard.HotKey.parse(self.primary_str), on_primary_activate) if is_valid(self.primary_str) else None
        self.secondary_hk = keyboard.HotKey(keyboard.HotKey.parse(self.secondary_str), on_secondary_activate) if is_valid(self.secondary_str) else None
        self.cursorlock_hk = keyboard.HotKey(keyboard.HotKey.parse(self.cursorlock_str), on_cursorlock_activate) if is_valid(self.cursorlock_str) else None
        self.aot_hk = keyboard.HotKey(keyboard.HotKey.parse(self.aot_str), on_aot_activate) if is_valid(self.aot_str) else None
        self.network_hk = keyboard.HotKey(keyboard.HotKey.parse(self.network_str), on_network_activate) if is_valid(self.network_str) else None

        def on_press(key):
            try:
                if winutils.get_idle_time_ms() > 1000:
                    self.reset_state()

                canonical_key = self.listener.canonical(key)

                if canonical_key in self._held_keys:
                    return
                self._held_keys.add(canonical_key)

                if self.primary_hk: self.primary_hk.press(canonical_key)
                if self.secondary_hk: self.secondary_hk.press(canonical_key)
                if self.cursorlock_hk: self.cursorlock_hk.press(canonical_key)
                if self.aot_hk: self.aot_hk.press(canonical_key)
                if self.network_hk: self.network_hk.press(canonical_key)
            except Exception:
                pass

        def on_release(key):
            try:
                canonical_key = self.listener.canonical(key)
                self._held_keys.discard(canonical_key)

                if self.primary_hk: self.primary_hk.release(canonical_key)
                if self.secondary_hk: self.secondary_hk.release(canonical_key)
                if self.cursorlock_hk: self.cursorlock_hk.release(canonical_key)
                if self.aot_hk: self.aot_hk.release(canonical_key)
                if self.network_hk: self.network_hk.release(canonical_key)

                if self.primary_active:
                    if key in self.primary_keys or canonical_key in self.primary_keys:
                        self.primary_active = False
                        self.primary_released.emit()
            except Exception:
                pass

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.start()

    def pause(self):
        if self.listener:
            self.listener.stop()
            self.listener = None

    def resume(self):
        self.start_listener()

    def set_primary_hotkey(self, primary):
        self.primary_str = primary
        self.settings.setValue("primary_hotkey", primary)
        self.start_listener()

    def set_secondary_hotkey(self, secondary):
        self.secondary_str = secondary
        self.settings.setValue("secondary_hotkey", secondary)
        self.start_listener()

    def set_cursorlock_hotkey(self, combo):
        self.cursorlock_str = combo
        self.settings.setValue("cursorlock_hotkey", combo)
        self.start_listener()

    def set_aot_hotkey(self, combo):
        self.aot_str = combo
        self.settings.setValue("aot_hotkey", combo)
        self.start_listener()

    def set_network_hotkey(self, combo):
        self.network_str = combo
        self.settings.setValue("network_hotkey", combo)
        self.start_listener()


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [
        ("usUsagePage", ctypes.c_ushort),
        ("usUsage", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("hwndTarget", ctypes.wintypes.HWND)
    ]


class TheaterOverlay(QOpenGLWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("TheaterMode", "Settings")
        self.controller = None
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.state = 'hidden'
        self.selection_rects = []
        self.current_rect = QRect()
        self._opacity = 0.0

        self.target_opacity = float(self.settings.value("opacity", 0.9))
        self.veil_color = QColor(self.settings.value("color", "#000000"))
        self.fade_duration = int(self.settings.value("delay", 3000))
        self.fade_duration_pause = int(self.settings.value("delay_pause", 1000))

        self.veil_type = self.settings.value("veil_type", "flat")
        self.veil = get_veil(self.veil_type)
        self.veil.set_parent(self)

        self.selection_shape = self.settings.value("selection_shape", "rectangle")
        self.veil_mode       = self.settings.value("veil_mode", "manual")
        self.auto_dim_manager = None
        self.anim = QPropertyAnimation(self, b"overlayOpacity")
        self.anim.setEasingCurve(QEasingCurve.InOutQuad)

    def nativeEvent(self, eventType, message):
        """Catches raw system input messages directly without hooks or timers."""
        if eventType == b"windows_generic_MSG":
            msg = ctypes.wintypes.MSG.from_address(int(message))
            if msg.message == 0x00FF:  # WM_INPUT
                if self.controller and hasattr(self.controller, 'screensaver_mgr') and self.controller.screensaver_mgr._ss_active:
                    self.controller.screensaver_mgr._deactivate()
        return super().nativeEvent(eventType, message)

    def register_raw_input(self, enable: bool):
        """Toggles Win32 Raw Input listening directly on overlay HWND."""
        hwnd = int(self.winId())
        RIDEV_INPUTSINK = 0x00000100
        RIDEV_REMOVE    = 0x00000001

        flags = RIDEV_INPUTSINK if enable else RIDEV_REMOVE
        target_hwnd = hwnd if enable else 0

        devices = (RAWINPUTDEVICE * 2)()
        # Mouse
        devices[0].usUsagePage = 0x01
        devices[0].usUsage     = 0x02
        devices[0].dwFlags     = flags
        devices[0].hwndTarget  = target_hwnd

        # Keyboard
        devices[1].usUsagePage = 0x01
        devices[1].usUsage     = 0x06
        devices[1].dwFlags     = flags
        devices[1].hwndTarget  = target_hwnd

        ctypes.windll.user32.RegisterRawInputDevices(
            devices, 2, ctypes.sizeof(RAWINPUTDEVICE)
        )

    def set_veil_type(self, new_type):
        if self.state != 'hidden': self.veil.on_hide()
        self.veil_type = new_type
        self.settings.setValue("veil_type", new_type)
        self.veil = get_veil(new_type)
        self.veil.set_parent(self)
        if self.state != 'hidden': self.veil.on_show()
        self.update()

    def set_selection_shape(self, shape):
        self.selection_shape = shape
        self.settings.setValue("selection_shape", shape)
        self.update()

    def set_veil_mode(self, mode: str):
        self.veil_mode = mode
        self.settings.setValue("veil_mode", mode)
        if mode != "auto_dim" and self.auto_dim_manager:
            self.auto_dim_manager.stop()

    def get_opacity(self): return self._opacity
    def set_opacity(self, value):
        self._opacity = value
        self.update()
    overlayOpacity = pyqtProperty(float, get_opacity, set_opacity)

    def update_geometry_for_all_screens(self):
        rect = QRect()
        for screen in QApplication.screens(): rect = rect.united(screen.geometry())
        self.setGeometry(rect)

    def _set_clickthrough(self, enabled):
        hwnd = int(self.winId())
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x80000
        WS_EX_TRANSPARENT = 0x20
    
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    
        if enabled:
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        else:
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
    
        self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)

    def start_selection(self):
        self.anim.stop()
        self.veil.on_hide()
        self.state = 'selecting'
        self.selection_rects = []
        self.current_rect = QRect()
        self._opacity = 0.0
        self.update_geometry_for_all_screens()
        
        winutils.set_window_topmost(int(self.winId()))
        self._set_clickthrough(False)
        
        self.setCursor(Qt.CrossCursor)
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    def start_fade(self):
        play_sound("Fade.ogg")
        self.veil.on_show()
        self.state = 'theater'
        self.setCursor(Qt.ArrowCursor)
        
        winutils.set_window_topmost(int(self.winId()))
        self._set_clickthrough(True)
        
        self.fade_to(self.target_opacity, self.fade_duration)

    def on_primary_pressed(self):
        if self.controller and hasattr(self.controller, 'screensaver_mgr') and self.controller.screensaver_mgr._ss_active:
            self.controller.screensaver_mgr._deactivate()
            return

        if self.veil_mode == "auto_dim":
            if self.state in ("hidden", "hiding"):
                play_sound("Activate.ogg")
                self._activate_auto_dim()
            else:
                play_sound("Clear.ogg")
                self.state = "hiding"
                self.fade_to(0.0, 300, callback=self.reset_and_hide)
        else:
            if self.state in ('hidden', 'hiding'):
                play_sound("Activate.ogg")
                self.start_selection()
            else:
                play_sound("Clear.ogg")
                self.state = 'hiding'
                self.fade_to(0.0, 300, callback=self.reset_and_hide)

    def _activate_auto_dim(self):
        play_sound("Activate.ogg")
        QTimer.singleShot(260, lambda: play_sound("Fade.ogg"))
        self.update_geometry_for_all_screens()
        self.selection_rects = []
        self.veil.on_show()
        self.state = "theater"
        self.setCursor(Qt.ArrowCursor)
        
        self._set_clickthrough(True)
        
        self.show()
        self.raise_()
        self.fade_to(self.target_opacity, self.fade_duration)
        if self.auto_dim_manager:
            self.auto_dim_manager.start()

    def screensaver_activate(self):
        play_sound("Fade.ogg")
        self.update_geometry_for_all_screens()
        self.selection_rects = []
        self.veil.on_show()
        self.state = "theater"
            
        winutils.set_window_topmost(int(self.winId()))
        self._set_clickthrough(True)
            
        self.show()
        self.raise_()
        self.fade_to(self.target_opacity, self.fade_duration)

    def on_primary_released(self):
        if self.state == 'selecting':
            self.start_fade()

    def toggle_pause(self):
        if self.state == 'theater':
            play_sound("Pause.ogg")
            self.state = 'paused'
            self.veil.on_hide()
            if self.auto_dim_manager:
                self.auto_dim_manager.stop()
            self.fade_to(0.0, self.fade_duration_pause, callback=self.hide)
        elif self.state == 'paused':
            play_sound("Unpause.ogg")
            self.state = 'theater'
            self.show()
            self.veil.on_show()
            if self.veil_mode == "auto_dim" and self.auto_dim_manager:
                self.auto_dim_manager.start()
            self.fade_to(self.target_opacity, self.fade_duration_pause)

    def reset_and_hide(self):
        self.veil.on_hide()
        if self.auto_dim_manager:
            self.auto_dim_manager.stop()
        self.state = 'hidden'
        self.selection_rects = []
        self.current_rect = QRect()
        self.hide()

    def fade_to(self, target, duration, callback=None):
        self.anim.stop()
        try: self.anim.finished.disconnect()
        except: pass
        self.anim.setDuration(duration)
        self.anim.setStartValue(self._opacity)
        self.anim.setEndValue(target)
        if callback: self.anim.finished.connect(callback)
        self.anim.start()

    def mousePressEvent(self, event):
        if self.state == 'selecting' and event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.current_rect = QRect(self.start_pos, self.start_pos)
            self.update()

    def mouseMoveEvent(self, event):
        if self.state == 'selecting' and self.start_pos:
            self.current_rect = QRect(self.start_pos, event.pos()).normalized()
            self.update()

    def mouseReleaseEvent(self, event):
        if self.state == 'selecting' and event.button() == Qt.LeftButton:
            if not self.current_rect.isEmpty():
                self.selection_rects.append(self.current_rect)
            self.current_rect = QRect()
            self.start_pos = None
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        
        painter.setRenderHint(QPainter.Antialiasing)

        if self.state == 'selecting':
            pen = QPen(QColor(255, 255, 255, 200), 2, Qt.DashLine)
            
            draw_selection_outlines(painter, self.selection_rects, self.selection_shape, pen)
            
            if not self.current_rect.isNull() and not self.current_rect.isEmpty():
                draw_selection_outlines(painter, [self.current_rect], self.selection_shape, pen)
            return

        if self.state in ('theater', 'paused'):
            self.veil.paint(
                painter, self.rect(), self.selection_rects, self._opacity, self.veil_color,
                self.selection_shape,
            )


# ── ZERO-POLLING AUTO DIM MANAGER ──────────────────────────────────────────
EVENT_SYSTEM_FOREGROUND = 3
WINEVENT_OUTOFCONTEXT = 0

WinEventProcType = ctypes.WINFUNCTYPE(
    None, ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD, ctypes.wintypes.HWND,
    ctypes.wintypes.LONG, ctypes.wintypes.LONG, ctypes.wintypes.DWORD, ctypes.wintypes.DWORD
)

class AutoDimManager(QObject):
    def __init__(self, overlay):
        super().__init__()
        self.overlay = overlay
        self._last_hwnd = 0
        self._desktop_hidden = False
        self.hook_id = None
        self.hook_proc = WinEventProcType(self._win_event_callback)

    def start(self):
        self._last_hwnd = 0
        self._desktop_hidden = False
        if not self.hook_id:
            self.hook_id = ctypes.windll.user32.SetWinEventHook(
                EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND,
                0, self.hook_proc, 0, 0, WINEVENT_OUTOFCONTEXT
            )

    def stop(self):
        if self.hook_id:
            ctypes.windll.user32.UnhookWinEvent(self.hook_id)
            self.hook_id = None

    def _win_event_callback(self, hWinEventHook, event, hwnd, idObject, idChild, dwEventThread, dwmsEventTime):
        if not hwnd: return
        
        buf = ctypes.create_unicode_buffer(256)
        ctypes.windll.user32.GetClassNameW(hwnd, buf, 256)
        cls = buf.value

        if cls in ["Progman", "WorkerW"]:
            if not self._desktop_hidden and self.overlay.state == 'theater':
                self.overlay.fade_to(0.0, self.overlay.fade_duration_pause)
                self._desktop_hidden = True
            return

        if cls in winutils.AUTODIM_EXEMPT_CLASSES or hwnd == int(self.overlay.winId()):
            return

        if self._desktop_hidden and self.overlay.state == 'theater':
            self.overlay.fade_to(self.overlay.target_opacity, self.overlay.fade_duration_pause)
            self._desktop_hidden = False

        if hwnd != self._last_hwnd:
            self._last_hwnd = hwnd
            winutils.set_window_z_order(int(self.overlay.winId()), hwnd)
# ────────────────────────────────────────────────────────────────────────────


class ScreensaverManager(QObject):
    def __init__(self, overlay, settings):
        super().__init__()
        self.overlay = overlay
        self.settings = settings
        self._ss_active = False
        self._enabled = settings.value("screensaver_enabled", False, type=bool)
        self._timeout_ms = settings.value("screensaver_timeout_min", 5, type=int) * 60_000

        self._check_timer = QTimer()
        self._check_timer.setInterval(5_000)
        self._check_timer.timeout.connect(self._check_timeout)

        if self._enabled:
            self._check_timer.start()

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.settings.setValue("screensaver_enabled", enabled)
        if enabled:
            self._check_timer.start()
        else:
            self._check_timer.stop()
            if self._ss_active:
                self._deactivate()

    def set_timeout_minutes(self, minutes: int):
        self._timeout_ms = minutes * 60_000
        self.settings.setValue("screensaver_timeout_min", minutes)

    def _check_timeout(self):
        if not self._ss_active:
            idle_ms = winutils.get_idle_time_ms()
            if idle_ms >= self._timeout_ms and self.overlay.state == "hidden":
                self._activate()

    def _activate(self):
        self._ss_active = True
        play_sound("Activate.ogg")
        
        # Register zero-latency Raw Input directly on overlay HWND
        self.overlay.register_raw_input(True)
        
        self.overlay.screensaver_activate()

    def _deactivate(self):
        if not self._ss_active:
            return
        self._ss_active = False
        
        # Immediately unregister raw input
        self.overlay.register_raw_input(False)

        # Sanitize hotkey state machine on exit
        if hasattr(self.overlay, 'controller') and self.overlay.controller:
            self.overlay.controller.hotkey_mgr.reset_state()

        if self.overlay.state in ("theater", "paused", "hiding"):
            play_sound("Clear.ogg")
            self.overlay.state = "hiding"
            self.overlay.fade_to(0.0, 300, callback=self.overlay.reset_and_hide)


class AppController(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.settings = QSettings("TheaterMode", "Settings")
        self.overlay = TheaterOverlay()
        self.overlay.controller = self
        self.hotkey_mgr = HotkeyManager()
        self.cursor_locked = False
        
        self._mouse_hook_id = None
        self._mouse_hook_callback = None

        self.hotkey_mgr.primary_pressed.connect(self.overlay.on_primary_pressed)
        self.hotkey_mgr.primary_released.connect(self.overlay.on_primary_released)
        self.hotkey_mgr.secondary_triggered.connect(self.overlay.toggle_pause)
        self.hotkey_mgr.cursorlock_triggered.connect(self.toggle_cursor_lock)
        self.hotkey_mgr.aot_triggered.connect(self.toggle_always_on_top)
        self.hotkey_mgr.network_triggered.connect(self.toggle_network)

        self.app.aboutToQuit.connect(winutils.release_cursor_lock)
        self.app.aboutToQuit.connect(self.hotkey_mgr.pause)
        
        self.mus_options = mus.Options()
        self.mus_options.set_unsnag(self.settings.value("unsnag_mouse", False, type=bool))
        self.mus_options.set_wrap(self.settings.value("wrap_mouse", False, type=bool))

        self.mus_logic = mus.MouseLogic(self.mus_options)
        self.mus_logic.on_wrap = lambda: play_sound("wrap.ogg")

        mus._rebuild_displays(self.mus_logic)

        self.mus_hook = mus.MouseHook(self.mus_logic)
        self.mus_hook.install()
        self.app.aboutToQuit.connect(self.mus_hook.uninstall)

        self.mus_watcher_thread = threading.Thread(
            target=mus._start_display_change_watcher, args=(self.mus_logic,), daemon=True
        )
        self.mus_watcher_thread.start()

        self.mus_hook_thread = threading.Thread(target=self.mus_hook.pump, daemon=True)
        self.mus_hook_thread.start()

        self._desktop_icon_toggle_enabled = self.settings.value("desktop_icon_toggle", False, type=bool)
        self._last_click_time = 0.0
        if self._desktop_icon_toggle_enabled:
            self._start_desktop_mouse_listener()
        self.app.aboutToQuit.connect(self._stop_desktop_mouse_listener)

        self.auto_dim_manager   = AutoDimManager(self.overlay)
        self.screensaver_mgr    = ScreensaverManager(self.overlay, self.settings)
        self.overlay.auto_dim_manager = self.auto_dim_manager

        self.settings_window = SettingsWindow(self)
        self.setup_tray()

    def set_desktop_icon_toggle(self, state: bool):
        self._desktop_icon_toggle_enabled = state
        self.settings.setValue("desktop_icon_toggle", state)
        if state:
            self._start_desktop_mouse_listener()
        else:
            self._stop_desktop_mouse_listener()

    def toggle_network(self):
        play_sound("Activate.ogg")
        def _run():
            script = (
                "$adapters = Get-NetAdapter | Where-Object {$_.Status -ne 'Disarmed'}; "
                "$connected = $adapters | Where-Object {$_.Status -eq 'Up'}; "
                "if ($connected) { "
                "   $adapters | Disable-NetAdapter -Confirm:$false -PassThru "
                "} else { "
                "   $adapters | Enable-NetAdapter -Confirm:$false -PassThru "
                "}"
            )
            try:
                subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    def _start_desktop_mouse_listener(self):
        if getattr(self, '_mouse_hook_id', None):
            return

        WH_MOUSE_LL = 14
        WM_LBUTTONDOWN = 0x0201
        
        _u32 = ctypes.WinDLL("user32", use_last_error=True)
        _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        
        _u32.WindowFromPoint.restype = ctypes.c_void_p
        _u32.GetClassNameW.restype   = ctypes.c_int
        _u32.GetAncestor.restype     = ctypes.c_void_p
        _u32.GetAncestor.argtypes    = [ctypes.c_void_p, ctypes.c_uint]
        
        _u32.FindWindowW.argtypes    = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        _u32.FindWindowW.restype     = ctypes.c_void_p
        _u32.FindWindowExW.argtypes  = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p]
        _u32.FindWindowExW.restype   = ctypes.c_void_p
        _u32.SendMessageW.argtypes   = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
        _u32.SendMessageW.restype    = ctypes.c_ssize_t

        CMPFUNC = ctypes.WINFUNCTYPE(ctypes.wintypes.LPARAM, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)

        _u32.SetWindowsHookExW.argtypes = [ctypes.c_int, CMPFUNC, ctypes.wintypes.HINSTANCE, ctypes.wintypes.DWORD]
        _u32.SetWindowsHookExW.restype = ctypes.wintypes.HHOOK
        
        _u32.CallNextHookEx.argtypes = [ctypes.wintypes.HHOOK, ctypes.c_int, ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM]
        _u32.CallNextHookEx.restype = ctypes.wintypes.LPARAM
        
        _k32.GetModuleHandleW.argtypes = [ctypes.wintypes.LPCWSTR]
        _k32.GetModuleHandleW.restype = ctypes.wintypes.HINSTANCE

        self._last_click_time = 0.0
        DOUBLE_CLICK_THRESHOLD = 0.4

        def get_desktop_listview():
            progman = _u32.FindWindowW("Progman", None)
            shell_view = _u32.FindWindowExW(progman, 0, "SHELLDLL_DefView", None)
            if not shell_view:
                workerw = 0
                while True:
                    workerw = _u32.FindWindowExW(0, workerw, "WorkerW", None)
                    if not workerw:
                        break
                    shell_view = _u32.FindWindowExW(workerw, 0, "SHELLDLL_DefView", None)
                    if shell_view:
                        break
            if shell_view:
                return _u32.FindWindowExW(shell_view, 0, "SysListView32", None)
            return 0

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long),
                        ("y", ctypes.c_long),
                        ("data", ctypes.c_uint32),
                        ("flags", ctypes.c_uint32),
                        ("time", ctypes.c_uint32),
                        ("extra", ctypes.POINTER(ctypes.c_ulong))]

        def low_level_mouse_handler(nCode, wParam, lParam):
            if nCode >= 0:
                if wParam == WM_LBUTTONDOWN:
                    now = time.time()
                    if now - self._last_click_time < DOUBLE_CLICK_THRESHOLD:
                        hook_struct = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        pt = ctypes.c_longlong((int(hook_struct.y) << 32) | (int(hook_struct.x) & 0xFFFFFFFF))
                        hwnd = _u32.WindowFromPoint(pt)
                        
                        if hwnd:
                            root = _u32.GetAncestor(hwnd, 2)
                            buf = ctypes.create_unicode_buffer(256)
                            _u32.GetClassNameW(root, buf, 256)
                            cls = buf.value
                            
                            if cls in ("Progman", "WorkerW"):
                                lv_hwnd = get_desktop_listview()
                                if lv_hwnd:
                                    selected_count = _u32.SendMessageW(lv_hwnd, 0x1032, 0, 0)
                                    if selected_count == 0:
                                        winutils.toggle_desktop_icons()
                                        play_sound("hide.ogg")
                        self._last_click_time = 0.0
                    else:
                        self._last_click_time = now

            return _u32.CallNextHookEx(self._mouse_hook_id, nCode, wParam, lParam)

        self._mouse_hook_callback = CMPFUNC(low_level_mouse_handler)
        self._mouse_hook_id = _u32.SetWindowsHookExW(
            WH_MOUSE_LL, self._mouse_hook_callback, _k32.GetModuleHandleW(None), 0
        )

    def _stop_desktop_mouse_listener(self):
        if getattr(self, '_mouse_hook_id', None):
            _u32 = ctypes.WinDLL("user32", use_last_error=True)
            _u32.UnhookWindowsHookEx.argtypes = [ctypes.wintypes.HHOOK]
            _u32.UnhookWindowsHookEx.restype = ctypes.wintypes.BOOL
            _u32.UnhookWindowsHookEx(self._mouse_hook_id)
            self._mouse_hook_id = None

    def set_unsnag(self, state: bool):
        self.mus_options.set_unsnag(state)
        self.settings.setValue("unsnag_mouse", state)

    def set_wrap(self, state: bool):
        self.mus_options.set_wrap(state)
        self.settings.setValue("wrap_mouse", state)

    def toggle_cursor_lock(self):
        play_sound("Cursorlock.ogg")
        self.cursor_locked = not self.cursor_locked
        if self.cursor_locked:
            hwnd = winutils.get_foreground_window()
            if not winutils.lock_cursor_to_window(hwnd):
                self.cursor_locked = False
        else:
            winutils.release_cursor_lock()

    def toggle_always_on_top(self):
        play_sound("AOT.ogg")
        winutils.toggle_always_on_top()

    def show_settings(self):
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(QIcon(os.path.join(SCRIPT_DIR, "icon.ico")))
        self.tray_icon.setToolTip("DMod")

        self.menu = QMenu()
        self.menu.addAction("Open Settings...", self.show_settings)
        self.menu.addSeparator()
        self.menu.addAction("Exit", self.app.quit)

        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_settings()


if __name__ == '__main__':
    format = QSurfaceFormat()
    format.setDepthBufferSize(24)
    format.setStencilBufferSize(8)
    format.setVersion(2, 1)
    format.setProfile(QSurfaceFormat.CompatibilityProfile)
    QSurfaceFormat.setDefaultFormat(format)

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    app.setWindowIcon(QIcon(os.path.join(SCRIPT_DIR, "icon.ico")))

    controller = AppController(app)
    sys.exit(app.exec_())