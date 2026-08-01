# -*- coding: utf-8 -*-
"""建立列印基準專用的兩份完整虛構 SQLite 資料庫。

用法：
    python tools/seed_print_baseline.py <輸出資料夾>
"""
from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import sqlite3
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib.db_schema import applySchema  # noqa: E402
from lib.db_seed import seedFreshDb  # noqa: E402


GENERAL_NAME = "dbfile.db"
MULTILINE_NAME = "dbfile_multiline_title.db"
FIXED_LAST_MODIFIED = "2026-01-01 00:00:00"
LONG_TEXT = (
    "【虛構測試】為驗證列印欄位在極長內容下會先縮小字級再於超出可用行數時截斷，"
    "本段刻意加入大量完全虛構的說明文字，並重複描述測試目的與預期版面行為，"
    "確保交辦主旨、刑案案由、一般公文主旨及敘獎事由都能走到相同的極端排版分支，"
    "所有姓名、案件、日期與編號均為自動產生的測試資料，與任何實際人物或事件無關。"
)
LONG_TICKET_NO = "LONG" + "0" * 24


PERSONNEL = (
    ("P01", "測試甲", 1, 1, ""),
    ("P02", "測試乙", 1, 2, ""),
    ("P03", "測試丙", 1, 3, ""),
    ("P04", "測試丁", 1, 4, ""),
    ("P05", "測試戊", 1, 5, ""),
    ("P06", "測試己", 1, 6, ""),
)


def _replace_reference_data(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM Ref_Personnel")
    conn.executemany(
        "INSERT INTO Ref_Personnel"
        "(staff_id,staff_name,is_active,sort_order,alias) VALUES(?,?,?,?,?)",
        PERSONNEL,
    )
    conn.execute(
        "UPDATE Ref_CaseTypes SET case_type_name="
        "CASE WHEN case_type_id='CT01' THEN ? ELSE '測試案類' || case_type_id END, "
        "alias=''",
        ("虛構極長案類名稱用來驗證固定字級與欄寬截斷分支是否正確運作測試",),
    )
    conn.execute(
        "UPDATE Ref_Departments SET dept_name='測試單位' || dept_id"
    )
    conn.executemany(
        "UPDATE App_Settings SET value=? WHERE key=?",
        (
            ("測試機關交辦單發文簽收表", "print_title_task"),
            ("測試機關刑案陳報單發文簽收表", "print_title_crim"),
            ("測試機關一般陳報單發文簽收表", "print_title_gen"),
            ("測試機關敘獎發文簽收表", "print_title_reward"),
            ("測試機關罰單簽收表", "print_title_ticket"),
            ("【虛構測試資料】", "print_note_current"),
        ),
    )


def _insert_tasks(conn: sqlite3.Connection) -> None:
    cases = (
        ("2026-05-11", 16),
        ("2026-02-23", 16),
        ("2026-06-22", 4),
        ("2026-08-10", 4),
    )
    doc_id = 1
    for date_text, count in cases:
        for index in range(count):
            subject = LONG_TEXT if date_text == "2026-08-10" and index == 0 else (
                f"【虛構測試】交辦事項{doc_id:03d}"
            )
            conn.execute(
                "INSERT INTO Document_Task"
                "(doc_id,receive_date,receive_id,dept_id,subject,processor_id,"
                "deadline,dispatch_date,sender_id,timestamp,last_modified) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(doc_id), date_text, f"P{index % 6 + 1:02d}",
                    f"D{index % 11 + 1:02d}", subject,
                    f"P{(index + 1) % 6 + 1:02d}", date_text, date_text,
                    f"P{(index + 2) % 6 + 1:02d}",
                    f"{date_text} 09:{index % 60:02d}:00", FIXED_LAST_MODIFIED,
                ),
            )
            doc_id += 1


def _insert_criminal(conn: sqlite3.Connection) -> None:
    cases = (
        ("2026-05-11", 26),
        ("2026-02-23", 22),
        ("2026-06-22", 31),
        ("2026-08-10", 3),
    )
    doc_id = 1
    for date_text, count in cases:
        for index in range(count):
            if date_text == "2026-05-11":
                status = "CS01" if index < 13 else "CS02"
            else:
                status = f"CS{index % 3 + 1:02d}"
            summary = LONG_TEXT if date_text == "2026-08-10" and index == 0 else (
                f"【虛構測試】刑案案由{doc_id:03d}"
            )
            conn.execute(
                "INSERT INTO Document_Criminal"
                "(doc_id,create_date,report_date,sender_id,case_type,case_status,"
                "processor_id,subject_summary,occurrence_date,reporter_name,"
                "receiver_id,is_reported,is_electronic,last_modified) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(doc_id), date_text, date_text,
                    f"P{index % 6 + 1:02d}", "CT01" if index == 0 else "CT02",
                    status, f"P{(index + 1) % 6 + 1:02d}", summary, date_text,
                    f"測試報案人{doc_id:03d}", f"P{(index + 2) % 6 + 1:02d}",
                    index % 2, "", FIXED_LAST_MODIFIED,
                ),
            )
            doc_id += 1


def _insert_general(conn: sqlite3.Connection) -> None:
    cases = (
        ("2026-05-11", 16),
        ("2026-02-23", 39),
        ("2026-06-22", 14),
        ("2026-08-10", 2),
    )
    doc_id = 1
    for date_text, count in cases:
        for index in range(count):
            subject = LONG_TEXT if date_text == "2026-08-10" and index == 0 else (
                f"【虛構測試】一般公文主旨{doc_id:03d}"
            )
            conn.execute(
                "INSERT INTO Document_General"
                "(doc_id,create_date,report_date,sender_id,dept_id,gen_cat_id,"
                "subject,processor_id,is_reported,is_electronic,last_modified) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(doc_id), date_text, date_text,
                    f"P{index % 6 + 1:02d}", f"D{index % 11 + 1:02d}",
                    f"GC{index % 3 + 1:02d}", subject,
                    f"P{(index + 1) % 6 + 1:02d}", index % 2, "",
                    FIXED_LAST_MODIFIED,
                ),
            )
            doc_id += 1


def _insert_rewards(conn: sqlite3.Connection) -> None:
    doc_id = 1
    for date_text, count in (("2026-05-11", 5), ("2026-08-10", 2)):
        for index in range(count):
            reason = LONG_TEXT if date_text == "2026-08-10" and index == 0 else (
                f"【虛構測試】敘獎事由{doc_id:03d}"
            )
            conn.execute(
                "INSERT INTO Document_Reward"
                "(doc_id,create_date,register_date,sender_id,reason,recipients,last_modified) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    str(doc_id), date_text, date_text,
                    f"P{index % 6 + 1:02d}", reason, "測試甲、測試乙",
                    FIXED_LAST_MODIFIED,
                ),
            )
            doc_id += 1


def _insert_tickets(conn: sqlite3.Connection) -> None:
    doc_id = 1
    for date_text, count in (
        ("2026-07-26", 180),
        ("2026-07-25", 10),
        ("2026-08-11", 27),
    ):
        for index in range(count):
            if date_text == "2026-08-11" and index == 0:
                ticket_no = LONG_TICKET_NO
            else:
                ticket_no = f"TEST{doc_id:08d}"
            issuer_id = "P01" if date_text == "2026-08-11" and index < 20 else (
                f"P{index % 6 + 1:02d}"
            )
            conn.execute(
                "INSERT INTO Document_Ticket"
                "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no,last_modified) "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    str(doc_id), date_text, date_text, "P06", issuer_id,
                    ticket_no, FIXED_LAST_MODIFIED,
                ),
            )
            doc_id += 1


def _build_general(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        applySchema(conn)
        seedFreshDb(conn)
        _replace_reference_data(conn)
        _insert_tasks(conn)
        _insert_criminal(conn)
        _insert_general(conn)
        _insert_rewards(conn)
        _insert_tickets(conn)
        for table in (
            "Document_Task",
            "Document_Criminal",
            "Document_General",
            "Document_Reward",
            "Document_Ticket",
        ):
            conn.execute(
                f"UPDATE {table} SET last_modified=?", (FIXED_LAST_MODIFIED,)
            )
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()


def build_databases(output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    general_path = output_dir / GENERAL_NAME
    multiline_path = output_dir / MULTILINE_NAME
    existing = [path for path in (general_path, multiline_path) if path.exists()]
    if existing:
        names = "、".join(path.name for path in existing)
        raise FileExistsError(f"拒絕覆寫既有資料庫：{names}")

    _build_general(general_path)
    shutil.copyfile(general_path, multiline_path)
    conn = sqlite3.connect(multiline_path)
    try:
        conn.executemany(
            "UPDATE App_Settings SET value=? WHERE key=?",
            (
                (
                    "測試機關交辦單發文簽收表\n（多行標題虛構測試）",
                    "print_title_task",
                ),
                (
                    "測試機關罰單簽收表\n（多行標題虛構測試）",
                    "print_title_ticket",
                ),
            ),
        )
        conn.commit()
        conn.execute("VACUUM")
    finally:
        conn.close()
    return general_path, multiline_path


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path, help="兩份基準資料庫的輸出資料夾")
    args = parser.parse_args(argv)
    try:
        paths = build_databases(args.output_dir.expanduser().resolve())
    except FileExistsError as exc:
        parser.error(str(exc))
    print("已建立虛構列印基準資料庫：")
    for path in paths:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
