# -*- coding: utf-8 -*-
"""產生程式內 HELP 用的「按鈕示意」SVG（圓角＋實際配色＋文字）。

為什麼用產生器：HELP 彈窗的 QTextBrowser 不支援 border-radius，inline span 做不出
圓角按鈕；改用 <img> 嵌 SVG 才有真圓角。手刻難維護，故以本腳本依 BUTTONS／TABS
清單批次產出，新增/改標籤改清單重跑即可。

產出（真按鈕與子頁籤分流到兩個資料夾，共用 icon 不歸此處管）：
  res/buttons/<key>.svg          真按鈕圖（qrc 別名 :/btn/）
  res/tabs/<key>.svg             子頁籤圖（qrc 別名 :/tab/）
  ui_utils/button_imgs.py        label → (qrc 路徑, 顯示寬, 顯示高) 對照（入庫）

配色比照 lib/theme.py 實際按鈕：
  default  白底深字灰框（多數鈕）
  primary  墨藍 #a1b4cb 白字（確認/送出/歸檔類）
  danger   紅 #e74c3c 白字（刪除 ✕）
  overdue  紅膠囊 #e07a72 白字（逾期未回篩選 active 態）

跑法（專案根目錄）：python gen_buttons.py
改了 SVG 後記得重編 qrc：pyside6-rcc res/resources.qrc -o res/resources_rc.py
"""
import os

# (key, label, style)
BUTTONS = [
    ("confirm_send",   "確認發文",   "primary"),
    ("confirm_recv",   "確認收文",   "primary"),
    ("confirm_report", "確認陳報",   "primary"),
    ("do_archive",     "檔案歸檔",   "primary"),
    ("paper_only",     "只歸紙本",   "primary"),
    ("remove",         "✕",          "danger"),
    ("gen_preview",    "產生預覽",   "default"),
    ("print_form",     "列印表單",   "default"),
    ("download_pdf",   "下載 PDF",   "default"),
    ("full",           "完整",       "default"),
    ("reload",         "重載",       "default"),
    ("reset",          "還原預設",   "default"),
    ("archive_folder", "歸檔資料夾", "default"),
    ("add",            "＋ 新增",     "default"),
    ("edit",           "✎ 修改",      "default"),
    ("save_order",     "💾 儲存排序", "default"),
    ("export_csv",     "CSV",        "default"),
    ("print_titles",   "簽收表設定", "default"),
    ("trash",          "資源回收筒", "default"),
    ("backup_restore", "備份還原",   "default"),
    ("overdue",        "逾期未回",   "overdue"),
    ("convert_type",   "⇄ 轉換類別", "convert"),
]

# 子頁籤（瀏覽 Tab6／歸檔 Tab7／陳報 Tab2 的小 Tab）：透明底＋選中色字＋底線。
# 與「真按鈕」分流：輸出到 res/tabs/、qrc 別名 :/tab/。
TABS = [
    ("task",        "▤ 交辦單",   "tab"),
    ("crim_report", "❐ 刑案陳報", "tab"),
    ("gen_report",  "❏ 一般陳報", "tab"),
    ("reward",      "☆ 敘獎登錄", "tab"),
    ("crim_arch",   "❐ 刑案歸檔", "tab"),
    ("gen_arch",    "❏ 一般歸檔", "tab"),
]

STYLES = {
    # bg, fg, stroke(None=無框), radius, pad(None=用全域 PAD)
    "default": ("#FFFFFF", "#1c1c1e", "#c6c6c8", 7, None),   # 白底＋細灰框，比照實際按鈕
    "primary": ("#a1b4cb", "#FFFFFF", None, 7, None),
    "danger":  ("#e74c3c", "#FFFFFF", None, 6, 7),   # 單字元 ✕ 用小內距，近方形
    "overdue": ("#e07a72", "#FFFFFF", None, 12, None),
    # convert：比照 edit_dialog._CONVERT_BTN_QSS（白底磚紅字＋淡紅框）
    "convert": ("#FFFFFF", "#a8442e", "#e6b9ad", 7, None),
    # tab：透明底、選中色 #8fa8c8 字、底部 2px 同色底線（見 tab_dbbrowse 子頁 QSS）
    "tab":     (None, "#8fa8c8", None, 0, 10),
}

FONT = "Microsoft JhengHei"   # 與全域字型一致（main.py app.setFont）。
# ⚠ QtSvg 的 font-family 要用「單一裸字型名」，逗號清單/引號會被當成不存在的字型名
# 而 fallback 成預設字型（字型看起來不對）。
# intrinsic 超取樣：SVG 檔的 width/height 屬性放大 SS 倍（viewBox 維持邏輯尺寸），
# HTML <img> 仍以邏輯 w×h 顯示 → QTextBrowser 以高解析點陣化再下採樣，較不糊。
# 實測 QTextBrowser 圖片點陣化解析度封頂在 ~2×（再大不再變銳），故取 2。
SS = 2
H = 24          # viewBox 高（= 顯示高 px）
FS = 14.5       # 字級
PAD = 12        # 左右內距
FW = 600        # 字重

def _text_width(s):
    """估算文字寬（不依賴 QApplication）：CJK/全形符號≈字級，半形≈0.56 字級。"""
    w = 0.0
    for ch in s:
        o = ord(ch)
        if o < 0x2E80 and ch not in "＋✎✕💾⇄":   # 半形 ASCII/數字/空白
            w += FS * 0.56
        else:                                      # CJK 與全形符號/emoji
            w += FS
    return w

def _arrows_path(x, fg):
    """畫 ⇄ 雙箭頭（16×10，垂直置中於 H）。
    ⚠ 不能用字元：微軟正黑體無 U+21C4，QtSvg 又不做字型 fallback，
    產出來會是豆腐（此前手截 PNG 就是為了繞這個雷）。改用 path 不吃字型。"""
    y1, y2 = H / 2 - 3.2, H / 2 + 3.2   # 上：向右；下：向左
    aw = 16
    return (
        f'<g stroke="{fg}" stroke-width="1.6" fill="none" '
        f'stroke-linecap="round" stroke-linejoin="round">'
        f'<path d="M{x},{y1} h{aw - 4} m0,0 l-3.5,-3 m3.5,3 l-3.5,3"/>'
        f'<path d="M{x + aw},{y2} h{-(aw - 4)} m0,0 l3.5,-3 m-3.5,3 l3.5,3"/>'
        f'</g>'), aw


def _svg(label, style):
    bg, fg, stroke, r, pad = STYLES[style]
    pad = PAD if pad is None else pad
    arrows = ""
    if label.startswith("⇄ "):          # 雙箭頭改畫 path（見 _arrows_path 註解）
        label = label[2:]
        ap, aw = _arrows_path(pad, fg)
        arrows = ap
        pad_left = pad + aw + 6          # 箭頭寬＋與文字間距
    else:
        pad_left = pad
    w = int(round(_text_width(label) + pad_left + pad))
    baseline = H / 2 + FS * 0.34          # 垂直置中近似（QtSvg dominant-baseline 不穩）
    # XML escape
    txt = (label.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    if style == "tab":
        # 子頁籤：無底框，僅底部 2px 底線（選中態），透明背景
        shape = f'<rect x="0" y="{H-2}" width="{w}" height="2" fill="{fg}"/>'
    else:
        rect_stroke = (f' stroke="{stroke}" stroke-width="1"' if stroke else "")
        inset = 0.5 if stroke else 0
        rw, rh = w - 2 * inset, H - 2 * inset
        shape = (f'<rect x="{inset}" y="{inset}" width="{rw}" height="{rh}" '
                 f'rx="{r}" ry="{r}" fill="{bg}"{rect_stroke}/>')
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {H}" '
        f'width="{w * SS}" height="{H * SS}">'
        f'{shape}{arrows}'
        f'<text x="{round(pad_left + _text_width(label)/2, 2) if arrows else w/2}" y="{baseline}" font-family="{FONT}" font-size="{FS}" '
        f'font-weight="{FW}" fill="{fg}" text-anchor="middle">{txt}</text>'
        f'</svg>'
    )
    return svg, w

def main():
    # 本檔在 tools/ 之下，repo 根為上一層
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mapping = {}   # label -> (src, w, h)
    # (清單, 子資料夾, qrc 別名前綴)
    for items, subdir, prefix in ((BUTTONS, "buttons", "btn"),
                                  (TABS, "tabs", "tab")):
        out_dir = os.path.join(root, "res", subdir)
        os.makedirs(out_dir, exist_ok=True)
        for key, label, style in items:
            svg, w = _svg(label, style)
            with open(os.path.join(out_dir, f"{key}.svg"), "w", encoding="utf-8") as f:
                f.write(svg)
            mapping[label] = (f":/{prefix}/{key}.svg", w, H)
    # 產對照模組
    lines = ['# -*- coding: utf-8 -*-',
             '"""自動產生，請勿手改。由 gen_buttons.py 產出。',
             'label -> (qrc 路徑, 顯示寬 px, 顯示高 px)。"""',
             'BTN_IMG = {']
    for label, (src, w, h) in mapping.items():
        lines.append(f'    {label!r}: ({src!r}, {w}, {h}),')
    lines.append('}')
    with open(os.path.join(root, "ui_utils", "button_imgs.py"), "w",
              encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"產出 {len(BUTTONS)} 按鈕 → res/buttons/、{len(TABS)} 子頁籤 → res/tabs/，"
          "對照 → ui_utils/button_imgs.py")
    print("記得重編 qrc：pyside6-rcc res/resources.qrc -o res/resources_rc.py")

if __name__ == "__main__":
    main()
