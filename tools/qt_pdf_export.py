# -*- coding: utf-8 -*-
"""用 QtCanvas ＋ QPdfWriter 輸出向量 PDF（階段 3 的第一條路徑）。

這是 `QtCanvas` 第一次接上 QImage 以外的 device。階段 2 的驗證指出這裡有
一個未驗證的假設：`QtCanvas` 的等效 dpi 是用 `width_px / A4_W_IN` **反推**
的，若與 `QPdfWriter` 實際的 `resolution()` 兜不起來，字級與版面座標會整批
偏移。本腳本會把兩者印出來對照，不吻合就直接中止。

用法：
    python tools/qt_pdf_export.py --out 輸出資料夾 [--resolution 1200]
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tabs.tab_print as tp
from lib.print_canvas import QtCanvas, A4_W_IN, A4_H_IN
from tools.render_diff import _case_page_specs
from tools.print_baseline import CASES, FROZEN_PRINT_DATE, _case_key


def _export_case(db, date_str, out_path, resolution):
    from PySide6.QtGui import QPageSize, QPainter, QPdfWriter
    from PySide6.QtCore import QMarginsF, QSizeF

    specs = _case_page_specs(db, date_str)
    if not specs:
        return None, None

    writer = QPdfWriter(out_path)
    writer.setResolution(resolution)
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(0, 0, 0, 0))

    w, h = writer.width(), writer.height()
    derived_dpi = w / A4_W_IN

    painter = QPainter(writer)
    try:
        tp._set_text_measurer("qt")
        first = True
        for kind, kw in specs:
            if not first:
                writer.newPage()
            first = False
            if kind == "blank":
                continue          # 雙面用空白頁：開一頁但不畫東西
            cv = QtCanvas(painter, w, h, (tp._REG, tp._BOLD))
            tp._draw_spec(kind, kw, cv)
    finally:
        painter.end()

    return (w, h, derived_dpi), len(specs)


def _inspect_pdf(path):
    """粗略檢查 PDF 是否為『內嵌字型的可選取文字』而非圖片／外框路徑。

    不引入任何 PDF 函式庫（本專案已刻意把 PDF 相依整串移出打包），直接看
    原始 bytes 裡的物件關鍵字即可分辨這三種情況。
    """
    raw = open(path, "rb").read()
    return {
        "size_kb": len(raw) / 1024,
        "has_font_obj": b"/Type /Font" in raw or b"/Type/Font" in raw,
        "has_embedded_fontfile": (b"/FontFile2" in raw or b"/FontFile3" in raw
                                  or b"/FontFile" in raw),
        "has_image_xobject": b"/Subtype /Image" in raw or b"/Subtype/Image" in raw,
    }


def main():
    ap = argparse.ArgumentParser(description="QtCanvas → QPdfWriter 向量 PDF")
    ap.add_argument("--out", required=True, help="輸出資料夾")
    ap.add_argument("--resolution", type=int, default=1200,
                    help="QPdfWriter 解析度（預設 1200，Qt 預設值）")
    ap.add_argument("--only", default=None,
                    help="只輸出指定日期（逗號分隔），預設全部案例")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841

    tp._today = lambda: FROZEN_PRINT_DATE
    os.makedirs(args.out, exist_ok=True)
    only = set(args.only.split(",")) if args.only else None

    print(f"QPdfWriter resolution = {args.resolution} dpi")
    ok = True
    for db, date_str, desc in CASES:
        if only and date_str not in only:
            continue
        case = _case_key(db, date_str)
        path = os.path.join(args.out, f"Qt向量_{case}.pdf")
        geom, npages = _export_case(db, date_str, path, args.resolution)
        if geom is None:
            print(f"  {case}: 查無資料，略過")
            continue
        w, h, derived = geom
        drift = abs(derived - args.resolution) / args.resolution * 100
        info = _inspect_pdf(path)
        flag = "OK" if drift < 1.0 else "★ dpi 不吻合"
        print(f"\n  {case}  {npages} 頁  {info['size_kb']:.0f} KB")
        print(f"    device = {w}×{h} px → 反推 dpi {derived:.1f}"
              f"（誤差 {drift:.3f}%）  {flag}")
        print(f"    內嵌字型={info['has_embedded_fontfile']}  "
              f"文字物件={info['has_font_obj']}  "
              f"影像物件={info['has_image_xobject']}")
        if drift >= 1.0 or not info["has_embedded_fontfile"]:
            ok = False
    print("\n[OK] 全部通過" if ok else "\n[X] 有項目未通過，見上方 ★")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
