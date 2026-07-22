import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton


def test_qtbot_clicks_offscreen_button(qtbot):
    button = QPushButton("click")
    qtbot.addWidget(button)
    clicked = []
    button.clicked.connect(lambda: clicked.append(True))

    button.show()
    qtbot.mouseClick(button, Qt.LeftButton)

    assert clicked == [True]
