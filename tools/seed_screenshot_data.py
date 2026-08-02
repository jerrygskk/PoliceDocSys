# -*- coding: utf-8 -*-
"""建立公開 README 截圖用的完整候選資料庫。

用法：
    python tools/seed_screenshot_data.py <輸出路徑> [--force]

輸出路徑已存在時必須明確加上 ``--force``。無論是否加旗標，本工具都拒絕
覆寫專案根目錄的 dbfile.db。

候選姓名待維護者對照真實名單核准；不得據此宣稱已證明不對應真人。
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lib import db_schema, db_seed  # noqa: E402
from tools.fake_seed_data import FAKE_DATA  # noqa: E402
MAIN_TABLES = (
    "Document_Task",
    "Document_Criminal",
    "Document_General",
    "Document_Reward",
    "Document_Ticket",
)
VIEWS = (
    "View_Task_Full",
    "View_Criminal_Full",
    "View_General_Full",
    "Document_Ticket_Full",
)


def _day(base: date, offset: int) -> str:
    return (base + timedelta(days=offset)).isoformat()


def _replace_reference_data(conn: sqlite3.Connection) -> None:
    """以共用候選資料取代正式 seed 的參照內容。"""
    personnel = tuple(
        (person.staff_id, person.name, 1, order, person.alias)
        for order, person in enumerate(FAKE_DATA.personnel, start=1)
    )
    conn.execute("DELETE FROM Ref_Personnel")
    conn.executemany(
        "INSERT INTO Ref_Personnel"
        "(staff_id,staff_name,is_active,sort_order,alias) VALUES(?,?,?,?,?)",
        personnel,
    )

    dept_names = (
        "行政組", "偵查隊", "交通組", "防治組", "保安組", "督察組",
        "勤務指揮中心", "秘書室", "人事室", "會計室", "已停用單位",
    )
    for index, name in enumerate(dept_names, start=1):
        conn.execute(
            "UPDATE Ref_Departments "
            "SET dept_name=?, is_active=?, sort_order=? WHERE dept_id=?",
            (name, 0 if index == 11 else 1, index, f"D{index:02d}"),
        )

    for index in range(1, 28):
        conn.execute(
            "UPDATE Ref_CaseTypes "
            "SET case_type_name=?, is_active=?, sort_order=?, alias=? "
            "WHERE case_type_id=?",
            (
                f"案件類別{index:02d}",
                0 if index == 27 else 1,
                index,
                f"類別{index:02d}",
                f"CT{index:02d}",
            ),
        )

    for status_id, name in (
        ("CS01", "持續偵辦"),
        ("CS02", "已到案"),
        ("CS03", "未到案"),
    ):
        conn.execute(
            "UPDATE Ref_Case_Status SET status_name=? WHERE status_id=?",
            (name, status_id),
        )
    for category_id, name in (
        ("GC01", "業務聯繫"),
        ("GC02", "相驗案件"),
        ("GC03", "其他公文"),
    ):
        conn.execute(
            "UPDATE Ref_General_Category SET gen_cat_name=? WHERE gen_cat_id=?",
            (name, category_id),
        )

    # 公開截圖庫不連結任何真實檔案系統位置。
    conn.execute(
        "INSERT INTO App_Settings(key,value) VALUES('archive_root','') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )


def _insert_tasks(conn: sqlite3.Connection, today: date) -> None:
    rows = (
        ("1", -4, "P01", "D01", FAKE_DATA.documents.task_subject, "P02", 5, None, None),
        ("2", -3, "P02", "D02", "本月巡守隊聯繫會報資料回覆", "P03", 0, None, None),
        ("3", -8, "P03", "D03", "重要節日勤務成果追蹤彙整", "P04", -3, None, None),
        ("4", -9, "P04", "D04", "校園安全宣導執行情形回覆", "P05", -2, -3, "P01"),
        ("5", -12, "P05", "D05", "勤務出勤紀錄統計回覆", "P06", -5, -2, "P02"),
        ("6", -2, "P06", "D06", "社區安全宣導參考資料", "P01", None, None, None),
        ("7", -1, "P01", "D07", "近期勤務裝備盤點", "P02", 10, None, None),
        ("8", -6, "P02", "D08", "跨單位協調事項辦理進度", "P03", -1, None, None),
        ("9", -7, "P03", "D09", "成果照片與紀錄核對回覆", "P04", -1, -1, "P05"),
        ("10", -15, "P04", "D10", "勤務規劃會議資料彙整", "P05", -9, -6, "P06"),
        ("11", 0, "P05", "D01", FAKE_DATA.documents.long_text, "P06", 2, None, None),
    )
    sql = """
        INSERT INTO Document_Task
            (doc_id,receive_date,receive_id,dept_id,subject,processor_id,
             deadline,dispatch_date,sender_id,timestamp)
        VALUES(?,?,?,?,?,?,?,?,?,?)
    """
    for doc_id, receive, receiver, dept, subject, processor, deadline, dispatch, sender in rows:
        receive_date = _day(today, receive)
        conn.execute(
            sql,
            (
                doc_id,
                receive_date,
                receiver,
                dept,
                subject,
                processor,
                _day(today, deadline) if deadline is not None else None,
                _day(today, dispatch) if dispatch is not None else None,
                sender,
                f"{receive_date} 09:00:00",
            ),
        )
    # 軟刪除空殼：保留文號，其餘業務欄清空。
    conn.execute("INSERT INTO Document_Task(doc_id) VALUES('12')")


def _insert_criminal(conn: sqlite3.Connection, today: date) -> None:
    sql = """
        INSERT INTO Document_Criminal
            (doc_id,report_date,sender_id,case_type,case_status,processor_id,
             subject_summary,occurrence_date,reporter_name,receiver_id,
             is_reported,is_electronic)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    """
    for index in range(1, 12):
        pending = index <= 3
        archived = index in {5, 7, 10}
        conn.execute(
            sql,
            (
                str(index),
                None if pending else _day(today, index - 12),
                None if pending else f"P{((index + 1) % 6) + 1:02d}",
                f"CT{((index - 1) % 8) + 1:02d}",
                f"CS{((index - 1) % 3) + 1:02d}",
                f"P{((index + 2) % 6) + 1:02d}",
                f"{FAKE_DATA.documents.criminal_reason}（案件{index:02d}）",
                _day(today, index - 15),
                FAKE_DATA.personnel[(index - 1) % len(FAKE_DATA.personnel)].name,
                f"P{((index + 3) % 6) + 1:02d}",
                1 if index % 3 == 0 or archived else 0,
                f"刑案陳報_{index:02d}.pdf" if archived else "",
            ),
        )
    conn.execute("INSERT INTO Document_Criminal(doc_id) VALUES('12')")


def _insert_general(conn: sqlite3.Connection, today: date) -> None:
    sql = """
        INSERT INTO Document_General
            (doc_id,report_date,sender_id,dept_id,gen_cat_id,subject,
             processor_id,is_reported,is_electronic)
        VALUES(?,?,?,?,?,?,?,?,?)
    """
    for index in range(1, 12):
        pending = index <= 3
        archived = index in {4, 8, 11}
        conn.execute(
            sql,
            (
                str(index),
                None if pending else _day(today, index - 13),
                None if pending else f"P{((index + 2) % 6) + 1:02d}",
                f"D{((index - 1) % 10) + 1:02d}",
                f"GC{((index - 1) % 3) + 1:02d}",
                f"{FAKE_DATA.documents.general_subject}（案件{index:02d}）",
                f"P{((index + 3) % 6) + 1:02d}",
                1 if index % 2 == 0 or archived else 0,
                f"一般陳報_{index:02d}.pdf" if archived else "",
            ),
        )
    conn.execute("INSERT INTO Document_General(doc_id) VALUES('12')")


def _insert_rewards(conn: sqlite3.Connection, today: date) -> None:
    sql = """
        INSERT INTO Document_Reward
            (doc_id,create_date,register_date,sender_id,reason,recipients)
        VALUES(?,?,?,?,?,?)
    """
    for index in range(1, 12):
        pending = index <= 4
        conn.execute(
            sql,
            (
                str(index),
                _day(today, index - 12),
                "" if pending else _day(today, index - 11),
                None if pending else f"P{((index + 1) % 6) + 1:02d}",
                f"{FAKE_DATA.documents.reward_reason}（第{index:02d}案）",
                "、".join(
                    person.name
                    for person in FAKE_DATA.personnel[
                        (index - 1) % len(FAKE_DATA.personnel):
                        (index - 1) % len(FAKE_DATA.personnel) + 2
                    ]
                ) or FAKE_DATA.personnel[0].name,
            ),
        )
    # register_date=NULL 是敘獎軟刪除哨兵，其他欄同步清空。
    conn.execute(
        "INSERT INTO Document_Reward(doc_id,register_date) "
        "VALUES('12',NULL)"
    )


def _insert_tickets(conn: sqlite3.Connection, today: date) -> None:
    sql = """
        INSERT INTO Document_Ticket
            (doc_id,create_date,register_date,sender_id,issuer_id,ticket_no)
        VALUES(?,?,?,?,?,?)
    """
    for index in range(1, 12):
        pending = index <= 4
        conn.execute(
            sql,
            (
                str(index),
                _day(today, index - 12),
                "" if pending else _day(today, index - 11),
                None if pending else f"P{((index + 2) % 6) + 1:02d}",
                f"P{((index - 1) % 6) + 1:02d}",
                f"QCA{today.year}{index:04d}",
            ),
        )
    # CHECK 所允許的罰單軟刪除空殼。
    conn.execute("INSERT INTO Document_Ticket(doc_id) VALUES('12')")


def _insert_documents(conn: sqlite3.Connection, today: date) -> None:
    _insert_tasks(conn, today)
    _insert_criminal(conn, today)
    _insert_general(conn, today)
    _insert_rewards(conn, today)
    _insert_tickets(conn, today)
    conn.executemany(
        "UPDATE Seq_DocId SET last_id=? WHERE table_name=?",
        ((12, table) for table in MAIN_TABLES),
    )


def _summary(conn: sqlite3.Connection) -> list[str]:
    lines = ["主表筆數："]
    for table in MAIN_TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        lines.append(f"  {table}: {count}")

    lines.append("View 查詢：")
    for view in VIEWS:
        count = conn.execute(f"SELECT COUNT(*) FROM {view}").fetchone()[0]
        lines.append(f"  {view}: {count}")

    lines.append("狀態分布：")
    task_states = conn.execute(
        'SELECT 狀態, COUNT(*) FROM View_Task_Full '
        "WHERE 交辦事由 IS NOT NULL GROUP BY 狀態 ORDER BY 狀態"
    ).fetchall()
    lines.append(
        "  交辦: " + "、".join(f"{state}={count}" for state, count in task_states)
    )
    for label, table in (
        ("刑案", "Document_Criminal"),
        ("一般", "Document_General"),
    ):
        pending, issued, archived, deleted = conn.execute(
            f"SELECT "
            "SUM(subject_summary IS NOT NULL AND report_date IS NULL), "
            "SUM(subject_summary IS NOT NULL AND report_date IS NOT NULL), "
            "SUM(subject_summary IS NOT NULL AND "
            "    is_electronic IS NOT NULL AND is_electronic<>''), "
            "SUM(subject_summary IS NULL) "
            f"FROM {table}"
            if table == "Document_Criminal"
            else
            "SELECT "
            "SUM(subject IS NOT NULL AND report_date IS NULL), "
            "SUM(subject IS NOT NULL AND report_date IS NOT NULL), "
            "SUM(subject IS NOT NULL AND "
            "    is_electronic IS NOT NULL AND is_electronic<>''), "
            "SUM(subject IS NULL) "
            "FROM Document_General"
        ).fetchone()
        lines.append(
            f"  {label}: 未發文={pending}、已發文={issued}、"
            f"已歸檔={archived}、軟刪除={deleted}"
        )
    for label, table in (
        ("敘獎", "Document_Reward"),
        ("罰單", "Document_Ticket"),
    ):
        pending, issued, deleted = conn.execute(
            f"SELECT "
            "SUM(register_date=''), "
            "SUM(register_date IS NOT NULL AND register_date<>''), "
            "SUM(register_date IS NULL) "
            f"FROM {table}"
        ).fetchone()
        lines.append(
            f"  {label}: 未發文={pending}、已發文={issued}、軟刪除={deleted}"
        )
    return lines


def _validate(conn: sqlite3.Connection) -> list[str]:
    counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in MAIN_TABLES
    }
    invalid = {table: count for table, count in counts.items() if not 8 <= count <= 15}
    if invalid:
        raise RuntimeError(f"主表筆數不符 8–15 筆：{invalid}")

    expected_doc_ids = [str(index) for index in range(1, 13)]
    invalid_doc_ids = {}
    for table in MAIN_TABLES:
        doc_ids = [
            row[0]
            for row in conn.execute(
                f"SELECT doc_id FROM {table} ORDER BY CAST(doc_id AS INTEGER)"
            )
        ]
        if doc_ids != expected_doc_ids:
            invalid_doc_ids[table] = doc_ids
    if invalid_doc_ids:
        raise RuntimeError(f"doc_id 未依正式流水號規則：{invalid_doc_ids}")

    for view in VIEWS:
        conn.execute(f"SELECT * FROM {view} LIMIT 1").fetchone()

    foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
    if foreign_key_errors:
        raise RuntimeError(f"參照完整性檢查失敗：{foreign_key_errors}")

    archive_root = conn.execute(
        "SELECT value FROM App_Settings WHERE key='archive_root'"
    ).fetchone()
    if archive_root != ("",):
        raise RuntimeError("archive_root 必須保持安全空值")
    return _summary(conn)


def build_database(out_path: Path) -> list[str]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{out_path.name}.", suffix=".tmp", dir=out_path.parent
    )
    os.close(handle)
    temp_path = Path(temp_name)
    try:
        conn = sqlite3.connect(temp_path)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            db_schema.applySchema(conn)
            db_seed.seedFreshDb(conn)
            _replace_reference_data(conn)
            _insert_documents(conn, date.today())
            conn.commit()
            summary = _validate(conn)
            conn.execute("VACUUM")
            conn.commit()
        finally:
            conn.close()
        os.replace(temp_path, out_path)
        return summary
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(str(left.resolve())) == os.path.normcase(str(right.resolve()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="輸出 SQLite DB 路徑")
    parser.add_argument(
        "--force",
        action="store_true",
        help="明確允許覆寫既有輸出檔",
    )
    args = parser.parse_args(argv)
    out_path = args.output.expanduser().resolve()

    if _same_path(out_path, ROOT / "dbfile.db"):
        parser.error("拒絕覆寫專案根目錄的 dbfile.db")
    if out_path.exists() and not args.force:
        parser.error(f"輸出路徑已存在：{out_path}；如要覆寫請加 --force")
    if out_path.exists() and not out_path.is_file():
        parser.error(f"輸出路徑不是一般檔案：{out_path}")

    summary = build_database(out_path)
    print(f"已建立公開截圖用候選資料庫：{out_path}")
    print("候選姓名待維護者對照真實名單核准，且畫面仍待人工目視確認。")
    print("\n".join(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
