"""
shapes.py – Selection shape helpers for Theater Mode.

Each shape is drawn inside the drag bounding box (QRect). The same geometry
is used when punching holes in the veil and when drawing selection outlines.
"""

from PyQt5.QtCore import Qt, QRect, QRectF
from PyQt5.QtGui import QPainter, QPen, QPainterPath


SELECTION_SHAPE_LABELS = [
    ("rectangle", "Rectangle"),
    ("ellipse",   "Ellipse"),
    ("circle",    "Circle"),
    ("diamond",   "Diamond"),
    ("triangle",  "Triangle"),
]


def _circle_rect(rect: QRect) -> QRect:
    """Largest axis-aligned square centered inside rect."""
    size = min(rect.width(), rect.height())
    x = rect.x() + (rect.width() - size) // 2
    y = rect.y() + (rect.height() - size) // 2
    return QRect(x, y, size, size)


def shape_path(shape: str, rect: QRect) -> QPainterPath:
    """Build a closed path for the given shape inside rect."""
    path = QPainterPath()
    if rect.isEmpty():
        return path

    if shape == "ellipse":
        path.addEllipse(QRectF(rect))
    elif shape == "circle":
        path.addEllipse(QRectF(_circle_rect(rect)))
    elif shape == "diamond":
        cx = rect.x() + rect.width() / 2
        cy = rect.y() + rect.height() / 2
        path.moveTo(cx, rect.top())
        path.lineTo(rect.right(), cy)
        path.lineTo(cx, rect.bottom())
        path.lineTo(rect.left(), cy)
        path.closeSubpath()
    elif shape == "triangle":
        cx = rect.x() + rect.width() / 2
        path.moveTo(cx, rect.top())
        path.lineTo(rect.right(), rect.bottom())
        path.lineTo(rect.left(), rect.bottom())
        path.closeSubpath()
    else:
        path.addRect(QRectF(rect))

    return path


def clear_selection_holes(painter: QPainter, selection_rects, shape: str):
    """Punch transparent holes for each selection using the active shape."""
    if not selection_rects:
        return
    painter.setCompositionMode(QPainter.CompositionMode_Clear)
    for rect in selection_rects:
        if rect.isEmpty():
            continue
        path = shape_path(shape, rect)
        if not path.isEmpty():
            painter.fillPath(path, Qt.transparent)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)


def draw_selection_outlines(painter: QPainter, selection_rects, shape: str, pen: QPen,
                            current_rect=None):
    """Draw dashed outlines for committed and in-progress selections."""
    painter.setPen(pen)
    for rect in selection_rects:
        if not rect.isEmpty():
            painter.drawPath(shape_path(shape, rect))
    if current_rect is not None and not current_rect.isNull() and not current_rect.isEmpty():
        painter.drawPath(shape_path(shape, current_rect))
