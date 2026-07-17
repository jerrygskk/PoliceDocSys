# gen_quickstart.py — 產生「快速上手速查卡」PDF（獨立工具，不入庫）
#
# 內容單一來源：ui_utils/help_content.py 的 QUICKSTART（濃縮母本）。
# 改速查卡文字只動 QUICKSTART，本檔只負責排版。
#
# 字型：嵌入微軟正黑體（Windows 內建 msjh.ttc / msjhbd.ttc），確保中文不變
# 豆腐方塊。產出 docs/Quick_Start.pdf（docs/ 已 gitignore）。
#
# 跑法（專案根目錄）：python gen_quickstart.py
#
# 配色對齊程式主題：鋼藍 #4977b1、淺鋼藍 #DCE5EF。

import os
import sys

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether,
    PageBreak)
from PIL import Image, ImageDraw

# 本檔在 tools/ 之下，repo 根為上一層（供 import ui_utils）
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
from ui_utils.help_content import QUICKSTART, HELP_TITLES  # noqa: E402

# ── 字型 ───────────────────────────────────────────────────────
_FONTS_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_REG = ("MSJH", os.path.join(_FONTS_DIR, "msjh.ttc"), 0)
_BD = ("MSJH-Bold", os.path.join(_FONTS_DIR, "msjhbd.ttc"), 0)

for name, path, idx in (_REG, _BD):
    if not os.path.exists(path):
        sys.exit(f"找不到字型：{path}（需 Windows 內建微軟正黑體）")
    pdfmetrics.registerFont(TTFont(name, path, subfontIndex=idx))

FONT, FONT_BD = _REG[0], _BD[0]

# ── 顏色 ───────────────────────────────────────────────────────
STEEL = colors.HexColor("#4977b1")
STEEL_LT = colors.HexColor("#DCE5EF")
INK = colors.HexColor("#1c1c1e")
GREY = colors.HexColor("#6b6b6e")
AMBER_BG = colors.HexColor("#FBF1DC")
AMBER_INK = colors.HexColor("#7a5b16")

# ── 樣式 ───────────────────────────────────────────────────────
_title = ParagraphStyle("title", fontName=FONT_BD, fontSize=20, textColor=colors.white,
                        leading=24)
_subtitle = ParagraphStyle("subtitle", fontName=FONT, fontSize=10.5,
                           textColor=colors.HexColor("#EAF0F7"), leading=14)
_sec_head = ParagraphStyle("sec", fontName=FONT_BD, fontSize=12.5, textColor=INK,
                          leading=16)
_purpose = ParagraphStyle("purpose", fontName=FONT, fontSize=10.5, textColor=GREY,
                         leading=15, spaceBefore=1, spaceAfter=3)
_step = ParagraphStyle("step", fontName=FONT, fontSize=10.5, textColor=INK,
                      leading=15.5, leftIndent=2)
_tip = ParagraphStyle("tip", fontName=FONT, fontSize=9.5, textColor=AMBER_INK,
                     leading=13.5)


X_IMG = None   # (path, 顯示寬pt, 顯示高pt)；於 __main__ 產好刪除鈕 PNG 後設定


def _make_x_button(path):
    """畫一顆紅底白叉的刪除鈕 PNG（比照介面刪除色 #e74c3c），供 PDF 內嵌。"""
    s = 6   # 放大倍率求清晰（顯示時再縮小）
    W, H = 26 * s, 22 * s
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=5 * s, fill="#e74c3c")
    cx, cy, arm, lw = W / 2, H / 2, 5 * s, 2 * s
    d.line([cx - arm, cy - arm, cx + arm, cy + arm], fill="white", width=lw)
    d.line([cx - arm, cy + arm, cx + arm, cy - arm], fill="white", width=lw)
    img.save(path)


def _purpose_html(purpose):
    """灰字說明；把 {X} 占位換成內嵌刪除鈕圖（無圖時退回文字 ✕）。"""
    if "{X}" not in purpose:
        return purpose
    if X_IMG:
        p, w, h = X_IMG
        return purpose.replace(
            "{X}", f'<img src="{p}" width="{w}" height="{h}" valign="-2"/>')
    return purpose.replace("{X}", "✕")


def _tip_blocks(tip):
    """tip 欄位正規化成「提示塊」串列。每塊為字串（單行）或 [帶頭句, 分點…]。"""
    return tip if isinstance(tip, (list, tuple)) else ([tip] if tip else [])


def _block_strings(block):
    """把一個提示塊攤平成純字串串列（供字形檢查用）。"""
    return list(block) if isinstance(block, (list, tuple)) else [block]


def _section(idx):
    """單一 Tab 區塊（標題列 + 用途 + 步驟 + 提示），整塊不跨頁。"""
    purpose, steps, tip = QUICKSTART[idx]
    flow = []

    # 標題列：鋼藍序號方塊 + 頁名
    badge = Table([[Paragraph(str(idx + 1), ParagraphStyle(
        "b", fontName=FONT_BD, fontSize=13, textColor=colors.white,
        alignment=1, leading=15))]], colWidths=[8 * mm], rowHeights=[8 * mm])
    badge.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), STEEL),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    head = Table([[badge, Paragraph(HELP_TITLES[idx], _sec_head)]],
                 colWidths=[10 * mm, None])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("LINEBELOW", (0, 0), (-1, -1), 1.2, STEEL_LT),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(head)
    flow.append(Spacer(1, 3))
    flow.append(Paragraph(_purpose_html(purpose), _purpose))

    for i, s in enumerate(steps, 1):
        flow.append(Paragraph(
            f'<font name="{FONT_BD}" color="#4977b1">{i}.</font>&nbsp;{s}', _step))

    for tp in _tip_blocks(tip):
        if isinstance(tp, (list, tuple)):
            html = "※&nbsp; " + tp[0] + "".join(
                "<br/>&nbsp;&nbsp;・ " + p for p in tp[1:])
        else:
            html = "※&nbsp; " + tp
        t = Table([[Paragraph(html, _tip)]], colWidths=[None])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), AMBER_BG),
            ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        flow.append(Spacer(1, 3))
        flow.append(t)

    flow.append(Spacer(1, 9))
    return KeepTogether(flow)


def _header_band(canvas, doc):
    """每頁頂端鋼藍標題帶。"""
    w, h = A4
    band_h = 22 * mm
    canvas.saveState()
    canvas.setFillColor(STEEL)
    canvas.rect(0, h - band_h, w, band_h, fill=1, stroke=0)
    canvas.setFillColor(colors.white)
    canvas.setFont(FONT_BD, 19)
    canvas.drawString(18 * mm, h - 12 * mm, "公文管理系統　快速上手")
    canvas.setFillColor(colors.HexColor("#EAF0F7"))
    canvas.setFont(FONT, 10)
    canvas.drawString(18 * mm, h - 18 * mm,
                      "八個分頁速查；詳細說明請點程式各頁右上角的「？」說明鈕。")
    canvas.restoreState()


def build(out_path):
    doc = SimpleDocTemplate(
        out_path, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=28 * mm, bottomMargin=14 * mm,
        title="公文管理系統 快速上手速查卡")
    # 版面分頁（指定）：
    #   第 1 頁＝交辦單發文／收文、公文陳報、敘獎登錄
    #   第 2 頁＝簽收單列印、資料庫瀏覽、檔案歸檔、資料庫設定
    PAGE1 = [0, 1, 2, 3]
    PAGE2 = [5, 6, 7, 8]
    story = []
    for idx in PAGE1:
        story.append(_section(idx))
    story.append(PageBreak())
    for idx in PAGE2:
        story.append(_section(idx))
    doc.build(story, onFirstPage=_header_band, onLaterPages=_header_band)


def _check_glyphs():
    """確認母本所有字元都在字型 cmap 內，避免缺字形（豆腐）。

    文字流抽得出來不代表畫得出字形（如 ⚠ U+26A0 微軟正黑體就缺），故直接
    查 cmap 覆蓋率，缺字立即報出。
    """
    from fontTools.ttLib import TTCollection
    cmap = set(TTCollection(_REG[1]).fonts[_REG[2]].getBestCmap())
    used = set("※公文管理系統快速上手八個分頁速查詳細說明請點程式各頁右上角的的鈕")
    for purpose, steps, tip in QUICKSTART.values():
        texts = [purpose, *steps]
        for blk in _tip_blocks(tip):
            texts += _block_strings(blk)
        for s in texts:
            used |= set(s)
    missing = sorted(c for c in used if c.strip() and ord(c) not in cmap)
    if missing:
        sys.exit("字型缺字形（會變豆腐）：" + " ".join(
            f"{c}(U+{ord(c):04X})" for c in missing))


if __name__ == "__main__":
    _check_glyphs()
    out_dir = os.path.join(_ROOT, "docs")
    os.makedirs(out_dir, exist_ok=True)
    xpng = os.path.join(out_dir, "_x_btn.png")
    _make_x_button(xpng)
    X_IMG = (xpng, 14, 12)
    out = os.path.join(out_dir, "Quick_Start.pdf")
    build(out)
    print(f"已產生：{out}")
