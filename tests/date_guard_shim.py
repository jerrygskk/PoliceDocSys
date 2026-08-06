"""測試環境的日期防呆遮蔽（單一來源）。

`ui_utils/date_guard` 會在送出的日期與本日落差過大時彈確認框。離線測試環境沒有
人可以按，Qt modal `exec()` 會無限等待，任何「以非今日日期送出」的測試都會整支
卡住（PITFALLS TST-4）。故測試一律讓它自動回「確認無誤」。

⚠️ **遮蔽只能有這一份**：pytest 由根 `conftest.py` 的 autouse fixture 呼叫、
`unittest` 由 `tests/__init__.py` 匯入時呼叫，兩條路徑都走這裡。不要再在個別
測試裡自己 patch 一次——防呆改寫時會漏掉那些散落的第二份。

本遮蔽只擋「防呆的提示」，不改其他行為；防呆本身由 `test_date_guard.py` 與
`test_date_guard_gui_pilot.py` 兩支專責測試涵蓋，它們自行覆寫本遮蔽。
"""
from __future__ import annotations

OWN_TESTS = {"test_date_guard.py", "test_date_guard_gui_pilot.py"}


def installAutoConfirm(monkeypatch=None):
    """讓日期防呆一律回「確認無誤」，並清掉「本次已確認」的模組層狀態。

    `monkeypatch` 給得出來時（pytest）用它替換，測試結束自動還原；給不出來時
    （unittest）直接指派，行程結束才消失。回傳 False 表示環境沒有 PySide6，
    不需要也無法遮蔽。
    """
    try:
        import ui_utils.date_guard as date_guard
    except Exception:
        return False        # 無 PySide6 的環境（純 stdlib 測試）不需處置
    date_guard.resetConfirmedDates()
    if monkeypatch is not None:
        monkeypatch.setattr(date_guard, "confirmBox", lambda *a, **kw: True)
    else:
        date_guard.confirmBox = lambda *a, **kw: True
    return True
