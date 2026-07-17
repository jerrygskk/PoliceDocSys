import sys
import os
import sqlite3
import json
import unicodedata


def getConn(db_path):
    """sqlite3 連線單一來源；呼叫端負責 commit/close。
    後續若要統一加 PRAGMA / timeout / row_factory，集中改這一處即可。

    busy_timeout=3000：多機 SMB 併發下，寫入鎖碰撞多為毫秒級，讓 SQLite
    自動等待重試最多 3 秒即可消化大半「資料庫忙線中」。⚠️ WAL 刻意不開
    （網路檔案系統上不安全），只加 busy_timeout。"""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def loadActivePersonnel(db_path):
    """載入在職人員（含 sort_order）與別名對照表，敘獎登錄頁與修改彈窗共用。

    回傳 ``(personnel, alias_map)``：
      - ``personnel``：``[(staff_id, staff_name, sort_order), ...]``，
        依 ``sort_order, staff_id`` 排序；彈窗僅取姓名、可忽略 sort_order。
      - ``alias_map``：``{staff_name: [別名, ...]}``，僅收錄有別名者。

    未套 alias 補欄的舊資料庫自動以 NULL 別名容錯（不報缺欄）。
    """
    conn = getConn(db_path)
    try:
        has_alias = any(
            row[1] == "alias"
            for row in conn.execute("PRAGMA table_info(Ref_Personnel)"))
        alias_col = "alias" if has_alias else "NULL AS alias"
        rows = conn.execute(
            f"SELECT staff_id,staff_name,sort_order,{alias_col} "
            "FROM Ref_Personnel WHERE is_active=1 "
            "ORDER BY sort_order,staff_id").fetchall()
    finally:
        conn.close()
    # 姓名去後綴（例：姓名-29 → 姓名），與右側候選名單／陳報等頁一致；
    # 搜尋下拉與填入欄位皆用乾淨姓名。
    from lib.archive_text import _trimName
    personnel = [(row[0], _trimName(row[1]), row[2]) for row in rows]
    alias_map = {
        _trimName(row[1]): [part.strip() for part in (row[3] or "").split(",")
                            if part.strip()]
        for row in rows if row[3]
    }
    return personnel, alias_map


# ── 開機磁碟空間檢查（C 槽空間不足軟性提醒用）──────────────────────
# 門檻 = 單次執行期間暫存佔用實測峰值（PyInstaller onefile 解壓等）
#        + DB 現有大小 ×2（本體 + 每日/每週備份各一份）+ 安全餘裕。
# 220MB/250MB 二擇一時改選 250MB：開機前後 fsutil 實測一次峰值約 216MB，
# 多留量測誤差緩衝（2026-07 與維護者議定，未重複量測取最大值，故保守抓高）。
DISK_RUNTIME_FOOTPRINT = 250 * 1024 ** 2   # 250MB
DISK_SAFETY_MARGIN     = 50 * 1024 ** 2    # 50MB


def diskSpaceThreshold(db_path):
    """回傳開機磁碟空間檢查門檻（bytes）。DB 不存在時當作 0 算。"""
    try:
        db_size = os.path.getsize(db_path)
    except OSError:
        db_size = 0
    return DISK_RUNTIME_FOOTPRINT + db_size * 2 + DISK_SAFETY_MARGIN


def _sameDrive(a, b):
    """兩路徑是否同一顆磁碟（磁碟代號／UNC share 比對，不分大小寫）。"""
    da = os.path.splitdrive(os.path.abspath(a))[0].lower()
    db = os.path.splitdrive(os.path.abspath(b))[0].lower()
    return da == db


def diskSpaceChecks(db_path, temp_dir=None):
    """回傳開機要檢查的 [(根路徑, 門檻bytes), ...] 清單。

    onefile 解壓峰值發生在「暫存碟」（%TEMP%，通常 C 槽）；DB 本體與 GFS 備份
    寫在「DB 所在碟」（部署常為 SMB 網路碟）——兩者可能不同顆，各查各的門檻。
    同一顆時合併為單一門檻（＝diskSpaceThreshold，行為與舊版一致）。
    """
    import tempfile
    if temp_dir is None:
        temp_dir = tempfile.gettempdir()
    db_dir = os.path.dirname(os.path.abspath(db_path)) or os.path.abspath(os.sep)
    if _sameDrive(temp_dir, db_dir):
        return [(temp_dir, diskSpaceThreshold(db_path))]
    try:
        db_size = os.path.getsize(db_path)
    except OSError:
        db_size = 0
    return [
        (temp_dir, DISK_RUNTIME_FOOTPRINT + DISK_SAFETY_MARGIN),
        (db_dir, db_size * 2 + DISK_SAFETY_MARGIN),
    ]


# ── 稽核紀錄（Audit_Log）─────────────────────────────────────────
def buildDetail(category, action, content=""):
    """組稽核 detail 字串：`[類別][動作]內容`。
    例：buildDetail("交辦","刪除","主旨：協尋失蹤人口")
        → "[交辦][刪除]主旨：協尋失蹤人口" """
    return f"[{category}][{action}]{content}"


def auditStaffName(conn, staff_id):
    """以 staff_id 解析當下姓名快照（operator 用）。查無回原 id 字串。"""
    if not staff_id:
        return ""
    try:
        r = conn.execute(
            "SELECT staff_name FROM Ref_Personnel WHERE staff_id=?",
            (staff_id,)).fetchone()
        return r[0] if r and r[0] else str(staff_id)
    except Exception:
        return str(staff_id)


def writeAudit(conn, *, role, action, detail,
               target_table=None, target_id=None, operator=None):
    """寫入一筆稽核紀錄。使用呼叫端傳入的同一個 conn（與業務操作同一
    transaction，由呼叫端統一 commit）。ts 由 SQLite 取本機時間。
    缺 Audit_Log 表的舊 DB 不致中斷業務操作（靜默跳過）。"""
    try:
        conn.execute(
            "INSERT INTO Audit_Log"
            "(ts, role, action, target_table, target_id, operator, detail) "
            "VALUES (datetime('now','localtime'), ?, ?, ?, ?, ?, ?)",
            (role, action, target_table, target_id, operator, detail))
    except Exception:
        pass


def writeAuditSafe(db_path, *, role, action, detail,
                   target_table=None, target_id=None, operator=None):
    """獨立稽核事件：自開連線寫一筆 → commit → close，全程吞例外。

    給 PWD／CONFIG／LOGIN_FAIL 這類「單獨記一筆、與業務操作不在同一
    transaction」的呼叫端用，免各處重抄 getConn→writeAudit→commit→close→
    try/except。需與業務操作同 transaction 者仍直接用 writeAudit(conn, ...)。"""
    try:
        conn = getConn(db_path)
        writeAudit(conn, role=role, action=action, detail=detail,
                   target_table=target_table, target_id=target_id,
                   operator=operator)
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── 誤刪還原回收筒（Trash_Documents）─────────────────────────────
# 主表「刪除」是清空欄位保留 doc_id（空殼列恆在）。刪除前先快照整列存進
# 回收筒，還原即把 payload 寫回原 doc_id 那列。表結構由 db_schema.ensureSchema
# 啟動時冪等建立；缺表的舊 DB 一律靜默跳過，不中斷業務（同 writeAudit 哲學）。
_TRASH_TABLES = (
    "Document_Task", "Document_Criminal", "Document_General",
    "Document_Reward",
)


def snapshotRow(conn, table, doc_id):
    """回傳該列 {欄名: 值} dict（清空式刪除前呼叫）。查無回 None。
    table 為呼叫端常數（受支援的業務主表名），非使用者輸入。"""
    if table not in _TRASH_TABLES:
        return None
    cur = conn.execute(f"SELECT * FROM {table} WHERE doc_id=?", (doc_id,))
    row = cur.fetchone()
    if row is None:
        return None
    cols = [d[0] for d in cur.description]
    return dict(zip(cols, row))


def writeTrash(conn, *, table_name, doc_id, payload,
               subject="", doc_person="", deleted_role=""):
    """把刪除前的整列快照寫進回收筒。用同一 conn（與清空同 transaction，
    呼叫端統一 commit）；缺 Trash_Documents 表的舊 DB 靜默跳過。"""
    try:
        conn.execute(
            "INSERT INTO Trash_Documents"
            "(table_name, doc_id, payload, subject, doc_person, "
            " deleted_ts, deleted_role) "
            "VALUES (?, ?, ?, ?, ?, datetime('now','localtime'), ?)",
            (table_name, str(doc_id),
             json.dumps(payload, ensure_ascii=False),
             subject or "", doc_person or "", deleted_role or ""))
    except Exception:
        pass


# ── 軟刪除單一業務紀錄（快照→回收筒→清空→稽核）─────────────────
# 主表「刪除」一律清空式 UPDATE 保留 doc_id。各頁差異以參數帶入，避免重複。
# 各主表的清空 SQL（清掉所有內容欄、保留 doc_id；歸檔旗標一併歸零）。
_DELETE_CLEAR_SQL = {
    "Document_Task": (
        "UPDATE Document_Task SET receive_date=NULL, receive_id=NULL, "
        "dept_id=NULL, subject=NULL, processor_id=NULL, deadline=NULL, "
        "dispatch_date=NULL, sender_id=NULL, timestamp=NULL WHERE doc_id=?"),
    "Document_Criminal": (
        "UPDATE Document_Criminal SET report_date=NULL, sender_id=NULL, "
        "case_type=NULL, case_status=NULL, processor_id=NULL, "
        "subject_summary=NULL, occurrence_date=NULL, reporter_name=NULL, "
        "receiver_id=NULL, is_reported=0, is_electronic='' WHERE doc_id=?"),
    "Document_General": (
        "UPDATE Document_General SET report_date=NULL, sender_id=NULL, "
        "dept_id=NULL, gen_cat_id=NULL, subject=NULL, processor_id=NULL, "
        "is_reported=0, is_electronic='' WHERE doc_id=?"),
    "Document_Reward": (
        "UPDATE Document_Reward SET register_date=NULL, reason=NULL, "
        "recipients=NULL WHERE doc_id=?"),
}

# 各主表稽核取值：
# (類別中文, 主旨欄, 對象人欄, 「記誰刪的」operator 來源欄, 對象人是否為 raw 文字)
# operator 規則：admin 跨庫操作與資料列的人脫鉤 → 一律留空；非 admin 記 operator 欄
# 的人。瀏覽頁刪除僅 admin，故 operator_col 給 None（恆留空）。
_DELETE_META = {
    "Document_Task":     ("交辦", "subject",         "processor_id", "receive_id", False),
    "Document_Criminal": ("刑案", "subject_summary", "processor_id", "sender_id", False),
    "Document_General":  ("一般", "subject",         "processor_id", "sender_id", False),
    # recipients 是姓名快照，不是 staff_id，不得走 auditStaffName 查詢。
    "Document_Reward":   ("敘獎", "reason",          "recipients",   None,        True),
}


def softDeleteDoc(conn, *, table, doc_id, role, is_admin, audit_operator=True):
    """軟刪除一筆公文：快照存回收筒 → 清空式 UPDATE → 寫稽核。用同一 conn，
    呼叫端統一 commit。回傳被刪那筆的主旨字串（供呼叫端顯示用，查無回 ''）。

    table          受支援的業務主表名（Task / Criminal / General / Reward）
    role           當前登入身分（current_role），寫入稽核 / 回收筒
    is_admin       是否 admin（決定稽核 operator 是否留空）
    audit_operator False＝operator 一律留空（瀏覽頁刪除僅 admin、與資料列脫鉤）
    """
    if table not in _DELETE_META:
        return ""
    category, subj_col, person_col, op_col, person_is_raw = _DELETE_META[table]
    snap = snapshotRow(conn, table, doc_id)
    subject = (snap.get(subj_col) if snap else "") or ""
    # operator：admin 或瀏覽頁 → 留空；非 admin 業務頁 → 記 op_col 的人
    if not audit_operator or is_admin or op_col is None:
        operator = None
    else:
        operator = auditStaffName(conn, snap.get(op_col)) if snap else ""
    if snap:
        person = snap.get(person_col)
        if not person_is_raw:
            person = auditStaffName(conn, person)
        writeTrash(conn, table_name=table, doc_id=doc_id, payload=snap,
                   subject=subject,
                   doc_person=person,
                   deleted_role=role)
    conn.execute(_DELETE_CLEAR_SQL[table], (doc_id,))
    if table == "Document_Reward":
        detail_text = (
            f"編號：{doc_id}；登錄日期：{(snap or {}).get('register_date') or ''}；"
            f"事由：{subject}；敘獎人員：{(snap or {}).get('recipients') or ''}"
        )
    else:
        detail_text = f"主旨：{subject}"
    writeAudit(conn, role=role, action="DELETE", target_table=table,
               target_id=doc_id, operator=operator,
               detail=buildDetail(category, "刪除", detail_text))
    return subject


def restoreFromTrash(conn, trash_id):
    """還原一筆：payload 寫回原 doc_id 空殼列，並刪該回收筒列。
    用同一 conn，呼叫端 commit。回 (table_name, doc_id)；查無／表名不合法／
    缺表回 None。"""
    try:
        r = conn.execute(
            "SELECT table_name, doc_id, payload FROM Trash_Documents "
            "WHERE trash_id=?", (trash_id,)).fetchone()
    except Exception:
        return None
    if not r:
        return None
    table_name, doc_id, payload_json = r
    if table_name not in _TRASH_TABLES:
        return None
    data = json.loads(payload_json)
    # 排除 doc_id（WHERE 條件）與 last_modified：後者必須讓 AFTER UPDATE trigger
    # 重新蓋成當下時間。若寫回快照的舊值，trigger 的 WHEN NEW.last_modified IS
    # OLD.last_modified 不成立而不觸發，last_modified 停在舊值，瀏覽/歸檔頁的指紋
    # （MAX(last_modified)／> since）偵測不到還原 → 清單不刷新（需手動重載）。
    cols = [c for c in data if c not in ("doc_id", "last_modified")]
    if not cols:
        return None
    set_clause = ", ".join(f"{c}=?" for c in cols)
    vals = [data[c] for c in cols]
    conn.execute(f"UPDATE {table_name} SET {set_clause} WHERE doc_id=?",
                 vals + [str(doc_id)])
    conn.execute("DELETE FROM Trash_Documents WHERE trash_id=?", (trash_id,))
    return (table_name, doc_id)


# ── 未預期例外 → 白話訊息 ───────────────────────────────────────
# 全域錯誤處理用：把工程語言的例外轉成承辦看得懂、可行動的提示。
# 技術細節（traceback）仍只進 error.log，不丟給使用者。純邏輯，可單測。
_GENERIC_ERROR = ("程式發生未預期的錯誤，已記錄至 error.log。\n"
                  "請將該檔案提供維護人員協助處理。")

# 磁碟空間不足時 error.log 本身也可能寫不進去（log 機制需要磁碟空間），
# 故獨立判斷成專屬訊息，不依賴 log 也能讓使用者立刻知道原因。
_DISK_FULL_MARKERS = (
    "disk full", "disk image is full", "database or disk is full",
    "no space left on device",
)


def isDiskFullError(exc_value):
    """判斷例外是否為「磁碟空間不足」（SQLite 或作業系統層級）。純邏輯，可單測。"""
    if isinstance(exc_value, OSError) and getattr(exc_value, "errno", None) == 28:
        return True  # ENOSPC
    low = str(exc_value or "").lower()
    return any(m in low for m in _DISK_FULL_MARKERS)


def friendlyErrorMessage(exc_type, exc_value):
    """依例外型別回傳白話、可行動的錯誤訊息（不含技術細節）。

    對照不到的型別一律回泛用訊息。`exc_type` 可為 None（此時只看 value）。
    """
    name = getattr(exc_type, "__name__", "") or type(exc_value).__name__
    text = str(exc_value or "")
    low = text.lower()

    if isDiskFullError(exc_value):
        return ("C 槽（或資料庫所在磁碟）空間不足，操作未完成。\n"
                "請清理磁碟空間後再試一次；本次錯誤可能未留下紀錄。")

    # SQLite：忙線鎖定 / 缺表 / 檔案損毀
    if name in ("OperationalError",) or "operationalerror" in low:
        if "locked" in low or "busy" in low:
            return ("資料庫忙線中，可能有其他視窗正開啟本程式。\n"
                    "請關閉其他視窗後再試一次。")
        return ("資料庫存取發生問題，請關閉程式後重新開啟；\n"
                "若持續發生，請聯繫維護人員並提供 error.log。")
    if name in ("DatabaseError", "IntegrityError", "DataError") or \
            "databaseerror" in low or "malformed" in low:
        return ("資料庫檔案可能損毀或格式異常。\n"
                "請聯繫維護人員，並提供 error.log 與資料庫備份檔。")

    # 檔案 / 權限 / 網路磁碟
    if name in ("PermissionError",):
        return ("無法存取檔案（可能正被其他程式開啟，或權限不足）。\n"
                "請關閉相關檔案後再試一次。")
    if name in ("FileNotFoundError",):
        return ("找不到所需的檔案或資料夾。\n"
                "若為歸檔資料夾，請至「設定」頁確認路徑是否正確。")
    if name in ("OSError", "IOError"):
        return ("檔案或資料夾存取失敗，可能是網路磁碟機已中斷連線。\n"
                "請確認網路磁碟機連線後再試一次。")

    return _GENERIC_ERROR


# ── 測試開關 ───────────────────────────────────────────────
# True：所有 disable/greyout 全部開啟（方便測試）
# False：正式行為，上線前確認為 False
DEBUG_MODE = False


def getResourcePath(relative_path):
    """
    - dbfile.db：永遠從 exe 所在目錄讀（真實資料）
    - 其他（.ui, .svg）：打包後從 _MEIPASS，開發時從當前目錄
    """
    if relative_path == 'dbfile.db':
        if getattr(sys, 'frozen', False):
            return os.path.join(os.path.dirname(sys.executable), relative_path)
        return os.path.join(os.path.abspath('.'), relative_path)

    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath('.'), relative_path)


def nextDocId(conn, table_name):
    """
    從 Seq_DocId 取得下一個流水號（只增不減）。
    conn 必須是已開啟的 sqlite3 連線，呼叫端負責 commit/close。
    """
    conn.execute(
        "INSERT OR IGNORE INTO Seq_DocId(table_name, last_id) VALUES (?, 0)",
        (table_name,)
    )
    conn.execute(
        "UPDATE Seq_DocId SET last_id = last_id + 1 WHERE table_name = ?",
        (table_name,)
    )
    row = conn.execute(
        "SELECT last_id FROM Seq_DocId WHERE table_name = ?",
        (table_name,)
    ).fetchone()
    return str(row[0])


# ══════════════════════════════════════════════════════════════════
# 跨年度重置（Reset）
# ══════════════════════════════════════════════════════════════════
# 三張參照表的重編設定：(表名, id欄, 前綴, 位數)
_RESET_REF_TABLES = [
    ("Ref_Personnel",   "staff_id",     "P",  2),
    ("Ref_Departments", "dept_id",      "D",  2),
    ("Ref_CaseTypes",   "case_type_id", "CT", 2),
]

# 主表中參照到參照表 id 的欄位：{參照表: [(主表, 欄位), ...]}
# 跨年度時主表會被清空，故重編 id 不需連動更新主表；此表僅供文件參考。
_RESET_SEQ_TABLES = [
    "Document_Task", "Document_Criminal", "Document_General",
    "Document_Reward",
]


def listInactiveRefItems(db_path):
    """
    回傳三張參照表中所有停用（is_active=0）項目，供 Reset 確認彈窗預覽。
    格式：[(表中文名, id, name), ...]
    """
    label = {
        "Ref_Personnel":   "人員",
        "Ref_Departments": "部門",
        "Ref_CaseTypes":   "案類",
    }
    name_col = {
        "Ref_Personnel":   "staff_name",
        "Ref_Departments": "dept_name",
        "Ref_CaseTypes":   "case_type_name",
    }
    out = []
    conn = sqlite3.connect(db_path)
    try:
        for tbl, idc, _, _ in _RESET_REF_TABLES:
            rows = conn.execute(
                f"SELECT {idc}, {name_col[tbl]} FROM {tbl} "
                f"WHERE is_active=0 ORDER BY sort_order"
            ).fetchall()
            for rid, rname in rows:
                out.append((label[tbl], rid, rname))
    finally:
        conn.close()
    return out


def performYearEndReset(db_path):
    """
    跨年度重置（破壞性操作，呼叫端須先備份 + 強確認）：
      1. 清空四張主表（Document_Task / Criminal / General / Reward）
      2. 刪除參照表中停用（is_active=0）項目
      3. 依 sort_order 重編參照表 id（連續，維持原前綴與位數）
      4. 重設 sort_order 為連續整數（1 起）
      5. 歸零 Seq_DocId
      6. commit 後 VACUUM：縮檔並清除已刪舊年度公文的實體殘留（slack space）

    1~5 全程單一 transaction，任一步失敗則 rollback 並拋出例外（資料不變）；
    VACUUM 在 commit 之後（不可在 transaction 內執行）。

    重編 id 採兩段式避開主鍵衝突：
      先把所有列改成暫時前綴（如 _TMP_P0001），再編回正式 id。
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")

        # 1. 清空四張主表
        for t in _RESET_SEQ_TABLES:
            conn.execute(f"DELETE FROM {t}")

        # 2~4. 逐張參照表：刪停用 → 依 sort_order 兩段式重編 → 重設 sort_order
        for tbl, idc, prefix, digits in _RESET_REF_TABLES:
            # 刪除停用項目
            conn.execute(f"DELETE FROM {tbl} WHERE is_active=0")

            # 依現行 sort_order 取出存活列（順序即為重編後順序）
            rows = conn.execute(
                f"SELECT {idc} FROM {tbl} ORDER BY sort_order, {idc}"
            ).fetchall()

            # 第一段：全部改為暫時前綴，避免與目標 id 撞主鍵
            for i, (old_id,) in enumerate(rows, start=1):
                tmp_id = f"__TMP__{prefix}{i:0{digits}d}"
                conn.execute(
                    f"UPDATE {tbl} SET {idc}=? WHERE {idc}=?", (tmp_id, old_id))

            # 第二段：暫時前綴 → 正式 id，並同步重設 sort_order
            for i in range(1, len(rows) + 1):
                tmp_id = f"__TMP__{prefix}{i:0{digits}d}"
                new_id = f"{prefix}{i:0{digits}d}"
                conn.execute(
                    f"UPDATE {tbl} SET {idc}=?, sort_order=? WHERE {idc}=?",
                    (new_id, i, tmp_id))

        # 5. 歸零 Seq_DocId
        conn.execute("UPDATE Seq_DocId SET last_id = 0")

        # 6. 清除歸檔根目錄設定（強制使用者進新年度後重新指定）
        for _k in (ARCHIVE_ROOT_KEY, "archive_subdir_crim", "archive_subdir_gen"):
            conn.execute(
                "INSERT INTO App_Settings(key, value) VALUES(?,'')"
                " ON CONFLICT(key) DO UPDATE SET value=''", (_k,))

        # 7. 清空稽核紀錄（重置前已整庫備份，歷史 log 留在備份檔；當前庫歸零）
        try:
            conn.execute("DELETE FROM Audit_Log")
        except Exception:
            pass  # 缺表的舊 DB 跳過

        # 8. 清空誤刪還原回收筒（主表已清，殘留快照無意義；缺表跳過）
        try:
            conn.execute("DELETE FROM Trash_Documents")
        except Exception:
            pass

        conn.commit()

        # 9. VACUUM 重建整庫：DELETE 只把資料頁列入 free-list、檔案不會縮，且被刪的
        #    舊年度公文（含個資）實體殘留在空閒頁（strings 掃得到）。VACUUM 重建成
        #    新檔→ 縮回最小並清除殘留。⚠️ 不可在 transaction 內執行，故置於 commit 之後。
        conn.execute("VACUUM")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════
# App_Settings 讀寫（key-value 設定；schema 不變，只新增 key）
# ══════════════════════════════════════════════════════════════════
def getSetting(db_path, key, default=""):
    """讀 App_Settings 單一設定；不存在回 default。"""
    conn = getConn(db_path)
    try:
        row = conn.execute(
            "SELECT value FROM App_Settings WHERE key=?", (key,)).fetchone()
        return row[0] if row else default
    finally:
        conn.close()


def setSetting(db_path, key, value):
    """寫 App_Settings 單一設定（upsert）。value 欄為 NOT NULL，None 一律存空字串。"""
    conn = getConn(db_path)
    try:
        conn.execute(
            "INSERT INTO App_Settings(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value or ""))
        conn.commit()
    finally:
        conn.close()


# ══════════════════════════════════════════════════════════════════
# 歸檔 PDF 定位（瀏覽 Tab6 開啟電子檔用）
#   - 根存「當年度資料夾」的 UNC（archive_root），與磁碟機代號脫鉤
#   - 刑案/一般各一個子夾名（archive_subdir_crim/gen），可空（空則走整年度層）
#   - 用 is_electronic 整串檔名於對應子夾遞迴比對；檔名 NFC 正規化避免同形不同碼
# ══════════════════════════════════════════════════════════════════
ARCHIVE_ROOT_KEY = "archive_root"
_ARCH_SUBDIR_KEY = {"crim": "archive_subdir_crim", "gen": "archive_subdir_gen"}


# ══════════════════════════════════════════════════════════════════
# 簽收表標題（使用者可自訂；存 App_Settings，未設定走預設）
# ──────────────────────────────────────────────────────────────────
# 機關名稱以「○○」佔位（不留真名）；列印一律 getSetting(key, 預設)。
# 跨年度重置不清這些 key（機關名稱是單位永久設定，見 performYearEndReset）。
PRINT_TITLE_KEYS = {
    "task": "print_title_task",
    "crim": "print_title_crim",
    "gen":  "print_title_gen",
    "reward": "print_title_reward",
    "note": "print_note_current",
}
PRINT_TITLE_DEFAULTS = {
    "print_title_task": "○○派出所交辦單發文簽收表",
    "print_title_crim": "○○派出所刑案陳報單發文簽收表",
    "print_title_gen":  "○○派出所一般陳報單發文簽收表",
    "print_title_reward": "○○派出所敘獎簽收表",
    "print_note_current": "＜現行犯已隨案移送免簽收＞",
}


def printTitle(db_path, which):
    """取簽收表標題／註記文字。未設定時回傳對應預設值。"""
    key = PRINT_TITLE_KEYS.get(which)
    if not key:
        return ""
    return getSetting(db_path, key, "") or PRINT_TITLE_DEFAULTS.get(key, "")


def printTitlesUnset(db_path):
    """四個標題／註記是否「皆未設定」（任一為空即視為未設定，供列印頁紅字警示）。
    回 True＝有未設定項。"""
    for key in PRINT_TITLE_DEFAULTS:
        if not (getSetting(db_path, key, "") or "").strip():
            return True
    return False


# ══════════════════════════════════════════════════════════════════
# 閒置逾時（設定頁「系統設定」可調；存 App_Settings，未設定/不合法走預設）
# ──────────────────────────────────────────────────────────────────
# close 預設 14.5 分：刻意低於 Windows（AD 部署）15 分鎖螢幕，搶先關閉並
# 清 SMB dbfile.lock（詳見 main.py 計時器註解與 DEVELOPER.md §3「閒置處理」）。
# ⚠️ 此約束不放 UI（維護者層級默契），設定頁僅驗證「關閉 > 登出」。
# 跨年度重置不清這些 key（單位環境常數，見 performYearEndReset）。
IDLE_TIMEOUT_KEYS = {"logout": "idle_logout_min", "close": "idle_close_min"}
IDLE_TIMEOUT_DEFAULTS = {"logout": 10.0, "close": 14.5}
IDLE_TIMEOUT_RANGE = (1.0, 60.0)


def parseIdleMinutes(which, raw):
    """App_Settings 存的字串 → 分鐘數（float）。
    0 為合法值＝該機制停用（不計時）；其餘非數字／超出範圍 → 回該項預設
    （DB 值被手動改壞時的保底）。"""
    try:
        val = float(str(raw).strip())
    except (TypeError, ValueError):
        return IDLE_TIMEOUT_DEFAULTS[which]
    if val == 0:
        return 0.0
    lo, hi = IDLE_TIMEOUT_RANGE
    if not (lo <= val <= hi):
        return IDLE_TIMEOUT_DEFAULTS[which]
    return val


def getIdleTimeoutsMs(db_path):
    """回傳 (自動登出 ms, 強制關閉 ms)；0＝停用該機制（呼叫端勿啟動計時器）。
    讀不到或不合法一律走預設，不拋例外。"""
    mins = {}
    for which, key in IDLE_TIMEOUT_KEYS.items():
        try:
            raw = getSetting(db_path, key, "")
        except Exception:
            raw = ""
        mins[which] = parseIdleMinutes(which, raw)
    return int(mins["logout"] * 60000), int(mins["close"] * 60000)


# ══════════════════════════════════════════════════════════════════
# 三表新增唯讀鎖（管理者可停用一般使用者新增）
# ──────────────────────────────────────────────────────────────────
# 跨年度重置不清這些 key（唯讀模式是管理端安全設定，見 performYearEndReset）。
INPUT_LOCK_KEYS = {
    "dispatch": "input_lock_dispatch",   # 交辦單發文（Tab0 確認發文）
    "task":     "input_lock_task",       # 交辦單收文（Tab1 新增）
    "crim":     "input_lock_crim",
    "gen":      "input_lock_gen",
}


def isInputLocked(db_path, kind):
    """該類別是否已被管理者停用新增（一般使用者唯讀）。
    App_Settings 值為 "1" 才算鎖定；未設定／"0"／壞值／讀不到一律回 False，不拋例外。"""
    key = INPUT_LOCK_KEYS.get(kind)
    if not key:
        return False
    try:
        return (getSetting(db_path, key, "") or "").strip() == "1"
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# 輸入模式（自助取號／送文者輸入；存 App_Settings；僅 admin 可改）
# ──────────────────────────────────────────────────────────────────
# 跨年度重置不清此 key（模式是單位的作業型態，見 performYearEndReset）。
REPORT_INPUT_MODE_KEY = "report_input_mode"


def isSelfServiceMode(db_path) -> bool:
    """是否為自助取號模式（App_Settings 值為 "1"）。
    未設定／壞值 fallback False（＝送文者輸入模式），不拋例外。"""
    try:
        return (getSetting(db_path, REPORT_INPUT_MODE_KEY, "") or "").strip() == "1"
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
# 第二備份位置（異地副本；存 App_Settings，未設定＝停用）
# ──────────────────────────────────────────────────────────────────
# 主備份固定寫 db 旁 backups/；另可指定第二資料夾（另顆網路碟／本機碟／外接碟），
# 啟動時同一套 GFS 輪替各寫一份，做到真正異地（見 lib/db_backup.run_auto_backup）。
# 跨年度重置不清此 key（單位永久設定，見 performYearEndReset 只清 archive_*）。
BACKUP_SECOND_DIR_KEY = "backup_second_dir"


def getBackupSecondDir(db_path):
    """第二備份位置（去頭尾空白）；未設定／讀不到回空字串（＝停用異地備份）。"""
    try:
        return (getSetting(db_path, BACKUP_SECOND_DIR_KEY, "") or "").strip()
    except Exception:
        return ""


_PDF_INDEX_CACHE = {}   # base_dir -> {nfc(檔名): 完整路徑}


def _nfc(s):
    return unicodedata.normalize("NFC", s or "")


def clearPdfIndexCache():
    """設定變更或年度重置後呼叫，清掉檔名索引快取。"""
    _PDF_INDEX_CACHE.clear()


def _buildPdfIndex(base_dir, force=False):
    """遞迴 base_dir 建「nfc(檔名)→完整路徑」索引（含子資料夾）。同名取第一個。"""
    if not force and base_dir in _PDF_INDEX_CACHE:
        return _PDF_INDEX_CACHE[base_dir]
    idx = {}
    for root, _dirs, files in os.walk(base_dir):
        for f in files:
            if f.lower().endswith(".pdf"):
                idx.setdefault(_nfc(f), os.path.join(root, f))
    _PDF_INDEX_CACHE[base_dir] = idx
    return idx


def archiveSubdir(db_path, key):
    """回傳該類別(crim/gen)設定的子夾名稱；未設定回空字串。"""
    return getSetting(db_path, _ARCH_SUBDIR_KEY.get(key, ""), "")


def archiveDefaultDir(db_path, key):
    """歸檔 Tab 選 PDF 資料夾時的預設起始路徑＝歸檔根(+該類別子夾)。
    未設定根回空字串（QFileDialog 會退回系統預設位置）。"""
    root = (getSetting(db_path, ARCHIVE_ROOT_KEY, "") or "").strip()
    if not root:
        return ""
    sub = (archiveSubdir(db_path, key) or "").strip()
    return os.path.join(root, sub) if sub else root


def resolveArchivedPdf(db_path, key, fname):
    """以 is_electronic 檔名定位實體 PDF。
    回傳 (完整路徑 or None, 狀態碼)：
      ok       命中
      noroot   尚未設定歸檔根
      noaccess 根/子夾無法存取（網路碟未掛或路徑錯）
      notfound 走訪後找不到該檔名
    """
    fname = _nfc((fname or "").strip())
    if not fname:
        return None, "notfound"
    root = (getSetting(db_path, ARCHIVE_ROOT_KEY, "") or "").strip()
    if not root:
        return None, "noroot"
    sub = (archiveSubdir(db_path, key) or "").strip()
    base = os.path.join(root, sub) if sub else root
    if not os.path.isdir(base):
        return None, "noaccess"
    idx = _buildPdfIndex(base)
    hit = idx.get(fname)
    if hit is None:                       # miss → 重建一次（吸收新歸檔的檔）
        idx = _buildPdfIndex(base, force=True)
        hit = idx.get(fname)
    if hit is None:
        return None, "notfound"
    return hit, "ok"


def _driveToUnc(path):
    """用 Windows 原生 WNetGetConnection 把對應的網路磁碟機代號（如 Z:）解析成 UNC。
    非對應磁碟機 / 非 Windows / 失敗皆回 None。"""
    p = path.replace("/", "\\")
    if len(p) < 2 or p[1] != ":":
        return None
    drive = p[:2]  # 如 Z:
    try:
        import ctypes
        from ctypes import wintypes
        mpr = ctypes.WinDLL("mpr")
        length = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(length.value)
        res = mpr.WNetGetConnectionW(drive, buf, ctypes.byref(length))
        if res != 0:  # 緩衝不足等，依回報長度重試一次
            buf = ctypes.create_unicode_buffer(length.value)
            res = mpr.WNetGetConnectionW(drive, buf, ctypes.byref(length))
        if res == 0 and buf.value.startswith("\\\\"):
            unc = buf.value.rstrip("\\")
            rel = p[2:].lstrip("\\")  # 磁碟機代號之後的相對路徑
            return unc + ("\\" + rel if rel else "")
    except Exception:
        pass
    return None


def toUncPath(path):
    """把含磁碟機代號的路徑（如 Z:\\歸檔\\2026）轉成 UNC（\\\\伺服器\\分享\\歸檔\\2026）。
    已是 UNC 直接回；非網路磁碟或轉換失敗回 None（呼叫端應改要求手動輸入 UNC）。"""
    if not path:
        return None
    p = path.replace("/", "\\")
    if p.startswith("\\\\"):
        return p.rstrip("\\")
    # 首選：WNetGetConnection 直接問磁碟機代號對應的 UNC（最可靠）
    unc = _driveToUnc(p)
    if unc:
        return unc
    # 後備：QStorageInfo（部分環境可抓到 \\伺服器\分享 來源）
    try:
        from PySide6.QtCore import QStorageInfo
        si = QStorageInfo(path)
        dev = (si.device() or "").replace("/", "\\")
        root = si.rootPath()
        if dev.startswith("\\\\") and root:
            rel = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
            if rel in (".", ""):
                return dev.rstrip("\\")
            return dev.rstrip("\\") + "\\" + rel.replace("/", "\\")
    except Exception:
        pass
    return None
