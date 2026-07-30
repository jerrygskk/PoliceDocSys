import io
import sqlite3
from dataclasses import dataclass
from datetime import date

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.font_manager as fm
from matplotlib.transforms import Bbox, TransformedBbox
from matplotlib.backends.backend_pdf import PdfPages

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QWidget, QDateEdit, QFileDialog,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui  import QPixmap, QImage, QPainter, QPageSize
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

def fp(size, bold=False):
    return fm.FontProperties(fname=_BOLD if bold else _REG, size=size)

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

_MEASURE_RENDERER = None
def _text_width_pt(text, prop):
    """以 matplotlib 實際字型度量回傳字串寬度(pt)。
    用 dpi=72 的 RendererAgg → 回傳像素數即等於點數（pt）。
    取代舊版「中文字當滿格 size + 0.86 經驗係數」的估算，避免欄寬還夠卻提早換行
    （臨界長度的主旨最容易被誤折，見 v1.1.x 修正）。"""
    global _MEASURE_RENDERER
    if _MEASURE_RENDERER is None:
        from matplotlib.backends.backend_agg import RendererAgg
        _MEASURE_RENDERER = RendererAgg(1, 1, 72)
    w, _h, _d = _MEASURE_RENDERER.get_text_width_height_descent(text or "", prop, False)
    return w


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
               page_num=1, total_pages=1, scheme='task', note_text=NOTE):
    fig = plt.figure(figsize=(A4_W, A4_H))
    ax  = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')
    fig.patch.set_facecolor('white')
    c_title, c_hdr, c_row_odd, c_border, c_text = SCHEMES[scheme]
    headers = [c['header'] for c in columns]
    col_ratios = [c['ratio'] for c in columns]

    # 列印日期（左）
    ax.text(TABLE_L + PAD, TOP - DATE_H/2,
            f'列印日期　{print_date}',
            fontproperties=fp(8), ha='left', va='center',
            transform=ax.transAxes, color='#333333')
    # 發文日期（右，粗體）
    ax.text(1-R-PAD, TOP - DATE_H/2,
            f'發文日期：{disp_date}',
            fontproperties=fp(10, bold=True), ha='right', va='center',
            transform=ax.transAxes, color=c_text)
    cy = TOP - DATE_H

    # 大標題
    ax.add_patch(patches.FancyBboxPatch(
        (TABLE_L, cy-TITLE_H), TABLE_W, TITLE_H,
        boxstyle='square,pad=0', lw=0, fc=c_title,
        transform=ax.transAxes, zorder=1))
    ax.text(TABLE_L + TABLE_W/2, cy - TITLE_H/2, table_title,
            fontproperties=fp(14, bold=True), ha='center', va='center',
            transform=ax.transAxes, color=c_text)
    cy -= TITLE_H

    # 欄 x 位置
    col_xs = [TABLE_L]
    for r in col_ratios[:-1]:
        col_xs.append(col_xs[-1] + TABLE_W * r)

    # 表頭
    # 表頭上方粗分隔線
    ax.plot([TABLE_L, TABLE_L+TABLE_W], [cy]*2,
            color=c_border, lw=0.8, transform=ax.transAxes, zorder=4)

    ax.add_patch(patches.FancyBboxPatch(
        (TABLE_L, cy-HDR_H), TABLE_W, HDR_H,
        boxstyle='square,pad=0', lw=0, fc=c_hdr,
        transform=ax.transAxes, zorder=1))
    for hidx, (hdr, cx, column) in enumerate(zip(headers, col_xs, columns)):
        if column.get('header_align') == 'center' or column['role'] != 'subject':
            x_pos = cx + TABLE_W * col_ratios[hidx] / 2
            ha = 'center'
        else:
            x_pos = cx + PAD
            ha = 'left'
        ax.text(x_pos, cy-HDR_H/2, hdr,
                fontproperties=fp(12, bold=True), ha=ha, va='center',
                transform=ax.transAxes, color=c_text)
    ax.plot([TABLE_L, TABLE_L+TABLE_W], [cy-HDR_H]*2,
            color=c_border, lw=0.8, transform=ax.transAxes)
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
        ax.add_patch(patches.FancyBboxPatch(
            (TABLE_L, cy-ROW_H), TABLE_W, ROW_H,
            boxstyle='square,pad=0', lw=0, fc=bg,
            transform=ax.transAxes, zorder=1))

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
            ax.text(x_pos, cy - ROW_H/2, text,
                    fontproperties=font, ha=ha, va='center',
                    transform=ax.transAxes, color=color, clip_on=True,
                    multialignment='left', linespacing=1.3)

        ax.plot([TABLE_L, TABLE_L+TABLE_W], [cy-ROW_H]*2,
                color=c_border, lw=0.5, transform=ax.transAxes)
        cy -= ROW_H

    # 外框
    box_top = TOP - DATE_H
    box_h   = box_top - cy
    ax.add_patch(patches.FancyBboxPatch(
        (TABLE_L, cy), TABLE_W, box_h,
        boxstyle='square,pad=0', lw=1.2,
        ec=c_border, fc='none',
        transform=ax.transAxes, zorder=3))

    # 欄線
    for cx in col_xs[1:]:
        ax.plot([cx, cx], [cy, box_top - TITLE_H],
                color=c_border, lw=0.5, transform=ax.transAxes)

    # 左側直排大字已移除

    # 頁碼（底部置中）
    ax.text(0.5, BOT/2,
            str(page_num),
            fontproperties=fp(9), ha='center', va='center',
            transform=ax.transAxes, color='#555555')
    return fig


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

TICKET_HEADER_BG = "#B9858E"
TICKET_HEADER_TEXT = "#FFFFFF"
TICKET_OUTER_BORDER = "#743A46"
TICKET_GROUP_BORDER = "#A56B76"
TICKET_GRID_BORDER = "#D7C4C8"
TICKET_SUMMARY_BG = "#F5EAEC"

_TICKET_OUTER_LW = 1.4
_TICKET_GROUP_LW = 0.8
_TICKET_GRID_LW = 0.4


def drawTicketPage(grid, *, table_title, print_date, disp_date, body_rows,
                   page_num=1, total_pages=1, scheme='ticket',
                   show_summary=False, total_count=0):
    """畫一頁罰單簽收表：三組並排、共六欄（開立人員｜罰單編號 ×3），
    開立人員依 `TicketCell.issuer_rowspan` 合併——本函式只讀取已算好的欄位
    值，不做任何排序、分組或分頁判斷。

    `grid`：`buildTicketGrid()` 回傳的三欄清單。`body_rows`：本頁固定列數
    （用於畫滿版面高度，筆數不足的欄以空白列補滿，維持各頁版面一致，
    比照既有四種簽收表 `_draw_page(fill_to=...)` 的作法）。

    每頁於表格下方加畫一次「本頁／本日總計／簽收人」區。
    """
    fig = plt.figure(figsize=(A4_W, A4_H))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis('off')
    fig.patch.set_facecolor('white')

    ax.text(TABLE_L + PAD, TOP - DATE_H/2, f'列印日期　{print_date}',
            fontproperties=fp(8), ha='left', va='center',
            transform=ax.transAxes, color='#333333')
    ax.text(1-R-PAD, TOP - DATE_H/2, f'發文日期：{disp_date}',
            fontproperties=fp(10, bold=True), ha='right', va='center',
            transform=ax.transAxes, color='#333333')
    cy = TOP - DATE_H
    ax.text(TABLE_L + TABLE_W/2, cy - TITLE_H/2, table_title,
            fontproperties=fp(14, bold=True), ha='center', va='center',
            transform=ax.transAxes, color='#333333')
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

    # 欄名列是唯一深色網底；標題與日期留在表格粗外框之外。
    ax.add_patch(patches.Rectangle(
        (TABLE_L, cy-HDR_H), TABLE_W, HDR_H,
        linewidth=0, facecolor=TICKET_HEADER_BG,
        transform=ax.transAxes, zorder=1))
    for b in range(3):
        sub_xs = _sub_xs(TABLE_L + band_w * b)
        for hdr, sx, ratio in zip(TICKET_SUB_HEADERS, sub_xs, _TICKET_SUB_RATIOS):
            ax.text(sx + band_w*ratio/2, cy-HDR_H/2, hdr,
                    fontproperties=fp(11, bold=True), ha='center', va='center',
                    transform=ax.transAxes, color=TICKET_HEADER_TEXT)
    cy -= HDR_H
    table_top = cy
    table_bottom = table_top - TICKET_ROW_H * body_rows

    # 明細一律純白；整塊鋪底避免逐列 patch 造成斑馬或相鄰邊界疊畫。
    ax.add_patch(patches.Rectangle(
        (TABLE_L, table_bottom), TABLE_W, table_top - table_bottom,
        linewidth=0, facecolor='#FFFFFF',
        transform=ax.transAxes, zorder=0.5))

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
                ax.text(sub_xs[0] + band_w*_TICKET_SUB_RATIOS[0]/2,
                        row_top - merge_h/2, text,
                        fontproperties=font, ha='center', va='center',
                        transform=ax.transAxes, color='#111111')
            no_font = _fit_font(cell.ticket_no, band_w*_TICKET_SUB_RATIOS[1],
                                 max_size=12, min_size=8)
            no_x0 = sub_xs[1]
            no_x1 = sub_xs[1] + band_w*_TICKET_SUB_RATIOS[1]
            no_text = ax.text(no_x0 + (no_x1-no_x0)/2,
                    row_top - TICKET_ROW_H/2, cell.ticket_no,
                    fontproperties=no_font, ha='center', va='center',
                    transform=ax.transAxes, color='#111111')
            # F2：_fit_font 以 8pt 觸底、非精確量測，超長編號（例如 20 字元）仍可能
            # 溢出格寬壓到鄰欄；用該格自己的 bbox 當 clip box（而非整張 axes，
            # ax 涵蓋整頁，單純 clip_on=True 擋不住跨欄溢出），確保超出部分被
            # 裁掉、不污染鄰欄。
            no_text.set_clip_box(TransformedBbox(
                Bbox.from_extents(
                    no_x0, row_top - TICKET_ROW_H, no_x1, row_top), ax.transAxes))
            no_text.set_clip_on(True)

    # 簽收格先鋪淡酒紅底，線條稍後統一只畫一次。
    if show_summary:
        summary_top = table_bottom
        summary_bottom = summary_top - TICKET_SUMMARY_H
        ax.add_patch(patches.Rectangle(
            (TABLE_L, summary_bottom), TABLE_W, TICKET_SUMMARY_H,
            linewidth=0, facecolor=TICKET_SUMMARY_BG,
            transform=ax.transAxes, zorder=0.5))
    else:
        summary_top = table_bottom
        summary_bottom = table_bottom

    # 欄名列下緣為一般格線，只畫一次。
    ax.plot([TABLE_L, TABLE_L+TABLE_W], [table_top]*2,
            color=TICKET_GRID_BORDER, lw=_TICKET_GRID_LW,
            transform=ax.transAxes, zorder=2)

    # 兩條三組邊界為中階單線；三條組內直線為一般細線。
    for b in range(3):
        band_left = TABLE_L + band_w * b
        if b > 0:
            ax.plot([band_left, band_left], [table_bottom, header_top],
                    color=TICKET_GROUP_BORDER, lw=_TICKET_GROUP_LW,
                    transform=ax.transAxes, zorder=2)
        for sx in _sub_xs(band_left)[1:]:
            ax.plot([sx, sx], [table_bottom, header_top],
                    color=TICKET_GRID_BORDER, lw=_TICKET_GRID_LW,
                    transform=ax.transAxes, zorder=2)

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
                ax.plot([band_left, band_left + band_w], [ry, ry],
                        color=TICKET_GROUP_BORDER, lw=_TICKET_GROUP_LW,
                        transform=ax.transAxes, zorder=2)
            elif ridx >= len(band):
                ax.plot([band_left, band_left + band_w], [ry, ry],
                        color=TICKET_GRID_BORDER, lw=_TICKET_GRID_LW,
                        transform=ax.transAxes, zorder=2)
            else:
                ax.plot([number_x0, number_x1], [ry, ry],
                        color=TICKET_GRID_BORDER, lw=_TICKET_GRID_LW,
                        transform=ax.transAxes, zorder=2)

    # 每頁 summary：上緣與左右分區皆為中階單線，不加簽名底線。
    if show_summary:
        ax.plot([TABLE_L, TABLE_L+TABLE_W], [summary_top]*2,
                color=TICKET_GROUP_BORDER, lw=_TICKET_GROUP_LW,
                transform=ax.transAxes, zorder=2)
        mid_x = TABLE_L + TABLE_W * 0.5
        ax.plot([mid_x, mid_x], [summary_bottom, summary_top],
                color=TICKET_GROUP_BORDER, lw=_TICKET_GROUP_LW,
                transform=ax.transAxes, zorder=2)
        page_count = sum(len(band) for band in grid)
        ax.text(TABLE_L + TABLE_W*0.25, (summary_top+summary_bottom)/2,
                f'本頁共 {page_count} 筆，本日總計 {total_count} 筆',
                fontproperties=fp(12, bold=True), ha='center', va='center',
                transform=ax.transAxes, color='#333333')
        ax.text(mid_x + PAD*1.5, (summary_top+summary_bottom)/2,
                '簽收人：',
                fontproperties=fp(12, bold=True), ha='left', va='center',
                transform=ax.transAxes, color='#333333')

    # 唯一粗框：只從欄名列頂端包到簽收格底端；標題／日期在框外。
    ax.add_patch(patches.Rectangle(
        (TABLE_L, summary_bottom), TABLE_W, header_top - summary_bottom,
        linewidth=_TICKET_OUTER_LW, edgecolor=TICKET_OUTER_BORDER,
        facecolor='none', transform=ax.transAxes, zorder=3))

    ax.text(0.5, BOT/2, str(page_num), fontproperties=fp(9),
            ha='center', va='center', transform=ax.transAxes, color='#555555')
    return fig


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
def generate_pages(db_path, date_str):
    """回傳預覽 PNG、PDF 與列印 PNG；查無資料時皆回傳 None。"""
    sections = _build_sections(db_path, date_str)
    if not sections:
        return None, None, None

    print_date = _today()
    disp_date = _fmt_date(date_str)
    per = _rows_per_page()
    note_text = printTitle(db_path, 'note')

    def _blank_page():
        """產生一頁空白頁（雙面印用）"""
        fig = plt.figure(figsize=(A4_W, A4_H))
        fig.patch.set_facecolor('white')
        return fig

    def _standard_section_figs(section):
        rows = section['rows']
        n = max(1, -(-len(rows) // per))
        section_figs = []
        for page_num, start in enumerate(range(0, max(len(rows), 1), per), start=1):
            chunk = rows[start:start+per]
            fig = _draw_page(section['side'], section['title'], print_date, disp_date,
                             section['columns'], chunk, per, section['is_crim'],
                             page_num=page_num, total_pages=n,
                             scheme=section['scheme'], note_text=note_text)
            section_figs.append(fig)
        return section_figs, n

    def _ticket_section_figs(section):
        # 罰單專用 renderer：每頁固定三組 × 20 筆且每頁有簽收格；不消費
        # per（那是既有四種簽收表的逐頁容量）。
        ticket_pages = paginateTicketRows(section['rows'])
        section_figs = []
        for tp in ticket_pages:
            grid = buildTicketGrid(
                tp.items, body_rows=TICKET_ROWS_PER_BAND)
            fig = drawTicketPage(
                grid, table_title=section['title'], print_date=print_date,
                disp_date=disp_date, body_rows=TICKET_ROWS_PER_BAND,
                page_num=tp.page_num, total_pages=tp.total_pages,
                scheme=section['scheme'], show_summary=tp.show_summary,
                total_count=tp.total_count)
            section_figs.append(fig)
        return section_figs, len(ticket_pages)

    figs = []
    for section in sections:
        if section.get('kind') == 'ticket':
            section_figs, section_total = _ticket_section_figs(section)
        else:
            section_figs, section_total = _standard_section_figs(section)

        figs.extend(section_figs)

        # 若此 section 為奇數頁，插入空白頁
        if section_total % 2 == 1:
            figs.append(_blank_page())

    # PNG bytes（用於預覽，不需 poppler）
    png_list = []
    for fig in figs:
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=200, bbox_inches='tight',
                    facecolor='white')
        buf.seek(0)
        png_list.append(buf.read())

    # PNG bytes（用於另存 / 列印）
    pdf_buf = io.BytesIO()
    with PdfPages(pdf_buf) as pdf:
        for fig in figs:
            pdf.savefig(fig, dpi=150)
    pdf_buf.seek(0)
    pdf_bytes = pdf_buf.read()

    # 列印用全頁影像（300 dpi，不裁切，維持 A4 比例對齊紙張）
    print_pngs = []
    for fig in figs:
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=300, facecolor='white')
        buf.seek(0)
        print_pngs.append(buf.read())

    for fig in figs:
        plt.close(fig)

    return png_list, pdf_bytes, print_pngs


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

        self._pdf_bytes  = None
        self._print_pngs = None
        self._gen_sig    = None     # 上次「產生」當下的標題指紋，供偵測過期
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
        if (self._print_pngs and self._gen_sig is not None
                and self._gen_sig != self._titles_sig()):
            self._clear()
            self._pdf_bytes = None
            self._print_pngs = None
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
            # 結算後以對話框實際選定的發文日產生簽收表（一條龍動線）
            if self.date_edit:
                self.date_edit.setDate(dlg.settledDate())
            self._on_generate()

    def on_activated(self):
        # 切入列印頁時刷新「標題未設定」提醒（保險：若框架日後改為會呼叫）
        self._refresh_title_warn()

    def _on_generate(self):
        # 前景產生＋modal「產生中」popup：matplotlib 走全域狀態，不宜在背景執行緒
        # 跑（會與主執行緒搶用而偶發崩潰）。改在主執行緒同步畫，期間以 popup 擋住
        # 互動，畫完即關（單機 1～2 秒可接受）。
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

        png_list, pdf_bytes, print_pngs = result
        if png_list is None:
            self._on_fail('查無資料')
        else:
            self._on_done(png_list, pdf_bytes, print_pngs)

    def _on_done(self, png_list, pdf_bytes, print_pngs):
        self._pdf_bytes  = pdf_bytes
        self._print_pngs = print_pngs
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
        if not self._print_pngs:
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
        """把 300 dpi 全頁影像逐頁畫到印表機頁面（等比置中填滿）"""
        painter = QPainter(printer)
        first = True
        for png_bytes in self._print_pngs:
            img = QImage.fromData(png_bytes)
            if img.isNull():
                continue
            if not first:
                printer.newPage()
            first = False
            # viewport = 當前可列印區域（device pixel），避開 enum 命名空間差異
            vp = painter.viewport()
            scaled = img.scaled(
                vp.width(), vp.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation)
            x = vp.x() + (vp.width()  - scaled.width())  // 2
            y = vp.y() + (vp.height() - scaled.height()) // 2
            painter.drawImage(x, y, scaled)
        painter.end()

    def _clear(self):
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.status_lbl.setText('')
