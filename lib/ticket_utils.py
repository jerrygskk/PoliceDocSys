# -*- coding: utf-8 -*-
"""罰單登錄（Document_Ticket）的 domain 層：編號正規化、唯一性與 CRUD。

界線（重要）：
  - 所有罰單編號寫入入口一律先走 `normalizeTicketNo()`（去頭尾空白→轉大寫→
    只允許 ASCII 英數），UI 端不得自行 trim／upper 後直接寫 DB。
  - `register_date` 為三態欄位，語意與 `Document_Reward` 一致：
    `NULL`＝軟刪除空殼、`''`＝發文結算登錄未發文、非空日期＝發文者登錄已發文。
    因此「有效列」條件恆為 `register_date IS NOT NULL`。
  - 刪除一律清空業務欄位保留 `doc_id`（不真 DELETE、不寫 `Trash_Documents`；
    罰單為單欄輕量資料，不納入誤刪還原回收筒）。
  - 本模組全部函式使用呼叫端傳入的同一個 `conn`，Audit 與業務操作同一
    transaction，**由呼叫端統一 commit／rollback**（同 `db_utils.softDeleteDoc`）。
  - 純資料層，不彈視窗；驗證失敗一律拋例外，由 UI 層接住後走 `reportError`
    或顯示白話提示。
"""
import re
import sqlite3

from lib.db_utils import (
    LAST_MODIFIED_CAS_SQL, auditStaffName, buildDetail, nextDocId, writeAudit,
)


TICKET_TABLE = "Document_Ticket"

# 罰單有效列條件（NULL 僅代表軟刪除），供本模組與後續查詢頁共用。
TICKET_ACTIVE_SQL = "register_date IS NOT NULL"

# 罰單簽收歸屬日一律是實際發文／結算寫入的日期，與目前輸入模式無關。
TICKET_RECEIPT_DATE_COL = "register_date"

_AUDIT_CATEGORY = "罰單"


def ticketNoNaturalKey(ticket_no: str) -> tuple:
    """回傳罰單編號的大小寫無關自然排序 key。"""
    normalized = ticket_no.upper()
    parts = re.findall(r"[A-Z]+|\d+", normalized)
    segmented = tuple(
        (1, int(part), len(part)) if part.isdigit() else (0, part)
        for part in parts
    )
    return segmented, normalized


def ticketSortKey(issuer_sort_order, issuer_name, ticket_no) -> tuple:
    """罰單共用排序：人員順序、姓名、大小寫無關的自然罰單號。"""
    return (
        issuer_sort_order,
        issuer_name or "",
        ticketNoNaturalKey(ticket_no),
    )


class TicketValidationError(ValueError):
    """罰單欄位驗證失敗（編號格式、必填、參照人員不存在等）。"""
    pass


class TicketDuplicateError(TicketValidationError):
    """罰單編號在目前年度資料庫已存在（不分大小寫）。"""
    pass


class TicketNotFoundError(LookupError):
    """查無該筆罰單有效資料（不存在或已被刪除）。"""
    pass


class TicketConflictError(LookupError):
    """儲存時原值已變動，拒絕覆蓋其他電腦較新的資料。"""
    pass


_TICKET_RE = re.compile(r"^[A-Z0-9]+$")
TICKET_NO_MAX_LEN = 20

# ══════════════════════════════════════════════════════════════════
# 罰單編號最少字數（設定頁「系統設定 → 罰單編號長度」可調）
# ──────────────────────────────────────────────────────────────────
# 用途：現場輸入罰單編號時可能少打幾碼（例如只打到 `D4`），格式與唯一性都
# 檢查得過、就這樣存進去了。給一個下限讓它在送出時被擋下。
#
# **預設 0＝不限制**（維護者裁示）：既有資料裡可能已經有短編號，一上線就強制
# 會擋住現場作業；要啟用由管理者自己到設定頁填。
# ⚠️ 跨年度重置**不清**此 key（單位的長期設定，比照唯讀鎖／閒置逾時；
# `performYearEndReset` 只清 `archive_*`，故不必另外處理）。
#
# ⚠️ key 與讀取放在本檔而不是 `db_utils`：它是罰單專屬的驗證規則，而本模組是
# 「所有罰單編號寫入入口」的唯一來源（見檔頭界線）。放這裡才能跟
# `normalizeTicketNo` 的其他規則擺在一起，也避免 db_utils 反向依賴罰單常數。
TICKET_NO_MIN_LEN_KEY = "ticket_no_min_len"
TICKET_NO_MIN_LEN_DEFAULT = 0
TICKET_NO_MIN_LEN_RANGE = (0, TICKET_NO_MAX_LEN)


def parseTicketNoMinLen(raw):
    """App_Settings 的字串 → 最少字數（int）。

    0＝不限制。非數字／負數／超過上限一律回預設（DB 值被手動改壞時的保底），
    比照 `db_utils.parseIdleMinutes` 的作風：不拋例外、不擋住程式。
    """
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        return TICKET_NO_MIN_LEN_DEFAULT
    lo, hi = TICKET_NO_MIN_LEN_RANGE
    if not (lo <= val <= hi):
        return TICKET_NO_MIN_LEN_DEFAULT
    return val


def ticketNoMinLen(conn):
    """讀取目前設定的最少字數；讀不到一律回預設（0＝不限制）。

    ⚠️ 用呼叫端傳進來的同一個 `conn`（比照本模組其他函式），不另開連線——
    寫入流程本來就在一個 transaction 裡，另開連線在 SMB 多機下會多一次鎖競爭。
    """
    try:
        row = conn.execute(
            "SELECT value FROM App_Settings WHERE key=?",
            (TICKET_NO_MIN_LEN_KEY,)).fetchone()
    except Exception:
        return TICKET_NO_MIN_LEN_DEFAULT
    return parseTicketNoMinLen(row[0] if row else None)


def _requireMinLen(conn, ticket_no):
    """字數不足即擋下。⚠️ 三個寫入入口都要呼叫，不要只加在登錄頁那條。

    刻意**不放進 `normalizeTicketNo`**：那支是純函式、不碰資料庫，測試與
    `tools/` 都直接呼叫它；把設定讀取塞進去會讓它每次正規化都查一次 DB，
    也讓它不再能離線單測。
    """
    min_len = ticketNoMinLen(conn)
    if min_len and len(ticket_no) < min_len:
        raise TicketValidationError(
            f"罰單編號至少需 {min_len} 個字元，目前只有 {len(ticket_no)} 個。")


def normalizeTicketNo(value):
    """罰單編號正規化：去頭尾空白→轉大寫→驗證僅含 ASCII 英數→驗證長度上限。

    全形英數（如 `Ｄ４ＲＤ`）刻意不做轉換，一律視為不合法並要求重新輸入，
    避免使用者誤以為已輸入正確半形編號。長度上限對應簽收單列印欄寬，
    超過會被裁掉且無省略號，故在寫入前即擋下。
    """
    normalized = (value or "").strip().upper()
    if not normalized:
        raise TicketValidationError("請輸入罰單編號。")
    if not _TICKET_RE.fullmatch(normalized):
        raise TicketValidationError("罰單編號只能包含英文字母與數字。")
    if len(normalized) > TICKET_NO_MAX_LEN:
        raise TicketValidationError(
            f"罰單編號長度不可超過 {TICKET_NO_MAX_LEN} 個字元。")
    return normalized


def ticketExists(conn, ticket_no, *, exclude_doc_id=None):
    """該罰單編號是否已被有效列使用（不分大小寫）。

    軟刪除空殼的 `ticket_no` 為 NULL，天然不列入比對——刪除後同一編號可再登錄。
    `exclude_doc_id` 供編輯時排除自己那列。此處刻意不拋格式例外（純查詢用途），
    空字串直接回 False。
    """
    value = (ticket_no or "").strip().upper()
    if not value:
        return False
    sql = ("SELECT 1 FROM Document_Ticket "
           "WHERE ticket_no IS NOT NULL AND ticket_no = ? COLLATE NOCASE")
    params = [value]
    if exclude_doc_id is not None:
        sql += " AND doc_id <> ?"
        params.append(str(exclude_doc_id))
    return conn.execute(sql + " LIMIT 1", params).fetchone() is not None


def _requirePerson(conn, staff_id, label):
    """驗證人員 id 存在於 Ref_Personnel，回傳去空白後的 id。"""
    value = (staff_id or "").strip()
    if not value:
        raise TicketValidationError(f"請選擇{label}。")
    row = conn.execute(
        "SELECT 1 FROM Ref_Personnel WHERE staff_id = ?", (value,)).fetchone()
    if row is None:
        raise TicketValidationError(f"查無{label}（{value}），請重新選擇。")
    return value


def _requireCreateDate(create_date):
    value = (create_date or "").strip()
    if not value:
        raise TicketValidationError("請選擇登錄日期。")
    return value


def _requireUnique(conn, ticket_no, *, exclude_doc_id=None):
    if ticketExists(conn, ticket_no, exclude_doc_id=exclude_doc_id):
        raise TicketDuplicateError(f"罰單編號 {ticket_no} 已登錄，不可重複。")


def _raiseDuplicateIfUnique(exc, ticket_no):
    """`sqlite3.IntegrityError` 只在確為唯一性違規時轉成編號重複，其餘原樣重拋。

    外鍵違規（`FOREIGN KEY constraint failed`）與 CHECK 違規拋出的同樣是
    `IntegrityError`，若一律翻譯成「編號重複」會給使用者完全錯誤的提示。
    ⚠️ 不可改用訊息字串比對：SQLite 把主鍵衝突也寫成
    `UNIQUE constraint failed: Document_Ticket.doc_id`，流水號與實際
    最大 doc_id 失準時（還原舊備份、手改 DB）會把「配號撞號」誤報成
    「罰單編號重複」。改以 extended error code 精確區分：唯一索引違規是
    2067（`SQLITE_CONSTRAINT_UNIQUE`），主鍵違規是 1555
    （`SQLITE_CONSTRAINT_PRIMARYKEY`），兩者不同碼。
    `sqlite_errorcode` 需 Python 3.11+（本專案為 3.12），取不到時退回
    字串比對，寧可誤報也不要在資料層炸掉。
    """
    code = getattr(exc, "sqlite_errorcode", None)
    if code is not None:
        is_unique = code == 2067      # SQLITE_CONSTRAINT_UNIQUE
    else:
        is_unique = "unique constraint" in str(exc).lower()
    if is_unique:
        raise TicketDuplicateError(
            f"罰單編號 {ticket_no} 已登錄，不可重複。") from exc
    raise exc


def _raiseTicketUpdateMiss(conn, doc_id):
    active = conn.execute(
        "SELECT 1 FROM Document_Ticket WHERE doc_id=? AND " + TICKET_ACTIVE_SQL,
        (doc_id,),
    ).fetchone()
    if active is None:
        raise TicketNotFoundError(
            f"查無罰單資料（編號 {doc_id}），可能已被其他使用者刪除。")
    raise TicketConflictError("本筆罰單資料已被其他電腦修改，本次未儲存。")


def _detail(conn, *, doc_id, create_date, register_date, sender_id,
            issuer_id, ticket_no):
    """組稽核 detail 內容（人員一律存當下姓名快照）。"""
    return (
        f"編號：{doc_id}；罰單編號：{ticket_no or ''}；"
        f"開立人員：{auditStaffName(conn, issuer_id)}；"
        f"登錄日期：{create_date or ''}；"
        f"發文日期：{register_date or ''}；"
        f"發文人員：{auditStaffName(conn, sender_id)}"
    )


def _writeTicketAudit(conn, *, role, action, label, doc_id, create_date,
                      register_date, sender_id, issuer_id, ticket_no):
    """寫一筆罰單稽核。

    ⚠️ **罰單只在刪除時寫稽核**（維護者決定）：新增與修改屬高頻日常操作，
    逐筆寫進操作紀錄只會把紀錄洗掉、蓋住真正需要追查的事；刪除是不可逆且
    會抹掉內容的動作，故保留，且 detail 取的是**刪除前**的欄位值，事後才
    查得到刪掉的是哪張罰單。新增／修改請勿再把本函式加回去。

    `operator` 一律留空：罰單登錄開放所有已登入身分操作，資料列本身不足以
    判定「是誰按下的」（發文結算模式沒有發文人員、admin 亦可代改），與其寫入
    可能誤導的姓名，不如只留 `role`。
    """
    writeAudit(
        conn, role=role, action=action, target_table=TICKET_TABLE,
        target_id=str(doc_id), operator=None,
        detail=buildDetail(_AUDIT_CATEGORY, label, _detail(
            conn, doc_id=doc_id, create_date=create_date,
            register_date=register_date, sender_id=sender_id,
            issuer_id=issuer_id, ticket_no=ticket_no)))


def createTicket(conn, *, issuer_id, ticket_no, self_service, sender_id,
                 create_date, role):
    """新增一筆罰單，回傳配發到的 `doc_id`（字串）。

    發文結算模式：`register_date=''`、`sender_id=NULL`（UI 的發文者欄雖反灰仍可能
    有殘留值，此處一律忽略）。發文者登錄模式：`register_date=create_date`、
    寫入指定發文者。`doc_id` 由 `Seq_DocId` 配發，**與罰單編號完全無關**。
    """
    normalized = normalizeTicketNo(ticket_no)
    _requireMinLen(conn, normalized)
    create_date = _requireCreateDate(create_date)
    issuer_id = _requirePerson(conn, issuer_id, "開立人員")
    if self_service:
        sender_id = None
        register_date = ""
    else:
        sender_id = _requirePerson(conn, sender_id, "發文者")
        register_date = create_date
    _requireUnique(conn, normalized)

    doc_id = nextDocId(conn, TICKET_TABLE)
    try:
        conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id, create_date, register_date, sender_id, issuer_id, ticket_no) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (doc_id, create_date, register_date, sender_id, issuer_id,
             normalized))
    except sqlite3.IntegrityError as exc:
        # 併發下他機可能在唯一性檢查與寫入之間搶先登錄同一編號。
        _raiseDuplicateIfUnique(exc, normalized)
    return doc_id


def updateTicket(conn, *, doc_id, issuer_id, ticket_no, role,
                 last_modified):
    """罰單登錄頁的編輯：只改舉發人員與罰單編號。

    `create_date`／`register_date`／`sender_id` 一律保留原值（不因編輯而把
    未發文改成已發文，或竄改登錄日期）——這靠**不寫進 SET 子句**保證，
    與樂觀鎖無關。

    呼叫端必須傳入對話框載入時讀走的 `last_modified` 快照；漏傳直接
    `TypeError`，不可在儲存時重查（重查等於沒有鎖）。
    ⚠️ 2026-08-07 起改用 `last_modified` 樂觀鎖，取代原本比對五欄原值的
    做法——全專案五個編輯彈窗統一成同一套，理由與已知限制見
    `db_utils.LAST_MODIFIED_CAS_SQL` 上方註解。
    """
    doc_id = str(doc_id)

    normalized = normalizeTicketNo(ticket_no)
    _requireMinLen(conn, normalized)
    issuer_id = _requirePerson(conn, issuer_id, "開立人員")
    _requireUnique(conn, normalized, exclude_doc_id=doc_id)

    try:
        cur = conn.execute(
            "UPDATE Document_Ticket SET issuer_id = ?, ticket_no = ? "
            "WHERE doc_id = ? AND " + TICKET_ACTIVE_SQL + " "
            "AND " + LAST_MODIFIED_CAS_SQL,
            (issuer_id, normalized, doc_id, last_modified))
    except sqlite3.IntegrityError as exc:
        _raiseDuplicateIfUnique(exc, normalized)
    if cur.rowcount != 1:
        _raiseTicketUpdateMiss(conn, doc_id)


def updateTicketFromBrowse(conn, *, doc_id, create_date, register_date,
                           sender_id, issuer_id, ticket_no, role,
                           last_modified):
    """資料庫瀏覽頁的 admin 編輯：可改全部業務欄位。

    `register_date` 必須明確區分 `''`（未發文）與有效日期，**不接受 `None`**
    ——`NULL` 是刪除狀態的哨兵，只能經由 `deleteTicket()` 產生。
    另在 helper 層把關「已發文必有發文人員」（有發文日期就必然有發文者：
    發文者登錄模式當場指定、發文結算整批寫入），資料表 CHECK 不改動——既有
    資料庫的 CHECK 不會因改 schema 而重建，只有這裡擋得住。呼叫端必須傳入
    對話框載入時讀走的 `last_modified` 快照，不得於儲存時重查（見 `updateTicket`）。
    """
    doc_id = str(doc_id)
    if register_date is None:
        raise TicketValidationError(
            "發文日期資料無效；尚未發文請留空白，如需刪除請使用刪除功能。")

    normalized = normalizeTicketNo(ticket_no)
    _requireMinLen(conn, normalized)
    create_date = _requireCreateDate(create_date)
    issuer_id = _requirePerson(conn, issuer_id, "開立人員")
    register_date = (register_date or "").strip()
    if (sender_id or "").strip():
        sender_id = _requirePerson(conn, sender_id, "發文者")
    elif register_date:
        raise TicketValidationError("已填寫發文日期時，請一併選擇發文者。")
    else:
        sender_id = None
    _requireUnique(conn, normalized, exclude_doc_id=doc_id)

    try:
        cur = conn.execute(
            "UPDATE Document_Ticket SET create_date = ?, register_date = ?, "
            "sender_id = ?, issuer_id = ?, ticket_no = ? "
            "WHERE doc_id = ? AND " + TICKET_ACTIVE_SQL + " "
            "AND " + LAST_MODIFIED_CAS_SQL,
            (create_date, register_date, sender_id, issuer_id, normalized,
             doc_id, last_modified))
    except sqlite3.IntegrityError as exc:
        _raiseDuplicateIfUnique(exc, normalized)
    if cur.rowcount != 1:
        _raiseTicketUpdateMiss(conn, doc_id)


def deleteTicket(conn, *, doc_id, role):
    """軟刪除：清空業務欄位、保留 `doc_id` 空殼（流水號永久佔用）。

    `register_date IS NOT NULL` 同時是併發刪除保護——他機已刪則 rowcount=0，
    拋 `TicketNotFoundError` 由呼叫端提示，不會重複寫稽核。
    ⚠️ `last_modified` 明確寫入 `datetime('now','localtime')`：與 trigger 同一
    時區基準，不可用 `CURRENT_TIMESTAMP`（UTC，在本地時間之前，會讓瀏覽頁的
    `MAX(last_modified)` 指紋倒退而漏刷新）。
    """
    doc_id = str(doc_id)
    row = conn.execute(
        "SELECT create_date, register_date, sender_id, issuer_id, ticket_no "
        "FROM Document_Ticket WHERE doc_id = ? AND " + TICKET_ACTIVE_SQL,
        (doc_id,)).fetchone()

    cur = conn.execute(
        "UPDATE Document_Ticket "
        "SET create_date=NULL, "
        "    register_date=NULL, "
        "    sender_id=NULL, "
        "    issuer_id=NULL, "
        "    ticket_no=NULL, "
        "    last_modified=datetime('now','localtime') "
        "WHERE doc_id=? AND register_date IS NOT NULL",
        (doc_id,))
    if cur.rowcount != 1:
        raise TicketNotFoundError(
            f"查無罰單資料（編號 {doc_id}），可能已被其他使用者刪除。")

    create_date, register_date, sender_id, issuer_id, ticket_no = row
    _writeTicketAudit(
        conn, role=role, action="DELETE", label="刪除", doc_id=doc_id,
        create_date=create_date, register_date=register_date,
        sender_id=sender_id, issuer_id=issuer_id, ticket_no=ticket_no)
