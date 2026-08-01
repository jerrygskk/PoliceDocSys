# -*- coding: utf-8 -*-
"""補進「會踩到極端排版分支」的測試資料，供 print_baseline.py 建立基準。

背景：階段 1 的獨立驗證用突變測試證明——把罰單編號的防溢出裁切整個停用，
61 張基準影像**仍然全部相同**，因為原測試資料裡沒有長到會溢出的編號，
那條路徑根本沒被執行到。

逐位元組比對只證明「已涵蓋的路徑沒變」，不證明「沒有路徑壞掉」。
本腳本補的就是那些沒被走到的分支：

  1. 超長罰單編號   → `_fit_font` 縮到 8pt 觸底後仍溢出 → 觸發 clipRect 裁切
  2. 極長主旨／案類 → `_wrap_clamp` 12→10pt 縮字，再超過則截斷加「…」
  3. 單一舉發人員佔滿整個直欄 → 最大 rowspan 合併
  4. 標題含換行     → 多行文字的 linespacing／multialignment 路徑
  5. 剛好卡在欄寬臨界的字串 → 換行決策的邊界

⚠️ 一律使用**新日期**，不碰既有 6 個基準案例的日期，既有 61 張影像才會
維持不變、可與舊基準交叉核對。

⚠️ 人名一律用明顯假名（測試○），不得放入真實個資。

⚠️ **現行基準（`docs/print_baseline/`）是在「長編號唯一化」修正之前產生的**，
當時罰單案例實際只有 23 筆（非 27）、長編號只有 1 筆、滿欄合併 16 列（非 20）。
覆蓋度雖略低於設計值，但已足以觸發 clipRect 裁切路徑（突變測試證實抓得到）。
下次重新產生基準時（必須用未改動的 HEAD 程式碼跑 `print_baseline.py --save`），
罰單案例的影像會因本修正而改變，屬預期行為。

用法（在專案根目錄）：
    python tools/seed_extreme_cases.py            # 寫入 dbfile.db
    python tools/seed_extreme_cases.py --db 其他.db
"""

import argparse
import os
import sqlite3
import sys

# 極端案例專用日期（不與既有基準案例重疊）
D_LONG = "2026-08-10"   # 超長文字：主旨／案類／人員
D_TICKET = "2026-08-11"  # 罰單：超長編號＋滿欄合併

# 既有人員（Ref_Personnel 內已存在的 staff_id，避免外鍵失敗）
P_A, P_B, P_C = "P01", "P02", "P03"

LONG_SUBJECT = (
    "為辦理轄內治安顧慮人口查訪暨春safe專案勤務期間各項工作事宜，"
    "請各單位確實依照分局頒訂之作業規定辦理並於期限內回報執行情形，"
    "另有關查訪紀錄表之填寫方式如說明段所述，請確依規定辦理")
MID_SUBJECT = "為辦理轄內治安顧慮人口查訪暨專案勤務事宜請查照辦理"
EDGE_SUBJECT = "為辦理轄內治安顧慮人口查訪事宜請查照"
# 28 碼。長度是實測出來的，不是拍腦袋：罰單編號格寬 102.6pt，`_fit_font`
# 縮到 8pt 觸底後，ASCII 每字約 4.8pt——19 碼只有 91.2pt **還塞得下**，
# 要 24 碼（114.4pt）才真的溢出格線、才會觸發 clipRect 裁切那條路徑。
# 曾誤用 19 碼，導致停用裁切後基準仍全綠（照樣抓不到）。
LONG_TICKET_NO = "D4RD152630000123456789012345"


def seed(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    dept = cur.execute("SELECT dept_id FROM Ref_Departments LIMIT 1").fetchone()[0]
    ctype = cur.execute("SELECT case_type_id FROM Ref_CaseTypes LIMIT 1").fetchone()[0]
    gcat = cur.execute("SELECT gen_cat_id FROM Ref_General_Category LIMIT 1").fetchone()[0]

    # ── 1. 交辦單：長短交錯，觸發縮字與截斷 ────────────────────
    tasks = [
        ("9001", LONG_SUBJECT), ("9002", MID_SUBJECT),
        ("9003", EDGE_SUBJECT), ("9004", "短主旨"),
    ]
    for doc_id, subject in tasks:
        cur.execute(
            "INSERT OR REPLACE INTO Document_Task"
            "(doc_id,receive_date,receive_id,dept_id,subject,processor_id,"
            " deadline,dispatch_date,sender_id,timestamp,last_modified)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, D_LONG, P_A, dept, subject, P_B, D_LONG, D_LONG, P_A,
             f"{D_LONG} 10:00:00", f"{D_LONG} 10:00:00"))

    # ── 2. 刑案：含現行犯，案類欄固定 10pt 的截斷路徑 ──────────
    for doc_id, summary, status in (
            ("9001", LONG_SUBJECT, "CS01"),
            ("9002", MID_SUBJECT, "CS02"),
            ("9003", "短案由", "CS01")):
        cur.execute(
            "INSERT OR REPLACE INTO Document_Criminal"
            "(doc_id,report_date,sender_id,case_type,case_status,processor_id,"
            " subject_summary,occurrence_date,receiver_id,is_reported,"
            " is_electronic,last_modified,create_date) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, D_LONG, P_A, ctype, status, P_B, summary, D_LONG, P_B,
             1, "", f"{D_LONG} 10:00:00", D_LONG))

    # ── 3. 一般陳報：同上 ──────────────────────────────────────
    for doc_id, subject in (("9001", LONG_SUBJECT), ("9002", EDGE_SUBJECT)):
        cur.execute(
            "INSERT OR REPLACE INTO Document_General"
            "(doc_id,report_date,sender_id,dept_id,gen_cat_id,subject,"
            " processor_id,is_reported,is_electronic,last_modified,create_date)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (doc_id, D_LONG, P_A, dept, gcat, subject, P_B, 1, "",
             f"{D_LONG} 10:00:00", D_LONG))

    # ── 4. 敘獎：長事由與多人 ──────────────────────────────────
    for doc_id, reason, recips in (
            ("9001", LONG_SUBJECT, "測試甲,測試乙,測試丙,測試丁,測試戊,測試己"),
            ("9002", "短事由", "測試庚")):
        cur.execute(
            "INSERT OR REPLACE INTO Document_Reward"
            "(doc_id,register_date,sender_id,reason,recipients) VALUES(?,?,?,?,?)",
            (doc_id, D_LONG, P_A, reason, recips))

    # ── 5. 罰單：超長編號＋單一人員佔滿整欄（最大 rowspan）─────
    #    前 20 筆同一人（＝一個直欄的容量）→ 合併框跨滿整欄；
    #    其中數筆用超長編號 → _fit_font 觸底後仍溢出 → 走 clipRect。
    # ⚠️ `Document_Ticket` 有唯一索引 `ux_ticket_no_active`（ticket_no
    #    COLLATE NOCASE）。若多筆共用同一個 ticket_no，`INSERT OR REPLACE`
    #    會把先前那幾筆**整列換掉**而不是各自新增——踩過：長編號重複用 5 次，
    #    27 筆只剩 23 筆，滿欄合併從 20 列縮成 16 列、長編號只剩 1 筆。
    #    所以每個長編號都要各自唯一，用尾碼區分。
    rows = []
    for i in range(20):
        no = f"{LONG_TICKET_NO[:-2]}{i:02d}" if i % 5 == 0 else f"AA{i:07d}"
        rows.append((f"9{i:03d}", P_A, no))
    for i in range(6):   # 第二欄換人，驗證跨欄重建群組
        rows.append((f"92{i:02d}", P_B, f"BB{i:07d}"))
    rows.append(("9300", P_C, f"{LONG_TICKET_NO[:-2]}99"))
    for doc_id, issuer, no in rows:
        cur.execute(
            "INSERT OR REPLACE INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no)"
            " VALUES(?,?,?,?,?,?)",
            (doc_id, D_TICKET, D_TICKET, P_A, issuer, no))

    conn.commit()
    counts = {
        "交辦": cur.execute("SELECT count(*) FROM Document_Task WHERE dispatch_date=?", (D_LONG,)).fetchone()[0],
        "刑案": cur.execute("SELECT count(*) FROM Document_Criminal WHERE report_date=?", (D_LONG,)).fetchone()[0],
        "一般": cur.execute("SELECT count(*) FROM Document_General WHERE report_date=?", (D_LONG,)).fetchone()[0],
        "敘獎": cur.execute("SELECT count(*) FROM Document_Reward WHERE register_date=?", (D_LONG,)).fetchone()[0],
        "罰單": cur.execute("SELECT count(*) FROM Document_Ticket WHERE register_date=?", (D_TICKET,)).fetchone()[0],
    }
    conn.close()
    return counts


def make_multiline_title_db(src, dst):
    """另存一份「標題含換行」的 DB，用來走多行文字的排版分支。

    標題存在 App_Settings，是全域設定，改了會影響**每一張**簽收表，
    所以不能直接改主測試 DB（會讓既有 6 個基準案例的影像全變），
    必須另存一份、當成獨立案例。
    """
    import shutil
    shutil.copy(src, dst)
    conn = sqlite3.connect(dst)
    conn.execute(
        "UPDATE App_Settings SET value=? WHERE key='print_title_task'",
        ("龍興派出所交辦單發文簽收表\n（多行標題測試用第二行）",))
    conn.execute(
        "UPDATE App_Settings SET value=? WHERE key='print_title_ticket'",
        ("龍興派出所罰單簽收表\n（多行標題測試用第二行）",))
    conn.commit()
    conn.close()


def main():
    ap = argparse.ArgumentParser(description="補極端排版測試資料")
    ap.add_argument("--db", default="dbfile.db")
    ap.add_argument("--multiline-db", default="dbfile_multiline_title.db",
                    help="另存一份標題含換行的 DB（空字串表不產生）")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    if not os.path.exists(args.db):
        print(f"[X] 找不到 {args.db}")
        return 2
    counts = seed(args.db)
    print(f"[OK] 已寫入 {args.db}")
    print(f"  {D_LONG}（超長文字）：" +
          "／".join(f"{k} {v}" for k, v in counts.items() if k != "罰單"))
    print(f"  {D_TICKET}（罰單）：{counts['罰單']} 筆，"
          f"含 {LONG_TICKET_NO}（{len(LONG_TICKET_NO)} 碼）")
    if args.multiline_db:
        make_multiline_title_db(args.db, args.multiline_db)
        print(f"[OK] 已另存標題含換行的 DB：{args.multiline_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
