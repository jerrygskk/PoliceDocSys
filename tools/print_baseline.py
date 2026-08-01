# -*- coding: utf-8 -*-
"""簽收表輸出的基準快照與比對。

階段 1 建立本工具時，唯一驗收標準是「輸出完全沒變」——那時產品引擎仍是
matplotlib，任何差異都代表抽層抄錯了。**階段 3 起產品引擎已換成 Qt**，
`generate_pages()` 的輸出必然與本基準不同，本工具不再比對產品輸出。

改成明確走 **`tools/mpl_canvas.py` 的 matplotlib 路徑**（`_build_page_specs()`
與階段 1／2 建立基準時同一份分頁／排序邏輯＋同一顆 `MatplotlibCanvas`）
產生影像，證明「matplotlib 參考基準本身沒有位移」——`tools/render_diff.py`
拿它當比對基準才有意義。

用法：
    python tools/print_baseline.py --save             # 建立基準（已建好，勿重跑）
    python tools/print_baseline.py --save --force      # 基準已存在時強制覆寫
                                                         # （須以未改動的 HEAD 產生，否則使前面所有階段的驗收失效）
    python tools/print_baseline.py --check            # 比對，回傳碼 0 = 通過

基準檔放在 `docs/print_baseline/`（`.gitignore` 排除 `docs/*`，不會污染
`git status`）。比對失敗時會把有差異那幾頁的新舊 PNG 一起留在
`docs/print_baseline/diff/`，可直接開圖看差在哪。

⚠️ 本工具只驗「matplotlib 參考輸出有沒有位移」，不驗「Qt 畫得對不對」——
後者靠 `tools/render_diff.py`；也不驗既有邏輯正確性，那靠
`tests/test_ticket_print.py`。三者都要過。
"""

import argparse
import hashlib
import io
import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BASE_DIR = os.path.join("docs", "print_baseline")
MANIFEST = os.path.join(BASE_DIR, "manifest.json")
DIFF_DIR = os.path.join(BASE_DIR, "diff")

# 涵蓋全部五種 section 與各項邊界；每筆為 (DB 檔, 日期, 說明)。
# 依測試 DB 實際資料挑選，勿隨意更動——改了就不是同一組基準。
#
# ⚠️ 後段「極端排版」案例是階段 1 驗證的教訓：當時的基準只有前 6 筆，
# 把罰單編號的防溢出裁切整個停用，61 張影像**仍全部相同**——那條路徑
# 根本沒被走到。逐位元組比對只證明「已涵蓋的路徑沒變」，不證明「沒有
# 路徑壞掉」，所以必須有踩得到每條分支的測資。資料由
# `tools/seed_extreme_cases.py` 產生。
_DB = "dbfile.db"
_DB_ML = "dbfile_multiline_title.db"   # 標題含換行（全域設定，須獨立一份）

CASES = [
    # ── 一般路徑（階段 1 建立，勿更動）──
    (_DB, "2026-05-11", "交辦16/刑案26（含13筆現行犯免簽收）/一般16/敘獎5：四種表齊全＋現行犯註記"),
    (_DB, "2026-02-23", "交辦16/刑案22/一般39：最大資料量，多頁與奇數頁補白"),
    (_DB, "2026-06-22", "交辦4/刑案31/一般14：刑案跨頁"),
    (_DB, "2026-07-26", "罰單150筆：三頁滿版，跨欄／跨頁重建姓名群組"),
    (_DB, "2026-07-25", "罰單10筆：單頁未滿，補空白列"),
    (_DB, "2026-01-01", "查無資料：generate_pages 應回傳 (None, None, None)"),
    # ── 極端排版路徑 ──
    (_DB, "2026-08-10", "超長主旨／案類／敘獎事由：12→10pt 縮字與截斷加「…」"),
    (_DB, "2026-08-11", "罰單28碼超長編號＋單一人員佔滿整欄：_fit_font 觸底＋clipRect 裁切＋最大 rowspan"),
    (_DB_ML, "2026-08-10", "標題含換行：多行文字的 linespacing／multialignment 路徑"),
    (_DB_ML, "2026-08-11", "標題含換行（罰單表）"),
]


def _sha(b):
    return hashlib.sha256(b).hexdigest()


def _case_key(db, date_str):
    """案例識別字串。同一日期可能在不同 DB 各有一筆，故帶上 DB 名。"""
    stem = os.path.splitext(os.path.basename(db))[0]
    return date_str if stem == "dbfile" else f"{stem}_{date_str}"


# 每張簽收表左上角都印「列印日期」＝今天。若不固定住，基準會在**每天午夜
# 自動失效**（隔天比對整批不同，看起來像重構改壞了）。踩過一次：基準建於
# 2026-07-31，隔天重跑 6 個案例全報不同，實際上程式碼一行沒動。
# 故比對期間一律把 `_today()` 凍結成固定字串。
FROZEN_PRINT_DATE = "2026/07/31"


def collect():
    """跑完所有案例，回傳 {案例識別: {頁碼: (sha, png_bytes)}}。

    明確走 `tools/mpl_canvas.py` 的 matplotlib 路徑（見檔頭說明）：
    分頁／排序邏輯沿用 `tabs.tab_print._build_page_specs()`（與產品共用
    同一份，不重複實作），但畫圖與量測全部切回 matplotlib，
    與階段 1／2 建立基準當時的引擎完全一致。"""
    import tabs.tab_print as tp
    from tools.mpl_canvas import mpl_text_width_pt, new_mpl_page

    tp._today = lambda: FROZEN_PRINT_DATE

    out = {}
    try:
        tp._set_text_measurer(mpl_text_width_pt)
        for db, date_str, _desc in CASES:
            key = _case_key(db, date_str)
            specs = tp._build_page_specs(db, date_str)
            if not specs:
                out[key] = {"__empty__": ("EMPTY", b"")}
                continue
            pages = {}
            for i, (kind, kw) in enumerate(specs):
                import matplotlib.pyplot as plt
                fig, cv = new_mpl_page(tp.fp)
                try:
                    tp._draw_spec(kind, kw, cv)

                    buf = io.BytesIO()
                    fig.savefig(buf, format="png", dpi=200,
                                bbox_inches="tight", facecolor="white")
                    png = buf.getvalue()
                    pages[f"preview_{i:02d}"] = (_sha(png), png)

                    # 列印用 300dpi 全頁影像也要比對：與預覽走同一份 figure，
                    # 但 savefig 參數不同（不裁切），是另一條輸出路徑。
                    buf2 = io.BytesIO()
                    fig.savefig(buf2, format="png", dpi=300, facecolor="white")
                    png2 = buf2.getvalue()
                    pages[f"print_{i:02d}"] = (_sha(png2), png2)
                finally:
                    plt.close(fig)
            out[key] = pages
    finally:
        tp._set_text_measurer("qt")
    return out


def cmd_save(force=False):
    if os.path.exists(MANIFEST) and not force:
        print(f"[X] 基準已存在（{MANIFEST}），拒絕覆寫。"
              f"基準必須以未改動的 HEAD 程式碼產生，重建會使前面所有階段"
              f"的驗收失效；確定要重建才加 --force。")
        return 2
    os.makedirs(BASE_DIR, exist_ok=True)
    data = collect()
    manifest = {}
    for case, pages in data.items():
        manifest[case] = {k: sha for k, (sha, _b) in pages.items()}
        for key, (_sha_, blob) in pages.items():
            if blob:
                with open(os.path.join(BASE_DIR, f"{case}_{key}.png"), "wb") as f:
                    f.write(blob)
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    total = sum(len(v) for v in manifest.values())
    print(f"[OK] 基準已建立：{len(manifest)} 個案例、{total} 張影像 → {BASE_DIR}")
    for db, date_str, desc in CASES:
        k = _case_key(db, date_str)
        print(f"  {k}  {len(manifest[k]):3d} 張  {desc}")
    return 0


def cmd_check():
    if not os.path.exists(MANIFEST):
        print(f"[X] 找不到基準：{MANIFEST}（需先跑 --save，且必須在重構前跑）")
        return 2
    with open(MANIFEST, encoding="utf-8") as f:
        base = json.load(f)

    now = collect()
    shutil.rmtree(DIFF_DIR, ignore_errors=True)

    bad = []
    for db, date_str, _desc in CASES:
        case = _case_key(db, date_str)
        exp = base.get(case, {})
        got = now.get(case, {})
        if set(exp) != set(got):
            bad.append((case, f"頁數/組成不同：基準 {len(exp)} 張、現在 {len(got)} 張"))
            continue
        for key in sorted(exp):
            if exp[key] != got[key][0]:
                bad.append((case, f"{key} 內容不同"))
                os.makedirs(DIFF_DIR, exist_ok=True)
                src = os.path.join(BASE_DIR, f"{case}_{key}.png")
                if os.path.exists(src):
                    shutil.copy(src, os.path.join(DIFF_DIR, f"{case}_{key}_OLD.png"))
                with open(os.path.join(DIFF_DIR, f"{case}_{key}_NEW.png"), "wb") as f:
                    f.write(got[key][1])

    total = sum(len(v) for v in base.values())
    if not bad:
        print(f"[OK] {total} 張影像全部與基準逐位元組相同 → 階段 1 驗收通過")
        return 0

    print(f"[X] {len(bad)} 處與基準不同（共比對 {total} 張）：")
    for case, msg in bad:
        print(f"  {case}  {msg}")
    print(f"\n差異影像已輸出到 {DIFF_DIR}（_OLD 為基準、_NEW 為現在），可直接開圖比對。")
    return 1


def main():
    ap = argparse.ArgumentParser(description="簽收表輸出基準快照／比對")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save", action="store_true", help="建立基準（重構前）")
    g.add_argument("--check", action="store_true", help="比對基準（重構後）")
    ap.add_argument("--force", action="store_true",
                     help="配合 --save：基準已存在時仍強制覆寫")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    missing = sorted({db for db, _d, _x in CASES if not os.path.exists(db)})
    if missing:
        print(f"[X] 找不到資料庫：{'、'.join(missing)}（需在專案根目錄執行；"
              f"極端案例的 DB 由 tools/seed_extreme_cases.py 產生）")
        return 2
    return cmd_save(force=args.force) if args.save else cmd_check()


if __name__ == "__main__":
    sys.exit(main())
