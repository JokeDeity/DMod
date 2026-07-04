# veils_base.py
import math
from PyQt5.QtCore import Qt

# Move _clear_holes here (assuming shapes is in your directory)
try:
    from shapes import clear_selection_holes
except ImportError:
    def clear_selection_holes(painter, selection_rects, selection_shape):
        pass

def _clear_holes(painter, selection_rects, selection_shape="rectangle"):
    clear_selection_holes(painter, selection_rects, selection_shape)

class VeilBase:
    def __init__(self):
        self._parent = None
        
    def set_parent(self, widget):
        self._parent = widget
        
    def on_show(self): pass
    def on_hide(self): pass
    def paint(self, painter, full_rect, selection_rects, opacity, color_hex, selection_shape="rectangle"):
        pass