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
import random

from veils_base import VeilBase, _clear_holes
from gpu_veils import ShaderWavesVeil
from PyQt5.QtCore import Qt, QTimer, QRect, QPointF
from PyQt5.QtGui import QPainter, QColor, QImage, QPixmap, QMovie, QRadialGradient, QLinearGradient, QPainterPath, QFont

# Ensure shapes.py exists in the same directory as this file
try:
    from shapes import clear_selection_holes
except ImportError:
    # Fallback definition if clear_selection_holes is missing to prevent crash
    def clear_selection_holes(painter, selection_rects, selection_shape):
        pass

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Shared optimizations ──────────────────────────────────────────────────────

# Pre-compute frequently used constants
TWO_PI = math.pi * 2
HALF_PI = math.pi / 2

def _clear_holes(painter, selection_rects, selection_shape="rectangle"):
    """Punch transparent holes so the focused windows show through."""
    clear_selection_holes(painter, selection_rects, selection_shape)


# ── Base class ──────────────────────────────────────────────────────────────

class VeilBase:
    def __init__(self):
        self._parent = None

    def set_parent(self, widget):
        self._parent = widget

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        raise NotImplementedError

    def on_show(self): pass
    def on_hide(self): pass


# ── 1. Flat Color ─────────────────────────────────────────────────────────

class FlatColorVeil(VeilBase):
    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        c = QColor(color)
        c.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, c)
        _clear_holes(painter, selection_rects, selection_shape)


# ── 2. Waves ──────────────────────────────────────────────────────────────

class WavesVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._timer = QTimer()
        self._timer.setInterval(40)  # Increased from 33 to reduce CPU
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.015
        if self._parent:
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        w, h = full_rect.width(), full_rect.height()
        base = QColor(14, 12, 18)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)  # Disable for perf
        painter.setOpacity(opacity * 0.45)
        
        t = self._t
        c1 = QColor(color) if color != "#000000" else QColor(70, 130, 180)
        c2 = c1.darker(180)
        
        for j in range(3):
            path = QPainterPath()
            path.moveTo(0, h)
            step = 50
            for x in range(0, w + step, step):
                y = (h * 0.5) + math.sin(x * 0.0015 + t + j) * (h * 0.22) + math.cos(x * 0.003 - t * 0.8 + j * 1.5) * (h * 0.14)
                path.lineTo(x, y)
            path.lineTo(w, h)
            path.closeSubpath()

            grad = QLinearGradient(0, 0, w, h)
            grad.setColorAt(0.0, c1)
            grad.setColorAt(1.0, c2)
            painter.fillPath(path, grad)

        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 3. Waves 2 ────────────────────────────────────────────────────────────

class Waves2Veil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._timer = QTimer()
        self._timer.setInterval(50)  # Increased from 40 for better perf
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.012
        if self._parent:
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        w, h = full_rect.width(), full_rect.height()
        t = self._t

        base_color = QColor(color)
        base_color.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base_color)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

        for i in range(4):
            path = QPainterPath()
            wt = t + (i * 1.5)

            start_y = h * 0.5 + math.sin(wt * 0.8) * (h * 0.4)
            path.moveTo(-50, start_y)

            cp1_x = w * 0.35
            cp1_y = h * 0.5 + math.cos(wt * 1.1) * (h * 0.6)

            cp2_x = w * 0.65
            cp2_y = h * 0.5 + math.sin(wt * 0.9) * (h * 0.5)

            end_y = h * 0.5 + math.cos(wt * 1.2) * (h * 0.4)
            path.cubicTo(cp1_x, cp1_y, cp2_x, cp2_y, w + 50, end_y)

            path.lineTo(w + 50, h + 50)
            path.lineTo(-50, h + 50)
            path.closeSubpath()

            if i % 2 == 0:
                grad = QLinearGradient(0, 0, 0, h)
                grad.setColorAt(0.0, QColor(255, 255, 255, 20))
                grad.setColorAt(1.0, QColor(255, 255, 255, 0))
            else:
                grad = QLinearGradient(0, h, 0, 0)
                grad.setColorAt(0.0, QColor(0, 0, 0, 30))
                grad.setColorAt(1.0, QColor(0, 0, 0, 0))

            painter.fillPath(path, grad)

        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 4. Line Waves ─────────────────────────────────────────────────────────

class LineWavesVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._timer = QTimer()
        self._timer.setInterval(40)  # Increased from 33
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.012
        if self._parent:
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        w, h = full_rect.width(), full_rect.height()
        base = QColor(10, 11, 16)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode_Plus)
        
        aurora_color = QColor(color) if color != "#000000" else QColor(0, 210, 255)
        t = self._t
        
        for i in range(3):
            path = QPainterPath()
            step = 60
            for x in range(0, w + step, step):
                wave1 = math.sin(x * 0.002 + t + i * 1.3) * (h * 0.15)
                wave2 = math.cos(x * 0.005 - t * 0.8 + i) * (h * 0.08)
                y = h * (0.3 + i * 0.15) + wave1 + wave2
                
                if x == 0:
                    path.moveTo(x, y)
                else:
                    path.lineTo(x, y)
                    
            path.lineTo(w, h)
            
            grad = QLinearGradient(0, h * 0.2, 0, h)
            c1 = QColor(aurora_color)
            c1.setAlpha(int(opacity * 90))
            
            c2 = QColor(aurora_color)
            c2.setAlpha(0)
            
            grad.setColorAt(0.0, c1)
            grad.setColorAt(1.0, c2)
            
            p_stroke = painter.pen()
            p_stroke.setColor(c1)
            p_stroke.setWidth(3)
            painter.setPen(p_stroke)
            painter.drawPath(path)
            
        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 5. Ambient Colors ─────────────────────────────────────────────────────

import math
from PyQt5.QtCore import QTimer, QSize
from PyQt5.QtGui import QColor, QRadialGradient, QPainter, QImage
from veils_base import VeilBase, _clear_holes

class AmbientColorVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._timer = QTimer()
        self._timer.setInterval(70)  # Low overhead frame pace
        self._timer.timeout.connect(self._tick)
        self._buffer = None          # Persistent reuse buffer
        self._buf_size = QSize(0, 0)

    def _tick(self):
        self._t += 0.033
        if self._parent:
            self._parent.update()

    def on_show(self): 
        self._timer.start()
        
    def on_hide(self): 
        self._timer.stop()
        self._buffer = None          # Drop allocation when hidden
        self._buf_size = QSize(0, 0)

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        w, h, t = full_rect.width(), full_rect.height(), self._t
        if w <= 0 or h <= 0:
            return

        # 1. Downscale the buffer resolution (15% scale factor)
        # This cuts pixel rendering overhead by over 95% on the CPU thread
        scale = 0.15
        buf_w = max(16, int(w * scale))
        buf_h = max(16, int(h * scale))
        target_size = QSize(buf_w, buf_h)

        # Manage/Reuse the low-res offscreen surface
        if self._buffer is None or self._buf_size != target_size:
            self._buffer = QImage(target_size, QImage.Format_ARGB32_Premultiplied)
            self._buf_size = target_size
        
        self._buffer.fill(QColor(0, 0, 0, 0))

        side_painter = QPainter(self._buffer)
        side_painter.setRenderHint(QPainter.Antialiasing, False)

        # 2. Paint base theme canvas into the tiny buffer
        base = QColor(8, 8, 12, 255)
        side_painter.fillRect(0, 0, buf_w, buf_h, base)

        # 3. Render additive glow blobs relative to the low-res coordinate space
        side_painter.setCompositionMode(QPainter.CompositionMode_Plus)
        
        blobs = [
            (math.sin(t * 0.29) * 0.3 + 0.5, math.cos(t * 0.19) * 0.3 + 0.5, QColor(80, 10, 160)),
            (math.sin(t * 0.21 + 1.5) * 0.3 + 0.4, math.cos(t * 0.31 + 0.7) * 0.3 + 0.6, QColor(10, 130, 155)),
            (math.sin(t * 0.26 + 3.1) * 0.3 + 0.6, math.cos(t * 0.16 + 2.0) * 0.3 + 0.4, QColor(160, 10, 90)),
            (math.sin(t * 0.18 + 2.0) * 0.3 + 0.5, math.cos(t * 0.23 + 1.1) * 0.3 + 0.5, QColor(10, 130, 130)),
        ]
        radius = int(max(buf_w, buf_h) * 0.72)
        target_alpha = 160

        for cx_f, cy_f, c in blobs:
            cx = int(cx_f * buf_w)
            cy = int(cy_f * buf_h)
            grad = QRadialGradient(cx, cy, radius)
            
            c_full = QColor(c)
            c_full.setAlpha(target_alpha)
            
            c_edge = QColor(c)
            c_edge.setAlpha(0)
            
            grad.setColorAt(0.0, c_full)
            grad.setColorAt(1.0, c_edge)
            side_painter.fillRect(0, 0, buf_w, buf_h, grad)
            
        side_painter.end()

        # 4. Upscale the pre-blended buffer to screen coordinates using hardware acceleration
        painter.save()
        painter.setOpacity(opacity)
        
        # Forces smooth bilinear interpolation across the screen canvas
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.drawImage(full_rect, self._buffer)
        painter.restore()
        
        _clear_holes(painter, selection_rects, selection_shape)


# ── 6. Dark Ambient Colors ────────────────────────────────────────────────

class DarkAmbientColorVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._timer = QTimer()
        self._timer.setInterval(80)  # Increased from 60 for better perf
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.02
        if self._parent:
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        w, h, t = full_rect.width(), full_rect.height(), self._t

        base = QColor(20, 20, 25)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        blobs = [
            (math.sin(t * 0.15) * 0.3 + 0.5, math.cos(t * 0.1) * 0.3 + 0.5, QColor(80, 20, 100)),
            (math.sin(t * 0.12 + 1.5) * 0.3 + 0.4, math.cos(t * 0.2 + 0.7) * 0.3 + 0.6, QColor(20, 70, 120)),
            (math.sin(t * 0.18 + 3.1) * 0.3 + 0.6, math.cos(t * 0.12 + 2.0) * 0.3 + 0.4, QColor(110, 20, 60)),
            (math.sin(t * 0.1 * 2.0) * 0.3 + 0.5, math.cos(t * 0.15 + 1.1) * 0.3 + 0.5, QColor(20, 100, 80)),
        ]
        radius = int(max(w, h) * 0.6)

        painter.save()
        painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
        painter.setOpacity(opacity * 0.6)
        for cx_f, cy_f, c in blobs:
            cx = full_rect.x() + int(cx_f * w)
            cy = full_rect.y() + int(cy_f * h)
            grad = QRadialGradient(cx, cy, radius)
            c_full = QColor(c)
            c_full.setAlpha(140)
            c_edge = QColor(c)
            c_edge.setAlpha(0)
            grad.setColorAt(0.0, c_full)
            grad.setColorAt(1.0, c_edge)
            painter.fillRect(full_rect, grad)
        painter.restore()

        _clear_holes(painter, selection_rects, selection_shape)


# ── 7. Cosmic Starfield ──────────────────────────────────────────────────

class StarfieldVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._timer = QTimer()
        self._timer.setInterval(40)  # Increased from 30
        self._timer.timeout.connect(self._tick)
        self._stars = []

    def _tick(self):
        if not self._stars and self._parent:
            w, h = self._parent.width(), self._parent.height()
            self._stars = [
                [random.randint(0, w), random.randint(0, h), random.uniform(0.3, 1.8), random.uniform(2.0, 5.5), random.uniform(0.4, 1.0)]
                for _ in range(120)  # Reduced from 150
            ]

        if self._parent:
            w, h = self._parent.width(), self._parent.height()
            for s in self._stars:
                s[1] += s[2] * 0.65
                s[4] += random.uniform(-0.04, 0.04)
                s[4] = max(0.2, min(1.0, s[4]))
                if s[1] > h:
                    s[1] = 0
                    s[0] = random.randint(0, w)
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        base = QColor(10, 10, 15)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        for s in self._stars:
            c = QColor(245, 245, 255)
            c.setAlpha(int(s[4] * opacity * 255))
            painter.setPen(Qt.NoPen)
            painter.setBrush(c)
            size = int(s[3])
            painter.drawEllipse(int(s[0] - size / 2), int(s[1] - size / 2), size, size)
        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 8. Geometric Constellation Link ───────────────────────────────────────

class ConstellationVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._timer = QTimer()
        self._timer.setInterval(40)  # Increased from 33
        self._timer.timeout.connect(self._tick)
        self._nodes = []

    def _tick(self):
        if not self._nodes and self._parent:
            w, h = self._parent.width(), self._parent.height()
            self._nodes = [[random.uniform(0, w), random.uniform(0, h), random.uniform(-1.0, 1.0), random.uniform(-1.0, 1.0)] for _ in range(50)]  # Reduced from 60
            
        if self._parent:
            w, h = self._parent.width(), self._parent.height()
            for n in self._nodes:
                n[0] += n[2] * 0.8
                n[1] += n[3] * 0.8
                if n[0] < 0 or n[0] > w: n[2] *= -1
                if n[1] < 0 or n[1] > h: n[3] *= -1
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        base = QColor(12, 14, 20)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        
        n_color = QColor(245, 245, 255)
        p = painter.pen()
        
        # Reduced connection distance to reduce line draws
        max_dist = 160  # Reduced from 190
        for i in range(len(self._nodes)):
            for j in range(i + 1, len(self._nodes)):
                n1, n2 = self._nodes[i], self._nodes[j]
                dx = n2[0] - n1[0]
                dy = n2[1] - n1[1]
                dist_sq = dx * dx + dy * dy
                if dist_sq < max_dist * max_dist:
                    dist = math.sqrt(dist_sq)
                    alpha = int((1.0 - (dist / max_dist)) * opacity * 100)
                    p.setColor(QColor(n_color.red(), n_color.green(), n_color.blue(), alpha))
                    p.setWidth(2)
                    painter.setPen(p)
                    painter.drawLine(int(n1[0]), int(n1[1]), int(n2[0]), int(n2[1]))
                    
        painter.setPen(Qt.NoPen)
        for n in self._nodes:
            c = QColor(n_color)
            c.setAlpha(int(opacity * 190))
            painter.setBrush(c)
            painter.drawEllipse(int(n[0] - 3), int(n[1] - 3), 6, 6)
            
        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 9. Cyber Rain ────────────────────────────────────────────────────────

class CyberRainVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._timer = QTimer()
        self._timer.setInterval(70)  # Increased from 50 to drop CPU usage
        self._timer.timeout.connect(self._tick)
        self._streams = []

    def _tick(self):
        if not self._streams and self._parent:
            cols = max(10, self._parent.width() // 50)  # Reduced density slightly
            self._streams = [
                [i * 50, random.randint(-400, 0), random.randint(4, 12), random.randint(5, 15)]
                for i in range(cols)
            ]

        if self._parent:
            h = self._parent.height()
            for s in self._streams:
                s[1] += s[2]
                if s[1] > h + 200:
                    s[1] = random.randint(-300, -50)
                    s[2] = random.randint(4, 12)
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        base = QColor(12, 14, 16)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        
        stream_color = QColor(color) if color != "#000000" else QColor(0, 255, 180)
        
        for s in self._streams:
            cx, cy, _, length = s
            for k in range(length):
                tick_y = cy - (k * 15)
                if 0 <= tick_y <= full_rect.height():
                    grad_alpha = int((1.0 - (k / length)) * opacity * 220)
                    c = QColor(stream_color)
                    c.setAlpha(grad_alpha)
                    # Swapped expensive drawRoundedRect for fillRect
                    painter.fillRect(cx, tick_y, 4, 10, c)
                    
        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 10. Matrix Digital Rain ──────────────────────────────────────────────

class MatrixRainVeil(VeilBase):
    """
    Hybrid Grid-Bake approach: Smooth float-positioned white heads slide over 
    an offscreen grid-locked green trail buffer. Includes active trail mutations 
    to remove rigid patterns and drop GPU/CPU utilization to baseline levels.
    """
    _CW = 28   # column width / horizontal char step
    _CH = 18   # row height  / vertical   char step
    CHARS = (
        "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        "!@#$%^&*()_+-=[]{}|;:,.<>?"
        "ÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÐÑÒÓÔÕÖØÙÚÛÜÝÞß"
        "ΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ"
        "АБВГДЕЖЗИКЛМНОПРСТУФХЦЧШЩЭЮЯ"
        "¢£¥§©®°±µ¶"
    )

    def __init__(self):
        super().__init__()
        self._timer = QTimer()
        self._timer.setInterval(33)      # Smooth ~30 FPS cinematic cadence
        self._timer.timeout.connect(self._tick)
        self._streams = []
        self._font = QFont("Courier New", 13, QFont.Bold)
        self._buf = None                 # Persistent offscreen green trail layer
        self._buf_sz = QSize(0, 0)
        self._m_color = QColor(30, 255, 40)
        self._head_color = QColor(245, 255, 245) # Bright gleaming white head
        self._last_color = None

    def _ensure_buf(self, size):
        if self._buf is None or self._buf_sz != size:
            self._buf = QImage(size, QImage.Format_ARGB32_Premultiplied)
            self._buf.fill(QColor(5, 8, 5))
            self._buf_sz = size
            self._streams = []

    def _init_streams(self, w):
        cols = max(10, w // self._CW)
        self._streams = [
            {
                "x": i * self._CW, 
                "y": random.uniform(-600.0, 0.0),
                "speed": random.uniform(3.5, 7.5),
                "last_spawned_row": -999
            }
            for i in range(cols)
        ]
        # Set initial row boundary tracking sync
        for s in self._streams:
            s["last_spawned_row"] = int(s["y"] // self._CH)

    def on_show(self): 
        self._timer.start()
    
    def on_hide(self):
        self._timer.stop()
        self._buf = None               
        self._buf_sz = QSize(0, 0)
        self._streams = []

    def _tick(self):
        parent = self._parent
        if not parent:
            return
        size = parent.size()
        self._ensure_buf(size)

        if not self._streams:
            self._init_streams(size.width())

        h = size.height()

        p = QPainter(self._buf)
        p.setFont(self._font)

        # Uniformly blend down old trails inside the memory buffer
        p.fillRect(self._buf.rect(), QColor(5, 8, 5, 22))

        for s in self._streams:
            # Advance the head smoothly via pixel float velocity
            s["y"] += s["speed"]
            current_row = int(s["y"] // self._CH)

            # When the head crosses into a new grid cell, stamp a stable green trail char behind it
            if current_row > s["last_spawned_row"]:
                col_seed = s["x"] // self._CW
                for r in range(s["last_spawned_row"] + 1, current_row + 1):
                    hy = r * self._CH
                    if 0 <= hy <= h + self._CH:
                        p.setPen(self._m_color)
                        char_idx = (r + col_seed) % len(self.CHARS)
                        p.drawText(s["x"], hy, self.CHARS[char_idx])
                s["last_spawned_row"] = current_row

            # Organic Mutation: 6% chance per frame to randomly glitch an active trail glyph
            if random.random() < 0.06:
                glitch_row = current_row - random.randint(1, 20)
                glitch_hy = glitch_row * self._CH
                if 0 <= glitch_hy <= h:
                    p.setPen(self._m_color)
                    p.drawText(s["x"], glitch_hy, random.choice(self.CHARS))

            # Recycle stream safely below visual range
            if s["y"] > h + 250:
                s["y"] = random.uniform(-400.0, -50.0)
                s["speed"] = random.uniform(3.5, 7.5)
                s["last_spawned_row"] = int(s["y"] // self._CH)

        p.end()
        parent.update()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        if color != self._last_color:
            self._last_color = color
            self._m_color = QColor(color) if color != "#000000" else QColor(30, 255, 40)
            self._buf = None   

        if self._buf and not self._buf.isNull():
            painter.save()
            painter.setOpacity(opacity)
            
            # 1. Blit pre-rendered grid-locked trails instantly via hardware acceleration
            painter.drawImage(full_rect.topLeft(), self._buf)
            
            # 2. Layer smooth float-positioned white heads over the background
            painter.setFont(self._font)
            h = full_rect.height()
            
            for s in self._streams:
                sy = s["y"]
                if 0 <= sy <= h + self._CH:
                    painter.setPen(self._head_color)
                    current_row = int(sy // self._CH)
                    col_seed = s["x"] // self._CW
                    char_idx = (current_row + col_seed) % len(self.CHARS)
                    painter.drawText(int(s["x"]), int(sy), self.CHARS[char_idx])
                    
            painter.restore()
        else:
            painter.fillRect(full_rect, QColor(5, 8, 5, int(opacity * 255)))

        _clear_holes(painter, selection_rects, selection_shape)


# ── 11. Retro CRT Scanlines ──────────────────────────────────────────────

class RetroCrtVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._offset = 0
        self._timer = QTimer()
        self._timer.setInterval(60)  # Increased from 50
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._offset = (self._offset + 1) % 6
        if self._parent:
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        base = QColor(10, 11, 10)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        p = painter.pen()
        
        p.setColor(QColor(245, 245, 255, int(opacity * 150)))
        p.setWidth(2)
        painter.setPen(p)
        
        for y in range(self._offset, full_rect.height(), 4):
            painter.drawLine(0, y, full_rect.width(), y)
            
        v_grad = QRadialGradient(full_rect.center(), max(full_rect.width(), full_rect.height()) * 0.75)
        v_grad.setColorAt(0.0, QColor(0, 0, 0, 0))
        v_grad.setColorAt(1.0, QColor(0, 0, 0, int(opacity * 200)))
        painter.fillRect(full_rect, v_grad)
        
        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 12. VHS Static Glitch ────────────────────────────────────────────────

class VhsGlitchVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._timer = QTimer()
        self._timer.setInterval(80)  # Increased from 60
        self._timer.timeout.connect(self._tick)
        self._glitches = []

    def _tick(self):
        if self._parent:
            self._glitches = []
            if random.random() < 0.4:
                h = self._parent.height()
                for _ in range(random.randint(1, 3)):
                    self._glitches.append([random.randint(0, h), random.randint(5, 35), random.randint(10, 80)])
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        base = QColor(15, 15, 18)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        for y, thickness, intensity in self._glitches:
            c = QColor(255, 255, 255, int(opacity * intensity))
            painter.fillRect(0, y, full_rect.width(), thickness, c)
            
            c_tint = QColor(255, 50, 50, int(opacity * 40)) if random.random() > 0.5 else QColor(50, 255, 255, int(opacity * 40))
            painter.fillRect(0, y + thickness, full_rect.width(), 3, c_tint)
            
        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 13. Radar Ping Sweep ─────────────────────────────────────────────────

class RadarVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._angle = 0.0
        self._timer = QTimer()
        self._timer.setInterval(40)  # Increased from 33
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._angle = (self._angle + 0.7) % 360.0
        if self._parent:
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        base = QColor(8, 16, 12)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        
        cx, cy = full_rect.center().x(), full_rect.center().y()
        r_color = QColor(color) if color != "#000000" else QColor(0, 255, 120)
        radius = max(full_rect.width(), full_rect.height())

        for t_step in range(10):  # Reduced from 12
            trail_angle = self._angle - (t_step * 1.5)
            rad_angle = math.radians(trail_angle)
            
            tx = cx + math.cos(rad_angle) * radius
            ty = cy + math.sin(rad_angle) * radius
            
            line_grad = QLinearGradient(cx, cy, tx, ty)
            
            c_start = QColor(r_color)
            c_start.setAlpha(int((1.0 - (t_step / 10.0)) * opacity * 130))
            c_end = QColor(r_color)
            c_end.setAlpha(0)
            
            line_grad.setColorAt(0.0, c_start)
            line_grad.setColorAt(1.0, c_end)
            
            p = painter.pen()
            p.setBrush(line_grad)
            p.setWidth(max(1, 4 - (t_step // 3)))
            painter.setPen(p)
            painter.drawLine(cx, cy, int(tx), int(ty))
        
        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 14. Shimmering God Rays ──────────────────────────────────────────────

class GodRaysVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._timer = QTimer()
        self._timer.setInterval(50)  # Increased from 33 for better perf
        self._timer.timeout.connect(self._tick)

    def _tick(self):
        self._t += 0.02
        if self._parent:
            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        w, h = full_rect.width(), full_rect.height()
        base = QColor(12, 12, 16)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)  # Disable for perf
        painter.setCompositionMode(QPainter.CompositionMode_Plus)

        ray_color = QColor(color) if color != "#000000" else QColor(255, 240, 200)
        
        start_x_min = w * 0.35
        start_x_max = w * 0.65
        bottom_y = h + 50

        for i in range(4):  # Reduced from 5 rays
            origin_x = start_x_min + (i * (start_x_max - start_x_min) / 3.0)
            origin_x += math.sin(self._t * 0.4 + i * 1.1) * (w * 0.03)
            
            target_x = (w * 0.5) + ((i - 1.5) * w * 0.35)
            target_x += math.cos(self._t * 0.3 + i * 1.5) * (w * 0.08)
            
            path = QPainterPath()
            
            base_width = w * 0.12
            path.moveTo(origin_x - (w * 0.015), 0)
            path.lineTo(origin_x + (w * 0.015), 0)
            path.lineTo(target_x + base_width, bottom_y)
            path.lineTo(target_x - base_width, bottom_y)
            path.closeSubpath()

            grad = QLinearGradient(0, 0, 0, h)
            c1 = QColor(ray_color)
            c1.setAlpha(int(opacity * 45))
            c2 = QColor(ray_color)
            c2.setAlpha(0)
            
            grad.setColorAt(0.0, c1)
            grad.setColorAt(1.0, c2)
            painter.fillPath(path, grad)

        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── 15. Cells ────────────────────────────────────────────────────────────

class CellsVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._timer = QTimer()
        self._timer.setInterval(40)  # Increased from 33
        self._timer.timeout.connect(self._tick)
        self._boids = []

    def _tick(self):
        if not self._boids and self._parent:
            w, h = self._parent.width(), self._parent.height()
            for _ in range(40):  # Reduced from 55
                angle = random.uniform(0, TWO_PI)
                speed = random.uniform(2.0, 4.5)
                self._boids.append([
                    random.uniform(100, w - 100), random.uniform(100, h - 100),
                    math.cos(angle) * speed, math.sin(angle) * speed,
                    random.uniform(4.0, 8.0)
                ])

        if self._parent:
            w, h = self._parent.width(), self._parent.height()
            for b1 in self._boids:
                avg_vx, avg_vy, avg_px, avg_py, close_x, close_y = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
                total = 0
                
                for b2 in self._boids:
                    if b1 is b2: continue
                    dx, dy = b2[0] - b1[0], b2[1] - b1[1]
                    dist = math.hypot(dx, dy)
                    if dist < 120:
                        avg_vx += b2[2]
                        avg_vy += b2[3]
                        avg_px += b2[0]
                        avg_py += b2[1]
                        total += 1
                        if dist < 30:
                            close_x -= dx
                            close_y -= dy

                if total > 0:
                    avg_vx /= total
                    avg_vy /= total
                    avg_px /= total
                    avg_py /= total
                    b1[2] += (avg_vx - b1[2]) * 0.04 + (avg_px - b1[0]) * 0.001 + close_x * 0.06
                    b1[3] += (avg_vy - b1[3]) * 0.04 + (avg_py - b1[1]) * 0.001 + close_y * 0.06

                speed = math.hypot(b1[2], b1[3])
                if speed > 5.0:
                    b1[2] = (b1[2] / speed) * 5.0
                    b1[3] = (b1[3] / speed) * 5.0

                b1[0] += b1[2]
                b1[1] += b1[3]

                if b1[0] < -20: b1[0] = w + 20
                if b1[0] > w + 20: b1[0] = -20
                if b1[1] < -20: b1[1] = h + 20
                if b1[1] > h + 20: b1[1] = -20

            self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        base = QColor(12, 12, 18)
        base.setAlpha(int(opacity * 255))
        painter.fillRect(full_rect, base)

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, False)
        
        swarm_color = QColor(color) if color != "#000000" else QColor(230, 90, 255)
        
        for b in self._boids:
            grad = QRadialGradient(b[0], b[1], b[4] * 4.5)
            c1 = QColor(swarm_color)
            c1.setAlpha(int(opacity * 160))
            
            c2 = QColor(swarm_color)
            c2.setAlpha(0)
            
            grad.setColorAt(0.0, c1)
            grad.setColorAt(1.0, c2)
            
            painter.setPen(Qt.NoPen)
            painter.setBrush(grad)
            painter.drawEllipse(QPointF(b[0], b[1]), b[4] * 4.5, b[4] * 4.5)
            
        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)
        
# ── 16. Fireworks ────────────────────────────────────────────
        
class Particle:
    def __init__(self, x, y, color, burst_type="default"):
        self.x = x
        self.y = y
        self.life = 1.0 
        self.color = color
        self.burst_type = burst_type
        
        # Physics base defaults
        self.size = random.uniform(0.5, 2.0)
        self.decay_rate = random.uniform(0.003, 0.01)
        self.gravity = random.uniform(0.01, 0.03)
        self.vx = random.uniform(-1.5, 1.5)
        self.vy = random.uniform(-1.5, 1.5)

        # Apply Burst Styles
        if burst_type == "willow": 
            self.vy = random.uniform(-0.5, 0.5)
            self.gravity = 0.02
            self.decay_rate = 0.003
        elif burst_type == "palm": 
            self.vx *= 2.0
            self.vy *= 2.0
            self.gravity = 0.05
        elif burst_type == "bees": 
            self.vx *= 2.5
            self.vy *= 2.5
            self.decay_rate = 0.02

    def update(self):
        if self.burst_type == "bees":
            self.vx += random.uniform(-0.2, 0.2)
            self.vy += random.uniform(-0.2, 0.2)
            
        self.x += self.vx
        self.y += self.vy
        self.vy += self.gravity
        self.life -= self.decay_rate


class FireworkVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self.particles = []
        self.timer = QTimer()
        self.timer.timeout.connect(self._tick)

    def _tick(self):
        roll = random.random()
        if roll < 0.03:
            type_roll = random.random()
            if type_roll < 0.1: b_type = "willow"
            elif type_roll < 0.2: b_type = "palm"
            elif type_roll < 0.25: b_type = "bees"
            else: b_type = "default"
            
            self._launch_firework(b_type)
        
        for p in self.particles:
            p.update()
            
        # O(N) list comprehension instead of O(N^2) list.remove()
        self.particles = [p for p in self.particles if p.life > 0]
        
        if self._parent:
            self._parent.update()

    def _launch_firework(self, b_type):
        if not self._parent: return
        rect = self._parent.rect()
        x = random.randint(0, rect.width())
        y = random.randint(0, rect.height())
        
        c1 = QColor(random.randint(100, 255), random.randint(100, 255), random.randint(100, 255))
        c2 = QColor(random.randint(100, 255), random.randint(100, 255), random.randint(100, 255))
        
        for _ in range(30):
            self.particles.append(Particle(x, y, c1, b_type))
            self.particles.append(Particle(x, y, c2, b_type))

    def on_show(self):
        self.timer.start(45)  # Increased from 30

    def on_hide(self):
        self.timer.stop()
        self.particles.clear()

    def paint(self, painter, full_rect, selection_rects, opacity, color_hex, selection_shape="rectangle"):
        # Explicitly disable AA to save rendering cycles on tiny particles
        painter.setRenderHint(QPainter.Antialiasing, False)
        
        bg_color = QColor(0, 0, 0, int(opacity * 255))
        painter.fillRect(full_rect, bg_color)
        
        for p in self.particles:
            alpha = int(p.life * 255 * opacity)
            
            # Replaced drawEllipse with fillRect (massive GPU savings)
            glow_color = QColor(p.color)
            glow_color.setAlpha(int(alpha * 0.2))
            painter.fillRect(int(p.x - p.size), int(p.y - p.size), int(p.size * 3), int(p.size * 3), glow_color)
            
            solid_color = QColor(p.color)
            solid_color.setAlpha(alpha)
            painter.fillRect(int(p.x), int(p.y), int(p.size), int(p.size), solid_color)
            
        _clear_holes(painter, selection_rects, selection_shape)

# ── 17 & 18. GIF-backed veils ────────────────────────────────────────────

class GifVeil(VeilBase):
    _LARGE_PX = 257

    def __init__(self, filename):
        super().__init__()
        self._path = os.path.join(SCRIPT_DIR, filename)
        self._movie = None
        self._last_cache_key = -1
        self._last_scaled = None
        self._last_rect = QRect()

    def _ensure_movie(self):
        if self._movie is not None:
            return
        if not os.path.exists(self._path):
            return
        self._movie = QMovie(self._path)
        self._movie.frameChanged.connect(self._on_frame)

    def _on_frame(self, _):
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

    def paint(self, painter, full_rect, selection_rects, opacity, color, selection_shape="rectangle"):
        if not self._movie:
            c = QColor(0, 0, 0)
            c.setAlpha(int(opacity * 255))
            painter.fillRect(full_rect, c)
            _clear_holes(painter, selection_rects, selection_shape)
            return

        raw = self._movie.currentPixmap()
        if raw.isNull():
            return

        # Use cacheKey() to accurately detect frame changes instead of object identity
        current_cache_key = raw.cacheKey()
        
        if current_cache_key != self._last_cache_key or full_rect != self._last_rect:
            self._last_cache_key = current_cache_key
            self._last_rect = full_rect
            if raw.width() >= self._LARGE_PX or raw.height() >= self._LARGE_PX:
                self._last_scaled = raw.scaled(
                    full_rect.size(),
                    Qt.KeepAspectRatioByExpanding,
                    Qt.FastTransformation  # Replaced SmoothTransformation for massive CPU gain
                )
            else:
                self._last_scaled = None

        painter.save()
        painter.setOpacity(opacity)
        if self._last_scaled:
            x = full_rect.x() + (full_rect.width() - self._last_scaled.width()) // 2
            y = full_rect.y() + (full_rect.height() - self._last_scaled.height()) // 2
            painter.drawPixmap(x, y, self._last_scaled)
        else:
            painter.drawTiledPixmap(full_rect, raw)
        painter.restore()
        _clear_holes(painter, selection_rects, selection_shape)


# ── Registry / factory ──────────────────────────────────────────────────────

VEIL_LABELS = [
    ("flat", "Flat Color"),
    ("color", "Ambient Color"),
    ("darkcolor", "Dark Ambient"),
    ("wave", "Wave"),
    ("waves", "Waves"),
    ("waves2", "Waves 2"),
    ("linewaves", "Line Waves"),
    ("starfield", "Cosmic Starfield"),
    ("constellation", "Constellation"),
    ("cyber", "Cyber Rain"),
    ("matrix", "Matrix Rain"),
    ("crt", "Retro CRT"),
    ("vhs", "VHS Glitch"),
    ("radar", "Radar Sweep"),
    ("godrays", "God Rays"),
    ("flock", "Cells"),
    ("fireworks", "Fireworks"),
    ("jellyfish", "Jellyfish"),
    ("chicks", "Chicks"),
]

_REGISTRY = {
    "flat":      lambda: FlatColorVeil(),
    "color":     lambda: AmbientColorVeil(),
    "darkcolor": lambda: DarkAmbientColorVeil(),
    "wave":      lambda: ShaderWavesVeil(), # GPU version
    "waves":     lambda: WavesVeil(),       # CPU version
    "waves2":    lambda: Waves2Veil(),
    "linewaves": lambda: LineWavesVeil(),
    "starfield": lambda: StarfieldVeil(),
    "constellation": lambda: ConstellationVeil(),
    "cyber": lambda: CyberRainVeil(),
    "matrix": lambda: MatrixRainVeil(),
    "crt": lambda: RetroCrtVeil(),
    "vhs": lambda: VhsGlitchVeil(),
    "radar": lambda: RadarVeil(),
    "godrays": lambda: GodRaysVeil(),
    "flock": lambda: CellsVeil(),
    "fireworks": lambda: FireworkVeil(),
    "jellyfish": lambda: GifVeil("jellyfish.gif"),
    "chicks": lambda: GifVeil("chicks.gif"),
}

def get_veil(key: str) -> VeilBase:
    return _REGISTRY.get(key, _REGISTRY["flat"])()
