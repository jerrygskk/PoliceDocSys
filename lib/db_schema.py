# -*- coding: utf-8 -*-
"""啟動時冪等確保結構存在（只增不改），並作為 schema 的「程式碼唯一來源」。

界線（重要）：
  - 只放 CREATE ... IF NOT EXISTS 與「缺欄才加」的 ADD COLUMN——冪等、零資料風險。
  - 破壞性變更（改型別、改既有資料、改 View 定義）不放這裡，走一次性手動腳本
    （改 View 需 DROP VIEW 後重建，IF NOT EXISTS 不會更新既有 View）。
  - 全部表/View/Trigger 在此登記＝唯一來源；`tools/gen_shell_db.py` 用本檔＋
    `db_seed` 產出乾淨空殼，測試也用本檔建表，三方共用同一份定義、不再走鐘。
  - 對既有現場庫：全 IF NOT EXISTS，已存在＝no-op，不動既有資料、免 migration。
  - 失敗只記 error.log，絕不拋例外、絕不擋開程式（同 db_backup / app_lock 哲學）。
"""
import os
import logging
import sqlite3

# 所有資料表（含基礎空殼表）。逐句獨立執行（見 ensureSchema）。
_TABLES = (
    # App_Settings
    """CREATE TABLE IF NOT EXISTS App_Settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
)""",
    # Audit_Log
    """CREATE TABLE IF NOT EXISTS Audit_Log (
  log_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  ts            TEXT NOT NULL,
  role          TEXT,
  action        TEXT,
  target_table  TEXT,
  target_id     TEXT,
  operator      TEXT,
  detail        TEXT
)""",
    # Document_Criminal
    """CREATE TABLE IF NOT EXISTS Document_Criminal (
    doc_id VARCHAR(50) PRIMARY KEY, report_date DATE, sender_id VARCHAR(10), case_type VARCHAR(10), case_status VARCHAR(10), processor_id VARCHAR(10), subject_summary TEXT, occurrence_date DATE, reporter_name VARCHAR(50), receiver_id VARCHAR(10), is_reported BOOLEAN, is_electronic TEXT, last_modified DATETIME
)""",
    # Document_General
    """CREATE TABLE IF NOT EXISTS Document_General (
    doc_id VARCHAR(50) PRIMARY KEY, report_date DATE, sender_id VARCHAR(10), dept_id VARCHAR(10), gen_cat_id VARCHAR(10), subject TEXT, processor_id VARCHAR(10), is_reported BOOLEAN, is_electronic TEXT, last_modified DATETIME
)""",
    # Document_Task
    """CREATE TABLE IF NOT EXISTS Document_Task (
    doc_id VARCHAR(50) PRIMARY KEY,
    receive_date DATE,
    receive_id VARCHAR(10),
    dept_id VARCHAR(10),
    subject TEXT,
    processor_id VARCHAR(10),
    deadline DATE,
    dispatch_date DATE,
    sender_id VARCHAR(10),
    timestamp DATETIME,
    last_modified DATETIME
)""",
    # Document_Reward
    """CREATE TABLE IF NOT EXISTS Document_Reward (
    doc_id VARCHAR(50) PRIMARY KEY,
    register_date DATE,
    reason TEXT,
    recipients TEXT,
    last_modified DATETIME
)""",
    # Ref_CaseTypes
    """CREATE TABLE IF NOT EXISTS Ref_CaseTypes (case_type_id VARCHAR(10) PRIMARY KEY, case_type_name VARCHAR(100) NOT NULL, is_active BOOLEAN NOT NULL DEFAULT 1, sort_order INTEGER, alias TEXT)""",
    # Ref_Case_Status
    """CREATE TABLE IF NOT EXISTS Ref_Case_Status (status_id VARCHAR(10) PRIMARY KEY, status_name VARCHAR(50) NOT NULL)""",
    # Ref_Departments
    """CREATE TABLE IF NOT EXISTS Ref_Departments (dept_id VARCHAR(10) PRIMARY KEY, dept_name VARCHAR(50) NOT NULL, is_active BOOLEAN NOT NULL DEFAULT 1, sort_order INTEGER)""",
    # Ref_General_Category
    """CREATE TABLE IF NOT EXISTS Ref_General_Category (gen_cat_id VARCHAR(10) PRIMARY KEY, gen_cat_name VARCHAR(50) NOT NULL)""",
    # Ref_Personnel
    """CREATE TABLE IF NOT EXISTS Ref_Personnel (staff_id VARCHAR(10) PRIMARY KEY, staff_name VARCHAR(50) NOT NULL, is_active BOOLEAN NOT NULL DEFAULT 1, sort_order INTEGER, alias TEXT)""",
    # Seq_DocId
    """CREATE TABLE IF NOT EXISTS Seq_DocId (
    table_name VARCHAR(50) PRIMARY KEY,
    last_id    INTEGER NOT NULL DEFAULT 0
)""",
    # 誤刪還原回收筒（v1.1.1 起，空殼未內建、靠本句長出）
    """CREATE TABLE IF NOT EXISTS Trash_Documents (
        trash_id      INTEGER PRIMARY KEY AUTOINCREMENT,
        table_name    TEXT NOT NULL,
        doc_id        TEXT NOT NULL,
        payload       TEXT NOT NULL,
        subject       TEXT,
        doc_person    TEXT,
        deleted_ts    TEXT NOT NULL,
        deleted_role  TEXT
    )""",
)

# 既有表新增欄位：(表, 欄, 型別宣告)，缺欄才加。
_COLUMNS = (
    ("Ref_CaseTypes", "alias", "TEXT"),
)

# 三個顯示用 View（JOIN 參照表＋算狀態）。改定義須手動 DROP 重建（見上界線）。
_VIEWS = (
    # View_Criminal_Full
    """CREATE VIEW IF NOT EXISTS View_Criminal_Full AS
SELECT
    C.doc_id AS '送文編號',
    C.report_date AS '陳報日期',
    P1.staff_name AS '送文人員',
    COALESCE(CT.case_type_name, C.case_type) AS '案類',
    CS.status_name AS '發文分類',
    COALESCE(P2.staff_name, C.processor_id) AS '主承辦人',
    C.subject_summary AS '嫌疑人_案由',
    C.occurrence_date AS '受理日期',
    C.reporter_name AS '報案人',
    P3.staff_name AS '受理人',
    CASE WHEN C.is_reported = 1 THEN '是' ELSE '否' END AS '紙本',
    CASE WHEN C.is_electronic IS NOT NULL AND C.is_electronic != '' THEN '已歸檔' ELSE '未歸檔' END AS '電子檔'
FROM Document_Criminal C
LEFT JOIN Ref_Personnel  P1 ON C.sender_id    = P1.staff_id
LEFT JOIN Ref_Personnel  P2 ON C.processor_id = P2.staff_id
LEFT JOIN Ref_Personnel  P3 ON C.receiver_id  = P3.staff_id
LEFT JOIN Ref_CaseTypes  CT ON C.case_type    = CT.case_type_id
LEFT JOIN Ref_Case_Status CS ON C.case_status = CS.status_id""",
    # View_General_Full
    """CREATE VIEW IF NOT EXISTS View_General_Full AS
SELECT
    G.doc_id AS '送文編號',
    G.report_date AS '陳報日期',
    P1.staff_name AS '送文人員',
    D.dept_name AS '業務單位',
    GC.gen_cat_name AS '分類',
    G.subject AS '陳報主旨',
    COALESCE(P2.staff_name, G.processor_id) AS '陳報人',
    CASE WHEN G.is_reported = 1 THEN '是' ELSE '否' END AS '紙本',
    CASE WHEN G.is_electronic IS NOT NULL AND G.is_electronic != '' THEN '已歸檔' ELSE '未歸檔' END AS '電子檔'
FROM Document_General G
LEFT JOIN Ref_Personnel  P1 ON G.sender_id    = P1.staff_id
LEFT JOIN Ref_Personnel  P2 ON G.processor_id = P2.staff_id
LEFT JOIN Ref_Departments D  ON G.dept_id      = D.dept_id
LEFT JOIN Ref_General_Category GC ON G.gen_cat_id = GC.gen_cat_id""",
    # View_Task_Full
    """CREATE VIEW IF NOT EXISTS View_Task_Full AS
SELECT
    T.doc_id        AS '編號',
    T.receive_date  AS '收文日期',
    P2.staff_name   AS '收文人員',
    D.dept_name     AS '業務組',
    T.subject       AS '交辦事由',
    COALESCE(P3.staff_name, T.processor_id) AS '所承辦人',
    T.deadline      AS '限辦日期',
    T.dispatch_date AS '發文日期',
    P1.staff_name   AS '送文人員',
    T.timestamp     AS '紀錄時間',
    CASE
        WHEN T.deadline IS NULL OR T.deadline = '' THEN '免覆'
        WHEN T.dispatch_date IS NOT NULL AND T.dispatch_date <> '' THEN
            CASE
                WHEN T.dispatch_date > T.deadline
                    THEN '已發文，逾期 ' || CAST(julianday(T.dispatch_date) - julianday(T.deadline) AS INT) || ' 天'
                ELSE '已發文'
            END
        WHEN date('now','localtime') < T.deadline
            THEN '剩餘 ' || CAST(julianday(T.deadline) - julianday(date('now','localtime')) AS INT) || ' 天'
        WHEN date('now','localtime') = T.deadline THEN '本日截止'
        ELSE '逾期 ' || CAST(julianday(date('now','localtime')) - julianday(T.deadline) AS INT) || ' 天'
    END AS '狀態'
FROM Document_Task T
LEFT JOIN Ref_Personnel  P1 ON T.sender_id    = P1.staff_id
LEFT JOIN Ref_Personnel  P2 ON T.receive_id   = P2.staff_id
LEFT JOIN Ref_Personnel  P3 ON T.processor_id = P3.staff_id
LEFT JOIN Ref_Departments D  ON T.dept_id      = D.dept_id""",
)

# 主表的 last_modified 自動更新 trigger。
_TRIGGERS = (
    # trg_crim_insert
    """CREATE TRIGGER IF NOT EXISTS trg_crim_insert AFTER INSERT ON Document_Criminal
BEGIN
    UPDATE Document_Criminal SET last_modified = datetime('now','localtime') WHERE doc_id = NEW.doc_id;
END""",
    # trg_crim_update
    """CREATE TRIGGER IF NOT EXISTS trg_crim_update AFTER UPDATE ON Document_Criminal
WHEN NEW.last_modified IS OLD.last_modified
BEGIN
    UPDATE Document_Criminal SET last_modified = datetime('now','localtime') WHERE doc_id = NEW.doc_id;
END""",
    # trg_gen_insert
    """CREATE TRIGGER IF NOT EXISTS trg_gen_insert AFTER INSERT ON Document_General
BEGIN
    UPDATE Document_General SET last_modified = datetime('now','localtime') WHERE doc_id = NEW.doc_id;
END""",
    # trg_gen_update
    """CREATE TRIGGER IF NOT EXISTS trg_gen_update AFTER UPDATE ON Document_General
WHEN NEW.last_modified IS OLD.last_modified
BEGIN
    UPDATE Document_General SET last_modified = datetime('now','localtime') WHERE doc_id = NEW.doc_id;
END""",
    # trg_task_insert
    """CREATE TRIGGER IF NOT EXISTS trg_task_insert AFTER INSERT ON Document_Task
BEGIN
    UPDATE Document_Task SET last_modified = datetime('now','localtime') WHERE doc_id = NEW.doc_id;
END""",
    # trg_task_update
    """CREATE TRIGGER IF NOT EXISTS trg_task_update AFTER UPDATE ON Document_Task
WHEN NEW.last_modified IS OLD.last_modified
BEGIN
    UPDATE Document_Task SET last_modified = datetime('now','localtime') WHERE doc_id = NEW.doc_id;
END""",
    # trg_reward_insert
    """CREATE TRIGGER IF NOT EXISTS trg_reward_insert AFTER INSERT ON Document_Reward
BEGIN
    UPDATE Document_Reward SET last_modified = datetime('now','localtime') WHERE doc_id = NEW.doc_id;
END""",
    # trg_reward_update
    """CREATE TRIGGER IF NOT EXISTS trg_reward_update AFTER UPDATE ON Document_Reward
WHEN NEW.last_modified IS OLD.last_modified
BEGIN
    UPDATE Document_Reward SET last_modified = datetime('now','localtime') WHERE doc_id = NEW.doc_id;
END""",
)


def ensureSchema(db_path):
    """逐句冪等套用 _TABLES / _COLUMNS / _VIEWS / _TRIGGERS。

    各語句獨立 try：單句失敗（如多機併發短暫 locked）不影響其餘，下次啟動再補。
    整體再包一層 try：任何意外都不阻擋程式開啟。
    """
    if not db_path or not os.path.exists(db_path):
        return
    conn = None
    try:
        conn = sqlite3.connect(db_path)
        applySchema(conn)
    except Exception:
        logging.error("ensureSchema 異常", exc_info=True)
    finally:
        if conn is not None:
            conn.close()


def applySchema(conn):
    """對已開啟的連線套用全部結構（表→欄→View→Trigger）。
    供 ensureSchema 與 tools/gen_shell_db.py、單元測試共用，確保三方同一份定義。"""
    for sql in _TABLES:
        _run(conn, sql)
    for table, column, decl in _COLUMNS:
        _add_column(conn, table, column, decl)
    for sql in _VIEWS:
        _run(conn, sql)
    for sql in _TRIGGERS:
        _run(conn, sql)


def _run(conn, sql):
    """執行單句 DDL（自帶 commit）；失敗只記 log，不中斷其餘。"""
    try:
        conn.execute(sql)
        conn.commit()
    except Exception:
        logging.error("ensureSchema 語句失敗", exc_info=True)


def _add_column(conn, table, column, decl):
    """欄位不存在才 ADD COLUMN（冪等）；失敗只記 log。"""
    try:
        cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
            conn.commit()
    except Exception:
        logging.error("ensureSchema 加欄失敗", exc_info=True)
