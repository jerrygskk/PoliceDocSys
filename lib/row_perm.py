"""登錄／收發文五頁的「這一列能不能改、能不能刪」單一來源。

純邏輯、不 import Qt 也不開連線，可直接單測（`tests/test_row_perm.py`）。

## 為什麼有這支檔案

身分變更時，五頁的預覽清單原本整張清空（`InputLockMixin._onRoleClearList`）。
2026-08-04 維護者裁示改為**逐列重算權限**，清單留著；判斷規則若散在各頁，
下一次改權限一定會漏掉其中幾頁，故集中在這裡。各頁只負責「取值、套用外觀」。

## 頁面代號沿用既有詞彙

`dispatch`／`task`／`crim`／`gen`／`ticket`／`reward`，與
`lib.db_utils.INPUT_LOCK_KEYS` 完全相同，**不另造第二套**（`task`＝交辦單收文、
`crim`／`gen`＝公文陳報的刑案與一般兩張表）。

## 三態：各頁的表示法本來就不同，不可套同一條規則

| 頁 | 未發文 | 軟刪除空殼 |
|---|---|---|
| `reward`／`ticket` | `register_date = ''` | `register_date IS NULL` |
| `crim`／`gen` | `report_date IS NULL` | 與日期無關，看主旨欄被清空 |
| `dispatch`／`task` | `dispatch_date` 空 | 與日期無關，看主旨欄被清空 |

⚠️ 2026-08-07 修正：本專案的計畫書原先把「`NULL`＝軟刪除」當成全頁通則，
照著寫會把**陳報所有未發文列誤判成已刪除**。故「已發文」與「這列還在不在」
拆成兩支函式，前者跨頁同規則、後者逐頁不同（見 `LIVE_COLUMN`）。

⚠️ 統一的是判斷邏輯，**不是資料庫存的值**：現場既有資料不動，五張主表的哨兵
維持現狀（見 CLAUDE.md「既有真實資料的相容退路照留」）。
"""

# ══════════════════════════════════════════════════════════════════
# 頁面 → 資料表欄位對照（各頁組查詢時取用，避免把欄位名寫死在分頁裡）
# ──────────────────────────────────────────────────────────────────
#   table       該頁預覽列所屬的業務主表
#   date_column 判斷「已發文」的日期欄
#   live_column 判斷「這列還在（非軟刪除空殼）」的欄位；軟刪除一律把它清成 NULL
#
# ⚠️ `reward`／`ticket` 的 date_column 與 live_column **刻意是同一欄**：該欄是
# 三態欄位（NULL＝軟刪除、''＝未發文、日期＝已發文），見 db_utils.rewardState。
PAGE_TABLE = {
    "dispatch": "Document_Task",
    "task":     "Document_Task",
    "crim":     "Document_Criminal",
    "gen":      "Document_General",
    "ticket":   "Document_Ticket",
    "reward":   "Document_Reward",
}

DATE_COLUMN = {
    "dispatch": "dispatch_date",
    "task":     None,            # 收文頁沒有「已發文」的概念
    "crim":     "report_date",
    "gen":      "report_date",
    "ticket":   "register_date",
    "reward":   "register_date",
}

LIVE_COLUMN = {
    "dispatch": "subject",
    "task":     "subject",
    "crim":     "subject_summary",
    "gen":      "subject",
    "ticket":   "register_date",
    "reward":   "register_date",
}

PAGES = tuple(PAGE_TABLE)

# 登錄頁（規則相同的一組）。
ENTRY_PAGES = ("crim", "gen", "ticket", "reward")

# ══════════════════════════════════════════════════════════════════
# ⚠️⚠️ 凌駕一切的原則（2026-08-07 維護者裁示，優先於下方任何矩陣）
# ──────────────────────────────────────────────────────────────────
# **不管權限與設定怎麼調整，都不允許擋住「還在預覽列裡、剛登錄完」的資料的
# 修改與刪除。唯一例外是交辦單發文。**
#
# 理由（維護者定義的作業節奏）：這些預覽列就是承辦人自己這一次打進去的東西，
# 打錯字當場自己改掉、按 ✕ 重來，是最高頻的日常操作。任何把它擋下來的規則，
# 都會逼使用者為了一個錯字去找管理身分，那不是權限設計該達成的事。
#
# 為什麼 `dispatch` 除外：交辦單發文的預覽列不是「剛登錄的資料」——它是**掃入
# 文號後從資料庫拉出來的既有公文**（見 `tab_dispatch.handleQuery`／`_insertRow`），
# 本來就可能是別人建立、甚至已經發文的單。故該頁維持 `_EDIT_RULE` 的矩陣。
#
# 下面這五頁的預覽列**只**由「本次送出」寫入（各頁的 `_insertCrimRow`／
# `_insertGenRow`／`_insertPreviewRow`／`_append_preview`／`_appendPreview` 都只在
# submit 成功後才被呼叫），所以「在預覽列裡」等同「本次登錄的」，不需要另外
# 維護一份 session 名單來判斷。
# ⚠️ **唯讀鎖是這條原則的唯一例外**（2026-08-07 維護者追加裁示）：管理者把該
# 流程設為唯讀時（多用於跨年度切換），**三種身分一律不准動**——連預覽列、連
# admin 都不行。唯讀的語意就是「這個功能停用」，留任何改刪入口都與它衝突；
# 要改資料就先到「資料庫設定 → 系統設定」把唯讀關掉（那個入口不受本鎖影響）。
# ⚠️ 這同時把六支硬 gate 的 `not is_manager() and ...` 豁免一併拿掉了，
# 管理身分在唯讀下也不能新增，全專案語意一致。
#
# ⚠️ **日後若讓這些預覽列載入非本次登錄的資料（例如開頁時撈出今天已登錄的），
# 這個等式就不成立，必須改成明確判斷該列是否屬於本次 session，不可沿用。**
#
# ⚠️⚠️ **這是「改回去」，不是新規則**：開發初期本來就是這樣，中途被改成「降權
# 就把預覽清單整張清空」「已發文列鎖住一般使用者」，維護者當時即覺得不合理，
# 事後還得花時間調回來。**看到這段不要再「修正」一次**——要動先問維護者。
# 相關歷史：PITFALLS PRM-1、DEVELOPER §10「預覽列權限」。
SESSION_PREVIEW_PAGES = ("task", "crim", "gen", "ticket", "reward")


def _requirePage(page):
    if page not in PAGE_TABLE:
        raise ValueError(
            f"未知的頁面代號 {page!r}；可用值：{', '.join(PAGES)}"
            "（沿用 db_utils.INPUT_LOCK_KEYS 的詞彙，勿另造）")
    return page


# ══════════════════════════════════════════════════════════════════
# 三態判斷
# ──────────────────────────────────────────────────────────────────
def isDispatched(date_value) -> bool:
    """該列是否「已發文」——只有**非空日期**為真。

    `None`（陳報的未發文／敘獎罰單的軟刪除）與 `''`（敘獎罰單的未發文）
    一律回 False：兩者都不是已發文，權限判斷上待遇相同，故本函式跨頁同規則、
    不需要 `page` 參數。要區分「未發文」與「已刪除」請用 `isLiveRow`。
    """
    if date_value is None:
        return False
    return str(date_value).strip() != ""


def isLiveRow(page, live_value) -> bool:
    """該列是否為有效資料（不是軟刪除留下的空殼）。

    `live_value` 取自 `LIVE_COLUMN[page]` 那一欄的 DB 真值；軟刪除一律把它
    清成 NULL（敘獎罰單清 `register_date`，其餘頁清主旨欄），故判斷即
    「不是 None」。⚠️ 空字串仍算有效——敘獎與罰單的未發文哨兵正是 `''`。
    """
    _requirePage(page)
    return live_value is not None


def rowStateSql(page, doc_ids):
    """組出「一次查回這批 doc_id 的發文狀態與存活狀態」的 SQL。

    回傳 `(sql, params)`，查詢結果每列為 `(doc_id, 發文日期, 存活欄值)`，
    交給 `isDispatched` 與 `isLiveRow` 判讀。⚠️ 一次 `IN` 查詢即可，登錄清單
    是 session 累積、實務上頂多十幾筆，不必做批次最佳化。

    ⚠️ **必須查 DB，不得讀表格上的顯示字串**：畫面上「未發文」與「已刪除」
    都是空白，從 cell 文字在原理上分不出三態。
    """
    _requirePage(page)
    date_col = DATE_COLUMN[page] or "NULL"
    ids = [str(d) for d in doc_ids]
    placeholders = ",".join("?" * len(ids))
    sql = (f"SELECT doc_id, {date_col}, {LIVE_COLUMN[page]} "
           f"FROM {PAGE_TABLE[page]} WHERE doc_id IN ({placeholders})")
    return sql, ids


def liveRowSql(page) -> str:
    """該頁「有效列」的 SQL 條件片段，供各頁組查詢時直接串上。

    與 `isLiveRow` 是同一條規則的兩種形態（一個給 Python 值、一個給 SQL），
    改規則兩處要一起改——`tests/test_row_perm.py` 有測試釘住兩者一致。
    """
    return f"{LIVE_COLUMN[_requirePage(page)]} IS NOT NULL"


# ══════════════════════════════════════════════════════════════════
# 交辦單發文的編輯矩陣（唯一還受身分與狀態限制的預覽列）
# ──────────────────────────────────────────────────────────────────
# ⚠️ 只有 `dispatch` 進得來：其餘五頁屬於 SESSION_PREVIEW_PAGES，預覽列一律
# 開放（見該常數上方的凌駕原則），`canEditRow` 在查表之前就回 True。
# 這裡刻意**不為那五頁留一份用不到的規則**——留著會讓下一個人以為那才是真正
# 生效的條件，而實際上永遠走不到。
#
# 交辦單發文的規則：
#   未發文 → 三身分皆可改（一般使用者只能改承辦人，見 dispatchEditIsRestricted）
#   已發文 → 只有 admin（歸檔管理也不行——交辦單不在歸檔業務範圍內）
#
# ⚠️ 唯讀凍結已在 `canEditRow` 開頭統一處理（三種身分一律擋），本表只管
# 「沒有唯讀時，誰能改哪一列」，不必也不得再判 `input_locked`。
_EDIT_RULE = {
    "dispatch": lambda is_admin, is_manager, dispatched: is_admin or not dispatched,
}

# ⚠️ 沒有 _DELETE_RULE：有刪除入口的頁全都是 SESSION_PREVIEW_PAGES（一律開放），
# 而 dispatch 的 ✕ 是佇列移除、不納入矩陣。見 canDeleteRow。


def canEditRow(page, *, is_admin, is_manager, dispatched, input_locked) -> bool:
    """這一列的編輯入口（編號欄連結／編輯彈窗）是否開放給當前身分。

    ⚠️ `SESSION_PREVIEW_PAGES` 一律回 True——那是凌駕矩陣的原則，見該常數
    上方註解；`dispatched` 對這些頁**刻意無作用**。
    ⚠️ 唯一例外是 `input_locked`：唯讀時**三種身分一律回 False**。
    """
    _requirePage(page)
    if input_locked:
        return False        # 唯讀＝三種身分一律不准動（原則的唯一例外）
    if page in SESSION_PREVIEW_PAGES:
        return True
    rule = _EDIT_RULE[page]
    return rule(is_admin, is_manager, dispatched)


def canDeleteRow(page, *, is_admin, is_manager, dispatched, input_locked) -> bool:
    """這一列的刪除入口（✕ 鈕）是否開放給當前身分。

    ⚠️ `SESSION_PREVIEW_PAGES` 一律回 True，理由同 `canEditRow`——✕ 正是
    「剛登錄打錯、當場重來」的主要工具，擋掉它等於擋掉自我更正。
    ⚠️ 唯一例外同樣是 `input_locked`：唯讀時三種身分都不能刪。

    ⚠️ **`dispatch` 蓄意不支援、傳進來就拋 ValueError**：交辦單發文頁的 ✕ 是
    「從待發文佇列移除」（`removeRow`，完全不碰 DB），與其餘四頁「✕＝軟刪除
    資料庫那一筆」不是同一件事，該頁的 ✕ 恆啟用是既有的頁面特性
    （2026-08-07 維護者裁示不處理）。這裡拋錯是為了讓「日後有人把它接上來」
    當場失敗，而不是靜默把使用者本來就該有的佇列移除功能鎖掉。
    """
    _requirePage(page)
    if page == "dispatch":
        raise ValueError(
            "交辦單發文頁的 ✕ 是佇列移除（不碰 DB）、恆啟用，"
            "不納入權限矩陣；勿把它接到 canDeleteRow")
    return not input_locked     # 唯讀＝三種身分一律不准動


def dispatchEditIsRestricted(*, is_manager) -> bool:
    """交辦單發文頁的編輯彈窗是否只開放「承辦人」一欄（`TaskEditDialog(restricted=)`）。

    ⚠️ 判斷是 `not is_manager()`，**不是** `not is_admin()`：歸檔管理者在
    未發文的單上可以全改（計畫 §2.1 矩陣）。已發文那道硬 gate 另以
    `canEditRow` 判定，仍維持只有 admin 能過。
    """
    return not is_manager
