import sys
import os
import pygame
from PyQt5.QtWidgets import (QApplication, QWidget, QSystemTrayIcon, QMenu, QAction,
                             QInputDialog, QColorDialog)
from PyQt5.QtCore import Qt, QRect, QPropertyAnimation, pyqtProperty, pyqtSignal, QObject, QSettings, QEasingCurve
from PyQt5.QtGui import QPainter, QColor, QPen, QIcon, QPixmap
from pynput import keyboard
from veil import get_veil, VEIL_LABELS

# ── Sound setup ──────────────────────────────────────────────────────────────
pygame.mixer.init()
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def play_sound(filename):
    """Play an MP3 from the script's directory, non-blocking. Silently no-ops if missing."""
    path = os.path.join(SCRIPT_DIR, filename)
    try:
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────

class HotkeyManager(QObject):
    primary_pressed = pyqtSignal()
    primary_released = pyqtSignal()
    secondary_triggered = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = QSettings("TheaterMode", "Settings")
        self.listener = None
        self.primary_str = self.settings.value("primary_hotkey", "<ctrl>+<f3>")
        self.secondary_str = self.settings.value("secondary_hotkey", "<shift>+<ctrl>+<f3>")
        self.primary_active = False
        self.start_listener()

    def start_listener(self):
        if self.listener:
            self.listener.stop()

        self.primary_keys = set(keyboard.HotKey.parse(self.primary_str))
        
        def on_primary_activate():
            self.primary_active = True
            self.primary_pressed.emit()

        def on_secondary_activate():
            self.secondary_triggered.emit()

        self.primary_hk = keyboard.HotKey(keyboard.HotKey.parse(self.primary_str), on_primary_activate)
        self.secondary_hk = keyboard.HotKey(keyboard.HotKey.parse(self.secondary_str), on_secondary_activate)

        def on_press(key):
            try:
                canonical_key = self.listener.canonical(key)
                self.primary_hk.press(canonical_key)
                self.secondary_hk.press(canonical_key)
            except AttributeError:
                pass

        def on_release(key):
            try:
                canonical_key = self.listener.canonical(key)
                self.primary_hk.release(canonical_key)
                self.secondary_hk.release(canonical_key)

                if self.primary_active:
                    # If any key making up the primary combo is released, trigger the release event
                    if key in self.primary_keys or canonical_key in self.primary_keys:
                        self.primary_active = False
                        self.primary_released.emit()
            except AttributeError:
                pass

        self.listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.listener.start()

    def set_primary_hotkey(self, primary):
        self.primary_str = primary
        self.settings.setValue("primary_hotkey", primary)
        self.start_listener()

    def set_secondary_hotkey(self, secondary):
        self.secondary_str = secondary
        self.settings.setValue("secondary_hotkey", secondary)
        self.start_listener()


class TheaterOverlay(QWidget):
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

        self.anim = QPropertyAnimation(self, b"overlayOpacity")
        self.anim.setEasingCurve(QEasingCurve.InOutQuad)

    def set_veil_type(self, new_type):
        """Swaps the active veil renderer."""
        if self.state != 'hidden':
            self.veil.on_hide()
            
        self.veil_type = new_type
        self.settings.setValue("veil_type", new_type)
        self.veil = get_veil(new_type)
        self.veil.set_parent(self)
        
        if self.state != 'hidden':
            self.veil.on_show()
        self.update()

    def get_opacity(self):
        return self._opacity

    def set_opacity(self, value):
        self._opacity = value
        self.update()

    overlayOpacity = pyqtProperty(float, get_opacity, set_opacity)

    def update_geometry_for_all_screens(self):
        rect = QRect()
        for screen in QApplication.screens():
            rect = rect.united(screen.geometry())
        self.setGeometry(rect)

    def on_primary_pressed(self):
        if self.state == 'hidden':
            play_sound("Activate.mp3")
            self.start_selection()
        elif self.state in ('theater', 'paused'):
            play_sound("Clear.mp3")
            self.state = 'hiding' # Prevent the upcoming release from triggering a fade-in
            self.fade_to(0.0, 300, callback=self.reset_and_hide)

    def on_primary_released(self):
        if self.state == 'selecting':
            self.start_fade()

    def toggle_pause(self):
        if self.state == 'theater':
            play_sound("Pause.mp3")
            self.state = 'paused'
            self.veil.on_hide()
            self.fade_to(0.0, self.fade_duration_pause, callback=self.hide)
        elif self.state == 'paused':
            play_sound("Unpause.mp3")
            self.state = 'theater'
            self.show()
            self.veil.on_show()
            self.fade_to(self.target_opacity, self.fade_duration_pause)

    def fade_to(self, target, duration, callback=None):
        self.anim.stop()
        try:
            self.anim.finished.disconnect()
        except Exception:
            pass

        self.anim.setDuration(duration)
        self.anim.setStartValue(self._opacity)
        self.anim.setEndValue(target)

        if callback:
            self.anim.finished.connect(callback)

        self.anim.start()

    def start_selection(self):
        self.update_geometry_for_all_screens()
        self.state = 'selecting'
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setCursor(Qt.CrossCursor)
        self._opacity = 0.0
        self.selection_rects = []
        self.current_rect = QRect()
        self.show()
        self.raise_()
        self.activateWindow()
        self.update()

    def reset_and_hide(self):
        self.veil.on_hide()
        self.state = 'hidden'
        self.selection_rects = []
        self.current_rect = QRect()
        self.hide()

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

    def start_fade(self):
        play_sound("Fade.mp3")
        self.veil.on_show()
        self.state = 'theater'
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.fade_to(self.target_opacity, self.fade_duration)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        if self.state == 'selecting':
            painter.fillRect(self.rect(), QColor(0, 0, 0, 80))
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            
            for rect in self.selection_rects:
                painter.fillRect(rect, Qt.transparent)
            if not self.current_rect.isNull():
                painter.fillRect(self.current_rect, Qt.transparent)
                
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            pen = QPen(QColor(255, 255, 255), 2, Qt.DashLine)
            painter.setPen(pen)
            
            for rect in self.selection_rects:
                painter.drawRect(rect)
            if not self.current_rect.isNull():
                painter.drawRect(self.current_rect)
                
        elif self.state in ('theater', 'paused'):
            self.veil.paint(painter, self.rect(), self.selection_rects, self._opacity, self.veil_color)


class AppController(QObject):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.overlay = TheaterOverlay()
        self.hotkey_mgr = HotkeyManager()

        self.hotkey_mgr.primary_pressed.connect(self.overlay.on_primary_pressed)
        self.hotkey_mgr.primary_released.connect(self.overlay.on_primary_released)
        self.hotkey_mgr.secondary_triggered.connect(self.overlay.toggle_pause)

        self.setup_tray()

    def setup_tray(self):
        self.tray_icon = QSystemTrayIcon()
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor(100, 100, 100))
        painter.drawRoundedRect(2, 2, 28, 28, 5, 5)
        painter.setCompositionMode(QPainter.CompositionMode_Clear)
        painter.drawRect(8, 8, 16, 16)
        painter.end()

        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("Theater Mode")

        self.menu = QMenu()
        self.menu.addAction("Set Main Hotkey...", self.change_main_hotkey)
        self.menu.addAction("Set Pause Hotkey...", self.change_pause_hotkey)
        
        veil_menu = self.menu.addMenu("Veil Type")
        for key, label in VEIL_LABELS:
            action = veil_menu.addAction(label)
            action.triggered.connect(lambda checked, k=key: self.overlay.set_veil_type(k))

        self.menu.addSeparator()
        self.menu.addAction("Set Opacity...", self.change_opacity)
        self.menu.addAction("Set Veil Color...", self.change_color)
        self.menu.addAction("Set Fade Delay...", self.change_delay)
        self.menu.addAction("Set Pause Fade Delay...", self.change_delay_pause)
        self.menu.addSeparator()
        self.menu.addAction("Exit", self.app.quit)

        self.tray_icon.setContextMenu(self.menu)
        self.tray_icon.show()

    def change_main_hotkey(self):
        text, ok = QInputDialog.getText(None, "Main Hotkey", "Enter primary hotkey:", text=self.hotkey_mgr.primary_str)
        if ok and text:
            self.hotkey_mgr.set_primary_hotkey(text.lower().strip())

    def change_pause_hotkey(self):
        text, ok = QInputDialog.getText(None, "Pause Hotkey", "Enter pause hotkey:", text=self.hotkey_mgr.secondary_str)
        if ok and text:
            self.hotkey_mgr.set_secondary_hotkey(text.lower().strip())

    def change_opacity(self):
        val, ok = QInputDialog.getInt(None, "Opacity", "Percentage (10-100):", int(self.overlay.target_opacity * 100), 10, 100)
        if ok:
            self.overlay.target_opacity = val / 100.0
            self.overlay.settings.setValue("opacity", self.overlay.target_opacity)

    def change_color(self):
        text, ok = QInputDialog.getText(None, "Color", "Hex Color (e.g., #000000):", text=self.overlay.veil_color.name())
        if ok and text:
            color = QColor(text.strip())
            if color.isValid():
                self.overlay.veil_color = color
                self.overlay.settings.setValue("color", color.name())

    def change_delay(self):
        val, ok = QInputDialog.getInt(None, "Fade Delay", "Milliseconds:", self.overlay.fade_duration, 0, 10000)
        if ok:
            self.overlay.fade_duration = val
            self.overlay.settings.setValue("delay", val)

    def change_delay_pause(self):
        val, ok = QInputDialog.getInt(None, "Pause Fade Delay", "Milliseconds:", self.overlay.fade_duration_pause, 0, 10000)
        if ok:
            self.overlay.fade_duration_pause = val
            self.overlay.settings.setValue("delay_pause", val)


if __name__ == '__main__':
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    controller = AppController(app)
    sys.exit(app.exec_())