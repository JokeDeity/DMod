"""
veil.py – Pluggable veil renderers for Theater Mode.

Each VeilBase subclass owns its own animation timer / asset loading and
exposes three hooks called by TheaterOverlay:
    paint(painter, full_rect, selection_rects, opacity, color)
    on_show()   – overlay became visible; start timers / movies
    on_hide()   – overlay was hidden;    stop  timers / movies
"""

import math
import os

from PyQt5.QtCore import Qt, QTimer, QRect
from PyQt5.QtGui import QPainter, QColor, QPixmap, QMovie, QRadialGradient, QImage, QLinearGradient, QPainterPath

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ── Shared helper ─────────────────────────────────────────────────────────────

def _clear_holes(painter, selection_rects):
    """Punch transparent holes so the focused windows show through."""
    if not selection_rects:
        return
    painter.setCompositionMode(QPainter.CompositionMode_Clear)
    for rect in selection_rects:
        if not rect.isEmpty():
            painter.fillRect(rect, Qt.transparent)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)


# ── Base class ────────────────────────────────────────────────────────────────

class VeilBase:
    def __init__(self):
        self._parent = None

    def set_parent(self, widget):
        self._parent = widget

    def paint(self, painter, full_rect, selection_rects, opacity, color):
        raise NotImplementedError

    def on_show(self): pass
    def on_hide(self): pass


# ── 1. Flat Color ─────────────────────────────────────────────────────────────

class FlatColorVeil(VeilBase):
    def paint(self, painter, full_rect, selection_rects, opacity, color):
        c = QColor(color)
        c.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, c)
        _clear_holes(painter, selection_rects)


# ── 2. Waves ────────

class WavesVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._timer = QTimer()
        self._timer.setInterval(40) # ~25 fps, buttery smooth
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.012 # Gentle, drifting speed
        if self._parent:
            self._parent.update()

    def on_show(self):
        self._timer.start()

    def on_hide(self):
        self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color):
        w, h = full_rect.width(), full_rect.height()
        t = self._t

        # 1. The Concrete Base: Completely fixes any unwanted transparency.
        base_color = QColor(color)
        base_color.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base_color)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        # 2. The Liquid Curves
        for i in range(4):
            path = QPainterPath()
            wt = t + (i * 1.5)

            # Anchor off-screen to the left
            start_y = h * 0.5 + math.sin(wt * 0.8) * (h * 0.4)
            path.moveTo(-50, start_y)

            # Control Points for a smooth, organic 'S' curve
            cp1_x = w * 0.35
            cp1_y = h * 0.5 + math.cos(wt * 1.1) * (h * 0.6)

            cp2_x = w * 0.65
            cp2_y = h * 0.5 + math.sin(wt * 0.9) * (h * 0.5)

            # Anchor off-screen to the right
            end_y = h * 0.5 + math.cos(wt * 1.2) * (h * 0.4)
            path.cubicTo(cp1_x, cp1_y, cp2_x, cp2_y, w + 50, end_y)

            # Pull the shape down to the bottom corners to fill it
            path.lineTo(w + 50, h + 50)
            path.lineTo(-50, h + 50)
            path.closeSubpath()

            # Alternate between "Highlight" waves and "Shadow" waves
            if i % 2 == 0:
                # Soft light catching the crest of the wave
                grad = QLinearGradient(0, 0, 0, h)
                grad.setColorAt(0.0, QColor(255, 255, 255, 20))
                grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            else:
                # Deep shadow sinking into the trough
                grad = QLinearGradient(0, h, 0, 0)
                grad.setColorAt(0.0, QColor(0, 0, 0, 30))
                grad.setColorAt(1.0, QColor(0, 0, 0, 0))

            painter.fillPath(path, grad)

        painter.restore()
        _clear_holes(painter, selection_rects)


# ── 3 / 4. GIF-backed veils (Smoke, Jellyfish) ──────────────────

class GifVeil(VeilBase):
    # GIFs wider/taller than this are scaled-to-cover instead of tiled
    _LARGE_PX = 257

    def __init__(self, filename):
        super().__init__()
        self._path        = os.path.join(SCRIPT_DIR, filename)
        self._movie       = None
        self._last_raw    = None   # QPixmap that was last scaled
        self._last_scaled = None   # cached result
        self._last_rect   = QRect()

    def _ensure_movie(self):
        if self._movie is not None:
            return
        if not os.path.exists(self._path):
            return
        self._movie = QMovie(self._path)
        self._movie.frameChanged.connect(self._on_frame)

    def _on_frame(self, _):
        self._last_raw = None      # invalidate scale cache
        if self._parent:
            self._parent.update()

    def on_show(self):
        self._ensure_movie()
        if not self._movie:
            return
        if self._movie.state() == QMovie.NotRunning:
            self._movie.start()
        else:
            self._movie.setPaused(False)

    def on_hide(self):
        if self._movie and self._movie.state() == QMovie.Running:
            self._movie.setPaused(True)

    def paint(self, painter, full_rect, selection_rects, opacity, color):
        if not self._movie:
            # GIF file missing – fall back to a plain dark fill
            c = QColor(0, 0, 0)
            c.setAlpha(int(opacity * 255))
            painter.fillRect(full_rect, c)
            _clear_holes(painter, selection_rects)
            return

        raw = self._movie.currentPixmap()
        if raw.isNull():
            return

        # Rebuild scaled cache only when the frame or target rect changes
        if raw is not self._last_raw or full_rect != self._last_rect:
            self._last_raw  = raw
            self._last_rect = full_rect
            if raw.width() >= self._LARGE_PX or raw.height() >= self._LARGE_PX:
                self._last_scaled = raw.scaled(
                    full_rect.size(),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation
                )
            else:
                self._last_scaled = None   # use tiling

        painter.save()
        painter.setOpacity(opacity)
        if self._last_scaled:
            x = full_rect.x() + (full_rect.width()  - self._last_scaled.width())  // 2
            y = full_rect.y() + (full_rect.height() - self._last_scaled.height()) // 2
            painter.drawPixmap(x, y, self._last_scaled)
        else:
            painter.drawTiledPixmap(full_rect, raw)
        painter.restore()
        _clear_holes(painter, selection_rects)


# ── 5. Ambient Colors (aurora / neon light blobs, zero dependencies) ───────────

class AmbientColorVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t     = 0.0
        self._timer = QTimer()
        self._timer.setInterval(33)          # ~30 fps
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.033
        if self._parent:
            self._parent.update()

    def on_show(self):
        self._timer.start()

    def on_hide(self):
        self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color):
        w, h, t = full_rect.width(), full_rect.height(), self._t

        # Dark base so the colors read as light rather than as a tint
        base = QColor(8, 8, 12)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        # Four color blobs that drift independently around the screen
        blobs = [
            (math.sin(t * 0.29)        * 0.3 + 0.5,
             math.cos(t * 0.19)        * 0.3 + 0.5, QColor(80,  10, 160)),
            (math.sin(t * 0.21 + 1.5)  * 0.3 + 0.4,
             math.cos(t * 0.31 + 0.7)  * 0.3 + 0.6, QColor( 10, 130, 155)),
            (math.sin(t * 0.26 + 3.1)  * 0.3 + 0.6,
             math.cos(t * 0.16 + 2.0)  * 0.3 + 0.4, QColor(160,  10, 90)),
            (math.sin(t * 0.18 + 2.0)  * 0.3 + 0.5,
             math.cos(t * 0.23 + 1.1)  * 0.3 + 0.5, QColor( 10, 130, 130)),
        ]
        radius = int(max(w, h) * 0.72)

        # Additive blending makes overlapping blobs mix like coloured light
        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        painter.setOpacity(opacity)
        for cx_f, cy_f, c in blobs:
            cx = full_rect.x() + int(cx_f * w)
            cy = full_rect.y() + int(cy_f * h)
            grad   = QRadialGradient(cx, cy, radius)
            c_full = QColor(c); c_full.setAlpha(160)
            c_edge = QColor(c); c_edge.setAlpha(0)
            grad.setColorAt(0.0, c_full)
            grad.setColorAt(1.0, c_edge)
            painter.fillRect(full_rect, grad)
        painter.restore()

        _clear_holes(painter, selection_rects)
        
# ── 6. Dark Ambient Colors (aurora / neon light blobs, zero dependencies) ───────────

class DarkAmbientColorVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t     = 0.0
        self._timer = QTimer()
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.02
        if self._parent:
            self._parent.update()

    def on_show(self):
        self._timer.start()

    def on_hide(self):
        self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color):
        w, h, t = full_rect.width(), full_rect.height(), self._t

        # Slightly lighter background (shifted from 5,5,8 to 20,20,25)
        base = QColor(20, 20, 25)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        # Subtle saturation boost
        blobs = [
            (math.sin(t * 0.15) * 0.3 + 0.5, math.cos(t * 0.1) * 0.3 + 0.5, QColor(80, 20, 100)),
            (math.sin(t * 0.12 + 1.5) * 0.3 + 0.4, math.cos(t * 0.2 + 0.7) * 0.3 + 0.6, QColor(20, 70, 120)),
            (math.sin(t * 0.18 + 3.1) * 0.3 + 0.6, math.cos(t * 0.12 + 2.0) * 0.3 + 0.4, QColor(110, 20, 60)),
            (math.sin(t * 0.1 + 2.0) * 0.3 + 0.5, math.cos(t * 0.15 + 1.1) * 0.3 + 0.5, QColor(20, 100, 80)),
        ]
        radius = int(max(w, h) * 0.6)

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        # Increased overall opacity (0.4 -> 0.6) so it feels more tangible
        painter.setOpacity(opacity * 0.6) 
        for cx_f, cy_f, c in blobs:
            cx = full_rect.x() + int(cx_f * w)
            cy = full_rect.y() + int(cy_f * h)
            grad   = QRadialGradient(cx, cy, radius)
            # Increased internal blob alpha (100 -> 140)
            c_full = QColor(c); c_full.setAlpha(140)
            c_edge = QColor(c); c_edge.setAlpha(0)
            grad.setColorAt(0.0, c_full)
            grad.setColorAt(1.0, c_edge)
            painter.fillRect(full_rect, grad)
        painter.restore()

        _clear_holes(painter, selection_rects)

# ── Registry / factory ────────────────────────────────────────────────────────

VEIL_LABELS = [
    ("flat",           "Flat Color"),
    ("color",          "Ambient Color"),
    ("darkcolor",      "Dark Ambient"),
    ("waves",          "Waves"),
    ("smoke",          "Smoke"),
    ("energy",         "Energy"),
    ("ripples",        "Ripples"),
    ("jellyfish",      "Jellyfish"),
    ("chicks",         "Chicks"),
]

_REGISTRY = {
    "flat":            lambda: FlatColorVeil(),
    "color":           lambda: AmbientColorVeil(),
    "darkcolor":       lambda: DarkAmbientColorVeil(),
    "waves":           lambda: WavesVeil(),
    "smoke":           lambda: GifVeil("smoke.gif"),
    "energy":          lambda: GifVeil("energy.gif"),
    "ripples":         lambda: GifVeil("ripples.gif"),
    "jellyfish":       lambda: GifVeil("jellyfish.gif"),
    "chicks":          lambda: GifVeil("chicks.gif"),
}

def get_veil(key: str) -> VeilBase:
    return _REGISTRY.get(key, _REGISTRY["flat"])()