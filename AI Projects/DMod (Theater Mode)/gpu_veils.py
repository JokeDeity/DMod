# gpu_veils.py
import struct
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import (
    QOpenGLShaderProgram, QOpenGLShader, QColor, QOpenGLContext, 
    QOpenGLBuffer, QOpenGLVertexArrayObject
)
from veils_base import VeilBase, _clear_holes
from OpenGL.GL import (
    glDrawArrays, GL_TRIANGLES, glUseProgram, glBindVertexArray, 
    glBindBuffer, glDisable, GL_BLEND, GL_ARRAY_BUFFER
)

VERTICES = [
    -1.0, -1.0,  1.0, -1.0, -1.0, 1.0,
     1.0, -1.0,  1.0,  1.0, -1.0, 1.0
]

VERTEX_SHADER = """
attribute vec2 position;
void main() {
    gl_Position = vec4(position, 0.0, 1.0);
}
"""

FRAGMENT_SHADER_WAVES = """
#version 120
uniform float time;
uniform vec2 resolution;
uniform vec3 color;
void main() {
    vec2 uv = gl_FragCoord.xy / resolution.xy;
    float y = 0.5 + sin(uv.x * 6.0 + time) * 0.2 + cos(uv.x * 12.0 - time * 0.5) * 0.1;
    float line = smoothstep(0.05, 0.0, abs(uv.y - y));
    float glow = smoothstep(0.4, 0.0, abs(uv.y - y)) * 0.2;
    vec3 finalColor = color * (line + glow);
    gl_FragColor = vec4(finalColor, 1.0);
}
"""

class ShaderWavesVeil(VeilBase):
    def __init__(self):
        super().__init__()
        self._t = 0.0
        self._timer = QTimer()
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._program = None
        self._vao = None
        self._vbo = None

    def _tick(self):
        self._t += 0.02
        if self._parent: self._parent.update()

    def on_show(self): self._timer.start()
    def on_hide(self): self._timer.stop()

    def _reset_gl_state(self):
        glUseProgram(0)
        glBindVertexArray(0)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glDisable(GL_BLEND)

    def _init_gl(self):
        if self._program: return
        ctx = QOpenGLContext.currentContext()
        if not ctx: return

        self._program = QOpenGLShaderProgram()
        self._program.addShaderFromSourceCode(QOpenGLShader.Vertex, VERTEX_SHADER)
        self._program.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAGMENT_SHADER_WAVES)
        if not self._program.link():
            self._program = None
            return

        self._vao = QOpenGLVertexArrayObject()
        self._vao.create()
        self._vao.bind()
        self._vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
        self._vbo.create()
        self._vbo.bind()
        buffer_data = struct.pack(f'{len(VERTICES)}f', *VERTICES)
        self._vbo.allocate(buffer_data, len(buffer_data))
        self._program.enableAttributeArray("position")
        self._program.setAttributeBuffer("position", 0x1406, 0, 2)
        self._vao.release()
        self._reset_gl_state()

    def paint(self, painter, full_rect, selection_rects, opacity, color_hex, selection_shape="rectangle"):
        self._init_gl()
        if not self._program:
            painter.fillRect(full_rect, QColor(color_hex))
            _clear_holes(painter, selection_rects, selection_shape)
            return

        painter.beginNativePainting()
        self._program.bind()
        self._vao.bind()
        c = QColor(color_hex)
        self._program.setUniformValue("time", self._t)
        self._program.setUniformValue("resolution", float(full_rect.width()), float(full_rect.height()))
        self._program.setUniformValue("color", c.redF(), c.greenF(), c.blueF())
        glDrawArrays(GL_TRIANGLES, 0, 6)
        self._vao.release()
        self._program.release()
        self._reset_gl_state()
        painter.endNativePainting()
        _clear_holes(painter, selection_rects, selection_shape)