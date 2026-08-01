# -*- coding: utf-8 -*-
"""階段 2 驗收工具：新舊繪圖引擎（matplotlib／Qt）逐格比對。

沿用 `tools/print_baseline.py` 的同一組 10 個案例，每個案例的每一頁分別用
matplotlib 量測後端（產品現況）與 Qt 量測後端（1200dpi 固定基準）各跑一次 `RecordingCanvas`，逐一比對兩份 op 記錄。

⚠️ **必須做歸因摺疊**：以「一格文字」（一筆 `TextOp`）為單位比對，先比
wrap 結果（行數＋每行內容＋字級），wrap 不同就整格報一條，不逐座標展開。
本專案目前的版面計算裡，欄位座標（`op.x`／`op.y`）只由固定的欄寬／列高
幾何算出，**不吃字串量測結果**，所以理論上不會有「換行差異→座標連鎖差異」
的情形；但比對邏輯仍照這個前提設計，避免未來版面一旦真的依賴量測結果、
沒有折疊機制就會整批爆開。

用法：
    $env:QT_QPA_PLATFORM='offscreen'; python tools/engine_diff.py

輸出：
    - stdout：各類差異數量與逐條說明（依嚴重度排序）。
    - docs/engine_diff/{案例}_page{頁碼}.png：QtCanvas 實際畫出的頁面
      （每案第一個非空白頁），供人工目視比對。

不驗證產品輸出有沒有變（那是 `print_baseline.py` 的工作）、也不修改任何
測資或基準──**這裡有差異是預期的**，重點是如實呈現＋解釋成因。
"""

import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tabs.tab_print as tp
from lib.print_canvas import A4_H_IN, A4_W_IN, LineOp, QtCanvas, RecordingCanvas, RectOp, TextOp
from tools.mpl_canvas import mpl_text_width_pt
from tools.print_baseline import CASES, FROZEN_PRINT_DATE, _case_key

OUT_DIR = os.path.join("docs", "engine_diff")

# 嚴重度（由高到低）。
SEVERITY = ("SIZE_DIFF", "TRUNC_DIFF", "LINECOUNT_DIFF", "WRAP_SHIFT", "OTHER_DIFF")


def _case_page_specs(db, date_str):
    """回傳一個案例、依 generate_pages() 相同順序展開的頁面規格清單：
    每項為 (kind, kwargs)，kind ∈ {'standard', 'ticket', 'blank'}。
    階段 3 起直接複用 `tabs.tab_print._build_page_specs()`（產品自己的
    分頁／排序邏輯），不再重複實作一份——避免兩邊各自維護、慢慢長歪
    （踩過的教訓）。"""
    return tp._build_page_specs(
        db, date_str, print_date=FROZEN_PRINT_DATE, disp_date=tp._fmt_date(date_str))


# ── 用指定量測後端錄一頁的 ops ──────────────────────────────
def _record_ops(kind, kw, measurer):
    tp._set_text_measurer(measurer)
    cv = RecordingCanvas()
    tp._draw_spec(kind, kw, cv)
    return cv.ops


# ── 用 QtCanvas 實際畫一張 PNG（人工目視用）────────────────
_RENDER_DPI = 150


def _render_qt_png(kind, kw, out_path):
    from PySide6.QtGui import QImage, QPainter

    tp._set_text_measurer("qt")
    width_px = round(A4_W_IN * _RENDER_DPI)
    height_px = round(A4_H_IN * _RENDER_DPI)
    img = QImage(width_px, height_px, QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    try:
        cv = QtCanvas(painter, width_px, height_px, (tp._REG, tp._BOLD))
        tp._draw_spec(kind, kw, cv)
    finally:
        painter.end()
    img.save(out_path, "PNG")


# ── 歸因摺疊比對：一筆 TextOp 就是「一格文字」────────────────
def _text_excerpt(s, n=14):
    flat = s.replace("\n", "／")
    return flat if len(flat) <= n else flat[:n] + "…"


def _classify_text_op(old, new):
    """回傳 (kind, detail) 或 None（完全相同、無差異）。"""
    if old == new:
        return None
    old_lines = old.s.split("\n")
    new_lines = new.s.split("\n")
    if old.size != new.size:
        return "SIZE_DIFF", (
            f"字級不同：舊 {old.size}pt／新 {new.size}pt"
            f"（「{_text_excerpt(old.s)}」）")
    old_trunc = old.s.endswith("…")
    new_trunc = new.s.endswith("…")
    if old_trunc != new_trunc:
        return "TRUNC_DIFF", (
            f"截斷狀態不同：舊{'有' if old_trunc else '無'}截斷／"
            f"新{'有' if new_trunc else '無'}截斷"
            f"（舊「{_text_excerpt(old.s)}」／新「{_text_excerpt(new.s)}」）")
    if len(old_lines) != len(new_lines):
        return "LINECOUNT_DIFF", (
            f"行數不同：舊 {len(old_lines)} 行／新 {len(new_lines)} 行"
            f"（舊「{_text_excerpt(old.s)}」／新「{_text_excerpt(new.s)}」）")
    if old_lines != new_lines:
        # 行數、字級、截斷狀態皆同，只有斷點位移了幾個字──已核可可接受。
        for i, (lo, ln) in enumerate(zip(old_lines, new_lines)):
            if lo != ln:
                return "WRAP_SHIFT", (
                    f"換行斷點位移（第 {i + 1} 行）：舊 {len(lo)} 字／新 {len(ln)} 字"
                    f"（舊「{lo}」／新「{ln}」）")
        return "WRAP_SHIFT", "換行斷點位移（無法定位確切行，內容比對異常）"
    # 文字內容完全相同，但其餘欄位（座標／顏色／對齊…）不同──非量測差異，
    # 是 canvas 層本身的問題，理論上不應發生。
    return "OTHER_DIFF", (
        f"文字相同但其他欄位不同：舊 {old!r}／新 {new!r}")


def _diff_page(case, page_idx, old_ops, new_ops):
    diffs = []
    if len(old_ops) != len(new_ops):
        diffs.append({
            "case": case, "page": page_idx, "kind": "OTHER_DIFF",
            "detail": f"op 筆數不同：舊 {len(old_ops)}／新 {len(new_ops)}（結構性差異，未逐筆比對）"})
        return diffs
    for i, (old, new) in enumerate(zip(old_ops, new_ops)):
        if old == new:
            continue
        if isinstance(old, TextOp) and isinstance(new, TextOp):
            result = _classify_text_op(old, new)
            if result is None:
                continue
            kind, detail = result
        elif isinstance(old, (RectOp, LineOp)) or isinstance(new, (RectOp, LineOp)):
            kind, detail = "OTHER_DIFF", f"非文字 op 不同：舊 {old!r}／新 {new!r}"
        else:
            kind, detail = "OTHER_DIFF", f"op 型別不同：舊 {old!r}／新 {new!r}"
        diffs.append({
            "case": case, "page": page_idx, "op_index": i,
            "kind": kind, "detail": detail})
    return diffs


def run():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.makedirs(OUT_DIR, exist_ok=True)
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])  # noqa: F841  (需存活到程式結束)

    all_diffs = []
    total_pages = 0
    total_ops = 0

    # ⚠️ _record_ops()／_render_qt_png() 會改 tp._TEXT_WIDTH_FN 這個全域
    # 狀態（見 tp._set_text_measurer()）；用 try/finally 確保無論中途是否
    # 拋例外，離開 run() 時都還原成產品預設 'qt'，不讓量測後端停在 mpl
    # 滲透到呼叫端後續動作（STAGE2-FIX-BRIEF §2-4；階段 3 起產品預設是
    # 'qt'，還原目標跟著換）。
    try:
        for db, date_str, desc in CASES:
            case = _case_key(db, date_str)
            specs = _case_page_specs(db, date_str)
            rendered = False
            page_idx = 0
            for kind, kw in specs:
                if kind == "blank":
                    page_idx += 1
                    continue
                old_ops = _record_ops(kind, kw, mpl_text_width_pt)
                new_ops = _record_ops(kind, kw, "qt")
                total_ops += len(old_ops)
                all_diffs.extend(_diff_page(case, page_idx, old_ops, new_ops))
                if not rendered:
                    out_path = os.path.join(OUT_DIR, f"{case}_page{page_idx:02d}.png")
                    _render_qt_png(kind, kw, out_path)
                    rendered = True
                page_idx += 1
            total_pages += page_idx
    finally:
        tp._set_text_measurer("qt")

    counts = Counter(d["kind"] for d in all_diffs)

    print(f"[engine_diff] {len(CASES)} 個案例、{total_pages} 頁、{total_ops} 筆 op 已比對完成。")
    print("差異統計（依嚴重度）：")
    for kind in SEVERITY:
        print(f"  {kind:15s} {counts.get(kind, 0)}")
    if not all_diffs:
        print("[engine_diff] 兩引擎逐格比對完全相同，無任何差異。")
        return 0

    print("\n差異明細：")
    for kind in SEVERITY:
        items = [d for d in all_diffs if d["kind"] == kind]
        if not items:
            continue
        print(f"\n── {kind}（{len(items)} 條）──")
        for d in items:
            where = f"[{d['case']} 第 {d['page'] + 1} 頁]"
            print(f"  {where} {d['detail']}")

    print(f"\nQtCanvas 實際畫出的頁面（每案第一頁）已輸出到 {OUT_DIR}，可直接開圖目視。")
    return 0


if __name__ == "__main__":
    sys.exit(run())
