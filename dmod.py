import sys
import os
import ctypes
import threading
import pygame
import traceback
from PyQt5.QtWidgets import QApplication, QWidget, QSystemTrayIcon, QMenu, QOpenGLWidget
from PyQt5.QtCore import Qt, QRect, QPropertyAnimation, pyqtProperty, pyqtSignal, QObject, QSettings, QEasingCurve, QTimer
from PyQt5.QtGui import QPainter, QColor, QPen, QIcon, QPixmap, QSurfaceFormat
from PyQt5.QtOpenGL import QGLFormat
from pynput import keyboard, mouse as pynput_mouse
from veil import get_veil, VEIL_LABELS
from gui import SettingsWindow
from shapes import clear_selection_holes, draw_selection_outlines
import winutils
import mus

# ── Sound setup ────────────────────────────────────────────────────────────
pygame.mixer.init()
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def play_sound(filename):
    settings = QSettings("TheaterMode", "Settings")
    # We store the mute state in a setting, e.g., "mute_Activate.mp3"
    # If the user checks the box, we save True.
    if settings.value(f"mute_{filename}", False, type=bool):
        return
    """Play an MP3 from the script's directory, non-blocking. Silently no-ops if missing."""
    path = os.path.join(SCRIPT_DIR, filename)
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
    except Exception:
        pass


# ────────────────────────────────────────────────────────────────────────────

class HotkeyManager(QObject):
    primary_pressed = pyqtSignal()
    primary_released = pyqtSignal()
    secondary_triggered = pyqtSignal()
    cursorlock_triggered = pyqtSignal()
    aot_triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = QSettings("TheaterMode", "Settings")
        self.listener = None
        self.primary_str = self.settings.value("primary_hotkey", "<ctrl>+<f3>")
        self.secondary_str = self.settings.value("secondary_hotkey", "<shift>+<ctrl>+<f3>")
        self.cursorlock_str = self.settings.value("cursorlock_hotkey", "<f7>")
        self.aot_str = self.settings.value("aot_hotkey", "<f8>")
        self.primary_active = False
        self._held_keys = set()
        self.start_listener()

    def start_listener(self):
        if self.listener:
            self.listener.stop()

        self._held_keys = set()
        self.primary_keys = set(keyboard.HotKey.parse(self.primary_str))
        
        def on_primary_activate():
            self.primary_active = True
            self.primary_pressed.emit()

        def on_secondary_activate():
            self.secondary_triggered.emit()

        def on_cursorlock_activate():
            self.cursorlock_triggered.emit()

        def on_aot_activate():
            self.aot_triggered.emit()

        self.primary_hk = keyboard.HotKey(keyboard.HotKey.parse(self.primary_str), on_primary_activate)
        self.secondary_hk = keyboard.HotKey(keyboard.HotKey.parse(self.secondary_str), on_secondary_activate)
        self.cursorlock_hk = keyboard.HotKey(keyboard.HotKey.parse(self.cursorlock_str), on_cursorlock_activate)
        self.aot_hk = keyboard.HotKey(keyboard.HotKey.parse(self.aot_str), on_aot_activate)

        def on_press(key):
            try:
                canonical_key = self.listener.canonical(key)

                if canonical_key in self._held_keys:
                    return
                self._held_keys.add(canonical_key)

                self.primary_hk.press(canonical_key)
                self.secondary_hk.press(canonical_key)
                self.cursorlock_hk.press(canonical_key)
                self.aot_hk.press(canonical_key)
            except AttributeError:
                pass

        def on_release(key):
            try:
                canonical_key = self.listener.canonical(key)
                self._held_keys.discard(canonical_key)

                self.primary_hk.release(canonical_key)
                self.secondary_hk.release(canonical_key)
                self.cursorlock_hk.release(canonical_key)
                self.aot_hk.release(canonical_key)

                if self.primary_active:
                    if key in self.primary_keys or canonical_key in self.primary_keys:
                        self.primary_active = False
                        self.primary_released.emit()
            except AttributeError:
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


class TheaterOverlay(QOpenGLWidget):
    def __init__(self):
        super().__init__()
        self.settings = QSettings("TheaterMode", "Settings")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.state = 'hidden'
        self.selection_rects = []
        self.current_rect = QRect()
        self.start_pos = None
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
        self.auto_dim_manager: "AutoDimManager | None" = None  # set by AppController
        self.anim = QPropertyAnimation(self, b"overlayOpacity")
        self.anim.setEasingCurve(QEasingCurve.InOutQuad)

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
        """Switch between 'manual' (draw-to-select) and 'auto_dim' (track active window)."""
        self.veil_mode = mode
        self.settings.setValue("veil_mode", mode)
        # Stop any running auto-dim tracking when switching away
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
        """
        True: Clicks pass through (Theater Mode)
        False: Clicks are caught by the window (Selection Mode)
        """
        hwnd = int(self.winId())
        # GWL_EXSTYLE constant
        GWL_EXSTYLE = -20
        # WS_EX_LAYERED | WS_EX_TRANSPARENT
        WS_EX_LAYERED = 0x80000
        WS_EX_TRANSPARENT = 0x20
    
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    
        if enabled:
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT)
        else:
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT)
    
        # Also keep the Qt attribute in sync
        self.setAttribute(Qt.WA_TransparentForMouseEvents, enabled)

    # Then update your state-changing methods:

    def start_selection(self):
        self.anim.stop()
        self.veil.on_hide()
        self.state = 'selecting'
        self.selection_rects = []
        self.current_rect = QRect()
        self._opacity = 0.0
        self.update_geometry_for_all_screens()
        
        # FIX: Restore TopMost flag and disable clickthrough for drawing
        winutils.set_window_topmost(int(self.winId()))
        self._set_clickthrough(False)
        
        self.setCursor(Qt.CrossCursor)
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    def start_fade(self):
        play_sound("Fade.mp3")
        self.veil.on_show()
        self.state = 'theater'
        self.setCursor(Qt.ArrowCursor)
        
        # FIX: Restore TopMost flag and enable clickthrough for manual viewing
        winutils.set_window_topmost(int(self.winId()))
        self._set_clickthrough(True)
        
        self.fade_to(self.target_opacity, self.fade_duration)

    def on_primary_pressed(self):
        if self.veil_mode == "auto_dim":
            if self.state in ("hidden", "hiding"):
                play_sound("Activate.mp3")
                self._activate_auto_dim()
            elif self.state in ("theater", "paused"):
                play_sound("Clear.mp3")
                self.state = "hiding"
                self.fade_to(0.0, 300, callback=self.reset_and_hide)
        else:
            # --- Original manual-selection behaviour ---
            if self.state in ('hidden', 'hiding'):
                play_sound("Activate.mp3")
                self.start_selection()
            elif self.state in ('theater', 'paused'):
                play_sound("Clear.mp3")
                self.state = 'hiding'
                self.fade_to(0.0, 300, callback=self.reset_and_hide)

    def _activate_auto_dim(self):
        """Start the veil immediately covering all screens; AutoDimManager punches the hole."""
        play_sound("Activate.mp3")
        QTimer.singleShot(260, lambda: play_sound("Fade.mp3"))
        self.update_geometry_for_all_screens()
        self.selection_rects = []
        self.veil.on_show()
        self.state = "theater"
        self.setCursor(Qt.ArrowCursor)
        
        # FIX: Force OS-level clickthrough immediately on startup
        self._set_clickthrough(True)
        
        self.show()
        self.raise_()
        self.fade_to(self.target_opacity, self.fade_duration)
        if self.auto_dim_manager:
            self.auto_dim_manager.start()

    def screensaver_activate(self):
        """Called by ScreensaverManager. Respects the current veil mode."""
        play_sound("Fade.mp3")
        self.update_geometry_for_all_screens()
        self.selection_rects = []
        self.veil.on_show()
        self.state = "theater"
            
        # FIX: Restore TopMost and OS clickthrough for manual fullscreen
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
            play_sound("Pause.mp3")
            self.state = 'paused'
            self.veil.on_hide()
            if self.auto_dim_manager:
                self.auto_dim_manager.stop()
            self.fade_to(0.0, self.fade_duration_pause, callback=self.hide)
        elif self.state == 'paused':
            play_sound("Unpause.mp3")
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
        
        # 1. Clear the canvas (prevents trails)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.fillRect(self.rect(), Qt.transparent)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        
        painter.setRenderHint(QPainter.Antialiasing)

        # 2. SELECTION MODE: Draw both existing and current with chosen shape
        if self.state == 'selecting':
            pen = QPen(QColor(255, 255, 255, 200), 2, Qt.DashLine)
            
            # Draw existing selections
            draw_selection_outlines(painter, self.selection_rects, self.selection_shape, pen)
            
            # Draw currently active selection
            if not self.current_rect.isNull() and not self.current_rect.isEmpty():
                draw_selection_outlines(painter, [self.current_rect], self.selection_shape, pen)
            return

        # 3. THEATER MODE
        if self.state in ('theater', 'paused'):
            self.veil.paint(
                painter, self.rect(), self.selection_rects, self._opacity, self.veil_color,
                self.selection_shape,
            )


class AutoDimManager(QObject):
    def __init__(self, overlay):
        super().__init__()
        self.overlay = overlay
        self._timer = QTimer()
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._poll)
        self._last_hwnd = 0
        self._desktop_hidden = False # Tracks if we temporarily faded out

    def start(self):
        self._last_hwnd = 0
        self._desktop_hidden = False
        self._timer.start()

    def stop(self):
        self._timer.stop()

    def _poll(self):
        hwnd, cls, _, _, _, _ = winutils.get_foreground_window_info()

        # 1. Desktop clicked: Smooth fade out, but keep the loop running
        if cls in ["Progman", "WorkerW"]:
            if not self._desktop_hidden and self.overlay.state == 'theater':
                self.overlay.fade_to(0.0, self.overlay.fade_duration_pause)
                self._desktop_hidden = True
            return

        # 2. Skip invalid windows or the overlay itself
        if not hwnd or cls in winutils.AUTODIM_EXEMPT_CLASSES or hwnd == int(self.overlay.winId()):
            return

        # 3. Valid app clicked: Smooth fade back in if we were hiding
        if self._desktop_hidden and self.overlay.state == 'theater':
            self.overlay.fade_to(self.overlay.target_opacity, self.overlay.fade_duration_pause)
            self._desktop_hidden = False

        # 4. Stack the veil behind the active app
        if hwnd != self._last_hwnd:
            self._last_hwnd = hwnd
            winutils.set_window_z_order(int(self.overlay.winId()), hwnd)


class ScreensaverManager(QObject):
    """
    Monitors system idle time via GetLastInputInfo and auto-activates the
    veil when the user has been idle for the configured duration.
    Dismissed automatically as soon as any input is detected.
    """

    def __init__(self, overlay, settings):
        super().__init__()
        self.overlay  = overlay
        self.settings = settings
        self._ss_active   = False
        self._enabled     = settings.value("screensaver_enabled", False, type=bool)
        self._timeout_ms  = settings.value("screensaver_timeout_min", 5, type=int) * 60_000

        self._timer = QTimer()
        self._timer.setInterval(8_000)        # Check every 8 s — negligible overhead
        self._timer.timeout.connect(self._check)

        if self._enabled:
            self._timer.start()

    # ── Public API ────────────────────────────────────────────────────────────

    def set_enabled(self, enabled: bool):
        self._enabled = enabled
        self.settings.setValue("screensaver_enabled", enabled)
        if enabled:
            self._timer.start()
        else:
            self._timer.stop()
            if self._ss_active:
                self._deactivate()

    def set_timeout_minutes(self, minutes: int):
        self._timeout_ms = minutes * 60_000
        self.settings.setValue("screensaver_timeout_min", minutes)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _check(self):
        idle_ms = winutils.get_idle_time_ms()
        if self._ss_active:
            # Dismiss the moment any real input is detected (< 2 s idle)
            if idle_ms < 2_000:
                self._deactivate()
        else:
            if idle_ms >= self._timeout_ms and self.overlay.state == "hidden":
                self._activate()

    def _activate(self):
        self._ss_active = True
        play_sound("Activate.mp3")
        self.overlay.screensaver_activate()

    def _deactivate(self):
        self._ss_active = False
        if self.overlay.state in ("theater", "paused", "hiding"):
            play_sound("Clear.mp3")
            self.overlay.state = "hiding"
            self.overlay.fade_to(0.0, 300, callback=self.overlay.reset_and_hide)


class AppController(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.settings = QSettings("TheaterMode", "Settings")
        self.overlay = TheaterOverlay()
        self.hotkey_mgr = HotkeyManager()
        self.cursor_locked = False

        self.hotkey_mgr.primary_pressed.connect(self.overlay.on_primary_pressed)
        self.hotkey_mgr.primary_released.connect(self.overlay.on_primary_released)
        self.hotkey_mgr.secondary_triggered.connect(self.overlay.toggle_pause)
        self.hotkey_mgr.cursorlock_triggered.connect(self.toggle_cursor_lock)
        self.hotkey_mgr.aot_triggered.connect(self.toggle_always_on_top)

        # Safety nets for app exit
        self.app.aboutToQuit.connect(winutils.release_cursor_lock)
        
        # ── Initialize MouseUnSnag logic natively ──
        self.mus_options = mus.Options()
        self.mus_options.set_unsnag(self.settings.value("unsnag_mouse", False, type=bool))
        self.mus_options.set_wrap(self.settings.value("wrap_mouse", False, type=bool))

        self.mus_logic = mus.MouseLogic(self.mus_options)
        # Hook up a callback for wrapping events
        self.mus_logic.on_wrap = lambda: play_sound("wrap.mp3")

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
        # ──────────────────────────────────────────

        # ── Desktop icon double-click toggle ──
        self._desktop_icon_toggle_enabled = self.settings.value("desktop_icon_toggle", False, type=bool)
        self._last_click_time = 0.0
        self._mouse_listener = None
        if self._desktop_icon_toggle_enabled:
            self._start_desktop_mouse_listener()
        self.app.aboutToQuit.connect(self._stop_desktop_mouse_listener)
        # ─────────────────────────────────────

        # Pass self so SettingsWindow can access everything
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

    def _start_desktop_mouse_listener(self):
        if self._mouse_listener is not None:
            return
        import time as _time

        _u32 = ctypes.WinDLL("user32", use_last_error=True)
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

        def on_click(x, y, button, pressed):
            if pressed and button == pynput_mouse.Button.left:
                now = _time.time()
                if now - self._last_click_time < DOUBLE_CLICK_THRESHOLD:
                    pt = ctypes.c_longlong((int(y) << 32) | (int(x) & 0xFFFFFFFF))
                    hwnd = _u32.WindowFromPoint(pt)
                    
                    if hwnd:
                        root = _u32.GetAncestor(hwnd, 2) # GA_ROOT = 2
                        buf = ctypes.create_unicode_buffer(256)
                        _u32.GetClassNameW(root, buf, 256)
                        cls = buf.value
                        
                        if cls in ("Progman", "WorkerW"):
                            lv_hwnd = get_desktop_listview()
                            if lv_hwnd:
                                # Send LVM_GETSELECTEDCOUNT (0x1032)
                                selected_count = _u32.SendMessageW(lv_hwnd, 0x1032, 0, 0)
                                # 0 selected items strictly means empty workspace space was double-clicked
                                if selected_count == 0:
                                    winutils.toggle_desktop_icons()
                                    play_sound("hide.mp3")
                    self._last_click_time = 0.0
                else:
                    self._last_click_time = now

        self._mouse_listener = pynput_mouse.Listener(on_click=on_click)
        self._mouse_listener.start()

    def _stop_desktop_mouse_listener(self):
        if self._mouse_listener is not None:
            self._mouse_listener.stop()
            self._mouse_listener = None

    def set_unsnag(self, state: bool):
        self.mus_options.set_unsnag(state)
        self.settings.setValue("unsnag_mouse", state)

    def set_wrap(self, state: bool):
        self.mus_options.set_wrap(state)
        self.settings.setValue("wrap_mouse", state)

    def toggle_cursor_lock(self):
        play_sound("Cursorlock.wav")
        self.cursor_locked = not self.cursor_locked
        if self.cursor_locked:
            hwnd = winutils.get_foreground_window()
            if not winutils.lock_cursor_to_window(hwnd):
                self.cursor_locked = False
        else:
            winutils.release_cursor_lock()

    def toggle_always_on_top(self):
        play_sound("AOT.wav")
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
