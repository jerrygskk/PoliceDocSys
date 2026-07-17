from datetime import datetime
from PySide6.QtGui import QColor


def calcOverdue(deadlineStr, dispatchStr):
    """計算逾期狀態字串"""
    if not deadlineStr or str(deadlineStr) in ("", "None", "nan"):
        return "免覆"
    try:
        today      = datetime.now().date()
        deadline   = datetime.strptime(str(deadlineStr), "%Y-%m-%d").date()
        dispatched = dispatchStr and str(dispatchStr) not in ("", "None", "nan")
        if dispatched:
            d    = datetime.strptime(str(dispatchStr), "%Y-%m-%d").date()
            diff = (d - deadline).days
            return "已發文" if diff <= 0 else f"已發文（逾期 {diff} 日）"
        diff = (deadline - today).days
        if diff > 0:  return f"剩餘 {diff} 日"
        if diff == 0: return "今日到期"
        return f"逾期 {-diff} 日"
    except Exception:
        return "格式錯誤"


def colorForStatus(status):
    """根據狀態字串回傳 QColor，無需上色時回傳 None"""
    if "逾期" in status and "已發文" not in status: return QColor("#e74c3c")
    if "今日" in status:                            return QColor("#e67e22")
    if "已發文" in status and "逾期" not in status: return QColor("#27ae60")
    if "已發文" in status and "逾期" in status:     return QColor("#e67e22")
    return None
