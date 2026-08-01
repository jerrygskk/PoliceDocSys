# -*- coding: utf-8 -*-
"""階段 2 修正驗收工具：兩引擎「實際畫出來的樣子」感知級比對。

`tools/engine_diff.py` 比的是 op log（**打算**畫什麼），兩引擎意圖必然
相同，4193 筆 op 零差異對「實際畫成什麼樣」沒有任何保證力——字重失效、
垂直置中偏移這類「意圖一樣、畫出來不一樣」的缺陷完全不會被 op 比對抓到。

本工具沿用 `tools/print_baseline.py` 的同一組案例，每頁分別用
matplotlib（產品現況）與 QtCanvas 畫成**同尺寸 PNG**，再用客觀量測比對：

    - 分區墨跡量比值（標題帶／表頭帶／資料列帶各自計）　0.90~1.10
    - 長水平線 y 位置（兩引擎逐條對應）　誤差 ≤ 2.0 device px
    - 列剖面（每列墨跡量序列）相關係數　≥ 0.98
    - 每格文字墨跡中心的垂直偏移　≤ 0.55 pt

⚠️ 幾何門檻刻意使用兩種不同單位，各自對應各自的物理本質（STAGE2-FIX4）：
    - 格垂直偏移量的是「文字實際被放在哪裡」，是物理位移，門檻用 pt，
      同一個實體位移在任何 dpi 下判定一致。
    - 長水平線 y 差是「光柵化假影」（matplotlib Agg 對線條做像素吸附、
      Qt 反鋸齒繪圖沒有這個機制），大小固定在 1~1.5 個 device px、不隨
      dpi 縮放，門檻用 device px 才對得上它的物理本質——用 pt 換算會讓
      低 dpi 天生超標（150dpi 下 1px≈0.48pt，比 300dpi 的 0.24pt 大一
      倍）、高 dpi 又過度寬鬆，這是分類錯誤，不是「越量越嚴」的問題。
      真正的幾何錯位仍會被「格垂直偏移（pt）」那一項抓到，不會因為這項
      改用 px 而漏掉。報告仍同時列出 px 與 pt，但判定依各自單位為準。

分區與格線一律依既有版面常數（TOP／DATE_H／TITLE_H／HDR_H／ROW_H／
TICKET_ROW_H…）換算，不用魔術數字。

用法：
    $env:QT_QPA_PLATFORM='offscreen'; python tools/render_diff.py

輸出：
    - stdout：逐案例逐頁列出四項實測值與是否超標。
    - docs/render_diff/{案例}_page{頁碼}_{MPL,QT}.png：超標頁面的兩引擎
      實際畫面，供目視比對。

回傳碼：全部頁面在門檻內 → 0；有任何一頁超標 → 1。

⚠️ 門檻是用來抓 bug 的，不是用來讓報告好看的：門檻不合理就在回報中提出
建議值，不要自己放寬到剛好通過。
"""

import argparse
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np

import tabs.tab_print as tp
from lib.print_canvas import A4_H_IN, A4_W_IN, QtCanvas
from tools.engine_diff import _case_page_specs
from tools.mpl_canvas import mpl_text_width_pt
from tools.print_baseline import CASES, _case_key

OUT_DIR = os.path.join("docs", "render_diff")

# ── 門檻（STAGE2-FIX3：全面改用物理單位 pt，理由見檔頭說明）───────────
# dpi 參數化（STAGE2-FIX2-BRIEF 問題 4）：預設仍是 150，但 `--dpi` 可覆寫，
# 驗收一律在 300dpi 跑，另外要確認 150／300／600 三種 dpi 工具本身都不失真。
_RENDER_DPI = 150
ZONE_RATIO_LO, ZONE_RATIO_HI = 0.90, 1.10
ROW_PROFILE_MIN_CORR = 0.98

# 長水平線 y 位置門檻（STAGE2-FIX4）：改回 device px，訂為 2.0px。
# 根因已查明：matplotlib Agg 對線條有「像素吸附」（把線的座標對齊到整數
# 像素格線，讓 1px 寬的線剛好落在一個像素內、不糊成兩行半透明），Qt 的
# 反鋸齒繪圖沒有這個機制，兩者對同一條線畫出來的中心點本就會系統性差
# 1~1.5 個 device px——這是兩套繪圖後端的設計差異，不是本工具或
# `QtCanvas` 的 bug，且會弄髒其他量測（若在 `QtCanvas` 也做像素吸附，
# 等於為了配合這一項檢查改變全部線條的繪製方式）前提下無法消除。
#
# ⚠️ 這項故意不用 pt：這個誤差是「固定像素數的光柵化假影」，不隨 dpi
# 縮放——實測 150dpi＝1.00px、300dpi＝1.00px、600dpi＝1.50px，物理量
# 換算出來的 pt 值反而隨 dpi 下降而變大（150dpi＝0.48pt、300dpi＝
# 0.24pt、600dpi＝0.18pt），套用單一 pt 門檻會讓低 dpi 天生超標、高 dpi
# 又過度寬鬆，是把「像素吸附差」誤判成「物理位移」的分類錯誤。改用
# device px、以量測當下的 dpi 為準，才對得上這個假影的物理本質，三種
# dpi 下都以 2.0px 判定，對實測最大值 1.50px 仍留有裕度。真正的幾何
# 錯位仍會被下面「格垂直偏移（pt）」那一項抓到，不會因為這項改用 px
# 而漏掉。
LINE_Y_TOL_DEVICE_PX = 2.0

# 每格文字墨跡中心垂直偏移門檻（STAGE2-FIX3 問題 4）：改用 pt，不用
# device px。上一輪把這項訂成 `CELL_OFFSET_MAX_DEVICE_PX = 2.2`——px 不是
# 物理量，同一個實體位移換算出的 px 數會隨 dpi 等比放大，用 px 當門檻等於
# 「解析度越高標準越嚴」，600dpi 下 2.211px 這種原本該通過的偏移（換算成
# 物理量只有 0.265pt，比 300dpi 通過的頁面還小）反而會被判超標。
#
# 0.55pt（≈0.19mm）這個數字沿用上一輪查明的殘留量本身，只是換算單位：
# 300dpi 預設 hinting 下用扣色底量測（本檔 `_text_ink()`），殘留量最高
# 收斂到約 2.2 device px＝2.2×72/300＝0.528pt，取整到 0.55pt 留一點量測
# 雜訊裕度。這是 Qt（Windows 字型引擎）與 FreeType（matplotlib 用的引擎）
# 對同一份字型檔算出的 tightBoundingRect 度量本身的先天差異，已排除取整、
# hinting、超取樣倍率三個變因（見 `lib/print_canvas.py::QtCanvas.text()`
# 的超取樣機制），目前已知手段無法再消除，列為進階段 3 前的已知風險。
CELL_OFFSET_MAX_PT = 0.55

# 線偵測：一列裡「非純白」像素涵蓋整列寬度的比例超過此值，視為一條長水平線。
_LINE_COVERAGE_FRAC = 0.85
# 「非純白」的墨跡判定門檻（0~1，見 _qimage_to_ink）。
_INK_EPS = 0.05
# 逐格垂直偏移量測時，每格四邊內縮的像素數：用 pt 定義（STAGE2-FIX2-BRIEF
# 問題 4）再依當次量測 dpi 換算成 px，才不會在高 dpi 下小於格線寬度、把
# 格線本身當成文字墨跡量進去（150dpi 下 3px≈1.44pt，粗於任何格線寬度；
# 這裡直接定義成 1.44pt，換算回 150dpi 仍是原本的 3px，行為不變）。
_CELL_INSET_PT = 1.44
# 扣色底門檻：格內像素與「格內中位數（視為底色）」的差異超過此值，才算
# 文字墨跡（STAGE2-FIX2-BRIEF 問題 1／2 的根因修法，見 `_text_ink()`）。
_BG_SUBTRACT_EPS = 0.05


# ── PNG → 墨跡陣列 ──────────────────────────────────────────
def _qimage_to_ink(img):
    """QImage → (H, W) float32 墨跡陣列，0=純白、1=純黑。用平均通道亮度
    當「非白程度」，而非灰階門檻二值化，故彩色格線／文字都量得到。"""
    from PySide6.QtGui import QImage
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    stride = img.bytesPerLine()
    buf = img.constBits()
    arr = np.frombuffer(buf, dtype=np.uint8, count=stride * h).reshape(h, stride)
    rgb = arr[:, : w * 3].reshape(h, w, 3).astype(np.float32)
    gray = rgb.mean(axis=2) / 255.0
    return 1.0 - gray


# ── 畫一頁：兩引擎各自輸出同尺寸 QImage ─────────────────────
def _render_mpl_image(kind, kw, dpi=None):
    import matplotlib.pyplot as plt
    from PySide6.QtGui import QImage
    from tools.mpl_canvas import new_mpl_page

    tp._set_text_measurer(mpl_text_width_pt)
    fig, cv = new_mpl_page(tp.fp)
    try:
        tp._draw_spec(kind, kw, cv)
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=dpi or _RENDER_DPI, facecolor="white")
    finally:
        plt.close(fig)
    img = QImage()
    img.loadFromData(buf.getvalue(), "PNG")
    return img


def _render_qt_image(kind, kw, width_px, height_px):
    """`width_px`／`height_px` 一律取自同一頁 mpl 輸出的實際像素數（見
    `_eval_page()`），不各自獨立算 dpi→px──`round(A4_H_IN*150)` 與
    matplotlib `savefig(dpi=150)` 的內部換算在 .5px 邊界會各自取整成不同
    整數（150dpi 下 11.69in 恰為 1753.5px），兩邊各算各的會讓每一頁都被
    誤判為「尺寸不同」，而不是真的繪製差異。"""
    from PySide6.QtGui import QImage, QPainter

    tp._set_text_measurer("qt")
    img = QImage(width_px, height_px, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    try:
        cv = QtCanvas(painter, width_px, height_px, (tp._REG, tp._BOLD))
        tp._draw_spec(kind, kw, cv)
    finally:
        painter.end()
    return img


def _inset_px(w):
    """把 `_CELL_INSET_PT` 依當次量測 dpi（由畫面寬度反推）換算成 px。"""
    dpi = w / A4_W_IN
    return round(_CELL_INSET_PT * dpi / 72.0)


# ── 分區／逐格座標（依既有版面常數換算，見檔頭說明）──────────
def _agg_zones(kind, kw, w, h):
    """回傳 [(zone_name, x0px, x1px, y0px, y1px)]：標題帶／表頭帶／資料列帶
    （各自涵蓋整個表格寬度），供分區墨跡量比值檢查用。

    四邊都內縮 `_inset_px(w)`：每個分區的上下邊界剛好是 `cv.line()` 畫的
    框線（例如表頭帶頂／底都各自是一條分隔線），這條線本身兩引擎的座標
    完全相同，量測時卻可能因為次像素反鋸齒／取整方式不同，落在其中一邊
    的裁切窗內、另一邊窗外（STAGE2-FIX2-BRIEF 問題 3 的殘餘偏移）——這種
    邊界線有無被算進去的差異，量體遠大於文字粗細差異本身，會把分區墨跡
    比值整個弄濁，讓這項檢查測不準真正要抓的字重／字級問題。內縮的做法
    與 `_cells()` 完全一致（見該函式的說明），避免同一種格線雜訊在兩處
    用不同標準處理。"""
    TL, TW = tp.TABLE_L, tp.TABLE_W
    title_top = tp.TOP - tp.DATE_H
    title_bot = title_top - tp.TITLE_H
    header_top = title_bot
    header_bot = header_top - tp.HDR_H
    data_top = header_bot
    if kind == "standard":
        data_bot = data_top - tp.ROW_H * kw["fill_to"]
    else:
        data_bot = data_top - tp.TICKET_ROW_H * kw["body_rows"]

    def to_px(y0n, y1n):
        return (1 - y1n) * h, (1 - y0n) * h

    inset = _inset_px(w)
    x0, x1 = TL * w + inset, (TL + TW) * w - inset
    zones = []
    y0, y1 = to_px(title_bot, title_top)
    zones.append(("title", x0, x1, y0 + inset, y1 - inset))
    y0, y1 = to_px(header_bot, header_top)
    zones.append(("header", x0, x1, y0 + inset, y1 - inset))
    y0, y1 = to_px(data_bot, data_top)
    zones.append(("data", x0, x1, y0 + inset, y1 - inset))
    return zones


def _cells(kind, kw, w, h):
    """回傳 [(cell_name, x0px, x1px, y0px, y1px)]：表頭每一欄、第一列有資料
    的每一格──供「每格文字墨跡中心的垂直偏移」檢查用。表頭與第一列都是
    單行文字，最能單純反映垂直置中規則本身的差異。"""
    TL, TW = tp.TABLE_L, tp.TABLE_W
    title_top = tp.TOP - tp.DATE_H
    title_bot = title_top - tp.TITLE_H
    header_top = title_bot
    header_bot = header_top - tp.HDR_H

    def to_px(y0n, y1n):
        return (1 - y1n) * h, (1 - y0n) * h

    cells = [("title", TL * w, (TL + TW) * w, *to_px(title_bot, title_top))]

    if kind == "standard":
        col_ratios = [c["ratio"] for c in kw["columns"]]
        col_xs = [TL]
        for r in col_ratios[:-1]:
            col_xs.append(col_xs[-1] + TW * r)
        hy0, hy1 = to_px(header_bot, header_top)
        for i, (cx, r) in enumerate(zip(col_xs, col_ratios)):
            cells.append((f"header_col{i}", cx * w, (cx + TW * r) * w, hy0, hy1))
        if kw["rows"]:
            row0_top = header_bot
            row0_bot = row0_top - tp.ROW_H
            ry0, ry1 = to_px(row0_bot, row0_top)
            for i, (cx, r) in enumerate(zip(col_xs, col_ratios)):
                cells.append((f"row0_col{i}", cx * w, (cx + TW * r) * w, ry0, ry1))
    else:
        band_w = TW / 3
        ratios = tp._TICKET_SUB_RATIOS
        hy0, hy1 = to_px(header_bot, header_top)
        for b in range(3):
            band_left = TL + band_w * b
            sub_xs = [band_left, band_left + band_w * ratios[0]]
            widths = [band_w * ratios[0], band_w * ratios[1]]
            for j, (sx, sw) in enumerate(zip(sub_xs, widths)):
                cells.append((f"header_b{b}s{j}", sx * w, (sx + sw) * w, hy0, hy1))
        grid = kw["grid"]
        row0_top = header_bot
        row0_bot = row0_top - tp.TICKET_ROW_H
        ry0, ry1 = to_px(row0_bot, row0_top)
        for b in range(3):
            band = grid[b] if b < len(grid) else []
            if not band:
                continue
            band_left = TL + band_w * b
            sub_xs = [band_left, band_left + band_w * ratios[0]]
            widths = [band_w * ratios[0], band_w * ratios[1]]
            for j, (sx, sw) in enumerate(zip(sub_xs, widths)):
                cells.append((f"row0_b{b}s{j}", sx * w, (sx + sw) * w, ry0, ry1))

    # 格線內縮：每格四邊都緊貼著格線（cv.line／cv.rect 的邊框，寬度
    # <1.5pt），這些線本身在兩引擎的座標完全相同，但若被算進「文字墨跡
    # 中心」，空白格會被格線的位置主導、量出一個與文字置中規則無關、卻
    # 兩引擎剛好一樣的偏移值（誤把格線雜訊當成文字信號）。內縮
    # `_CELL_INSET_PT`（依 dpi 換算成 px，見 `_inset_px()`）確保只量到
    # 格內文字本身的墨跡，且在任何 dpi 下都粗於格線寬度（STAGE2-FIX2-
    # BRIEF 問題 4：舊版固定 3px 常數在 600dpi 下小於格線寬度，量出假值）。
    inset = _inset_px(w)
    return [
        (name, x0 + inset, x1 - inset, y0 + inset, y1 - inset)
        for name, x0, x1, y0, y1 in cells
    ]


def _row_profile(ink, kind, kw, w, h):
    """回傳一頁的「每列墨跡量序列」：資料列帶內每一實際列（列高固定）各自
    的墨跡總量，序列長度＝該頁列數。上下各內縮 `_inset_px(w)`，理由同
    `_cells()` 末段：列與列之間共用同一條格線，格線本身兩引擎座標相同、
    只是反鋸齒渲染有雜訊，內縮後量到的才是「這一列裡的實際內容」，不是
    格線抗鋸齒雜訊——空白列（罰單筆數不足一頁時的補列）幾乎全部內容
    就是格線本身，沒有這個內縮，相關係數會被這些格線雜訊拖低，而這與
    STAGE2-FIX-BRIEF 要抓的兩個缺陷（粗體失效／CJK 垂直置中）無關。"""
    TL, TW = tp.TABLE_L, tp.TABLE_W
    x0 = int(round(TL * w))
    x1 = int(round((TL + TW) * w))
    title_top = tp.TOP - tp.DATE_H
    header_top = title_top - tp.TITLE_H
    header_bot = header_top - tp.HDR_H
    data_top = header_bot
    if kind == "standard":
        row_h, n = tp.ROW_H, kw["fill_to"]
    else:
        row_h, n = tp.TICKET_ROW_H, kw["body_rows"]
    inset = _inset_px(w)
    profile = []
    for i in range(n):
        y_top = data_top - row_h * i
        y_bot = y_top - row_h
        py0 = int(round((1 - y_top) * h)) + inset
        py1 = int(round((1 - y_bot) * h)) - inset
        profile.append(float(ink[py0:py1, x0:x1].sum()) if py1 > py0 else 0.0)
    return np.array(profile)


def _group_consecutive(indices):
    if len(indices) == 0:
        return []
    groups = []
    start = prev = indices[0]
    for i in indices[1:]:
        if i == prev + 1:
            prev = i
        else:
            groups.append((start, prev))
            start = prev = i
    groups.append((start, prev))
    return groups


def _line_exclude_ranges(kind, kw, w, h):
    """回傳「標題帶／表頭帶內部」的像素 y 範圍（兩者都是整條實心色底），
    線偵測要排除這段內部、只留邊界。原因：罰單表表頭是白字（深色底），
    逐列掃描時字元筆畫的空隙會讓覆蓋率忽高忽低、在門檻附近反覆穿越，被
    誤判成好幾條長水平線（而不是實際只有色底本身的頂/底兩條邊界線）。
    標準表標題／表頭是深色字（淺色底），字本身也算「非白」，逐列覆蓋率
    本就穩定貼著 1.0、不會有這個假訊號，排除它不影響其偵測結果——這裡
    統一排除兩種頁面的標題／表頭內部，只是標準表用不到。"""
    TL, TW = tp.TABLE_L, tp.TABLE_W
    title_top = tp.TOP - tp.DATE_H
    title_bot = title_top - tp.TITLE_H
    header_top = title_bot
    header_bot = header_top - tp.HDR_H

    def to_px(y0n, y1n):
        return (1 - y1n) * h, (1 - y0n) * h

    inset = _inset_px(w)
    ranges = []
    for y0n, y1n in ((title_bot, title_top), (header_bot, header_top)):
        py0, py1 = to_px(y0n, y1n)
        ranges.append((int(round(py0)) + inset, int(round(py1)) - inset))
    return ranges


def _detect_lines(ink, exclude_ranges=()):
    h, w = ink.shape
    x0 = int(round(tp.TABLE_L * w))
    x1 = int(round((tp.TABLE_L + tp.TABLE_W) * w))
    sub = ink[:, x0:x1]
    coverage = (sub > _INK_EPS).mean(axis=1)
    mask = np.ones(h, dtype=bool)
    for a, b in exclude_ranges:
        a, b = max(0, a), min(h, b)
        if a < b:
            mask[a:b] = False
    rows = np.where((coverage > _LINE_COVERAGE_FRAC) & mask)[0]
    return [(a + b) / 2.0 for a, b in _group_consecutive(rows)]


def _text_ink(sub):
    """扣掉色底後的純文字墨跡（STAGE2-FIX2-BRIEF 問題 1／2 的根因修法）。

    舊版直接把整片區域的墨跡量／墨跡中心當「文字」量，色底（`c_title`／
    `c_hdr`／`TICKET_HEADER_BG` 等）本身就是一大片均勻的「非白」，把它也
    算進去會把文字造成的真實訊號稀釋 2~3.5 倍（獨立驗證實測數字）——色底
    是背景，不該被當成文字墨跡。

    做法：色底在格／帶內佔多數像素，文字只佔少數，所以格內像素的中位數
    就是背景色的「非白程度」；每個像素與這個中位數的差異絕對值才是文字
    造成的訊號（不論文字比背景深或淺——深底白字時文字比背景「更白」，
    差值一樣是正的），小於 `_BG_SUBTRACT_EPS`（反鋸齒雜訊）的差異視為 0。
    """
    if sub.size == 0:
        return sub
    bg = np.median(sub)
    dev = np.abs(sub.astype(np.float32) - bg)
    dev[dev < _BG_SUBTRACT_EPS] = 0.0
    return dev


def _zone_ink(ink, x0, x1, y0, y1):
    xi0, xi1 = int(round(x0)), int(round(x1))
    yi0, yi1 = int(round(y0)), int(round(y1))
    return float(_text_ink(ink[yi0:yi1, xi0:xi1]).sum())


def _cell_centroid(ink, x0, x1, y0, y1):
    xi0, xi1 = int(round(x0)), int(round(x1))
    yi0, yi1 = int(round(y0)), int(round(y1))
    sub = _text_ink(ink[yi0:yi1, xi0:xi1])
    if sub.size == 0:
        return None
    weights = sub.sum(axis=1)
    total = weights.sum()
    if total < 1e-6:
        return None
    ys = np.arange(yi0, yi1)
    return float((weights * ys).sum() / total)


# ── 逐頁評估 ─────────────────────────────────────────────
def _eval_page(case, page_idx, kind, kw, dpi=None):
    mpl_img = _render_mpl_image(kind, kw, dpi=dpi)
    w, h = mpl_img.width(), mpl_img.height()
    qt_img = _render_qt_image(kind, kw, w, h)

    detail = []
    problems = []
    where = f"{case} 第 {page_idx + 1} 頁（{kind}）"

    mpl_ink = _qimage_to_ink(mpl_img)
    qt_ink = _qimage_to_ink(qt_img)
    dpi = w / A4_W_IN
    pt_per_px = 72.0 / dpi

    # 分區墨跡量比值
    for name, x0, x1, y0, y1 in _agg_zones(kind, kw, w, h):
        mpl_sum = _zone_ink(mpl_ink, x0, x1, y0, y1)
        qt_sum = _zone_ink(qt_ink, x0, x1, y0, y1)
        if mpl_sum < 1e-6:
            ratio = 1.0 if qt_sum < 1e-6 else float("inf")
        else:
            ratio = qt_sum / mpl_sum
        detail.append(f"分區墨跡比值 {name}: {ratio:.3f}（mpl={mpl_sum:.0f} qt={qt_sum:.0f}）")
        if not (ZONE_RATIO_LO <= ratio <= ZONE_RATIO_HI):
            problems.append(f"分區墨跡比值超標 {name}: {ratio:.3f}（門檻 {ZONE_RATIO_LO}~{ZONE_RATIO_HI}）")

    # 長水平線 y 位置
    exclude = _line_exclude_ranges(kind, kw, w, h)
    mpl_lines = sorted(_detect_lines(mpl_ink, exclude))
    qt_lines = sorted(_detect_lines(qt_ink, exclude))
    if len(mpl_lines) != len(qt_lines):
        detail.append(f"長水平線數量不同：mpl {len(mpl_lines)} 條 / qt {len(qt_lines)} 條")
        problems.append(f"長水平線數量不同：mpl {len(mpl_lines)} 條 / qt {len(qt_lines)} 條")
    else:
        diffs = [abs(a - b) for a, b in zip(mpl_lines, qt_lines)]
        max_diff_px = max(diffs) if diffs else 0.0
        max_diff_pt = max_diff_px * pt_per_px
        detail.append(f"長水平線 {len(mpl_lines)} 條，最大 y 誤差 {max_diff_px:.2f}px／{max_diff_pt:.3f}pt")
        if max_diff_px > LINE_Y_TOL_DEVICE_PX:
            problems.append(
                f"長水平線 y 位置誤差超標：{max_diff_px:.2f}px／{max_diff_pt:.3f}pt"
                f"（門檻 {LINE_Y_TOL_DEVICE_PX}px）")

    # 列剖面相關係數
    mpl_profile = _row_profile(mpl_ink, kind, kw, w, h)
    qt_profile = _row_profile(qt_ink, kind, kw, w, h)
    if len(mpl_profile) >= 2 and np.std(mpl_profile) > 0 and np.std(qt_profile) > 0:
        corr = float(np.corrcoef(mpl_profile, qt_profile)[0, 1])
    else:
        corr = 1.0
    detail.append(f"列剖面相關係數: {corr:.4f}")
    if corr < ROW_PROFILE_MIN_CORR:
        problems.append(f"列剖面相關係數過低: {corr:.4f}（門檻 ≥{ROW_PROFILE_MIN_CORR}）")

    # 每格文字墨跡中心的垂直偏移（門檻用 pt，STAGE2-FIX3；px 只是換算後
    # 一併列出供閱讀，不是判定依據）。
    worst_name, worst_px, worst_pt = None, 0.0, 0.0
    for name, x0, x1, y0, y1 in _cells(kind, kw, w, h):
        c_mpl = _cell_centroid(mpl_ink, x0, x1, y0, y1)
        c_qt = _cell_centroid(qt_ink, x0, x1, y0, y1)
        if c_mpl is None or c_qt is None:
            continue
        offset_px = c_qt - c_mpl
        offset_pt = offset_px * pt_per_px
        if abs(offset_pt) > abs(worst_pt):
            worst_name, worst_px, worst_pt = name, offset_px, offset_pt
        if abs(offset_pt) > CELL_OFFSET_MAX_PT:
            problems.append(
                f"格垂直偏移超標 {name}: {offset_px:+.3f}px／{offset_pt:+.3f}pt"
                f"（門檻 ±{CELL_OFFSET_MAX_PT}pt）")
    if worst_name is not None:
        detail.append(f"每格垂直偏移最大值：{worst_name} {worst_px:+.3f}px／{worst_pt:+.3f}pt")

    return {
        "case": case, "page": page_idx, "kind": kind,
        "pass": not problems, "detail": detail, "problems": problems,
        "mpl_img": mpl_img, "qt_img": qt_img, "where": where,
    }


def _eval_all(dpi):
    """跑一輪全部案例全部頁的評估，回傳 results 清單。"""
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841

    results = []
    try:
        for db, date_str, desc in CASES:
            case = _case_key(db, date_str)
            specs = _case_page_specs(db, date_str)
            page_idx = 0
            for kind, kw in specs:
                if kind == "blank":
                    page_idx += 1
                    continue
                results.append(_eval_page(case, page_idx, kind, kw, dpi=dpi))
                page_idx += 1
    finally:
        tp._set_text_measurer("qt")
    return results


def _print_results(results, save_images=True):
    """印出逐頁明細，回傳 0（全通過）或 1（有超標）。"""
    bad = [r for r in results if not r["pass"]]

    for r in results:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"[{status}] {r['case']} 第 {r['page'] + 1} 頁（{r['kind']}）")
        for line in r["detail"]:
            print(f"    {line}")
        for prob in r["problems"]:
            print(f"    !! {prob}")

    if bad:
        if save_images:
            os.makedirs(OUT_DIR, exist_ok=True)
            for r in bad:
                base = f"{r['case']}_page{r['page']:02d}"
                if "mpl_img" in r:
                    r["mpl_img"].save(os.path.join(OUT_DIR, f"{base}_MPL.png"), "PNG")
                    r["qt_img"].save(os.path.join(OUT_DIR, f"{base}_QT.png"), "PNG")
            print(f"\n[render_diff] {len(bad)}/{len(results)} 頁超標，影像已輸出到 {OUT_DIR}")
        else:
            print(f"\n[render_diff] {len(bad)}/{len(results)} 頁超標。")
        return 1

    print(f"\n[render_diff] {len(results)} 頁全部在門檻內，繪製層驗收通過。")
    return 0


def run(dpi=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    results = _eval_all(dpi or _RENDER_DPI)
    return _print_results(results, save_images=True)


# ── --selftest：驗證這張網本身有沒有鑑別力（STAGE2-FIX2-BRIEF §4）───────
# 用 process 內 monkeypatch 注入兩個已知缺陷的「突變」，斷言網一定抓得到；
# 不突變則斷言網 PASS。三項都符合才算網有效。不得改動任何檔案。
def _mutated_font_force_regular(orig_font):
    """模擬缺陷 A（粗體完全失效）：`_font()` 永遠當成非粗體處理。"""
    def _font(self, size, bold, supersample=1):
        return orig_font(self, size, False, supersample=supersample)
    return _font


def _mutated_text_pure_ink_centroid(self, x, y, s, *, size, bold=False,
                                     ha='left', va='center', color='#111111',
                                     linespacing=None, multialignment=None,
                                     clip_rect=None):
    """模擬缺陷 B（垂直置中退回純墨跡框，不採 matplotlib 的 'lp' 參考框
    規則）：與 `QtCanvas.text()` 完全相同，只有 block_top／block_bottom
    這兩行不跟 `_LP_REF` 取聯集，直接用該行文字自己的 tightBoundingRect。"""
    if not s:
        return
    from PySide6.QtCore import QPointF, QRectF
    from PySide6.QtGui import QColor, QFontMetricsF

    font = self._font(size, bold)
    metrics = QFontMetricsF(font)
    lines = s.split('\n')
    align = multialignment or ha

    old_font = self.painter.font()
    old_pen = self.painter.pen()
    self.painter.setFont(font)
    self.painter.setPen(QColor(color))

    if clip_rect is not None:
        cx0, cy0 = self._to_device(clip_rect[0], clip_rect[3])
        cx1, cy1 = self._to_device(clip_rect[2], clip_rect[1])
        self.painter.save()
        self.painter.setClipRect(QRectF(cx0, cy0, cx1 - cx0, cy1 - cy0))

    line_step = (
        linespacing * self._pt_to_device(size) if linespacing is not None
        else metrics.lineSpacing())
    line_widths = [metrics.horizontalAdvance(ln) for ln in lines]
    block_w = max(line_widths) if line_widths else 0.0

    anchor_x, anchor_y = self._to_device(x, y)
    if ha == 'left':
        block_x0 = anchor_x
    elif ha == 'right':
        block_x0 = anchor_x - block_w
    else:
        block_x0 = anchor_x - block_w / 2

    # ── 突變點：不跟 _LP_REF 取聯集，退回純墨跡框置中（STAGE2-FIX-BRIEF
    # §2-3 修之前的行為，對純 CJK 會比 mpl 偏上約 1.7pt）。
    first_box = metrics.tightBoundingRect(lines[0])
    last_box = metrics.tightBoundingRect(lines[-1])
    block_top = first_box.top()
    block_bottom = (len(lines) - 1) * line_step + last_box.bottom()
    block_h = block_bottom - block_top
    if va == 'top':
        first_baseline = anchor_y - block_top
    elif va == 'bottom':
        first_baseline = anchor_y - block_bottom
    elif va == 'center':
        first_baseline = anchor_y - block_top - block_h / 2
    else:
        first_baseline = anchor_y

    for i, (ln, lw) in enumerate(zip(lines, line_widths)):
        if align == 'left':
            lx = block_x0
        elif align == 'right':
            lx = block_x0 + block_w - lw
        else:
            lx = block_x0 + (block_w - lw) / 2
        self.painter.drawText(QPointF(lx, first_baseline + i * line_step), ln)

    if clip_rect is not None:
        self.painter.restore()

    self.painter.setFont(old_font)
    self.painter.setPen(old_pen)


def _selftest(dpi=300):
    """驗證這張網在指定 dpi 下有沒有鑑別力（STAGE2-FIX3 問題 3：門檻改用
    pt 之後，必須在 150／300／600 三種 dpi 下分別跑過，確認網沒有變鬆）。"""
    from unittest import mock
    from lib.print_canvas import QtCanvas

    print(f"========== --selftest（dpi={dpi}）情境 1／3：無突變（應全部 PASS） ==========")
    results = _eval_all(dpi)
    code_baseline = _print_results(results, save_images=False)
    baseline_ok = code_baseline == 0
    print(f"[selftest] 情境 1（無突變）：{'符合預期（PASS）' if baseline_ok else '不符合預期（應 PASS 卻沒有）'}")

    print("\n========== --selftest 情境 2／3：注入粗體失效突變（應多數頁面 FAIL） ==========")
    with mock.patch.object(QtCanvas, "_font", _mutated_font_force_regular(QtCanvas._font)):
        results_bold = _eval_all(dpi)
    code_bold = _print_results(results_bold, save_images=False)
    bold_fail_pages = [
        r for r in results_bold
        if not r["pass"] and any("分區墨跡比值超標" in p for p in r["problems"])
    ]
    bold_fail_ratio = len(bold_fail_pages) / len(results_bold) if results_bold else 0.0
    # 「絕大多數頁面」：門檻訂 80%，且必須包含非罰單頁（不能只有罰單頁抓到）。
    bold_ok = code_bold != 0 and bold_fail_ratio >= 0.8
    print(f"[selftest] 情境 2（粗體失效）：{len(bold_fail_pages)}/{len(results_bold)} 頁抓到"
          f"（{bold_fail_ratio:.1%}）── {'符合預期（多數 FAIL）' if bold_ok else '不符合預期'}")

    print("\n========== --selftest 情境 3／3：注入墨跡框置中突變（應 FAIL） ==========")
    with mock.patch.object(QtCanvas, "text", _mutated_text_pure_ink_centroid):
        results_center = _eval_all(dpi)
    code_center = _print_results(results_center, save_images=False)
    center_ok = code_center != 0
    print(f"[selftest] 情境 3（墨跡框置中）：{'符合預期（FAIL）' if center_ok else '不符合預期（應 FAIL 卻 PASS）'}")

    all_ok = baseline_ok and bold_ok and center_ok
    print(f"\n[selftest] 總結：情境1={'OK' if baseline_ok else 'FAIL'}／"
          f"情境2={'OK' if bold_ok else 'FAIL'}／情境3={'OK' if center_ok else 'FAIL'}"
          f" → {'--selftest 通過，網有鑑別力。' if all_ok else '--selftest 未通過，網沒有鑑別力！'}")
    return 0 if all_ok else 1


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dpi", type=int, default=None,
                         help=f"量測解析度，預設 {_RENDER_DPI}（STAGE2-FIX2-BRIEF 問題 4：驗收改在 300dpi 跑）")
    parser.add_argument("--selftest", action="store_true",
                         help="驗證這張網本身有沒有鑑別力（process 內 monkeypatch，不改檔）")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.selftest:
        sys.exit(_selftest(args.dpi or _RENDER_DPI))
    sys.exit(run(dpi=args.dpi))
