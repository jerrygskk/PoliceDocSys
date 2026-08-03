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
    python tools/print_baseline.py --db-dir tmp/print-baseline --save --force
    python tools/print_baseline.py --db-dir tmp/print-baseline --check

PNG 放在 `docs/print_baseline/`（`.gitignore` 排除 `docs/*`）；可攜的
manifest 放在 `tests/print_baseline_manifest.json`。比對失敗時會把有差異那幾頁的新舊 PNG 一起留在
`docs/print_baseline/diff/`，可直接開圖看差在哪。

⚠️ 本工具只驗「matplotlib 參考輸出有沒有位移」，不驗「Qt 畫得對不對」——
後者靠 `tools/render_diff.py`；也不驗既有邏輯正確性，那靠
`tests/test_ticket_print.py`。三者都要過。
"""

import argparse
from contextlib import contextmanager
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = Path(__file__).resolve().parents[1]
BASE_DIR = str(ROOT / "docs" / "print_baseline")
MANIFEST = str(ROOT / "tests" / "print_baseline_manifest.json")
DIFF_DIR = os.path.join(BASE_DIR, "diff")

# 涵蓋全部五種 section 與各項邊界；每筆為 (DB 檔, 日期, 說明)。
# 依測試 DB 實際資料挑選，勿隨意更動——改了就不是同一組基準。
#
# ⚠️ 後段「極端排版」案例是階段 1 驗證的教訓：當時的基準只有前 6 筆，
# 把罰單編號的防溢出裁切整個停用，61 張影像**仍全部相同**——那條路徑
# 根本沒被走到。逐位元組比對只證明「已涵蓋的路徑沒變」，不證明「沒有
# 路徑壞掉」，所以必須有踩得到每條分支的測資。資料由
# `tools/seed_print_baseline.py` 產生。
_DB = "dbfile.db"
_DB_ML = "dbfile_multiline_title.db"   # 標題含換行（全域設定，須獨立一份）

CASES = [
    # ── 一般路徑 ──
    (_DB, "2026-05-11", "交辦16/刑案26（含13筆現行犯免簽收）/一般16/敘獎5：四種表齊全＋現行犯註記"),
    (_DB, "2026-02-23", "交辦16/刑案22/一般39：最大資料量，多頁與奇數頁補白"),
    (_DB, "2026-06-22", "交辦4/刑案31/一般14：刑案跨頁"),
    (_DB, "2026-07-26", "罰單180筆：三頁滿版，跨欄／跨頁重建姓名群組"),
    (_DB, "2026-07-25", "罰單10筆：單頁未滿，補空白列"),
    (_DB, "2026-01-01", "查無資料：generate_pages 應回傳 (None, None, None)"),
    # ── 極端排版路徑 ──
    (_DB, "2026-08-10", "超長主旨／案類／敘獎事由：12→10pt 縮字與截斷加「…」"),
    (_DB, "2026-08-11", "罰單28碼超長編號＋單一人員佔滿整欄：_fit_font 觸底＋clipRect 裁切＋最大 rowspan"),
    (_DB_ML, "2026-08-10", "標題含換行：多行文字的 linespacing／multialignment 路徑"),
    (_DB_ML, "2026-08-11", "標題含換行（罰單表）"),
]


def resolve_cases(db_dir):
    """把固定案例映射到 seed 工具產生的資料庫目錄。"""
    root = Path(db_dir).expanduser().resolve()
    return [(str(root / db), date_str, desc) for db, date_str, desc in CASES]


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


@contextmanager
def _isolated_mpl_config():
    """讓一整次 command 在任何 matplotlib import 前使用獨立設定目錄。"""
    temp_config = tempfile.TemporaryDirectory(prefix="policedocsys-mpl-")
    config_path = temp_config.name
    old_config = os.environ.get("MPLCONFIGDIR")
    os.environ["MPLCONFIGDIR"] = config_path
    print(f"[MPL] 本次設定目錄：{config_path}")
    try:
        yield config_path
    finally:
        if old_config is None:
            os.environ.pop("MPLCONFIGDIR", None)
        else:
            os.environ["MPLCONFIGDIR"] = old_config
        temp_config.cleanup()
        print(f"[MPL] 已清理設定目錄：{config_path}")


def collect(db_dir):
    """以獨立 MPL 設定跑完所有案例，回傳影像 hash 與 bytes。"""
    with _isolated_mpl_config():
        return _collect_with_mpl_config(db_dir)


def _collect_with_mpl_config(db_dir):
    """在 command 配置的單次 matplotlib 設定目錄內產生影像。

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
        for db, date_str, _desc in resolve_cases(db_dir):
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


def _font_version(path):
    from matplotlib.ft2font import FT2Font

    for key, value in FT2Font(path).get_sfnt().items():
        if key[-1] != 5:
            continue
        try:
            return value.decode("utf-16-be" if key[0] == 3 else "utf-8")
        except UnicodeDecodeError:
            continue
    return "unknown"


def _windows_scaling_percent():
    if sys.platform != "win32":
        return 100
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop\WindowMetrics",
        ) as key:
            dpi, _kind = winreg.QueryValueEx(key, "AppliedDPI")
        return round(int(dpi) * 100 / 96)
    except (OSError, TypeError, ValueError):
        try:
            import ctypes

            return round(ctypes.windll.user32.GetDpiForSystem() * 100 / 96)
        except (AttributeError, OSError):
            return 100


def environment_metadata():
    """回傳會影響逐位元組輸出的可攜環境描述。"""
    import PySide6
    import matplotlib
    from PySide6.QtCore import qVersion
    import tabs.tab_print as tp

    def font(path):
        return {"file": Path(path).name, "version": _font_version(path)}

    return {
        "fonts": {"regular": font(tp._REG), "bold": font(tp._BOLD)},
        "matplotlib_version": matplotlib.__version__,
        "qt_version": qVersion(),
        "pyside6_version": PySide6.__version__,
        "windows_scaling_percent": _windows_scaling_percent(),
    }


def _flatten_environment(environment, prefix=""):
    flat = {}
    for key, value in environment.items():
        name = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_environment(value, name))
        else:
            flat[name] = value
    return flat


def _print_environment_comparison(recorded, current):
    recorded_flat = _flatten_environment(recorded)
    current_flat = _flatten_environment(current)
    print("\n環境資訊（記錄值 vs 目前值）：")
    print(f"  {'項目':<32} {'記錄值':<28} 目前值")
    for key in sorted(set(recorded_flat) | set(current_flat)):
        old = str(recorded_flat.get(key, "<未記錄>"))
        new = str(current_flat.get(key, "<無>"))
        print(f"  {key:<32} {old:<28} {new}")


def cmd_save(db_dir, force=False):
    if os.path.exists(MANIFEST) and not force:
        print(f"[X] 基準已存在（{MANIFEST}），拒絕覆寫。"
              f"基準必須以未改動的 HEAD 程式碼產生，重建會使前面所有階段"
              f"的驗收失效；確定要重建才加 --force。")
        return 2
    os.makedirs(BASE_DIR, exist_ok=True)
    with _isolated_mpl_config():
        metadata = environment_metadata()
        data = _collect_with_mpl_config(db_dir)
    cases = {}
    for case, pages in data.items():
        cases[case] = {k: sha for k, (sha, _b) in pages.items()}
        for key, (_sha_, blob) in pages.items():
            if blob:
                with open(os.path.join(BASE_DIR, f"{case}_{key}.png"), "wb") as f:
                    f.write(blob)
    manifest = {"environment": metadata, "cases": cases}
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    total = sum(len(v) for v in cases.values())
    print(f"[OK] 基準已建立：{len(cases)} 個案例、{total} 張影像 → {BASE_DIR}")
    for db, date_str, desc in CASES:
        k = _case_key(db, date_str)
        print(f"  {k}  {len(cases[k]):3d} 張  {desc}")
    return 0


def _environment_drift_message(db_dir):
    return (
        "[X] 產生環境與基準記錄不同，已**停止比對**（沒有算圖）。\n"
        "    雜湊基準綁字型檔、matplotlib／Qt／PySide6 版本與顯示縮放，環境不同時\n"
        "    逐位元組比對沒有意義——會得到「上百處不同」，那是環境漂移、不是程式回歸。\n"
        "    請擇一處理：\n"
        "      ① 把環境對齊回記錄值（多半是 requirements-dev.txt 的 pin 被裝成別版）；\n"
        f"      ② 確定要以目前環境當新起點，就重建基準並重新人工目視核准：\n"
        f"         python tools/seed_print_baseline.py {db_dir}\n"
        f"         python tools/print_baseline.py --db-dir {db_dir} --save --force\n"
        "         （雜湊全綠只證明前後一致、不證明畫得對，重建後仍須逐張目視，\n"
        "          見 PRINTING.md §4）\n"
        "      ③ 只是想看差異圖、明知環境不同：加 --allow-environment-drift 續跑。"
    )


def cmd_check(db_dir, allow_environment_drift=False):
    if not os.path.exists(MANIFEST):
        print(f"[X] 找不到完整基準：{BASE_DIR} / {MANIFEST}")
        print("請依序重建：")
        print(f"  python tools/seed_print_baseline.py {db_dir}")
        print(f"  python tools/print_baseline.py --db-dir {db_dir} --save --force")
        return 2
    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)

    base = manifest.get("cases", {})
    recorded_environment = manifest.get("environment", {})

    # 環境先行：算圖要 90 秒以上，而環境不同時那 90 秒的結果一定是「上百處不同」，
    # 既浪費時間又容易被誤判成程式回歸（實際發生過）。故先比環境再決定要不要算。
    with _isolated_mpl_config():
        current_environment = environment_metadata()
        drifted = recorded_environment != current_environment
        if drifted and not allow_environment_drift:
            print(_environment_drift_message(db_dir))
            _print_environment_comparison(recorded_environment, current_environment)
            return 3
        now = _collect_with_mpl_config(db_dir)
    shutil.rmtree(DIFF_DIR, ignore_errors=True)

    bad = []
    if drifted:
        print("[!] 環境與基準不同，但已指定 --allow-environment-drift，續行比對；"
              "以下差異可能全部來自環境漂移。")
        bad.append(("environment", "產生環境不同"))
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
    _print_environment_comparison(recorded_environment, current_environment)
    print(f"\n差異影像已輸出到 {DIFF_DIR}（_OLD 為基準、_NEW 為現在），可直接開圖比對。")
    return 1


def main():
    ap = argparse.ArgumentParser(description="簽收表輸出基準快照／比對")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--save", action="store_true", help="建立基準（重構前）")
    g.add_argument("--check", action="store_true", help="比對基準（重構後）")
    ap.add_argument("--force", action="store_true",
                     help="配合 --save：基準已存在時仍強制覆寫")
    ap.add_argument("--allow-environment-drift", action="store_true",
                     help="配合 --check：環境與基準不同時仍續行比對"
                          "（預設是停下不算圖，結束碼 3）")
    ap.add_argument(
        "--db-dir",
        default=str(ROOT / "tmp" / "print-baseline"),
        help="tools/seed_print_baseline.py 產生兩份資料庫的資料夾",
    )
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if args.check and not os.path.exists(MANIFEST):
        return cmd_check(args.db_dir, args.allow_environment_drift)
    missing = sorted(
        {db for db, _d, _x in resolve_cases(args.db_dir) if not os.path.exists(db)}
    )
    if missing:
        print(f"[X] 找不到資料庫：{'、'.join(missing)}（需在專案根目錄執行；"
              f"請先執行 tools/seed_print_baseline.py）")
        return 2
    if args.save:
        return cmd_save(args.db_dir, force=args.force)
    return cmd_check(args.db_dir, args.allow_environment_drift)


if __name__ == "__main__":
    sys.exit(main())
