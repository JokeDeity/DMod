"""
gui.py – The DMod settings panel and hotkey-capture dialog.
Forced to use Fusion style to completely isolate styling from Windows system themes.
"""

import winutils
from PyQt5.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QComboBox, QSlider, QSpinBox, QColorDialog, QCheckBox, QFrame
)
from PyQt5.QtCore import Qt, pyqtSignal
from pynput import keyboard

from veil import VEIL_LABELS
from shapes import SELECTION_SHAPE_LABELS

# ── Modern Dashboard CSS ───────────────────────────────────────────────────

STYLE_SHEET = """
QWidget {
    background-color: #121318;
    color: #e2e4e9;
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 12px;
}

/* Clear background fixes for system-forced text styling */
QLabel {
    background-color: transparent;
}

/* Dashboard Cards */
QFrame#card {
    background-color: #1a1c23;
    border: 1px solid #2a2c36;
    border-radius: 5px;
}

QLabel#header {
    font-size: 20px;
    font-weight: bold;
    color: #ffffff;
    margin-bottom: 4px;
    background-color: transparent;
}

QLabel#mutedText {
    color: #8b92a5;
    font-size: 11px;
    background-color: transparent;
}

QLabel#hotkeyText {
    color: #4d8df0;
    font-family: monospace;
    font-size: 14px;
    font-weight: bold;
    background-color: transparent;
}

/* ComboBox with Arrow Indicator */
QComboBox {
    background-color: #121318;
    border: 1px solid #2a2c36;
    border-radius: 5px;
    padding: 6px 30px 6px 10px;
    color: #e2e4e9;
}
QComboBox:hover {
    border-color: #4d8df0;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 28px;
    border-left: 1px solid #2a2c36;
    border-top-right-radius: 5px;
    border-bottom-right-radius: 5px;
    background-color: #1a1c23;
}
QComboBox QAbstractItemView {
    background-color: #1a1c23;
    border: 1px solid #2a2c36;
    selection-background-color: #4d8df0;
}

/* Buttons */
QPushButton {
    background-color: #2a2c36;
    border: 1px solid #363945;
    border-radius: 6px;
    padding: 6px 14px;
    color: #e2e4e9;
    font-weight: bold;
}
QPushButton:hover {
    background-color: #313440;
    border-color: #4d8df0;
}
QPushButton:pressed {
    background-color: #121318;
    border-color: #366ac7;
}

/* Clear, High-Contrast Action Button for Admin Escalation */
QPushButton#primaryBtn {
    background-color: #b45309;
    border: 1px solid #d97706;
    color: #ffffff;
}
QPushButton#primaryBtn:hover {
    background-color: #f98817;
    border-color: #f69f1c;
}
QPushButton#primaryBtn:pressed {
    background-color: #78350f;
}

/* Bulletproof Standard Base64 Toggle Switches */
QCheckBox {
    background-color: transparent;
    spacing: 12px;
}
QCheckBox::indicator {
    width: 15px;
    height: 15px;
    border-radius: 8px;
}

/* Base Unchecked State */
QCheckBox::indicator:unchecked {
    background-color: #2a2c36;
    border: 1px solid #363945;
}

/* Unchecked Hover State: Seamless subtle background highlight + interactive accent border */
QCheckBox::indicator:unchecked:hover {
    background-color: #343745;
    border: 1px solid #4d8df0;
}

/* Base Checked State */
QCheckBox::indicator:checked {
    background-color: #4d8df0;
    border: 1px solid #4d8df0;
}

/* Checked Hover State: Lighter, vibrant blue pop to feel responsive and high-fidelity */
QCheckBox::indicator:checked:hover {
    background-color: #9fb9f8;
    border: 1px solid #9da9f8;
}

/* Opacity Slider Track & Top Bounds Cutoff Fix */
QSlider {
    background-color: transparent;
    padding-top: 5px;
    padding-bottom: 5px;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #2a2c36;
    border-radius: 1px;
}
QSlider::handle:horizontal {
    background: #4d8df0;
    width: 16px;
    height: 16px;
    margin: -5px 1px;
    border-radius: 8px;

}
QSlider::handle:horizontal:hover {
    background: #ffffff;
}
"""

# ── Hotkey Capture Dialog ───────────────────────────────────────────────────

class HotkeyCaptureDialog(QDialog):
    _modifiers_updated = pyqtSignal(str)
    _combo_finished = pyqtSignal(str)
    _cancelled = pyqtSignal()

    _MODIFIER_TOKENS = {
        keyboard.Key.ctrl_l: "<CTRL>",  keyboard.Key.ctrl_r: "<CTRL>",
        keyboard.Key.alt_l: "<ALT>",    keyboard.Key.alt_r: "<ALT>",
        keyboard.Key.shift_l: "<SHIFT>", keyboard.Key.shift_r: "<SHIFT>",
        keyboard.Key.cmd_l: "<CMD>",    keyboard.Key.cmd_r: "<CMD>",
    }

    def __init__(self, parent=None, current=""):
        super().__init__(parent)
        self.setWindowTitle("Set Hotkey")
        self.setFixedSize(420, 230)
        self.setModal(True)
        self.setStyleSheet(STYLE_SHEET)

        self.result_hotkey = None
        self._held_modifiers = []
        self._listener = None

        self._modifiers_updated.connect(self._on_modifiers_updated)
        self._combo_finished.connect(self._on_combo_finished)
        self._cancelled.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)

        prompt = QLabel("Listening for keystrokes...\nPress Esc to cancel.")
        prompt.setAlignment(Qt.AlignCenter)
        prompt.setObjectName("mutedText")
        layout.addWidget(prompt)

        self.preview = QLabel(current.upper() or " ")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet("font-size: 22px; font-weight: bold; color: #ffffff; background: #1a1c23; border: 1px solid #4d8df0; border-radius: 8px; padding: 12px;")
        layout.addWidget(self.preview)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

    def showEvent(self, event):
        super().showEvent(event)
        self._start_listener()

    def reject(self):
        self._stop_listener()
        super().reject()

    def _start_listener(self):
        self._held_modifiers = []
        def on_press(key):
            if key == keyboard.Key.esc:
                self._cancelled.emit()
                return
            if key in self._MODIFIER_TOKENS:
                token = self._MODIFIER_TOKENS[key]
                if token not in self._held_modifiers:
                    self._held_modifiers.append(token)
                    self._modifiers_updated.emit(" + ".join(self._held_modifiers))
            else:
                token = self._key_to_token(key)
                if token:
                    combo = "+".join(self._held_modifiers + [token.upper()])
                    self._combo_finished.emit(combo)

        self._listener = keyboard.Listener(on_press=on_press)
        self._listener.start()

    def _stop_listener(self):
        if self._listener:
            self._listener.stop()
            self._listener = None

    def _key_to_token(self, key):
        try:
            if hasattr(key, "char") and key.char is not None:
                return key.char
            name = str(key).replace("Key.", "")
            return f"<{name}>"
        except Exception:
            return None

    def _on_modifiers_updated(self, text):
        self.preview.setText(text)

    def _on_combo_finished(self, combo):
        self._stop_listener()
        self.result_hotkey = combo.upper()
        self.preview.setText(self.result_hotkey)
        self.accept()


# ── Main Settings Window ────────────────────────────────────────────────────

class SettingsWindow(QWidget):
    def __init__(self, controller):
        # Explicitly force Fusion style to bypass Windows theme engine contamination
        if QApplication.instance():
            QApplication.instance().setStyle('Fusion')
            
        super().__init__()
        self.controller = controller
        self.overlay = controller.overlay
        self.hotkey_mgr = controller.hotkey_mgr

        self.setWindowTitle("DMod Settings")
        self.setFixedSize(1280, 500) # Ample scale prevents text cutoff across monitors
        self.setStyleSheet(STYLE_SHEET)

        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(20)

        main_layout.addWidget(self._build_col_hotkeys(), 1)
        main_layout.addWidget(self._build_col_veil(), 1)
        main_layout.addWidget(self._build_col_audio(), 1)
        main_layout.addWidget(self._build_col_system(), 1)

    def _build_col_hotkeys(self):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("Keybinds")
        header.setObjectName("header")
        layout.addWidget(header)
        layout.addSpacing(10)

        grid = QGridLayout()
        grid.setVerticalSpacing(20)
        grid.setHorizontalSpacing(15)

        self.main_hotkey_label = QLabel(self.hotkey_mgr.primary_str.upper())
        self.pause_hotkey_label = QLabel(self.hotkey_mgr.secondary_str.upper())
        self.cursorlock_hotkey_label = QLabel(self.hotkey_mgr.cursorlock_str.upper())
        self.aot_hotkey_label = QLabel(self.hotkey_mgr.aot_str.upper())

        rows = [
            ("Veil", "Hold to select veil.\nOr press once for fullscreen.\nPress again to clear.", self.main_hotkey_label, self.hotkey_mgr.set_primary_hotkey),
            ("Pause", "Pauses and restores veil.", self.pause_hotkey_label, self.hotkey_mgr.set_secondary_hotkey),
            ("Cursor Lock", "Toggles locking the cursor \nto the active window.", self.cursorlock_hotkey_label, self.hotkey_mgr.set_cursorlock_hotkey),
            ("Always On Top", "Toggles forcing the active\nwindow to always on top.", self.aot_hotkey_label, self.hotkey_mgr.set_aot_hotkey),
        ]

        for i, (name, subtitle, value_label, setter) in enumerate(rows):
            lbl_layout = QVBoxLayout()
            lbl_layout.setSpacing(2)
            name_lbl = QLabel(name)
            name_lbl.setStyleSheet("font-weight: bold;")
            sub_lbl = QLabel(subtitle)
            sub_lbl.setObjectName("mutedText")
            lbl_layout.addWidget(name_lbl)
            lbl_layout.addWidget(sub_lbl)
            grid.addLayout(lbl_layout, i, 0)

            value_label.setObjectName("hotkeyText")
            value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            grid.addWidget(value_label, i, 1)

            btn = QPushButton("Rebind")
            btn.setFixedWidth(85)
            btn.clicked.connect(lambda _, lbl=value_label, fn=setter: self._capture_and_apply(lbl, fn))
            grid.addWidget(btn, i, 2)

        layout.addLayout(grid)
        layout.addStretch()
        return card

    def _capture_and_apply(self, label, setter):
        self.hotkey_mgr.pause()
        dlg = HotkeyCaptureDialog(self, current=label.text())
        if dlg.exec_() == QDialog.Accepted and dlg.result_hotkey:
            upper_hotkey = dlg.result_hotkey.upper()
            setter(upper_hotkey)
            label.setText(upper_hotkey)
        self.hotkey_mgr.resume()
        
    def _build_col_veil(self):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("Veil Appearance")
        header.setObjectName("header")
        layout.addWidget(header)
        layout.addSpacing(6)

# ── Veil Mode (top-level behaviour switch) ────────────────────────
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Veil Mode:"))
        self.veil_mode_combo = QComboBox()
        self.veil_mode_combo.addItem("Manual Selection",          userData="manual")
        self.veil_mode_combo.addItem("Auto-Dim (Active Window)",  userData="auto_dim")
        idx = self.veil_mode_combo.findData(self.overlay.veil_mode)
        if idx >= 0:
            self.veil_mode_combo.setCurrentIndex(idx)
        self.veil_mode_combo.currentIndexChanged.connect(self._on_veil_mode_changed)
        mode_row.addWidget(self.veil_mode_combo, 1)
        layout.addLayout(mode_row)

        mode_hint = QLabel(
            "Auto-Dim dynamically covers everything except\nthe active window.\n"
            "Manual lets you draw custom selection areas."
        )
        mode_hint.setObjectName("mutedText")
        mode_hint.setWordWrap(True)
        layout.addWidget(mode_hint)
        layout.addSpacing(10)

        grid = QGridLayout()
        grid.setVerticalSpacing(15)
        grid.setHorizontalSpacing(10)

        # Dropdowns
        grid.addWidget(QLabel("Veil Style:"), 0, 0)
        self.veil_combo = QComboBox()
        for key, label in VEIL_LABELS:
            self.veil_combo.addItem(label, userData=key)
        idx = self.veil_combo.findData(self.overlay.veil_type)
        if idx >= 0: self.veil_combo.setCurrentIndex(idx)
        self.veil_combo.currentIndexChanged.connect(self._on_veil_type_changed)
        grid.addWidget(self.veil_combo, 0, 1)

        grid.addWidget(QLabel("Selection Tool:"), 1, 0)
        self.shape_combo = QComboBox()
        for key, label in SELECTION_SHAPE_LABELS:
            self.shape_combo.addItem(label, userData=key)
        idx = self.shape_combo.findData(self.overlay.selection_shape)
        if idx >= 0: self.shape_combo.setCurrentIndex(idx)
        self.shape_combo.currentIndexChanged.connect(self._on_selection_shape_changed)
        grid.addWidget(self.shape_combo, 1, 1)

        # Base Tint & Swatch
        color_label_layout = QVBoxLayout()
        color_label_layout.setContentsMargins(0, 0, 0, 0)
        color_label_layout.addWidget(QLabel("Base Color:"))
              
        color_btn = QPushButton("Select")
        color_btn.setFixedWidth(65)
        color_btn.setFixedHeight(25)
        color_btn.clicked.connect(self._on_pick_color)
        color_label_layout.addWidget(color_btn)
        
        grid.addLayout(color_label_layout, 2, 0, Qt.AlignTop)
        
        swatch_layout = QHBoxLayout()
        self.color_preview = QLabel()
        self.color_preview.setFixedSize(96, 48) 
        self._update_color_swatch()
        
        self.color_hex = QLabel(self.overlay.veil_color.name().upper())
        self.color_hex.setStyleSheet("font-family: monospace; color: #8b92a5; font-size: 14px; font-weight: bold;")
        
        swatch_layout.addWidget(self.color_preview)
        swatch_layout.addSpacing(12)
        swatch_layout.addWidget(self.color_hex)
        swatch_layout.addStretch()
        
        grid.addLayout(swatch_layout, 2, 1, Qt.AlignTop)

        # Opacity
        grid.addWidget(QLabel("Opacity:"), 3, 0)
        op_row = QHBoxLayout()
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(1, 100)
        self.opacity_slider.setValue(int(self.overlay.target_opacity * 100))
        self.opacity_value_label = QLabel(f"{int(self.overlay.target_opacity * 100)}%")
        self.opacity_value_label.setFixedWidth(40)
        self.opacity_slider.valueChanged.connect(self._on_opacity_changed)
        op_row.addWidget(self.opacity_slider)
        op_row.addWidget(self.opacity_value_label)
        grid.addLayout(op_row, 3, 1)

        layout.addLayout(grid)
        layout.addStretch()
        
        # Fade Durations (Added)
        grid.addWidget(QLabel("Fade Speed (ms):"), 4, 0)
        self.fade_spin = QSpinBox()
        self.fade_spin.setRange(10, 50000)
        self.fade_spin.setValue(self.overlay.fade_duration)
        self.fade_spin.valueChanged.connect(self._on_fade_changed)
        grid.addWidget(self.fade_spin, 4, 1)

        grid.addWidget(QLabel("Pause Fade (ms):"), 5, 0)
        self.pause_fade_spin = QSpinBox()
        self.pause_fade_spin.setRange(10, 50000)
        self.pause_fade_spin.setValue(self.overlay.fade_duration_pause)
        self.pause_fade_spin.valueChanged.connect(self._on_pause_fade_changed)
        grid.addWidget(self.pause_fade_spin, 5, 1)
        return card        

    def _on_veil_type_changed(self, index):
        self.overlay.set_veil_type(self.veil_combo.itemData(index))

    def _on_veil_mode_changed(self, index):
        self.overlay.set_veil_mode(self.veil_mode_combo.itemData(index))

    def _on_selection_shape_changed(self, index):
        self.overlay.set_selection_shape(self.shape_combo.itemData(index))

    def _update_color_swatch(self):
        color_name = self.overlay.veil_color.name()
        self.color_preview.setStyleSheet(f"background-color: {color_name}; border-radius: 8px; border: 2px solid #363945;")
        if hasattr(self, 'color_hex'):
            self.color_hex.setText(color_name.upper())

    def _on_pick_color(self):
        color = QColorDialog.getColor(self.overlay.veil_color, self, "Select Veil Color")
        if color.isValid():
            self.overlay.veil_color = color
            self.overlay.settings.setValue("color", color.name())
            self._update_color_swatch()

    def _on_opacity_changed(self, value):
        self.opacity_value_label.setText(f"{value}%")
        self.overlay.target_opacity = value / 100.0
        self.overlay.settings.setValue("opacity", self.overlay.target_opacity)
        
    def _on_fade_changed(self, value):
        self.overlay.fade_duration = value
        self.overlay.settings.setValue("delay", value)

    def _on_pause_fade_changed(self, value):
        self.overlay.fade_duration_pause = value
        self.overlay.settings.setValue("delay_pause", value)

    def _build_col_audio(self):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("Sound Effects")
        header.setObjectName("header")
        layout.addWidget(header)
        layout.addStretch()
        
        
        sounds = [("Activate.ogg", "Activate"),  ("Fade.ogg", "Fade"),
                  ("Clear.ogg", "Clear"), ("Pause.ogg", "Pause"),
                  ("Unpause.ogg", "Unpause"), ("Cursorlock.ogg", "Cursor Lock"),
                  ("AOT.ogg", "Always on Top"), ("hide.ogg", "Icon Hider"),
                  ("wrap.ogg", "Monitor Wrap")]

        for i, (filename, label_text) in enumerate(sounds):
            chk = QCheckBox(f"Play {label_text} Sound")
            is_muted = self.controller.settings.value(f"mute_{filename}", False, type=bool)
            chk.setChecked(not is_muted)
            
            def create_callback(f):
                return lambda state: self.controller.settings.setValue(f"mute_{f}", not bool(state))
            
            chk.stateChanged.connect(create_callback(filename))
            layout.addWidget(chk)
            
            # Apply 11px spacing after each checkbox except the last
            if i < len(sounds) - 1:
                layout.addStretch()
            
        return card

    def _build_col_system(self):
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 20, 20, 20)

        header = QLabel("System Utilities")
        header.setObjectName("header")
        layout.addWidget(header)
        layout.addStretch()

        # Precise text-wrapping layout for utility toggles
        self.desktop_icons_chk = QCheckBox("Toggle Desktop Icons on Double-Click")
        self.desktop_icons_chk.setChecked(self.controller.settings.value("desktop_icon_toggle", False, type=bool))
        self.desktop_icons_chk.stateChanged.connect(lambda state: self.controller.set_desktop_icon_toggle(bool(state)))
        layout.addWidget(self.desktop_icons_chk)

        layout.addSpacing(11)

        self.unsnag_chk = QCheckBox("Unsnag Cursor from Monitor Corners")
        self.unsnag_chk.setChecked(self.controller.settings.value("unsnag_mouse", False, type=bool))
        self.unsnag_chk.stateChanged.connect(lambda state: self.controller.set_unsnag(bool(state)))
        layout.addWidget(self.unsnag_chk)

        layout.addSpacing(11)

        self.wrap_chk = QCheckBox("Wrap Cursor Around Monitors")
        self.wrap_chk.setChecked(self.controller.settings.value("wrap_mouse", False, type=bool))
        self.wrap_chk.stateChanged.connect(lambda state: self.controller.set_wrap(bool(state)))
        layout.addWidget(self.wrap_chk)
        
        layout.addSpacing(11)
        
        # Startup toggle
        self.startup_chk = QCheckBox("Run at Windows Startup")
        self.startup_chk.setChecked(winutils.is_autostart_enabled())
        self.startup_chk.stateChanged.connect(lambda state: winutils.set_autostart(bool(state)))
        layout.addWidget(self.startup_chk)
        
        layout.addStretch()

# ── Screensaver ───────────────────────────────────────────────────
        # The ONE master box enclosing the entire screensaver section
        ss_frame = QFrame()
        # Added 'QFrame' selector so these styles ONLY apply to the container, not the inputs inside it
        ss_frame.setStyleSheet("QFrame { background-color: #1E202A; border-radius: 6px; border: 1px solid #2a2c36; }")
        ss_layout = QVBoxLayout(ss_frame)
        ss_layout.setContentsMargins(12, 12, 12, 12)
        ss_layout.setSpacing(10)

        self.ss_chk = QCheckBox("Screensaver Mode")
        self.ss_chk.setChecked(self.controller.settings.value("screensaver_enabled", False, type=bool))
        self.ss_chk.stateChanged.connect(
            lambda state: self.controller.screensaver_mgr.set_enabled(bool(state))
        )
        self.ss_chk.setStyleSheet("background: transparent; border: none;")
        ss_layout.addWidget(self.ss_chk)

        # Time entry row
        ss_time_row = QHBoxLayout()
        ss_time_row.setSpacing(8)
        
        lbl_activate = QLabel("Idle time:")
        lbl_activate.setStyleSheet("background: transparent; border: none;")
        ss_time_row.addWidget(lbl_activate)

        self.ss_spin = QSpinBox()
        self.ss_spin.setRange(1, 1200000)
        self.ss_spin.setSuffix(" min")
        self.ss_spin.setValue(self.controller.settings.value("screensaver_timeout_min", 5, type=int))
        self.ss_spin.valueChanged.connect(self.controller.screensaver_mgr.set_timeout_minutes)
        # No inline styles here; it will now perfectly inherit the same look as Fade Speed
        ss_time_row.addWidget(self.ss_spin)
        ss_time_row.addStretch()
        
        ss_layout.addLayout(ss_time_row)

        ss_note = QLabel("Activates the veil after idle. Any input dismisses it.")
        ss_note.setObjectName("mutedText")
        ss_note.setWordWrap(True)
        ss_note.setStyleSheet("background: transparent; border: none;")
        ss_layout.addWidget(ss_note)

        layout.addWidget(ss_frame)
        layout.addSpacing(8)

        # Re-engineered Admin Callout
        admin_frame = QFrame()
        admin_frame.setStyleSheet("background-color: #1E202A; border-radius: 6px; border: 1px solid #2a2c36;")
        admin_layout = QVBoxLayout(admin_frame)
        admin_layout.setContentsMargins(10, 10, 10, 10)

        if winutils.is_admin():
            status = QLabel("✓ Administrator Mode Active")
            status.setStyleSheet("color: #10b981; font-weight: bold; border: none;")
            status.setAlignment(Qt.AlignCenter)
            admin_layout.addWidget(status)
        else:
            info = QLabel("Limited Mode: Always on top hotkey fails in some apps without running as admin.")
            info.setObjectName("mutedText")
            info.setWordWrap(True)
            info.setStyleSheet("border: none;")
            info.setAlignment(Qt.AlignCenter)
            admin_layout.addWidget(info)
            
            btn = QPushButton("Restart as Admin")
            btn.setObjectName("primaryBtn")
            btn.setMinimumHeight(30)
            btn.clicked.connect(self._on_relaunch_admin)
            admin_layout.addWidget(btn)

        layout.addWidget(admin_frame)
        return card

    def _on_relaunch_admin(self):
        winutils.relaunch_as_admin()
        QApplication.instance().quit()

    def closeEvent(self, event):
        event.ignore()
        self.hide()