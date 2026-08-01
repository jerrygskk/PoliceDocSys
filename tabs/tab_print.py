import os
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import date

from lib.print_canvas import QtCanvas

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QDateEdit, QFileDialog,
)
from PySide6.QtCore import Qt, QDate, QMarginsF
from PySide6.QtGui  import QPixmap, QImage, QPainter, QPageSize, QPdfWriter
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog

from lib.base_tab import BaseTab
from lib.db_utils import getResourcePath, printTitle, printTitlesUnset
from lib.ticket_utils import TICKET_RECEIPT_DATE_COL, ticketNoNaturalKey
from ui_utils import loadUi, msgInfo, msgWarning
from ui_utils import runWithBusy

# ── 字型（跨平台）────────────────────────────────────────
def _find_cjk_fonts():
    import os
    candidates = {
        'reg': [
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',  # Linux
            '/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc',
            r'C:\Windows\Fonts\msjh.ttc',      # Windows 微軟正黑體
            r'C:\Windows\Fonts\mingliu.ttc',
            r'C:\Windows\Fonts\kaiu.ttf',
            r'C:\Windows\Fonts\simsun.ttc',
            '/System/Library/Fonts/PingFang.ttc',  # macOS
        ],
        'bold': [
            '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc',
            '/usr/share/fonts/noto-cjk/NotoSansCJK-Bold.ttc',
            r'C:\Windows\Fonts\msjhbd.ttc',
            r'C:\Windows\Fonts\msjh.ttc',
            r'C:\Windows\Fonts\kaiu.ttf',
            '/System/Library/Fonts/PingFang.ttc',
        ],
    }
    reg  = next((p for p in candidates['reg']  if os.path.exists(p)), None)
    bold = next((p for p in candidates['bold'] if os.path.exists(p)), None)
    if reg is None:
        raise FileNotFoundError(
            '找不到中文字型，請確認系統已安裝微軟正黑體（msjh.ttc）')
    return reg, bold or reg

_REG, _BOLD = _find_cjk_fonts()


class FontSpec:
    """輕量字型描述：`fp()` 的回傳型別（階段 3 起不再依賴 matplotlib 的
    `FontProperties`）。只帶版面計算需要的三樣東西：字型檔路徑、字級(pt)、
    是否粗體。`get_size()` 保留是為了讓 `_draw_page()`／`drawTicketPage()`
    既有的 `font.get_size()` 呼叫點不必逐一改寫。"""
    __slots__ = ('path', 'size', 'bold')

    def __init__(self, path, size, bold=False):
        self.path = path
        self.size = size
        self.bold = bold

    def get_size(self):
        return self.size


def fp(size, bold=False):
    return FontSpec(_BOLD if bold else _REG, size, bold)

# ── A4 直向（inch）────────────────────────────────────────
A4_W, A4_H = 8.27, 11.69

# ── 版面常數（normalized 0~1）────────────────────────────
R        = 0.03
TOP      = 0.95
BOT      = 0.03
TITLE_H  = 0.050
HDR_H    = 0.038
ROW_H    = 0.052
DATE_H   = 0.030
PAD      = 0.008
TABLE_L  = 0.03
TABLE_W  = 1 - TABLE_L - R

NOTE = '＜現行犯已隨案移送免簽收＞'


# ── 工具函式 ──────────────────────────────────────────────
def _fmt_date(d):
    if not d: return ''
    try:
        y, m, day = d.split('-')
        return f'{y}/{m}/{day}'
    except: return d

def _today():
    return date.today().strftime('%Y/%m/%d')

_A4_PT = 595.3   # A4 寬（pt），1 inch=72pt × 8.27 ≈ 595.3


# 產品量測器（階段 3 起唯一內建後端，取代舊版預設的 matplotlib 量測）。
# ⚠️ 量測基準固定 1200dpi、與任何實際繪製 device 的解析度無關（STAGE2-
# BRIEF §3-1）：階段 0 實測過，低 dpi 下 Qt 會把每個字的寬度取整到整數
# device pixel，換行結果對不上（96dpi 下就有 1 條截斷差異）。
_QT_MEASURE_DPI = 1200
_qt_measure_font_cache = {}
def _qt_text_width_pt(text, prop):
    """`prop` 是 `fp()` 回傳的 `FontSpec`（`.path`／`.size`／`.bold`）。

    ⚠️ 一定要呼叫 `setBold()`：本機 msjh.ttc／msjhbd.ttc 回傳的 family 名
    完全相同（見 lib/print_canvas.py `_load_font_family()` 說明），若只靠
    `QFont(family)` 不設字重旗標，量到的永遠是 regular 字重的寬度——這與
    缺陷 A（QtCanvas 粗體失效）同一個根因。`_wrap_clamp()`／`_fit_font()`
    目前都只用 `fp(size)`（非粗體）呼叫本函式，所以還沒有實際爆開；一併
    修掉是因為階段 3 擴大 Qt 量測範圍到粗體文字時就會踩到同一個雷
    （STAGE2-FIX2-BRIEF §5）。直接用 `prop.bold`（`FontSpec` 明確欄位），
    不再靠字型 family 名或路徑比對判斷字重。"""
    from PySide6.QtGui import QFont, QFontMetricsF
    from lib.print_canvas import _load_font_family
    path, size, bold = prop.path, prop.size, prop.bold
    key = (path, size, bold)
    font = _qt_measure_font_cache.get(key)
    if font is None:
        font = QFont(_load_font_family(path))
        font.setBold(bold)
        font.setPixelSize(max(1, round(size * _QT_MEASURE_DPI / 72.0)))
        _qt_measure_font_cache[key] = font
    width_px = QFontMetricsF(font).horizontalAdvance(text or "")
    return width_px * 72.0 / _QT_MEASURE_DPI


# 產品行為預設：一律走 Qt 量測，_TEXT_WIDTH_FN 全程不 import matplotlib。
# 比對工具（tools/render_diff.py、tools/engine_diff.py、
# tools/print_baseline.py）用 `_set_text_measurer(tools.mpl_canvas.
# mpl_text_width_pt)` 切到 matplotlib 版比對，比完務必切回
# `_set_text_measurer('qt')`（或直接開新 process），不得讓這個全域狀態
# 滲透到產品路徑。matplotlib 量測器本身已搬到 tools/mpl_canvas.py——
# 本檔（tabs/tab_print.py）刻意不 import 它，只接受呼叫端傳進來的函式物件，
# 才能保證 `import tabs.tab_print` 全程不觸發 matplotlib import
# （見 tools/check_no_matplotlib.py）。
_TEXT_WIDTH_FN = _qt_text_width_pt
def _text_width_pt(text, prop):
    return _TEXT_WIDTH_FN(text, prop)


def _set_text_measurer(measurer):
    """切換 `_text_width_pt()` 的量測後端：字串 `'qt'`（預設、內建）或直接
    傳入量測函式物件（例如 `tools/mpl_canvas.py::mpl_text_width_pt`，供
    比對工具切到 matplotlib 版）。`_wrap_clamp()` 的演算法本身不因此改變，
    只換「量一個字串多寬」這個動作的實作。"""
    global _TEXT_WIDTH_FN
    _TEXT_WIDTH_FN = _qt_text_width_pt if measurer == 'qt' else measurer


def _wrap_clamp(text, col_width_norm, max_lines=2, pad=PAD, fixed_size=None):
    """
    fixed_size=None（預設）：12pt先試，超過縮10pt，還超過截斷加…
    fixed_size=N：固定N pt不縮小，超過直接截斷加…
    回傳 (wrapped_text, font_prop)

    換行寬度以 matplotlib 真實字型度量計（_text_width_pt），不再用估算係數。
    """
    if not text:
        return '', fp(fixed_size or 12)

    A4_PT    = _A4_PT
    # 可用寬＝欄寬扣左右內距（保留約 1.2×PAD 邊距，文字不貼欄線）。
    max_w_pt = (col_width_norm - pad * 1.2) * A4_PT

    def wrap(t, size):
        prop = fp(size)
        lines, line = [], ''
        for ch in t:
            if line and _text_width_pt(line + ch, prop) > max_w_pt:
                lines.append(line); line = ch
            else:
                line += ch
        if line: lines.append(line)
        return lines

    def truncate(lines, size):
        lines = lines[:max_lines]
        prop = fp(size)
        last = lines[-1]
        while last and _text_width_pt(last + '…', prop) > max_w_pt:
            last = last[:-1]
        lines[-1] = last + '…'
        return '\n'.join(lines), fp(size)

    if fixed_size:
        # 固定字體，只截斷不縮小
        lines = wrap(text, fixed_size)
        if len(lines) <= max_lines:
            return '\n'.join(lines), fp(fixed_size)
        return truncate(lines, fixed_size)

    # 試 12pt
    lines = wrap(text, 12)
    if len(lines) <= max_lines:
        return '\n'.join(lines), fp(12)

    # 縮到 10pt
    lines = wrap(text, 10)
    if len(lines) <= max_lines:
        return '\n'.join(lines), fp(10)

    # 還超過：截斷
    return truncate(lines, 10)


def _fit_font(text, col_width_norm, max_size=14, min_size=8, pad=PAD):
    """自動縮小字體，讓文字剛好放進欄寬（不換行）"""
    if not text:
        return fp(max_size)
    A4_PT    = 595.3
    max_w_pt = (col_width_norm - pad * 2) * A4_PT * 0.86

    for size in range(max_size, min_size - 1, -1):
        def char_w(ch):
            return size if ord(ch) > 0x2E80 else size * 0.6
        w = sum(char_w(c) for c in text)
        if w <= max_w_pt:
            return fp(size)
    return fp(min_size)



def _rows_per_page():
    avail = TOP - DATE_H - TITLE_H - HDR_H - BOT
    return max(1, int(avail / ROW_H))


# ── 畫單頁 ────────────────────────────────────────────────
# 色彩配置：(標題背景, 表頭背景, 奇數列背景, 外框/欄線, 標題文字)
SCHEMES = {
    'task':     ('#B3C6E6', '#C9D9EE', '#DDEBF7', '#4472C4', '#1F3864'),
    'criminal': ('#6B8E4E', '#A8C68F', '#EEF5E8', '#4A6A32', '#1E3B12'),
    'general':  ('#F4B183', '#F8CBAD', '#FCE4D6', '#C05000', '#3D1500'),
    'reward':   ('#9B8BB8', '#C4B7D7', '#F1EDF6', '#66547F', '#2E2238'),
    'ticket':   ('#8FA8C7', '#B9CBE0', '#EAF0F7', '#4A6D93', '#1B3049'),
}

STANDARD_COLUMNS = (
    {'header': '編號', 'role': 'id', 'ratio': 0.07},
    {'header': '發文日期', 'role': 'date', 'ratio': 0.146},
    {'header': '業務組／案類', 'role': 'category', 'ratio': 0.13},
    {'header': '承辦人', 'role': 'handler', 'ratio': 0.15},
    {'header': '主旨', 'role': 'subject', 'ratio': 0.234, 'stretch': True},
    {'header': '簽收', 'role': 'signature', 'ratio': 0.27},
)
REWARD_COLUMNS = (
    {'header': '編號', 'role': 'id', 'ratio': 0.07},
    {'header': '發文日期', 'role': 'date', 'ratio': 0.146},
    {'header': '敘獎人員', 'role': 'recipients', 'ratio': 0.23},
    {'header': '敘獎事由', 'role': 'subject', 'ratio': 0.284, 'stretch': True,
     'header_align': 'center'},
    {'header': '簽收', 'role': 'signature', 'ratio': 0.27},
)

def _draw_page(side_label, table_title, print_date, disp_date,
               columns, rows, fill_to, is_crim=False,
               page_num=1, total_pages=1, scheme='task', note_text=NOTE,
               *, canvas):
    """畫一頁到 `canvas`（必填：`QtCanvas`、`RecordingCanvas()`，或
    `tools/mpl_canvas.py::MatplotlibCanvas` 供比對用）。**只畫圖，不建立
    也不回傳 figure**——本函式不再擁有繪圖裝置的生命週期，那是呼叫端
    （`generate_pages()`／比對工具）的責任。"""
    cv = canvas
    c_title, c_hdr, c_row_odd, c_border, c_text = SCHEMES[scheme]
    headers = [c['header'] for c in columns]
    col_ratios = [c['ratio'] for c in columns]

    # 列印日期（左）
    cv.text(TABLE_L + PAD, TOP - DATE_H/2,
            f'列印日期　{print_date}',
            size=8, ha='left', va='center', color='#333333')
    # 發文日期（右，粗體）
    cv.text(1-R-PAD, TOP - DATE_H/2,
            f'發文日期：{disp_date}',
            size=10, bold=True, ha='right', va='center', color=c_text)
    cy = TOP - DATE_H

    # 大標題
    cv.rect(TABLE_L, cy-TITLE_H, TABLE_W, TITLE_H,
            facecolor=c_title, linewidth=0, zorder=1)
    cv.text(TABLE_L + TABLE_W/2, cy - TITLE_H/2, table_title,
            size=14, bold=True, ha='center', va='center', color=c_text)
    cy -= TITLE_H

    # 欄 x 位置
    col_xs = [TABLE_L]
    for r in col_ratios[:-1]:
        col_xs.append(col_xs[-1] + TABLE_W * r)

    # 表頭
    # 表頭上方粗分隔線
    cv.line(TABLE_L, cy, TABLE_L+TABLE_W, cy,
            color=c_border, linewidth=0.8, zorder=4)

    cv.rect(TABLE_L, cy-HDR_H, TABLE_W, HDR_H,
            facecolor=c_hdr, linewidth=0, zorder=1)
    for hidx, (hdr, cx, column) in enumerate(zip(headers, col_xs, columns)):
        if column.get('header_align') == 'center' or column['role'] != 'subject':
            x_pos = cx + TABLE_W * col_ratios[hidx] / 2
            ha = 'center'
        else:
            x_pos = cx + PAD
            ha = 'left'
        cv.text(x_pos, cy-HDR_H/2, hdr,
                size=12, bold=True, ha=ha, va='center', color=c_text)
    cv.line(TABLE_L, cy-HDR_H, TABLE_L+TABLE_W, cy-HDR_H,
            color=c_border, linewidth=0.8)
    cy -= HDR_H

    # 資料列
    for ridx in range(fill_to):
        if ridx < len(rows):
            row = rows[ridx]
            if is_crim:
                is_current = str(row[-1]) == 'CS01'   # CS01 = 現行犯（用 ID 判斷，與顯示名脫鉤）
                display = list(row[:-1]) + ['']
            else:
                is_current = False
                display = list(row)
        else:
            display    = [''] * len(headers)
            is_current = False

        bg = c_row_odd if ridx % 2 == 0 else '#FFFFFF'
        cv.rect(TABLE_L, cy-ROW_H, TABLE_W, ROW_H,
                facecolor=bg, linewidth=0, zorder=1)
        # ⚠️ 這一列的字型（font）刻意仍由 fp()／_fit_font()／_wrap_clamp()
        # 產生完整 FontProperties（brief §5：字型度量本階段不動），畫圖時
        # 才用 font.get_size() 換回 Canvas.text() 要的 size；三者內部一律
        # 只呼叫 fp(size)（不帶 bold），故 bold 在這個迴圈恆為 False。

        for val, cx, ratio, column in zip(display, col_xs, col_ratios, columns):
            role = column['role']
            # 依欄位 role 決定排版，不依賴欄位位置。
            if role == 'signature' and is_current:
                text  = note_text
                color = '#C00000'
                font  = fp(10)
                ha    = 'center'
            elif role == 'id':
                text  = str(val) if val else ''
                color = '#111111'
                font  = _fit_font(text, TABLE_W * ratio, max_size=20, min_size=8)
                ha    = 'center'
            elif role == 'date':
                text  = str(val) if val else ''
                color = '#111111'
                font  = fp(10)
                ha    = 'center'
            elif role == 'handler':
                text  = str(val) if val else ''
                color = '#111111'
                font  = fp(12)
                ha    = 'center'
            elif role == 'signature':
                text  = str(val) if val else ''
                color = '#111111'
                font  = fp(12)
                ha    = 'center'
            else:
                text  = str(val) if val else ''
                color = '#111111'
                font  = fp(12)
                ha    = 'left'

            # 長文字欄：業務/案類(2) 超2行縮10pt再截斷；主旨(4) 直接12pt截斷
            if role in ('category', 'recipients', 'subject') and not (role == 'signature' and is_current):
                if role in ('category', 'recipients'):
                    # 刑案類型名稱本身長、長短不一會大小參差又壓迫：刑案此欄固定 10pt
                    # （＝長案類縮後的大小當天花板，整欄一致）。一般陳報的業務單位欄
                    #   不受影響，維持 12→10 自動縮。
                    cat_fs = 10 if is_crim and role == 'category' else None
                    text, font = _wrap_clamp(text, TABLE_W * ratio, max_lines=2,
                                             fixed_size=cat_fs)
                    ha = 'center'   # 業務/案類置中
                else:
                    text, font = _wrap_clamp(text, TABLE_W * ratio, max_lines=2, fixed_size=12)

            # 置中欄用欄位中心 x
            x_pos = cx + TABLE_W * ratio / 2 if ha == 'center' else cx + PAD
            cv.text(x_pos, cy - ROW_H/2, text,
                    size=font.get_size(), bold=False, ha=ha, va='center',
                    color=color, linespacing=1.3, multialignment='left',
                    clip_rect=(0, 0, 1, 1))

        cv.line(TABLE_L, cy-ROW_H, TABLE_L+TABLE_W, cy-ROW_H,
                color=c_border, linewidth=0.5)
        cy -= ROW_H

    # 外框
    box_top = TOP - DATE_H
    box_h   = box_top - cy
    cv.rect(TABLE_L, cy, TABLE_W, box_h,
            edgecolor=c_border, facecolor=None, linewidth=1.2, zorder=3)

    # 欄線
    for cx in col_xs[1:]:
        cv.line(cx, cy, cx, box_top - TITLE_H,
                color=c_border, linewidth=0.5)

    # 左側直排大字已移除

    # 頁碼（底部置中）
    cv.text(0.5, BOT/2,
            str(page_num),
            size=9, ha='center', va='center', color='#555555')


# ── 罰單簽收表：純邏輯層（排序／六欄分組／分頁）────────────
# 設計原則：排序、分頁、rowspan 全部在這裡算完，drawTicketPage() 只消費已
# 整理好的 TicketPage／grid，不得在 renderer 的座標迴圈裡臨時決策資料。
@dataclass
class TicketCell:
    """簽收表單一格的展示資料。

    `issuer_rowspan`：本格所屬「欄內連續同一舉發人員」群組的合併列數；
    群組起始列＝實際列數（≥1），群組內非起始列＝0（renderer 依此判斷
    是否要畫姓名／合併框，不重覆顯示姓名）。由 `buildTicketGrid()` 計算，
    `sortTicketRows()`／`paginateTicketRows()` 產生的清單一律先預設為 1
    （尚未分欄，尚無「群組」概念）。
    """
    doc_id: str = ''
    ticket_no: str = ''
    issuer_id: str = ''
    issuer_name: str = ''
    issuer_sort_order: int = 0
    issuer_rowspan: int = 1


def _toTicketCell(row):
    """`row` 可為 dict（DB 查詢列）或既有 TicketCell（複製一份，避免呼叫端
    重複使用同一物件、被 buildTicketGrid 的原地標記互相污染）。"""
    if isinstance(row, TicketCell):
        return TicketCell(
            doc_id=row.doc_id, ticket_no=row.ticket_no,
            issuer_id=row.issuer_id, issuer_name=row.issuer_name,
            issuer_sort_order=row.issuer_sort_order)
    return TicketCell(
        doc_id=row.get('doc_id', ''),
        ticket_no=row['ticket_no'],
        issuer_id=row.get('issuer_id', ''),
        issuer_name=row['issuer_name'],
        issuer_sort_order=row.get('issuer_sort_order', 0))


def sortTicketRows(rows):
    """依開立人員順序、姓名與共用罰單自然 key 排序。"""
    cells = [_toTicketCell(r) for r in rows]
    cells.sort(key=lambda c: (c.issuer_sort_order, c.issuer_name or "",
                               ticketNoNaturalKey(c.ticket_no)))
    return cells


@dataclass
class TicketPage:
    """一頁簽收表的已整理資料。`items` 為本頁攤平（未分欄）清單，供
    `buildTicketGrid()` 進一步分欄；`grid` 由呼叫端另行以
    `buildTicketGrid(page.items, body_rows)` 產生，本 dataclass 不預先算，
    避免與分頁邏輯耦合。罰單每頁版面固定含簽收格。"""
    items: list
    show_summary: bool = True
    total_count: int = 0
    page_num: int = 1
    total_pages: int = 1


def paginateTicketRows(rows):
    """排序後以固定三組、每組 20 筆分頁；每頁都保留簽收格。

    0 筆回傳空清單（沿用既有 `_build_sections` 慣例：查無資料的類別不產生
    section／頁面）。
    """
    sorted_rows = sortTicketRows(rows)
    total = len(sorted_rows)
    if total == 0:
        return []

    capacity = TICKET_ROWS_PER_BAND * 3
    pages_items = [
        sorted_rows[start:start + capacity]
        for start in range(0, total, capacity)
    ]

    pages = []
    n = len(pages_items)
    for idx, items in enumerate(pages_items, start=1):
        pages.append(TicketPage(
            items=items,
            show_summary=True,
            total_count=total,
            page_num=idx,
            total_pages=n))
    return pages


def buildTicketGrid(rows, body_rows):
    """把一頁的攤平清單（已排序）切成左／中／右三個直欄，每欄最多
    `body_rows` 筆，並在「每欄之內」獨立計算連續同一舉發人員的
    rowspan——跨欄（甚至跨頁，因為每頁各自呼叫本函式）一律重建群組、
    重新顯示姓名，不做全域合併。純資料整形，不畫圖。

    `rows` 可為 dict 或 TicketCell；回傳前一律轉為 TicketCell 新物件。
    """
    if body_rows < 1:
        raise ValueError("body_rows 必須為正整數。")
    cells = [_toTicketCell(r) for r in rows]
    capacity = body_rows * 3
    if len(cells) > capacity:
        raise ValueError(
            f"資料筆數（{len(cells)}）超過本頁欄位容量（{capacity}）。")

    bands = [cells[i * body_rows:(i + 1) * body_rows] for i in range(3)]
    for band in bands:
        _applyLocalRowspan(band)
    return bands


def _applyLocalRowspan(band):
    """單一直欄內，就地標記連續同一 issuer_id 的 rowspan（群組起始列＝
    實際列數；群組內其餘列＝0 且姓名清空，交給 renderer 判斷合併）。"""
    i, n = 0, len(band)
    while i < n:
        j = i
        while (j + 1 < n and band[i].issuer_id
               and band[j + 1].issuer_id == band[i].issuer_id):
            j += 1
        span = j - i + 1
        band[i].issuer_rowspan = span
        for k in range(i + 1, j + 1):
            band[k].issuer_rowspan = 0
            band[k].issuer_name = ''
        i = j + 1


# ── 罰單簽收表：renderer（只消費已整理好的 grid／TicketPage）────
# spec §11.1：每頁三組並排、共六欄（開立人員｜罰單編號 ×3），逐列「簽收」
# 子欄是 Task 8 骨架的規格外殘留，已移除（簽收改為 §11.4 末頁一次性簽收人區）。
TICKET_SUB_HEADERS = ('開立人員', '罰單編號')
# 開立人員欄略窄、罰單編號欄略寬（spec §11.1）；9 碼以上編號需保留足夠寬度
# 不縮字（如 D4RD15263）。
_TICKET_SUB_RATIOS = (0.45, 0.55)

# 罰單簽收表標題：比照既有四張，可在設定頁「簽收表標題」自訂（print_title_ticket）；
# 未設定走 db_utils.PRINT_TITLE_DEFAULTS 的 ○○ 預設（見 printTitle(db_path, 'ticket')）。

# 每頁固定三組 × 20 筆；簽收格沿用其他表的一個可蓋章列高。
TICKET_ROWS_PER_BAND = 20
TICKET_SUMMARY_H = ROW_H
TICKET_BODY_H = TOP - DATE_H - TITLE_H - HDR_H - BOT - TICKET_SUMMARY_H
TICKET_ROW_H = TICKET_BODY_H / TICKET_ROWS_PER_BAND

# 上深下淺兩層網底（比照標準表）：標題帶用原欄名列色，欄名列再淡一階。
# 底色與文字色成對，改一個要一併確認另一個的對比。
TICKET_TITLE_BG = "#B9858E"
TICKET_TITLE_TEXT = "#FFFFFF"
TICKET_HEADER_BG = "#F5EAEC"      # 同總計區底色（TICKET_SUMMARY_BG）
TICKET_HEADER_TEXT = "#333333"
TICKET_OUTER_BORDER = "#743A46"
TICKET_GROUP_BORDER = "#A56B76"
TICKET_GRID_BORDER = "#D7C4C8"
TICKET_SUMMARY_BG = "#F5EAEC"

_TICKET_OUTER_LW = 1.4
_TICKET_GROUP_LW = 0.8
_TICKET_GRID_LW = 0.4


def drawTicketPage(grid, *, table_title, print_date, disp_date, body_rows,
                   page_num=1, total_pages=1, scheme='ticket',
                   show_summary=False, total_count=0, canvas):
    """畫一頁罰單簽收表：三組並排、共六欄（開立人員｜罰單編號 ×3），
    開立人員依 `TicketCell.issuer_rowspan` 合併——本函式只讀取已算好的欄位
    值，不做任何排序、分組或分頁判斷。

    `grid`：`buildTicketGrid()` 回傳的三欄清單。`body_rows`：本頁固定列數
    （用於畫滿版面高度，筆數不足的欄以空白列補滿，維持各頁版面一致，
    比照既有四種簽收表 `_draw_page(fill_to=...)` 的作法）。

    每頁於表格下方加畫一次「本頁／本日總計／簽收人」區。

    `canvas`：必填，畫到哪個 `Canvas`（`QtCanvas`、`RecordingCanvas()`，
    或 `tools/mpl_canvas.py::MatplotlibCanvas` 供比對用）。**只畫圖，不建立
    也不回傳 figure**（與 `_draw_page()` 同一原則）。
    """
    cv = canvas

    cv.text(TABLE_L + PAD, TOP - DATE_H/2, f'列印日期　{print_date}',
            size=8, ha='left', va='center', color='#333333')
    cv.text(1-R-PAD, TOP - DATE_H/2, f'發文日期：{disp_date}',
            size=10, bold=True, ha='right', va='center', color='#333333')
    cy = TOP - DATE_H
    title_top = cy
    # 標題帶：粗外框往上延伸把標題包進來（原本標題浮在框外，導致本表上邊界
    # 比其他四張低一個 TITLE_H）。底色比欄名列深一階，形成上下兩層階層。
    cv.rect(TABLE_L, cy-TITLE_H, TABLE_W, TITLE_H,
            facecolor=TICKET_TITLE_BG, linewidth=0, zorder=1)
    cv.text(TABLE_L + TABLE_W/2, cy - TITLE_H/2, table_title,
            size=14, bold=True, ha='center', va='center',
            color=TICKET_TITLE_TEXT)
    cy -= TITLE_H
    header_top = cy

    band_w = TABLE_W / 3

    def _sub_xs(band_left):
        """回傳該組內每個子欄（開立人員／罰單編號）的左緣 x：長度固定為 2
        （對應 `TICKET_SUB_HEADERS`／`_TICKET_SUB_RATIOS`，皆已移除簽收子欄）。"""
        xs = [band_left]
        for r in _TICKET_SUB_RATIOS[:-1]:
            xs.append(xs[-1] + band_w * r)
        return xs

    # 欄名列：比標題帶淺一階，兩層之間以中階線分隔。
    cv.rect(TABLE_L, cy-HDR_H, TABLE_W, HDR_H,
            facecolor=TICKET_HEADER_BG, linewidth=0, zorder=1)
    cv.line(TABLE_L, cy, TABLE_L+TABLE_W, cy,
            color=TICKET_GROUP_BORDER, linewidth=_TICKET_GROUP_LW, zorder=2)
    for b in range(3):
        sub_xs = _sub_xs(TABLE_L + band_w * b)
        for hdr, sx, ratio in zip(TICKET_SUB_HEADERS, sub_xs, _TICKET_SUB_RATIOS):
            cv.text(sx + band_w*ratio/2, cy-HDR_H/2, hdr,
                    size=11, bold=True, ha='center', va='center',
                    color=TICKET_HEADER_TEXT)
    cy -= HDR_H
    table_top = cy
    table_bottom = table_top - TICKET_ROW_H * body_rows

    # 明細一律純白；整塊鋪底避免逐列 patch 造成斑馬或相鄰邊界疊畫。
    cv.rect(TABLE_L, table_bottom, TABLE_W, table_top - table_bottom,
            facecolor='#FFFFFF', linewidth=0, zorder=0.5)

    # 開立人員合併：只在群組起始列畫姓名。
    for ridx in range(body_rows):
        row_top = table_top - TICKET_ROW_H * ridx
        for b in range(3):
            band = grid[b] if b < len(grid) else []
            sub_xs = _sub_xs(TABLE_L + band_w * b)
            cell = band[ridx] if ridx < len(band) else None
            if cell is None:
                continue
            if cell.issuer_rowspan > 0:
                merge_h = TICKET_ROW_H * cell.issuer_rowspan
                text, font = _wrap_clamp(cell.issuer_name,
                                          band_w*_TICKET_SUB_RATIOS[0],
                                          max_lines=1, fixed_size=12)
                cv.text(sub_xs[0] + band_w*_TICKET_SUB_RATIOS[0]/2,
                        row_top - merge_h/2, text,
                        size=font.get_size(), bold=False, ha='center',
                        va='center', color='#111111')
            no_font = _fit_font(cell.ticket_no, band_w*_TICKET_SUB_RATIOS[1],
                                 max_size=12, min_size=8)
            no_x0 = sub_xs[1]
            no_x1 = sub_xs[1] + band_w*_TICKET_SUB_RATIOS[1]
            # F2：_fit_font 以 8pt 觸底、非精確量測，超長編號（例如 20 字元）仍可能
            # 溢出格寬壓到鄰欄；用該格自己的 bbox 當 clip box（而非整張 axes，
            # ax 涵蓋整頁，單純 clip_on=True 擋不住跨欄溢出），確保超出部分被
            # 裁掉、不污染鄰欄。
            cv.text(no_x0 + (no_x1-no_x0)/2,
                    row_top - TICKET_ROW_H/2, cell.ticket_no,
                    size=no_font.get_size(), bold=False, ha='center',
                    va='center', color='#111111',
                    clip_rect=(no_x0, row_top - TICKET_ROW_H, no_x1, row_top))

    # 簽收格先鋪淡酒紅底，線條稍後統一只畫一次。
    if show_summary:
        summary_top = table_bottom
        summary_bottom = summary_top - TICKET_SUMMARY_H
        cv.rect(TABLE_L, summary_bottom, TABLE_W, TICKET_SUMMARY_H,
                facecolor=TICKET_SUMMARY_BG, linewidth=0, zorder=0.5)
    else:
        summary_top = table_bottom
        summary_bottom = table_bottom

    # 欄名列下緣為一般格線，只畫一次。
    cv.line(TABLE_L, table_top, TABLE_L+TABLE_W, table_top,
            color=TICKET_GRID_BORDER, linewidth=_TICKET_GRID_LW, zorder=2)

    # 兩條三組邊界為中階單線；三條組內直線為一般細線。
    for b in range(3):
        band_left = TABLE_L + band_w * b
        if b > 0:
            cv.line(band_left, table_bottom, band_left, header_top,
                    color=TICKET_GROUP_BORDER, linewidth=_TICKET_GROUP_LW,
                    zorder=2)
        for sx in _sub_xs(band_left)[1:]:
            cv.line(sx, table_bottom, sx, header_top,
                    color=TICKET_GRID_BORDER, linewidth=_TICKET_GRID_LW,
                    zorder=2)

    # 明細共享邊界一次決定：群組結束畫一條中階線跨完整直欄；群組內只畫
    # 罰單編號細線，開立人員合併格不畫；空白補列則畫一般細線。
    for b in range(3):
        band = grid[b] if b < len(grid) else []
        sub_xs = _sub_xs(TABLE_L + band_w * b)
        band_left = TABLE_L + band_w * b
        number_x0, number_x1 = sub_xs[1], band_left + band_w
        for ridx in range(1, body_rows):
            ry = table_top - TICKET_ROW_H * ridx
            starts_group = (
                ridx < len(band) and band[ridx].issuer_rowspan > 0
            )
            ends_last_group = bool(band) and ridx == len(band)
            if starts_group or ends_last_group:
                cv.line(band_left, ry, band_left + band_w, ry,
                        color=TICKET_GROUP_BORDER, linewidth=_TICKET_GROUP_LW,
                        zorder=2)
            elif ridx >= len(band):
                cv.line(band_left, ry, band_left + band_w, ry,
                        color=TICKET_GRID_BORDER, linewidth=_TICKET_GRID_LW,
                        zorder=2)
            else:
                cv.line(number_x0, ry, number_x1, ry,
                        color=TICKET_GRID_BORDER, linewidth=_TICKET_GRID_LW,
                        zorder=2)

    # 每頁 summary：上緣與左右分區皆為中階單線，不加簽名底線。
    if show_summary:
        cv.line(TABLE_L, summary_top, TABLE_L+TABLE_W, summary_top,
                color=TICKET_GROUP_BORDER, linewidth=_TICKET_GROUP_LW,
                zorder=2)
        mid_x = TABLE_L + TABLE_W * 0.5
        cv.line(mid_x, summary_bottom, mid_x, summary_top,
                color=TICKET_GROUP_BORDER, linewidth=_TICKET_GROUP_LW,
                zorder=2)
        page_count = sum(len(band) for band in grid)
        cv.text(TABLE_L + TABLE_W*0.25, (summary_top+summary_bottom)/2,
                f'本頁共 {page_count} 筆，本日總計 {total_count} 筆',
                size=12, bold=True, ha='center', va='center',
                color='#333333')
        cv.text(mid_x + PAD*1.5, (summary_top+summary_bottom)/2,
                '簽收人：',
                size=12, bold=True, ha='left', va='center', color='#333333')

    # 唯一粗框：從標題帶頂端包到簽收格底端（列印日期／發文日期仍在框外），
    # 上邊界因此與其他四張簽收表齊平。
    cv.rect(TABLE_L, summary_bottom, TABLE_W, title_top - summary_bottom,
            edgecolor=TICKET_OUTER_BORDER, facecolor=None,
            linewidth=_TICKET_OUTER_LW, zorder=3)

    cv.text(0.5, BOT/2, str(page_num), size=9, ha='center', va='center',
            color='#555555')


def queryTicketPrintRows(db_path, date_text):
    """查詢指定簽收日可列印的已發文罰單。

    簽收歸屬由資料列本身的 `register_date` 決定，不讀取目前輸入模式；
    因此模式切換不會改變既有罰單應列入哪一天的簽收表。
    """
    conn = sqlite3.connect(db_path)
    try:
        sql = (
            "SELECT doc_id, issuer_id, issuer_name, issuer_sort_order, ticket_no "
            "FROM Document_Ticket_Full "
            f"WHERE {TICKET_RECEIPT_DATE_COL}=? "
            "  AND register_date IS NOT NULL "
            "  AND register_date<>'' "
            "  AND ticket_no IS NOT NULL"
        )
        cur = conn.execute(sql, (date_text,))
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        rows.sort(key=lambda row: (
            row["issuer_sort_order"], row["issuer_name"] or "",
            ticketNoNaturalKey(row["ticket_no"])))
        return rows
    finally:
        conn.close()


def _build_sections(db_path, date_str):
    """查詢指定日期並回傳自帶類別、配色與欄位角色的列印 sections。"""
    conn = sqlite3.connect(db_path)
    try:
        task = conn.execute(
            "SELECT 編號, 發文日期, 業務組, 所承辦人, 交辦事由 "
            "FROM View_Task_Full WHERE 發文日期=? "
            "ORDER BY 紀錄時間 IS NULL, 紀錄時間, CAST(編號 AS INT)",
            (date_str,)).fetchall()
        crim = conn.execute(
            "SELECT v.送文編號, v.陳報日期, v.案類, v.主承辦人, v.嫌疑人_案由, d.case_status "
            "FROM View_Criminal_Full v JOIN Document_Criminal d ON v.送文編號 = d.doc_id "
            "WHERE v.陳報日期=? ORDER BY CAST(v.送文編號 AS INT)",
            (date_str,)).fetchall()
        gen = conn.execute(
            "SELECT 送文編號, 陳報日期, 業務單位, 陳報人, 陳報主旨 "
            "FROM View_General_Full WHERE 陳報日期=? ORDER BY CAST(送文編號 AS INT)",
            (date_str,)).fetchall()
        reward = conn.execute(
            "SELECT doc_id, register_date, recipients, reason "
            "FROM Document_Reward WHERE register_date=? "
            "ORDER BY CAST(doc_id AS INTEGER)", (date_str,)).fetchall()
    finally:
        conn.close()

    def fmt(rows):
        out = []
        for r in rows:
            r = list(r); r[1] = _fmt_date(r[1]); out.append(tuple(r))
        return out

    sections = []
    if task:
        sections.append({'key': 'task', 'side': '交辦單發文',
            'title': printTitle(db_path, 'task'),
            'columns': tuple(
                {**c, 'header': '業務單位'} if c['role'] == 'category' else c
                for c in STANDARD_COLUMNS),
            'rows': fmt(task), 'is_crim': False, 'scheme': 'task'})
    if crim:
        sections.append({'key': 'criminal', 'side': '刑案陳報單發文',
            'title': printTitle(db_path, 'crim'),
            'columns': tuple(
                {**c, 'header': '刑案類型'} if c['role'] == 'category' else c
                for c in STANDARD_COLUMNS),
            'rows': fmt(crim), 'is_crim': True, 'scheme': 'criminal'})
    if gen:
        sections.append({'key': 'general', 'side': '一般陳報單發文',
            'title': printTitle(db_path, 'gen'),
            'columns': tuple(
                {**c, 'header': '業務單位'} if c['role'] == 'category' else c
                for c in STANDARD_COLUMNS),
            'rows': fmt(gen), 'is_crim': False, 'scheme': 'general'})
    if reward:
        reward_rows = [
            (doc_id, _fmt_date(register_date), recipients or '', reason or '', '')
            for doc_id, register_date, recipients, reason in reward
        ]
        sections.append({'key': 'reward', 'side': '敘獎',
            'title': printTitle(db_path, 'reward'), 'columns': REWARD_COLUMNS,
            'rows': reward_rows, 'is_crim': False, 'scheme': 'reward'})
    # 罰單：專用 renderer（六欄＋末頁總計／簽收人），不硬塞既有 subject／unit
    # 欄位（brief Step5 明令）。標題比照既有四張，走 print_title_ticket 設定。
    ticket_rows = queryTicketPrintRows(db_path, date_str)
    if ticket_rows:
        sections.append({'key': 'ticket', 'kind': 'ticket', 'side': '罰單簽收',
            'title': printTitle(db_path, 'ticket'), 'rows': ticket_rows, 'scheme': 'ticket'})
    return sections


# ── 產生所有頁（回傳 figures + pdf_bytes）────────────────
def _standard_section_specs(section, per, note_text, print_date, disp_date):
    """把一個「標準四表」section 展開成 `(kind, kwargs)` 規格清單，純資料
    整形，不畫圖、不建立 canvas——`kind` 恆為 `'standard'`，`kwargs` 是
    `_draw_page()` 除 `canvas` 外的全部關鍵字參數。"""
    rows = section['rows']
    n = max(1, -(-len(rows) // per))
    specs = []
    for page_num, start in enumerate(range(0, max(len(rows), 1), per), start=1):
        chunk = rows[start:start+per]
        specs.append(('standard', dict(
            side_label=section['side'], table_title=section['title'],
            print_date=print_date, disp_date=disp_date,
            columns=section['columns'], rows=chunk, fill_to=per,
            is_crim=section['is_crim'], page_num=page_num, total_pages=n,
            scheme=section['scheme'], note_text=note_text)))
    return specs, n


def _ticket_section_specs(section, print_date, disp_date):
    """罰單專用 renderer 的規格展開：每頁固定三組 × 20 筆且每頁有簽收格；
    不消費 `per`（那是既有四種簽收表的逐頁容量）。"""
    ticket_pages = paginateTicketRows(section['rows'])
    specs = []
    for tpg in ticket_pages:
        grid = buildTicketGrid(tpg.items, body_rows=TICKET_ROWS_PER_BAND)
        specs.append(('ticket', dict(
            grid=grid, table_title=section['title'], print_date=print_date,
            disp_date=disp_date, body_rows=TICKET_ROWS_PER_BAND,
            page_num=tpg.page_num, total_pages=tpg.total_pages,
            scheme=section['scheme'], show_summary=tpg.show_summary,
            total_count=tpg.total_count)))
    return specs, len(ticket_pages)


def _build_page_specs(db_path, date_str, print_date=None, disp_date=None):
    """展開一次要印的所有頁面規格：`[(kind, kwargs), ...]`，
    `kind ∈ {'standard', 'ticket', 'blank'}`（`'blank'` 的 `kwargs` 恆為
    `{}`，供雙面列印每個 section 補一頁）。純資料整形，與繪圖引擎、canvas
    完全無關——`generate_pages()`（產品，Qt）與 `tools/print_baseline.py`
    （比對基準，matplotlib）共用同一份規格，才不會有兩邊分頁/排序邏輯
    各自實作、慢慢長歪的風險。查無資料回傳空清單。

    `print_date`／`disp_date` 省略時分別取 `_today()`／`_fmt_date(date_str)`
    （產品正常呼叫的行為）；比對工具凍結日期時傳入固定字串。"""
    sections = _build_sections(db_path, date_str)
    if not sections:
        return []

    print_date = print_date if print_date is not None else _today()
    disp_date = disp_date if disp_date is not None else _fmt_date(date_str)
    per = _rows_per_page()
    note_text = printTitle(db_path, 'note')

    specs = []
    for section in sections:
        if section.get('kind') == 'ticket':
            section_specs, section_total = _ticket_section_specs(
                section, print_date, disp_date)
        else:
            section_specs, section_total = _standard_section_specs(
                section, per, note_text, print_date, disp_date)
        specs.extend(section_specs)
        # 若此 section 為奇數頁，插入空白頁（雙面印用）。
        if section_total % 2 == 1:
            specs.append(('blank', {}))
    return specs


def _draw_spec(kind, kw, canvas):
    """把一則 `_build_page_specs()` 規格畫到 `canvas` 上；`'blank'` 不畫
    任何東西（canvas 本身的空白底色即為一頁空白頁）。"""
    if kind == 'blank':
        return
    kw = dict(kw)
    if kind == 'ticket':
        grid = kw.pop('grid')
        drawTicketPage(grid, canvas=canvas, **kw)
    else:
        _draw_page(canvas=canvas, **kw)


# 預覽 PNG 解析度：沿用階段 1 以前的 200dpi 等級。⚠️ 已核可的已知差異
# 不再有 `bbox_inches='tight'` 的裁邊，改為整頁
# （留白更接近紙本）。
_PREVIEW_DPI = 200
# PDF 解析度：沿用 tools/qt_pdf_export.py 已驗證可行的設定（1200dpi、A4、
# 零邊界；實測 dpi 誤差 0.081%、內嵌字型、可選取文字、無影像物件）。
_PDF_RESOLUTION = 1200


def _render_preview_png(kind, kw):
    """把一頁規格畫成 200dpi 等級的預覽 PNG bytes（QImage → PNG）。"""
    from PySide6.QtCore import QBuffer, QIODevice

    width_px = round(A4_W * _PREVIEW_DPI)
    height_px = round(A4_H * _PREVIEW_DPI)
    img = QImage(width_px, height_px, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    if kind != 'blank':
        painter = QPainter(img)
        try:
            cv = QtCanvas(painter, width_px, height_px, (_REG, _BOLD))
            _draw_spec(kind, kw, cv)
        finally:
            painter.end()
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, 'PNG')
    return bytes(buf.data())


def _render_pdf_bytes(specs):
    """把整批頁面規格畫成一份向量 PDF（`QPdfWriter`），回傳 bytes。

    `QPdfWriter` 只接受檔名或 `QIODevice`；沿用
    `tools/qt_pdf_export.py::_export_case()` 已驗證可行、以檔名建立的
    方式（而非記憶體內的 `QIODevice`），寫到暫存檔再讀回 bytes、用完即刪，
    避免引入未經驗證的 API 組合。"""
    fd, path = tempfile.mkstemp(suffix='.pdf')
    os.close(fd)
    try:
        writer = QPdfWriter(path)
        writer.setResolution(_PDF_RESOLUTION)
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        w, h = writer.width(), writer.height()
        painter = QPainter(writer)
        try:
            first = True
            for kind, kw in specs:
                if not first:
                    writer.newPage()
                first = False
                if kind == 'blank':
                    continue
                cv = QtCanvas(painter, w, h, (_REG, _BOLD))
                _draw_spec(kind, kw, cv)
        finally:
            painter.end()
        del writer   # 確保 PDF 尾端資料在讀檔前已寫完（見上方說明）。
        with open(path, 'rb') as f:
            return f.read()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def generate_pages(db_path, date_str):
    """回傳預覽 PNG 清單、PDF bytes、頁面規格清單；查無資料時皆回傳 None。

    第三項（`page_specs`）取代舊版的「300dpi 列印用 PNG 清單」：改為
    `_build_page_specs()` 的原始規格，交給 `TabPrint._paint_pages()` 在
    `QPrinter` 上向量直印。"""
    specs = _build_page_specs(db_path, date_str)
    if not specs:
        return None, None, None

    png_list = [_render_preview_png(kind, kw) for kind, kw in specs]
    pdf_bytes = _render_pdf_bytes(specs)
    return png_list, pdf_bytes, specs


# ── Tab 5 UI ──────────────────────────────────────────────
class TabPrint(BaseTab):

    def setup(self, tab_index):
        page = self.tab_widget.widget(tab_index)
        if page is None:
            return

        # 載入 UI（與 tab_report 相同模式）
        ui = loadUi(getResourcePath('layouts/Layout4.ui'))
        if not ui:
            return
        inner = ui.centralWidget()

        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        # 簽收表標題未設定（仍為 ○○ 預設）→ 頂部紅字提醒去設定頁（比照歸檔未設定）
        self._title_warn = QLabel("⚠ 簽收表標題未設定，請至「資料庫設定 → 系統設定」更新")
        self._title_warn.setStyleSheet(
            "background-color: #fdecea; color: #c0392b; border: 1px solid #e74c3c;"
            "border-radius: 8px; padding: 8px 12px; font-weight: 600;")
        self._title_warn.setVisible(False)
        lay.addWidget(self._title_warn)
        lay.addWidget(inner)

        # 取得 UI 元件
        self.date_edit    = inner.findChild(QDateEdit,    'print_date')
        self.btn_gen      = inner.findChild(QPushButton,  'btn_generate')
        self.status_lbl   = inner.findChild(QLabel,       'lbl_status')
        self.btn_download = inner.findChild(QPushButton,  'btn_download')
        self.btn_print    = inner.findChild(QPushButton,  'btn_print')
        self.scroll       = inner.findChild(QScrollArea,  'scroll_preview')

        # 初始化日期
        if self.date_edit:
            self.date_edit.setDate(QDate.currentDate())

        # 按鈕樣式與信號
        _btn_style = """
            QPushButton { color: #111111; }
            QPushButton:disabled { color: #AAAAAA; background-color: #E0E0E0; border: 1px solid #CCCCCC; }
        """
        if self.btn_download:
            self.btn_download.setStyleSheet(_btn_style)
            self.btn_download.clicked.connect(self._on_download)
        if self.btn_print:
            self.btn_print.setStyleSheet(_btn_style)
            self.btn_print.clicked.connect(self._on_print)
        if self.btn_gen:
            self.btn_gen.clicked.connect(self._on_generate)

        # 捲動預覽容器
        self._container = inner.findChild(QWidget, 'scroll_contents')
        self._layout    = self._container.layout() if self._container else QVBoxLayout()
        if self._layout:
            self._layout.setAlignment(Qt.AlignHCenter | Qt.AlignTop)

        self._pdf_bytes   = None
        self._page_specs  = None    # 向量列印用頁面規格（見 generate_pages()）
        self._gen_sig     = None    # 上次「產生」當下的標題指紋，供偵測過期
        self._refresh_title_warn()

        # ── 自助取號模式：結算按鈕群（僅自助模式顯示）──
        _settle_ss = """
            QPushButton {
                background-color: #4977b1; color: #ffffff;
                border: none; border-radius: 8px;
                padding: 6px 18px; font-size: 13pt; font-weight: 600;
            }
            QPushButton:hover   { background-color: #39649a; }
            QPushButton:pressed { background-color: #2d5284; }
        """
        self._settle_group = QWidget()
        settle_hl = QHBoxLayout(self._settle_group)
        settle_hl.setContentsMargins(8, 4, 8, 0)
        settle_hl.setSpacing(12)
        self.btn_settle   = QPushButton("結算發文")
        self.lbl_unissued = QLabel("未發文：計算中…")
        self.lbl_unissued.setStyleSheet("font-size: 13pt; color: #e67e22; font-weight: 600;")
        self.btn_settle.setStyleSheet(_settle_ss)
        settle_hl.addWidget(self.btn_settle)
        settle_hl.addWidget(self.lbl_unissued)
        settle_hl.addStretch()
        self._settle_group.setVisible(False)
        lay.insertWidget(1, self._settle_group)   # 在 title_warn(0) 之後、inner(2) 之前
        self.btn_settle.clicked.connect(self._on_settle)

        # ⚠️ main._onTabChanged 不會對列印頁呼叫 on_activated（只對設定/瀏覽頁），
        # 故自行掛 currentChanged：切回本頁時重算紅字＋清掉過期預覽。
        self._tab_index = tab_index
        try:
            self.tab_widget.currentChanged.connect(self._onShown)
        except Exception:
            pass
        # 初次進入列印頁不一定會觸發 currentChanged（初始索引即本頁時不發），
        # 故在此設定結算群組初始可見性，否則自助模式下按鈕要等切頁才出現。
        self._refresh_settle_group()

    def _titles_sig(self):
        """目前各張表標題與註記的指紋，用來判斷產生後是否被改過。"""
        return tuple(printTitle(self.db_path, w)
                     for w in ("task", "crim", "gen", "reward", "ticket", "note"))

    def _refresh_title_warn(self):
        """簽收表標題未設定（仍 ○○ 預設）時顯示頂部紅字。"""
        w = getattr(self, "_title_warn", None)
        if w is not None:
            w.setVisible(printTitlesUnset(self.db_path))

    def _onShown(self, idx):
        """切回列印頁：重算紅字＋刷新結算群組；若標題改過則作廢過期預覽。"""
        if idx != getattr(self, "_tab_index", -1):
            return
        self._refresh_title_warn()
        self._refresh_settle_group()
        if (self._page_specs and self._gen_sig is not None
                and self._gen_sig != self._titles_sig()):
            self._clear()
            self._pdf_bytes = None
            self._page_specs = None
            if self.btn_download:
                self.btn_download.setEnabled(False)
            if self.btn_print:
                self.btn_print.setEnabled(False)
            if self.status_lbl:
                self.status_lbl.setText("標題已更新，請重新產生")

    def _refresh_settle_group(self):
        """依輸入模式決定是否顯示結算群組，並更新未發文計數。"""
        if not hasattr(self, "_settle_group"):
            return
        from ui_utils.settle_dialog import count_unissued, settle_entry_visible

        try:
            counts = count_unissued(self.db_path)
            count_failed = False
        except Exception:
            counts = {}
            count_failed = True
        show = settle_entry_visible(self.db_path, counts)
        self._settle_group.setVisible(show)
        if show:
            self._refresh_unissued(counts, unavailable=count_failed)

    def _refresh_unissued(self, counts=None, unavailable=False):
        """重算未發文計數並更新 lbl_unissued（依 SETTLE_META 逐型態列出，
        新增結算型態時本處自動涵蓋，不需另改）。

        ⚠️ 只列出「該類別自助取號模式開啟，或送文者輸入模式下仍有未發文殘留」
        的類別，與結算彈窗的類型 chip 同一條規則（`visible_chip_keys`）：
        送文者輸入模式且已無殘留的類別不該出現在這行，否則只開罰單的所裡也會
        看到「刑案 0／一般 0」這種與自己無關的字。"""
        try:
            from ui_utils.settle_dialog import (SETTLE_META, count_unissued,
                                                visible_chip_keys)
            from lib.db_utils import isSelfServiceMode
            if unavailable:
                self.lbl_unissued.setText("未發文：—")
                return
            if counts is None:
                counts = count_unissued(self.db_path)
            per_type = {m["key"]: counts.get(m["key"], 0) for m in SETTLE_META}
            modes = {m["key"]: isSelfServiceMode(self.db_path, m["key"])
                     for m in SETTLE_META}
            shown = visible_chip_keys(modes, per_type)
            total = sum(per_type.values())
            parts = "／".join(f"{m['label']} {per_type[m['key']]}"
                              for m in SETTLE_META if m["key"] in shown)
            self.lbl_unissued.setText(
                f"未發文：{total} 筆（{parts}）" if parts
                else f"未發文：{total} 筆")
        except Exception:
            self.lbl_unissued.setText("未發文：—")

    def _on_settle(self):
        """開啟結算彈窗，成功後以實際結算日自動產生簽收表。"""
        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db_path, parent=self.tab_widget)
        dlg.exec()
        if dlg.settled():
            self._refresh_settle_group()
            # 結算會補上敘獎的發文日期／人員 → 敘獎登錄頁的本次登錄清單與
            # 瀏覽頁敘獎子頁都可能過期，標記下次顯示時重載。
            self._flagRewardReload()
            self._flagConvertReload(("crim", "gen", "reward", "ticket"))
            # 結算後以對話框實際選定的發文日產生簽收表（一條龍動線）
            if self.date_edit:
                self.date_edit.setDate(dlg.settledDate())
            self._on_generate()

    def _flagRewardReload(self):
        """標記敘獎登錄頁：下次切入時依 DB 重建本次登錄清單（發文日期已改變）。"""
        try:
            mgr = getattr(self, "_manager", None)
            for t in getattr(mgr, "tabs", {}).values():
                if hasattr(t, "reward_data_dirty"):
                    t.reward_data_dirty = True
        except Exception:
            pass

    def on_activated(self):
        # 切入列印頁時刷新「標題未設定」提醒（保險：若框架日後改為會呼叫）
        self._refresh_title_warn()

    def _on_generate(self):
        # 前景產生＋modal「產生中」popup：改在主執行緒同步畫（Qt 繪圖走
        # 全域字型快取／QPainter 狀態，不宜在背景執行緒跑），期間以 popup
        # 擋住互動，畫完即關（單機 1～2 秒可接受）。
        date_str = self.date_edit.date().toString('yyyy-MM-dd')
        self.btn_gen.setEnabled(False)
        self._clear()
        try:
            result = runWithBusy(
                self.tab_widget,
                lambda: generate_pages(self.db_path, date_str),
                text='產生簽收表中，請稍候…')
        except Exception as e:
            self._on_fail(str(e))
            return
        finally:
            self.btn_gen.setEnabled(True)

        png_list, pdf_bytes, page_specs = result
        if png_list is None:
            self._on_fail('查無資料')
        else:
            self._on_done(png_list, pdf_bytes, page_specs)

    def _on_done(self, png_list, pdf_bytes, page_specs):
        self._pdf_bytes  = pdf_bytes
        self._page_specs = page_specs
        self._gen_sig    = self._titles_sig()   # 記下產生當下的標題，供切回時偵測過期
        self.btn_gen.setEnabled(True)
        self.btn_download.setEnabled(True)
        self.btn_print.setEnabled(True)
        self._render(png_list)

    def _on_fail(self, msg):
        self.btn_gen.setEnabled(True)
        self.btn_download.setEnabled(False)
        self.btn_print.setEnabled(False)
        self.status_lbl.setText('')
        if msg == '查無資料':
            msgInfo('提示', '此日期查無發文資料')
        else:
            msgWarning('錯誤', f'產生失敗：{msg}')

    def _render(self, png_list):
        self._clear()
        scroll_w = self.scroll.viewport().width() - 32
        for png_bytes in png_list:
            qimg = QImage.fromData(png_bytes)
            pix  = QPixmap.fromImage(qimg)
            if pix.width() > scroll_w > 0:
                pix = pix.scaledToWidth(scroll_w, Qt.SmoothTransformation)
            lbl = QLabel()
            lbl.setPixmap(pix)
            lbl.setAlignment(Qt.AlignHCenter)
            lbl.setStyleSheet('background:white; border:1px solid #BBBBBB;')
            self._layout.addWidget(lbl)
        self.status_lbl.setText(f'共 {len(png_list)} 頁')

    def _on_download(self):
        if not self._pdf_bytes:
            return
        date_str = self.date_edit.date().toString('yyyy-MM-dd')
        path, _ = QFileDialog.getSaveFileName(
            None, '儲存 PDF', f'簽收表_{date_str}.pdf', 'PDF 檔案 (*.pdf)')
        if path:
            with open(path, 'wb') as f:
                f.write(self._pdf_bytes)

    def _on_print(self):
        if not self._page_specs:
            return
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(QPageSize(QPageSize.A4))
        # 預設彩色＋長邊雙面（簽收表已為雙面設計，各類別奇數頁補空白頁）。
        # 僅設定預設值，使用者仍可於列印視窗改回單面／黑白；實際支援取決於印表機。
        printer.setColorMode(QPrinter.Color)
        printer.setDuplex(QPrinter.DuplexLongSide)
        dlg = QPrintPreviewDialog(printer, self.tab_widget)
        dlg.setWindowTitle('列印預覽')
        dlg.resize(900, 1000)
        dlg.paintRequested.connect(self._paint_pages)
        dlg.exec()

    def _paint_pages(self, printer):
        """逐頁在 `printer` 上用 `QtCanvas` 向量直印
        （取代舊版「貼 300dpi PNG」的作法）。版面決策（換行／字級）已在
        `generate_pages()` 產生 `page_specs` 時算好一次（固定 1200dpi
        基準），這裡只負責照著同一組結果畫，不重算。

        ⚠️ 等比例保底（唯一使用者看得到的行為改變，補於驗證後）：不能直接
        拿 `painter.viewport()` 的寬高當整頁 A4 填滿——可列印區域的長寬比
        會因印表機邊界設定而偏離 A4（Qt 預設 10mm 邊界下已有約 1.14% 的
        差異，實體印表機底邊界較大時可到 3%），版面會被拉伸失真。改為在
        `viewport()` 內算出**維持 A4 長寬比的最大矩形並置中**（等同舊版
        `KeepAspectRatio` 的 letterbox 行為），`QtCanvas` 用這個矩形的尺寸
        作畫；`QtCanvas` 本身假設原點在 (0,0)，故用 `painter.translate()`
        把原點移到矩形左上角，不改動 `QtCanvas` 的座標語意。"""
        painter = QPainter(printer)
        try:
            first = True
            for kind, kw in self._page_specs:
                if not first:
                    printer.newPage()
                first = False
                if kind == 'blank':
                    continue
                # viewport = 當前可列印區域（device pixel），避開 enum 命名空間差異
                vp = painter.viewport()
                vp_w, vp_h = vp.width(), vp.height()
                a4_ratio = A4_W / A4_H
                if vp_w / vp_h > a4_ratio:
                    # viewport 較「扁」：高度吃滿，寬度置中收窄
                    draw_h = vp_h
                    draw_w = draw_h * a4_ratio
                else:
                    # viewport 較「窄」：寬度吃滿，高度置中收窄
                    draw_w = vp_w
                    draw_h = draw_w / a4_ratio
                off_x = (vp_w - draw_w) / 2
                off_y = (vp_h - draw_h) / 2

                painter.save()
                painter.translate(off_x, off_y)
                cv = QtCanvas(painter, draw_w, draw_h, (_REG, _BOLD))
                _draw_spec(kind, kw, cv)
                painter.restore()
        finally:
            painter.end()

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.status_lbl.setText('')
