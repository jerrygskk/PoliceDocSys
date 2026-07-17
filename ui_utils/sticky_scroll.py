"""
sticky_scroll.py — 預覽表「黏底」捲動

attachStickyScroll(table):
    在表格右下角疊一顆浮動圓形按鈕，按一下：
      1. 立即捲到最底
      2. 進入黏底模式 → 之後新增列會自動跟著捲到底
    使用者手動往上捲 → 自動退出黏底模式。

    預設行為：若使用者原本就在底部，新增列會自動跟著捲到底。
    按鈕只在「捲軸有作用（內容超過可視範圍）」時顯示。
"""
from PySide6.QtCore    import Qt, QTimer, QObject, QEvent
from PySide6.QtWidgets import QPushButton


_BTN_NORMAL = """
QPushButton {
    background-color: rgba(174, 174, 178, 0.92);
    color: #ffffff;
    border: none;
    border-radius: 16px;
    font-size: 14pt;
    font-weight: 700;
    padding: 0px;
}
QPushButton:hover { background-color: rgba(155, 155, 160, 1.0); }
"""

_BTN_STICKY = """
QPushButton {
    background-color: rgba(110, 143, 172, 0.95);
    color: #ffffff;
    border: none;
    border-radius: 16px;
    font-size: 14pt;
    font-weight: 700;
    padding: 0px;
}
QPushButton:hover { background-color: rgba(95, 125, 152, 1.0); }
"""


def attachStickyScroll(table):
    """為 table 加上右下角浮動黏底按鈕。回傳該按鈕。"""
    btn = QPushButton("⤓", table)
    btn.setStyleSheet(_BTN_NORMAL)
    btn.setFixedSize(32, 32)
    btn.setToolTip("捲到底並跟隨最新")
    btn.setCursor(Qt.PointingHandCursor)

    state = {"sticky": False, "auto_started": False}
    sb = table.verticalScrollBar()

    def _can_scroll():
        return sb.maximum() > sb.minimum()

    def _reposition():
        m = 12
        x = table.viewport().x() + table.viewport().width() - btn.width() - m
        y = table.viewport().y() + table.viewport().height() - btn.height() - m
        btn.move(max(0, x), max(0, y))

    def _update_visibility():
        if _can_scroll():
            _reposition()
            btn.show()
            btn.raise_()
            # 第一次變成可捲動 → 自動啟動黏底並捲到底
            if not state["auto_started"]:
                state["auto_started"] = True
                state["sticky"] = True
                _updateStyle()
                QTimer.singleShot(0, _scrollToBottom)
        else:
            btn.hide()
            # 內容變少不可捲動時，重置以便下次再次自動啟動
            state["auto_started"] = False

    def _scrollToBottom():
        sb.setValue(sb.maximum())

    def _updateStyle():
        btn.setStyleSheet(_BTN_STICKY if state["sticky"] else _BTN_NORMAL)

    def _onClicked():
        state["sticky"] = True
        _scrollToBottom()
        _updateStyle()

    def _onValueChanged(_):
        _update_visibility()

    def _onRangeChanged(_min, _max):
        # 黏底模式下新增資料 → 自動跟到底
        if state["sticky"]:
            QTimer.singleShot(0, _scrollToBottom)
        QTimer.singleShot(0, _update_visibility)

    _orig_resize = table.resizeEvent
    def _resizeEvent(ev):
        _orig_resize(ev)
        _update_visibility()
    table.resizeEvent = _resizeEvent

    # 攔截滾輪：往上滾就退出黏底
    # 註：QAbstractScrollArea 的 wheel 事件由 viewport() 接收，
    # 覆寫 table.wheelEvent 不會被觸發，必須在 viewport 裝 eventFilter。
    class _WheelFilter(QObject):
        def eventFilter(self, obj, ev):
            if (ev.type() == QEvent.Wheel
                    and ev.angleDelta().y() > 0
                    and state["sticky"]):
                state["sticky"] = False
                _updateStyle()
            return False  # 不吃掉事件，原本的捲動行為繼續

    table._wheel_filter = _WheelFilter(table)   # 存屬性防 GC
    table.viewport().installEventFilter(table._wheel_filter)

    btn.clicked.connect(_onClicked)
    sb.valueChanged.connect(_onValueChanged)
    sb.rangeChanged.connect(_onRangeChanged)

    # 使用者拖動捲軸滑塊 → 立即退出黏底（sliderMoved 只在人為拖動時 emit）
    def _onSliderMoved(_):
        if state["sticky"]:
            state["sticky"] = False
            _updateStyle()
    sb.sliderMoved.connect(_onSliderMoved)

    QTimer.singleShot(0, _update_visibility)
    return btn
