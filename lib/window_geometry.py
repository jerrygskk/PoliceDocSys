# -*- coding: utf-8 -*-
"""主視窗啟動時的可用桌面收斂邏輯。

背景：維護者實機（Windows 125% 縮放、1920x1080）量到 Layout1.ui 預設
1440x800（邏輯像素）換算實際像素後，加標題列會超出扣掉工作列的可用高度。
`.ui` 預設值已調整，但換機器、接投影機、使用者改縮放倍率時仍可能再爆版，
故啟動時另外做一次「超出可用範圍才收斂」的保護。

`fit_window_to_available` 是純函式（只吃／吐 QRect，不碰真實螢幕或 widget），
專門給單元測試用；`apply_startup_geometry` 是薄封裝，串接真實 QWidget 與
QScreen，供 main.py 呼叫。
"""
from PySide6.QtCore import QRect


def fit_window_to_available(win_rect: QRect, avail_rect: QRect) -> QRect:
    """若 win_rect 超出 avail_rect（尺寸或位置），縮小並拉回可用範圍內；
    完全沒超出則原樣傳回（不干預 .ui 預設值／使用者已調整的大小）。

    - 只縮小尺寸到 avail_rect 之內，不會放大（沒超出的軸維持原值）。
    - 尺寸縮小後，位置也一併確保整個視窗落在 avail_rect 內。
    - 尺寸沒超出、但位置本身已超出可用範圍（例如換了較小的螢幕／解析度）
      時，同樣視為「超出」，只搬位置、尺寸不變。
    """
    x, y, w, h = win_rect.x(), win_rect.y(), win_rect.width(), win_rect.height()
    ax, ay = avail_rect.x(), avail_rect.y()
    aw, ah = avail_rect.width(), avail_rect.height()

    new_w = min(w, aw)
    new_h = min(h, ah)

    out_of_bounds = (
        x < ax or y < ay
        or x + w > ax + aw
        or y + h > ay + ah
    )
    if new_w == w and new_h == h and not out_of_bounds:
        return QRect(x, y, w, h)

    max_x = ax + aw - new_w
    max_y = ay + ah - new_h
    new_x = min(max(x, ax), max_x)
    new_y = min(max(y, ay), max_y)
    return QRect(new_x, new_y, new_w, new_h)


def apply_startup_geometry(window, screen):
    """main.py 進入點呼叫：用 screen 的「可用範圍」（已扣工作列）收斂 window。

    只在需要收斂時才 setGeometry；沒超出則完全不動視窗（不鎖 max size，
    使用者仍可自由縮放／最大化）。
    """
    avail = screen.availableGeometry()
    current = window.geometry()
    fitted = fit_window_to_available(current, avail)
    if fitted != current:
        window.setGeometry(fitted)
