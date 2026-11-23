"""Theme-coloured SVG symbols. All sizes are logical Qt pixels."""
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QSpinBox, QStyle, QStyleOptionSpinBox

ICONS = Path(__file__).with_name("icons")


@lru_cache(maxsize=128)
def pixmap(name, color, size):
    data = (ICONS / f"{name}.svg").read_bytes().replace(b"currentColor", color.encode("ascii"))
    renderer = QSvgRenderer(data)
    # The same pixmap can move between standard, fractional-DPI and Retina screens.
    scale = 4
    result = QPixmap(size * scale, size * scale)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    renderer.render(painter)
    painter.end()
    result.setDevicePixelRatio(scale)
    return result


def symbol_label(name, color, size):
    widget = QLabel()
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    widget.setPixmap(pixmap(name, color, size))
    return widget


def button_icon(button, name, color, size, disabled):
    icon = QIcon()
    icon.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal)
    icon.addPixmap(pixmap(name, disabled, size), QIcon.Mode.Disabled)
    button.setIcon(icon)
    button.setIconSize(QSize(size, size))


class RoundLimit(QSpinBox):
    """Keep native spin hit targets, keyboard handling and editing, with legible arrows."""
    def __init__(self, colors):
        super().__init__()
        self.colors = colors
        self.setFixedSize(60, 26)

    def paintEvent(self, event):
        super().paintEvent(event)
        option = QStyleOptionSpinBox()
        self.initStyleOption(option)
        painter = QPainter(self)
        for subcontrol, symbol, enabled in (
                (QStyle.SubControl.SC_SpinBoxUp, "chevron-up", self.value() < self.maximum()),
                (QStyle.SubControl.SC_SpinBoxDown, "chevron-down", self.value() > self.minimum())):
            rect = self.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, subcontrol, self)
            glyph = pixmap(symbol, self.colors["text" if self.isEnabled() and enabled else "muted"], 13)
            painter.drawPixmap(rect.center().x() - 6, rect.center().y() - 6, glyph)
        painter.end()
