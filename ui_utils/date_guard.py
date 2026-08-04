# -*- coding: utf-8 -*-
"""日期防呆：送出前確認日期沒有被誤改。

**為什麼需要**：登錄類分頁的日期欄在連續登錄時是共用的（送出後不重設，因為同一天
通常要連續登錄好幾筆）。焦點停在日期欄時，鍵盤方向鍵或滾輪會直接改到游標所在那一段
（年／月／日），畫面上只有一個數字變動，非常不容易察覺——而且一旦被改到，**之後每一筆
都會沿用那個錯誤日期**，錯成連續的一整段。實際發生過：某日發文日期的年份被多加一年，
當天 12 筆有 8 筆寫成隔年，簽收表只印得出前 4 筆。

**設計取捨**：
- **只提示、不擋**。補登前幾天的公文、跨年度前後作業都是正常情境，擋死會妨礙作業。
- **早於今日的門檻比晚於今日嚴格**（早 1 天就問、晚 10 天才問）：往前是常見的補登，
  但也是誤改最常見的方向；往後 10 天內可能是預定發文日。
- **同一欄位＋同一日期，本次執行只問一次**。連續登錄十幾筆時每筆都問會被無視，
  反而失去提醒效果；問一次即可，換成別的日期才會再問。
- 使用者按取消＝回去改日期，**不記錄**（下次仍會問）。
"""
from PySide6.QtCore import QDate

from .ui_common import confirmBox


# 早於今日：只要早這麼多天就提示（誤改最常見的方向）
PAST_GAP_DAYS = 1
# 晚於今日：晚這麼多天才提示（10 天內可能是預定發文日）
# `future_only` 欄位（查獲／受理日期）往後也用同一個門檻，只是往前不提示。
FUTURE_GAP_DAYS = 10

# 本次執行已確認過的 (欄位名稱, 日期字串)；不持久化，關掉程式即重來
_confirmed = set()


def _to_qdate(value):
    """接受 QDate 或 'yyyy-MM-dd' 字串；無法解析回 None（不擋流程）。"""
    if isinstance(value, QDate):
        return value if value.isValid() else None
    if not value:
        return None
    d = QDate.fromString(str(value).strip(), "yyyy-MM-dd")
    return d if d.isValid() else None


def dateGapDays(value, today=None):
    """回傳「該日期 − 今日」的天數；晚於今日為正、早於今日為負。無法解析回 None。"""
    d = _to_qdate(value)
    if d is None:
        return None
    return (today or QDate.currentDate()).daysTo(d)


def needsDateConfirm(value, *, future_only=False, today=None):
    """是否應該跳提示（純邏輯，供測試與呼叫端共用）。

    `future_only=True` 用於「查獲／受理日期」這類**本來就常是過去**的欄位：
    往前多久都正常（案件受理常在數週前），故只檢查往後那一側；門檻與其他欄位相同。
    """
    gap = dateGapDays(value, today=today)
    if gap is None:
        return False
    if gap >= FUTURE_GAP_DAYS:
        return True
    if gap > 0:
        return False
    if future_only:
        return False
    return -gap >= PAST_GAP_DAYS


def describeDateGap(value, label, today=None):
    """提示文字；日期本身與差距天數都寫出來，讓使用者一眼看出被改到哪一段。"""
    gap = dateGapDays(value, today=today)
    d = _to_qdate(value)
    shown = d.toString("yyyy-MM-dd") if d else str(value)
    if gap is None or gap == 0:
        return f"{label}為 {shown}。"
    direction = "晚於" if gap > 0 else "早於"
    return (f"{label}為 {shown}，{direction}本日 {abs(gap)} 天。")


def confirmDateGap(value, label="發文日期", *, parent=None, future_only=False,
                   today=None):
    """送出前呼叫。回傳 True 表示可以繼續（不需提示、或使用者已確認）。

    ⚠️ 呼叫端必須把回傳 False 當成「使用者要回去改日期」，中止本次送出。
    """
    if not needsDateConfirm(value, future_only=future_only, today=today):
        return True
    d = _to_qdate(value)
    key = (label, d.toString("yyyy-MM-dd") if d else str(value))
    if key in _confirmed:
        return True
    ok = confirmBox(
        "請確認日期",
        describeDateGap(value, label, today=today),
        informative="日期欄可能在輸入其他欄位時被鍵盤或滾輪誤改。\n"
                    "確認無誤才繼續，否則請返回修正。",
        confirm_text="確認無誤", cancel_text="返回修正",
        default_confirm=False, parent=parent, min_width=520)
    if ok:
        _confirmed.add(key)
    return ok


def resetConfirmedDates():
    """清掉「本次已確認」記錄（測試用；正式程式不需呼叫）。"""
    _confirmed.clear()
