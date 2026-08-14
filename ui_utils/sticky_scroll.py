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
from PySide6.QtWidgets import QAbstractSlider, QPushButton


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

    # _programmatic：本模組自己捲動時為 True，用來把「程式捲的」與「人捲的」分開。
    # _last_max：上次看到的捲軸上限，用來認出「新增/移除列造成的位移」不是人為捲動。
    state = {"sticky": False, "auto_started": False,
             "_programmatic": False, "_last_max": 0}
    sb = table.verticalScrollBar()
    state["_last_max"] = sb.maximum()

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
                _scrollToBottomLater()
        else:
            btn.hide()
            # 內容變少不可捲動時，重置以便下次再次自動啟動
            state["auto_started"] = False

    def _scrollToBottom():
        state["_programmatic"] = True
        try:
            sb.setValue(sb.maximum())
        finally:
            state["_programmatic"] = False
        state["_last_max"] = sb.maximum()

    def _scrollToBottomLater():
        """延後捲底：⚠️ 執行當下要再確認一次還在黏底。

        排程與執行之間隔了一輪事件迴圈，使用者可能已經手動捲走（sticky 已變 False），
        舊排程若無條件捲底就會把人硬拉回底部——正是「手動捲動就保留位置」要防的事。
        所有延後捲底一律走這裡，不要直接排 _scrollToBottom。"""
        def _run():
            if state["sticky"]:
                _scrollToBottom()
        QTimer.singleShot(0, _run)

    def _updateStyle():
        btn.setStyleSheet(_BTN_STICKY if state["sticky"] else _BTN_NORMAL)

    def _onClicked():
        state["sticky"] = True
        _scrollToBottom()
        _updateStyle()

    def _onValueChanged(_):
        # 只要人為離開底部就退出黏底——不論用什麼方式捲（滾輪、捲軸箭頭、點軌道、
        # 鍵盤、觸控）。⚠️ 別只攔滾輪與拖曳滑塊：點箭頭／軌道一樣是手動捲動，
        # 漏掉的話下次有新資料又會被拉回底部，違反「手動捲動就保留位置」。
        cur_max = sb.maximum()
        if cur_max != state["_last_max"]:
            # 列數變動造成的位移（重建表格、新增/移除列），不是人捲的
            state["_last_max"] = cur_max
        elif (state["sticky"] and not state["_programmatic"]
                and sb.value() < cur_max):
            state["sticky"] = False
            _updateStyle()
        _update_visibility()

    def _onRangeChanged(_min, _max):
        state["_last_max"] = sb.maximum()
        # 黏底模式下新增資料 → 自動跟到底
        if state["sticky"]:
            _scrollToBottomLater()
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

    # 對外暴露黏底狀態：整表重建時要據此決定「恢復原捲動位置」或「讓黏底贏」
    # （瀏覽頁 _reload 用）。唯讀用途，外部不應改寫。
    btn.sticky_state = state

    btn.clicked.connect(_onClicked)
    sb.valueChanged.connect(_onValueChanged)
    sb.rangeChanged.connect(_onRangeChanged)

    # 使用者往上操作捲軸 → 退出黏底。⚠️ 這條不能只靠 valueChanged：人在最頂端還
    # 按向上箭頭時 value 不變、valueChanged 不會 emit，但那仍是明確的手動操作，
    # 不攔的話待會的自動捲底就會把人拉走。actionTriggered 只由使用者操作觸發，
    # 程式 setValue() 不會走到這裡。
    # ⚠️ 存成 int：actionTriggered 傳回的是純 int，PySide6 的列舉與 int 不相等
    # （`5 == QAbstractSlider.SliderToMinimum` 為 False），直接比列舉會靜默失效。
    _UPWARD_ACTIONS = {
        QAbstractSlider.SliderSingleStepSub.value,
        QAbstractSlider.SliderPageStepSub.value,
        QAbstractSlider.SliderToMinimum.value,
    }

    def _onActionTriggered(action):
        if state["sticky"] and int(action) in _UPWARD_ACTIONS:
            state["sticky"] = False
            _updateStyle()
    sb.actionTriggered.connect(_onActionTriggered)

    # 使用者拖動捲軸滑塊 → 立即退出黏底（sliderMoved 只在人為拖動時 emit）
    def _onSliderMoved(_):
        if state["sticky"]:
            state["sticky"] = False
            _updateStyle()
    sb.sliderMoved.connect(_onSliderMoved)

    QTimer.singleShot(0, _update_visibility)
    return btn
