from __future__ import annotations

import configparser
import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import win32api
import win32con
from PyQt5.QtCore import QEvent, QObject, Qt, QThread, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QKeyEvent, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSlider,
    QVBoxLayout,
    QWidget,
)

try:
    import dxcam
    DXCAM_AVAILABLE = True
except ImportError:
    DXCAM_AVAILABLE = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SETTINGS_PATH = os.path.join(BASE_DIR, "settings.ini")
LOG_PATH = os.path.join(BASE_DIR, "ambient.log")

logging.basicConfig(
    filename=LOG_PATH,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# --- Settings & Data Structures ---

@dataclass
class MonitorInfo:
    index: int
    name: str
    left: int
    top: int
    right: int
    bottom: int
    is_primary: bool

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top


@dataclass
class DisplayConfig:
    monitor_index: int
    enabled: bool = True
    source_monitor_index: int = 0
    sample_edge: str = "Auto"  # Auto, Left, Right, Top, Bottom, Full
    contrast: float = 1.0
    brightness: float = 0.0
    scale_factor: float = 0.1
    blur_amount: int = 61
    target_fps: int = 30
    always_on_top: bool = False
    fullscreen: bool = False
    falloff_strength: float = 1.6
    glow_boost: float = 1.6
    saturation_boost: float = 1.3

    def clamp(self) -> None:
        self.contrast = min(max(self.contrast, 0.0), 4.0)
        self.brightness = min(max(self.brightness, -150.0), 150.0)
        self.scale_factor = min(max(self.scale_factor, 0.01), 1.0)
        self.blur_amount = int(min(max(self.blur_amount, 1), 200))
        self.target_fps = int(min(max(self.target_fps, 1), 300))
        self.falloff_strength = min(max(self.falloff_strength, 0.3), 4.0)
        self.glow_boost = min(max(self.glow_boost, 0.5), 3.0)
        self.saturation_boost = min(max(self.saturation_boost, 0.5), 2.5)
        if self.sample_edge not in ("Auto", "Left", "Right", "Top", "Bottom", "Full"):
            self.sample_edge = "Auto"
        if self.source_monitor_index < 0:
            self.source_monitor_index = 0

    def copy_tuning_from(self, other: DisplayConfig) -> None:
        self.source_monitor_index = other.source_monitor_index
        self.sample_edge = other.sample_edge
        self.contrast = other.contrast
        self.brightness = other.brightness
        self.scale_factor = other.scale_factor
        self.blur_amount = other.blur_amount
        self.target_fps = other.target_fps
        self.always_on_top = other.always_on_top
        self.fullscreen = other.fullscreen
        self.falloff_strength = other.falloff_strength
        self.glow_boost = other.glow_boost
        self.saturation_boost = other.saturation_boost
        self.clamp()


@dataclass
class AmbientAssignment:
    target_monitor: MonitorInfo
    source_monitor: MonitorInfo
    direction: str
    source_edge: str
    near_side: str
    orientation: str
    config: DisplayConfig
    tier: int = 0
    total_tiers: int = 1


class AmbientSettings:
    def __init__(self) -> None:
        self.displays: Dict[int, DisplayConfig] = {}

    def get_config(self, monitor_index: int) -> DisplayConfig:
        if monitor_index not in self.displays:
            self.displays[monitor_index] = DisplayConfig(monitor_index=monitor_index)
        return self.displays[monitor_index]


def load_settings() -> AmbientSettings:
    settings = AmbientSettings()
    config = configparser.ConfigParser()
    try:
        if config.read(SETTINGS_PATH):
            for sec_name in config.sections():
                if sec_name.startswith("Display_"):
                    try:
                        m_idx = int(sec_name.split("_")[1])
                        sec = config[sec_name]
                        disp = settings.get_config(m_idx)
                        disp.enabled = sec.getboolean("enabled", fallback=disp.enabled)
                        disp.source_monitor_index = sec.getint("source_monitor_index", fallback=disp.source_monitor_index)
                        disp.sample_edge = sec.get("sample_edge", fallback=disp.sample_edge)
                        disp.contrast = sec.getfloat("contrast", fallback=disp.contrast)
                        disp.brightness = sec.getfloat("brightness", fallback=disp.brightness)
                        disp.scale_factor = sec.getfloat("scale_factor", fallback=disp.scale_factor)
                        disp.blur_amount = sec.getint("blur_amount", fallback=disp.blur_amount)
                        disp.target_fps = sec.getint("target_fps", fallback=disp.target_fps)
                        disp.always_on_top = sec.getboolean("always_on_top", fallback=disp.always_on_top)
                        disp.fullscreen = sec.getboolean("fullscreen", fallback=disp.fullscreen)
                        disp.falloff_strength = sec.getfloat("falloff_strength", fallback=disp.falloff_strength)
                        disp.glow_boost = sec.getfloat("glow_boost", fallback=disp.glow_boost)
                        disp.saturation_boost = sec.getfloat("saturation_boost", fallback=disp.saturation_boost)
                        disp.clamp()
                    except ValueError:
                        continue
    except Exception:
        log.exception("Failed to load settings; using defaults")
    return settings


def save_settings(settings: AmbientSettings) -> bool:
    config = configparser.ConfigParser()
    try:
        for idx, disp in settings.displays.items():
            disp.clamp()
            sec_name = f"Display_{idx}"
            config[sec_name] = {k: str(v) for k, v in asdict(disp).items()}
        with open(SETTINGS_PATH, "w") as f:
            config.write(f)
        return True
    except OSError:
        log.exception("Failed to save settings")
        return False


# --- Screen Capture & Layout Helpers ---

def list_monitors() -> List[MonitorInfo]:
    monitors: List[MonitorInfo] = []
    try:
        for idx, (hmon, _hdc, _rect) in enumerate(win32api.EnumDisplayMonitors()):
            info = win32api.GetMonitorInfo(hmon)
            l, t, r, b = info["Monitor"]
            monitors.append(
                MonitorInfo(
                    index=idx,
                    name=info.get("Device", f"Monitor {idx + 1}"),
                    left=l, top=t, right=r, bottom=b,
                    is_primary=bool(info.get("Flags", 0) & 1),
                )
            )
    except Exception:
        log.exception("Monitor enumeration failed")

    if not monitors:
        l = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
        t = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)
        w = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
        h = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
        monitors.append(MonitorInfo(0, "Virtual Desktop", l, t, l + w, t + h, True))
    return monitors


class ScreenCapturer:
    """Wraps dxcam camera creation/reuse/release.

    Two fixes vs. a naive per-monitor dxcam.create():
      * dxcam's own device/output enumeration (DXGI) isn't guaranteed to
        line up with win32's EnumDisplayMonitors() order -- especially
        with multiple GPUs, or monitors that share a resolution. This
        builds an explicit MonitorInfo -> (device_idx, output_idx)
        mapping using resolution + primary-flag matching instead of just
        assuming monitor.index == output_idx, and logs a warning when it
        has to guess.
      * Cameras are released (not just abandoned) when a monitor stops
        being used as a source, and on shutdown. Desktop Duplication only
        allows one live duplication interface per output per process, so
        an un-released camera can make a monitor silently stop producing
        frames after a source switch, a sleep/wake, or a monitor
        unplug/replug.
    """

    def __init__(self) -> None:
        self._cameras: Dict[int, Any] = {}
        self._output_map: Dict[int, tuple] = {}  # monitor.index -> (device_idx, output_idx)
        self._map_built = False

    def invalidate_output_map(self) -> None:
        """Call whenever the monitor list may have changed (e.g. after a
        refresh) so the next capture rebuilds the dxcam output mapping."""
        self._map_built = False

    def _build_output_map(self, monitors: List[MonitorInfo]) -> None:
        self._output_map = {}
        self._map_built = True
        if not DXCAM_AVAILABLE:
            return

        entries = []  # [device_idx, output_idx, width, height, is_primary]
        try:
            for line in dxcam.output_info().strip().splitlines():
                dev = int(line.split("Device[")[1].split("]")[0])
                out = int(line.split("Output[")[1].split("]")[0])
                w, h = (int(v.strip()) for v in line.split("Res:(")[1].split(")")[0].split(","))
                entries.append([dev, out, w, h, "Primary:True" in line])
        except Exception:
            log.exception("Could not parse dxcam.output_info(); falling back to index order")
            self._output_map = {m.index: (0, m.index) for m in monitors}
            return

        used = [False] * len(entries)

        def claim(predicate):
            for i, e in enumerate(entries):
                if not used[i] and predicate(e):
                    used[i] = True
                    return i
            return None

        for m in monitors:
            i = claim(lambda e: e[4] == m.is_primary and e[2] == m.width and e[3] == m.height)
            if i is None:
                i = claim(lambda e: e[2] == m.width and e[3] == m.height)
                if i is not None:
                    log.info("Matched monitor %s to a dxcam output by resolution only", m.index)
            if i is None:
                i = claim(lambda e: True)
                log.warning(
                    "Could not confidently match monitor %s (%sx%s) to a dxcam output; "
                    "guessing by enumeration order -- verify the correct monitor lights up",
                    m.index, m.width, m.height,
                )
            if i is not None:
                self._output_map[m.index] = (entries[i][0], entries[i][1])

    def capture_monitor(self, monitor: MonitorInfo, all_monitors: Optional[List[MonitorInfo]] = None) -> Optional[np.ndarray]:
        if not DXCAM_AVAILABLE:
            return None

        if not self._map_built:
            self._build_output_map(all_monitors or [monitor])

        if monitor.index not in self._cameras:
            device_idx, output_idx = self._output_map.get(monitor.index, (0, monitor.index))
            try:
                cam = dxcam.create(device_idx=device_idx, output_idx=output_idx, output_color="BGR")
                if cam is not None:
                    self._cameras[monitor.index] = cam
            except Exception:
                log.exception("Failed to create DXcam for monitor %s", monitor.index)

        cam = self._cameras.get(monitor.index)
        if cam is None:
            return None
        try:
            frame = cam.grab()
            return np.ascontiguousarray(frame) if frame is not None else None
        except Exception:
            log.exception("Capture failed for monitor %s", monitor.index)
            return None

    def release_unused(self, needed_indices: set) -> None:
        """Release cameras for monitors no longer used as a capture source."""
        for idx in list(self._cameras):
            if idx not in needed_indices:
                self._release_one(idx)

    def release_all(self) -> None:
        for idx in list(self._cameras):
            self._release_one(idx)

    def _release_one(self, idx: int) -> None:
        cam = self._cameras.pop(idx, None)
        if cam is not None:
            try:
                cam.release()
            except Exception:
                log.exception("Failed to release DXcam camera for monitor %s", idx)


NEAR_SIDE_MAP = {"left": "right", "right": "left", "top": "bottom", "bottom": "top", "full": "right"}
ORIENT_MAP = {"left": "vertical", "right": "vertical", "top": "horizontal", "bottom": "horizontal", "full": "vertical"}


def compute_assignments(monitors: List[MonitorInfo], settings: AmbientSettings) -> List[AmbientAssignment]:
    if not monitors:
        return []
    
    monitors_by_idx = {m.index: m for m in monitors}
    assignments: List[AmbientAssignment] = []

    source_groups: Dict[tuple[int, str], List[tuple[float, MonitorInfo, DisplayConfig]]] = {}

    for m in monitors:
        cfg = settings.get_config(m.index)
        if not cfg.enabled:
            continue

        s_idx = cfg.source_monitor_index if cfg.source_monitor_index in monitors_by_idx else 0
        source = monitors_by_idx[s_idx]

        sx, sy = (source.left + source.right) / 2, (source.top + source.bottom) / 2
        ox, oy = (m.left + m.right) / 2, (m.top + m.bottom) / 2
        dx, dy = ox - sx, oy - sy

        if cfg.sample_edge != "Auto":
            direction = cfg.sample_edge.lower()
        else:
            if m.index == source.index:
                direction = "full"
            else:
                direction = ("right" if dx >= 0 else "left") if abs(dx) >= abs(dy) else ("bottom" if dy >= 0 else "top")

        if direction == "full":
            assignments.append(
                AmbientAssignment(
                    target_monitor=m,
                    source_monitor=source,
                    direction="full",
                    source_edge="full",
                    near_side="right",
                    orientation="vertical",
                    config=cfg,
                )
            )
        else:
            dist = abs(dx) if direction in ("left", "right") else abs(dy)
            key = (source.index, direction)
            if key not in source_groups:
                source_groups[key] = []
            source_groups[key].append((dist, m, cfg))

    for (s_idx, direction), items in source_groups.items():
        items.sort(key=lambda x: x[0])
        total = len(items)
        source = monitors_by_idx[s_idx]
        for tier, (_dist, m, cfg) in enumerate(items):
            assignments.append(
                AmbientAssignment(
                    target_monitor=m,
                    source_monitor=source,
                    direction=direction,
                    source_edge=direction,
                    near_side=NEAR_SIDE_MAP[direction],
                    orientation=ORIENT_MAP[direction],
                    config=cfg,
                    tier=tier,
                    total_tiers=total,
                )
            )

    return assignments


# --- Image Processing & Bleed Effect ---

def odd_kernel(size: int) -> int:
    s = max(1, int(size))
    return s if s % 2 == 1 else s + 1


def adjust_contrast_brightness(image: np.ndarray, contrast: float, brightness: float) -> np.ndarray:
    if abs(contrast - 1.0) < 1e-3 and abs(brightness) < 1e-3:
        return image.astype(np.uint8)

    orig_shape = image.shape
    if image.ndim == 1:
        arr = image.reshape(1, 1, 3).astype(np.uint8)
    elif image.ndim == 2:
        arr = image.reshape(-1, 1, 3).astype(np.uint8)
    else:
        arr = image.astype(np.uint8)

    scaled = cv2.convertScaleAbs(arr, alpha=contrast, beta=0)
    hls = cv2.cvtColor(scaled, cv2.COLOR_BGR2HLS).astype(np.int16)
    hls[:, :, 1] = np.clip(hls[:, :, 1] + brightness, 0, 255)
    res = cv2.cvtColor(hls.astype(np.uint8), cv2.COLOR_HLS2BGR)

    return res.reshape(orig_shape)


def sample_edge_colors(source_frame: np.ndarray, edge: str) -> np.ndarray:
    h, w = source_frame.shape[:2]
    if edge in ("left", "right"):
        depth = max(1, int(w * 0.15))
        strip = source_frame[:, :depth] if edge == "left" else source_frame[:, w - depth :]
        return strip.mean(axis=1)
    depth = max(1, int(h * 0.15))
    strip = source_frame[:depth, :] if edge == "top" else source_frame[h - depth :, :]
    return strip.mean(axis=0)


def render_ambient_glow(
    edge_colors: np.ndarray,
    cw: int,
    ch: int,
    orientation: str,
    near_side: str,
    falloff_strength: float,
    blur_amount: int,
    glow_boost: float,
    saturation_boost: float,
    tier: int = 0,
    total_tiers: int = 1,
) -> np.ndarray:
    cw, ch = max(1, cw), max(1, ch)
    colors = np.asarray(edge_colors, dtype=np.float32)

    if colors.ndim == 1:
        band = np.tile(colors.reshape(1, 1, 3), (ch, cw, 1))
        tier_scale = 1.0 / (1.0 + tier * 0.6)
        glowed = np.clip(band * glow_boost * tier_scale, 0, 255).astype(np.uint8)
    else:
        t_start = tier / max(1, total_tiers)
        t_end = (tier + 1) / max(1, total_tiers)
        t = np.linspace(t_start, t_end, max(2, cw if orientation == "vertical" else ch), dtype=np.float32)

        if orientation == "vertical":
            near_right = (near_side == "right")
            curve = (t if near_right else (1.0 - t)) ** max(0.1, falloff_strength)
            strip = cv2.resize(colors.reshape(-1, 1, 3), (1, ch), interpolation=cv2.INTER_LINEAR)
            band = np.repeat(strip, cw, axis=1)
            fade = curve.reshape(1, cw, 1)
        else:
            near_bottom = (near_side == "bottom")
            curve = (t if near_bottom else (1.0 - t)) ** max(0.1, falloff_strength)
            strip = cv2.resize(colors.reshape(1, -1, 3), (cw, 1), interpolation=cv2.INTER_LINEAR)
            band = np.repeat(strip, ch, axis=0)
            fade = curve.reshape(ch, 1, 1)

        glowed = np.clip(band * fade * glow_boost, 0, 255).astype(np.uint8)

    if abs(saturation_boost - 1.0) >= 1e-3:
        hsv = cv2.cvtColor(glowed, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * saturation_boost, 0, 255)
        glowed = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    k = odd_kernel(blur_amount)
    return cv2.GaussianBlur(glowed, (k, k), 0)


# --- Core Engine & Display ---

class SourceCaptureThread(QThread):
    frames_ready = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, settings: AmbientSettings, parent=None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._capturer = ScreenCapturer()
        self._assignments: List[AmbientAssignment] = []
        self._all_monitors: List[MonitorInfo] = []
        self._running = False

    def set_layout(self, monitors: List[MonitorInfo], assignments: List[AmbientAssignment]) -> None:
        self._all_monitors = monitors
        self._assignments = assignments
        # The monitor list may have changed (plugged/unplugged, or a
        # refresh) -- rebuild the dxcam device/output mapping on the next
        # capture instead of trusting a possibly-stale one.
        self._capturer.invalidate_output_map()

    def release_cameras(self) -> None:
        self._capturer.release_all()

    def stop(self) -> None:
        self._running = False
        self.wait(2000)

    def run(self) -> None:
        self._running = True
        while self._running:
            if not self._assignments or not self._all_monitors:
                self.msleep(100)
                continue

            sources_needed = {a.source_monitor.index: a.source_monitor for a in self._assignments}
            self._capturer.release_unused(set(sources_needed.keys()))
            captured_frames: Dict[int, Optional[np.ndarray]] = {}

            for s_idx, source in sources_needed.items():
                captured_frames[s_idx] = self._capturer.capture_monitor(source, self._all_monitors)

            frames_to_emit = {}
            min_fps = 300

            for a in self._assignments:
                cfg = a.config
                min_fps = min(min_fps, cfg.target_fps)
                raw = captured_frames.get(a.source_monitor.index)

                if raw is not None:
                    try:
                        if a.direction == "full":
                            raw_colors = raw.reshape(-1, 3).mean(axis=0)
                        else:
                            raw_colors = sample_edge_colors(raw, a.source_edge)

                        colors = adjust_contrast_brightness(raw_colors, cfg.contrast, cfg.brightness)

                        rw = max(20, int(a.target_monitor.width * cfg.scale_factor))
                        rh = max(20, int(a.target_monitor.height * cfg.scale_factor))

                        rendered = render_ambient_glow(
                            colors, rw, rh, a.orientation, a.near_side,
                            cfg.falloff_strength, cfg.blur_amount,
                            cfg.glow_boost, cfg.saturation_boost,
                            tier=a.tier, total_tiers=a.total_tiers
                        )
                        rgb = cv2.cvtColor(rendered, cv2.COLOR_BGR2RGB)
                        h, w, ch = rgb.shape
                        frames_to_emit[a.target_monitor.index] = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888).copy()
                    except Exception as exc:
                        log.exception("Rendering failed")
                        self.error.emit(str(exc))

            if frames_to_emit:
                self.frames_ready.emit(frames_to_emit)

            interval = max(1, int(1000 / max(1, min_fps)))
            self.msleep(interval)


class AmbientDisplayWindow(QWidget):
    def __init__(self, monitor: MonitorInfo) -> None:
        super().__init__()
        self.monitor = monitor
        self.setWindowTitle(f"Ambient - {monitor.name}")
        
        margin_w = int(monitor.width * 0.05)
        margin_h = int(monitor.height * 0.05)
        self._normal_rect = (
            monitor.left + margin_w,
            monitor.top + margin_h,
            monitor.width - (2 * margin_w),
            monitor.height - (2 * margin_h),
        )
        self.setGeometry(*self._normal_rect)
        self.setWindowFlags(Qt.Window | Qt.WindowMinMaxButtonsHint | Qt.WindowCloseButtonHint)

        self.label = QLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("background-color: black;")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self._is_fullscreen = False
        self._last_pixmap: Optional[QPixmap] = None

    def changeEvent(self, event: QEvent) -> None:
        """Intercept standard OS window maximize signals and convert them to true full screen."""
        if event.type() == QEvent.WindowStateChange:
            if self.isMaximized() and not self._is_fullscreen:
                QTimer.singleShot(0, lambda: self.toggle_fullscreen(True))
        super().changeEvent(event)

    def set_frame(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        self._last_pixmap = pixmap
        self.label.setPixmap(pixmap.scaled(self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        if self._last_pixmap is not None:
            self.label.setPixmap(self._last_pixmap.scaled(self.label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        super().resizeEvent(event)

    def toggle_fullscreen(self, enable: Optional[bool] = None) -> None:
        if enable is None:
            self._is_fullscreen = not self._is_fullscreen
        else:
            self._is_fullscreen = enable

        if self._is_fullscreen:
            self.showFullScreen()
        else:
            self.showNormal()
            self.setGeometry(*self._normal_rect)

    def set_always_on_top(self, enabled: bool) -> None:
        flags = self.windowFlags()
        flags = (flags | Qt.WindowStaysOnTopHint) if enabled else (flags & ~Qt.WindowStaysOnTopHint)
        self.setWindowFlags(flags)
        self.show()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key_Space, Qt.Key_Escape):
            self.toggle_fullscreen()
        else:
            super().keyPressEvent(event)


class AmbientWindowManager(QObject):
    def __init__(self, settings: AmbientSettings) -> None:
        super().__init__()
        self.settings = settings
        self.windows: Dict[int, AmbientDisplayWindow] = {}
        self.capture_thread = SourceCaptureThread(settings)
        self.capture_thread.frames_ready.connect(self._on_frames)
        self.capture_thread.start()
        self.rebuild()

    def rebuild(self) -> None:
        monitors = list_monitors()
        assignments = compute_assignments(monitors, self.settings)

        self.capture_thread.set_layout(monitors, assignments)
        wanted = {a.target_monitor.index: a for a in assignments}

        for idx in list(self.windows):
            if idx not in wanted:
                self.windows.pop(idx).close()

        for idx, assignment in wanted.items():
            if idx not in self.windows:
                win = AmbientDisplayWindow(assignment.target_monitor)
                self.windows[idx] = win
                win.set_always_on_top(assignment.config.always_on_top)
                win.toggle_fullscreen(assignment.config.fullscreen)

    def relaunch_window(self, monitor_index: int) -> None:
        if monitor_index in self.windows:
            self.windows.pop(monitor_index).close()
        self.rebuild()

    def _on_frames(self, frames: Dict[int, QImage]) -> None:
        for idx, img in frames.items():
            if idx in self.windows:
                self.windows[idx].set_frame(img)

    def shutdown(self) -> None:
        self.capture_thread.stop()
        self.capture_thread.release_cameras()
        for win in list(self.windows.values()):
            win.close()
        self.windows.clear()


# --- Custom Per-Monitor Tab Widget ---

class DoubleSpinBoxWrapper(QWidget):
    valueChanged = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.spin = QDoubleSpinBox(self)
        self.spin.setDecimals(2)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.spin)
        self.spin.valueChanged.connect(self.valueChanged.emit)

    def setRange(self, min_v, max_v): self.spin.setRange(min_v, max_v)
    def setSingleStep(self, s): self.spin.setSingleStep(s)
    def setValue(self, v): self.spin.setValue(v)
    def blockSignals(self, b): self.spin.blockSignals(b)


class DisplayTabWidget(QWidget):
    def __init__(
        self,
        monitor: MonitorInfo,
        all_monitors: List[MonitorInfo],
        settings: AmbientSettings,
        manager: AmbientWindowManager,
        on_change_cb,
    ) -> None:
        super().__init__()
        self.monitor = monitor
        self.all_monitors = all_monitors
        self.settings = settings
        self.manager = manager
        self.config = settings.get_config(monitor.index)
        self.on_change_cb = on_change_cb
        self._updating_ui = False

        self._build_ui()
        self.sync_from_config()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        hdr_group = QGroupBox("Target & Sample Setup")
        hdr_layout = QVBoxLayout(hdr_group)
        hdr_layout.setContentsMargins(6, 6, 6, 6)
        hdr_layout.setSpacing(4)

        top_row = QHBoxLayout()
        self.enable_check = QCheckBox(f"<b>Enable Display Output</b> ({self.monitor.width}x{self.monitor.height})")
        self.enable_check.toggled.connect(self._on_enable_toggle)
        top_row.addWidget(self.enable_check)
        hdr_layout.addLayout(top_row)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(4)

        self.source_combo = QComboBox()
        for m in self.all_monitors:
            label = f"{m.name} ({m.width}x{m.height})" + (" [Primary]" if m.is_primary else "")
            self.source_combo.addItem(label, m.index)
        self.source_combo.currentIndexChanged.connect(self._on_source_change)
        form.addRow("Watches Monitor:", self.source_combo)

        self.edge_combo = QComboBox()
        self.edge_combo.addItems(["Auto", "Left", "Right", "Top", "Bottom", "Full"])
        self.edge_combo.currentTextChanged.connect(self._on_edge_change)
        form.addRow("Sample Side:", self.edge_combo)

        hdr_layout.addLayout(form)
        main_layout.addWidget(hdr_group)

        win_group = QGroupBox("Display Window Controls")
        win_layout = QHBoxLayout(win_group)
        win_layout.setContentsMargins(6, 6, 6, 6)
        win_layout.setSpacing(6)

        self.fs_btn = QPushButton("Fullscreen")
        self.fs_btn.setCheckable(True)
        self.fs_btn.toggled.connect(self._on_fs_toggled)
        win_layout.addWidget(self.fs_btn)

        self.ontop_btn = QPushButton("On Top")
        self.ontop_btn.setCheckable(True)
        self.ontop_btn.toggled.connect(self._on_ontop_toggled)
        win_layout.addWidget(self.ontop_btn)

        relaunch_btn = QPushButton("Relaunch Window")
        relaunch_btn.clicked.connect(self._on_relaunch)
        win_layout.addWidget(relaunch_btn)

        main_layout.addWidget(win_group)

        copy_group = QGroupBox("Copy Settings")
        copy_layout = QHBoxLayout(copy_group)
        copy_layout.setContentsMargins(6, 6, 6, 6)
        copy_layout.setSpacing(6)

        copy_layout.addWidget(QLabel("From:"))
        self.copy_combo = QComboBox()
        for m in self.all_monitors:
            if m.index != self.monitor.index:
                self.copy_combo.addItem(m.name, m.index)
        copy_layout.addWidget(self.copy_combo, 1)

        copy_btn = QPushButton("Copy")
        copy_btn.clicked.connect(self._on_copy_from)
        copy_layout.addWidget(copy_btn)

        apply_all_btn = QPushButton("Apply to All Tabs")
        apply_all_btn.clicked.connect(self._on_apply_to_all)
        copy_layout.addWidget(apply_all_btn)

        main_layout.addWidget(copy_group)

        tune_group = QGroupBox("Display Tuning Controls")
        tune_form = QFormLayout(tune_group)
        tune_form.setContentsMargins(6, 6, 6, 6)
        tune_form.setVerticalSpacing(4)

        self.sliders: Dict[str, Any] = {}
        self._add_slider_control(tune_form, "contrast", "Contrast", 0.0, 4.0, 0.1, is_int=False)
        self._add_slider_control(tune_form, "brightness", "Brightness", -150.0, 150.0, 1.0, is_int=False)
        self._add_slider_control(tune_form, "scale_factor", "Scale factor", 0.01, 1.0, 0.01, is_int=False)
        self._add_slider_control(tune_form, "blur_amount", "Blur amount", 1, 200, 1, is_int=True)
        self._add_slider_control(tune_form, "target_fps", "Target FPS", 1, 300, 1, is_int=True)
        self._add_slider_control(tune_form, "falloff_strength", "Falloff strength", 0.3, 4.0, 0.1, is_int=False)
        self._add_slider_control(tune_form, "glow_boost", "Glow boost", 0.5, 3.0, 0.1, is_int=False)
        self._add_slider_control(tune_form, "saturation_boost", "Saturation boost", 0.5, 2.5, 0.1, is_int=False)

        main_layout.addWidget(tune_group)

    def _add_slider_control(self, form: QFormLayout, field_name: str, label: str, min_v: float, max_v: float, step: float, is_int: bool = False):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Horizontal)
        spin = QSpinBox() if is_int else DoubleSpinBoxWrapper()

        steps = int(round((max_v - min_v) / step))
        slider.setRange(0, steps)

        if is_int:
            spin.setRange(int(min_v), int(max_v))
            spin.setSingleStep(int(step))
        else:
            spin.setRange(min_v, max_v)
            spin.setSingleStep(step)

        def val_to_pos(val: float) -> int:
            return int(round((val - min_v) / step))

        def pos_to_val(pos: int) -> float:
            v = min_v + pos * step
            return int(round(v)) if is_int else round(v, 2)

        def on_slider(pos: int):
            if self._updating_ui:
                return
            v = pos_to_val(pos)
            spin.blockSignals(True)
            spin.setValue(v)
            spin.blockSignals(False)
            setattr(self.config, field_name, v)
            self.on_change_cb(False)

        def on_spin(v):
            if self._updating_ui:
                return
            slider.blockSignals(True)
            slider.setValue(val_to_pos(float(v)))
            slider.blockSignals(False)
            setattr(self.config, field_name, v)
            self.on_change_cb(False)

        slider.valueChanged.connect(on_slider)
        spin.valueChanged.connect(on_spin)

        layout.addWidget(slider)
        layout.addWidget(spin)
        form.addRow(label, layout)

        self.sliders[field_name] = {
            "slider": slider, "spin": spin, "min_v": min_v, "step": step, "is_int": is_int
        }

    def sync_from_config(self) -> None:
        self._updating_ui = True
        try:
            self.enable_check.setChecked(self.config.enabled)
            
            s_idx = self.source_combo.findData(self.config.source_monitor_index)
            if s_idx >= 0:
                self.source_combo.setCurrentIndex(s_idx)

            self.edge_combo.setCurrentText(self.config.sample_edge)
            self.fs_btn.setChecked(self.config.fullscreen)
            self.ontop_btn.setChecked(self.config.always_on_top)

            for key, meta in self.sliders.items():
                val = getattr(self.config, key)
                min_v, step = meta["min_v"], meta["step"]
                pos = int(round((val - min_v) / step))
                meta["slider"].setValue(pos)
                meta["spin"].setValue(val)
        finally:
            self._updating_ui = False

    def _on_enable_toggle(self, checked: bool) -> None:
        if self._updating_ui: return
        self.config.enabled = checked
        self.on_change_cb(False)

    def _on_source_change(self, idx: int) -> None:
        if self._updating_ui: return
        self.config.source_monitor_index = self.source_combo.currentData()
        self.on_change_cb(False)

    def _on_edge_change(self, text: str) -> None:
        if self._updating_ui: return
        self.config.sample_edge = text
        self.on_change_cb(False)

    def _on_fs_toggled(self, checked: bool) -> None:
        if self._updating_ui: return
        self.config.fullscreen = checked
        if self.monitor.index in self.manager.windows:
            self.manager.windows[self.monitor.index].toggle_fullscreen(checked)

    def _on_ontop_toggled(self, checked: bool) -> None:
        if self._updating_ui: return
        self.config.always_on_top = checked
        if self.monitor.index in self.manager.windows:
            self.manager.windows[self.monitor.index].set_always_on_top(checked)

    def _on_relaunch(self) -> None:
        self.manager.relaunch_window(self.monitor.index)

    def _on_copy_from(self) -> None:
        source_idx = self.copy_combo.currentData()
        if source_idx is not None:
            source_cfg = self.settings.get_config(source_idx)
            self.config.copy_tuning_from(source_cfg)
            self.sync_from_config()
            self.on_change_cb(True)

    def _on_apply_to_all(self) -> None:
        for m in self.all_monitors:
            if m.index != self.monitor.index:
                target_cfg = self.settings.get_config(m.index)
                target_cfg.copy_tuning_from(self.config)
        self.on_change_cb(True)


# --- Lazy lifecycle wrapper for embedding in another app ────────────────────

class AmbientController:
    """Owns the AmbientWindowManager, but only while turned on.

    DMod (or any host app) creates one of these once and calls
    set_enabled(True/False) from a checkbox. Nothing here touches screen
    capture, spawns the capture thread, or opens any windows until the
    first set_enabled(True) -- so importing/holding this object costs
    nothing when the feature is off.
    """

    def __init__(self) -> None:
        self.settings: AmbientSettings = load_settings()
        self.manager: Optional[AmbientWindowManager] = None

    @property
    def enabled(self) -> bool:
        return self.manager is not None

    def set_enabled(self, enabled: bool) -> None:
        if enabled and self.manager is None:
            self.manager = AmbientWindowManager(self.settings)
        elif not enabled and self.manager is not None:
            self.manager.shutdown()
            self.manager = None

    def save(self) -> bool:
        return save_settings(self.settings)
