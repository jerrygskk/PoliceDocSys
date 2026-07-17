"""平時自動備份：常規祖孫式（GFS）輪替（本機）。

單機程式平時零備份，硬碟外的損毀（檔案毀損、誤刪、DB malformed）一旦發生即無救。
本模組在 `dbfile.db` 旁維護 `backups/` 子夾，於程式啟動時做三層帶日期的備份，
各自輪替修剪：

- 每日：`dbfile_backup_day_YYYYMMDD.db`，每天第一次開啟時建一份（當天再開不重做），
        保留最近 `DAILY_KEEP` 份、較舊的刪除。最近一週有逐日粒度。
- 每週：`dbfile_backup_week_YYYYMMDD.db`，每週（ISO 週）第一次開啟時建一份，
        保留最近 `WEEKLY_KEEP` 份。誤刪當天靠每日救、過幾天才發現靠每週救。
- 每月：`dbfile_backup_month_YYYYMMDD.db`，每月第一次開啟時建一份，
        保留最近 `MONTHLY_KEEP` 份。毀損拖超過一個月才發現時的最後退路，
        回溯窗拉到約一年。

備份用 sqlite3 backup API（一致性快照，即使有並發寫入也安全），先寫 `.tmp`
再 `os.replace` 原子換上（中途失敗不會毀掉既有好檔）。**全程失敗一律靜默退讓、
寫 error.log，絕不阻擋程式開啟**（同 app_lock 哲學）。

純邏輯（filename/parse/is_*_due/prune_targets）可單測。
本層只做本機備份，**救不了硬碟整顆故障**；異地備份為後續另一層。
"""
import logging
import os
import re
import sqlite3
from datetime import datetime

BACKUP_DIR_NAME = "backups"
DAILY_PREFIX    = "dbfile_backup_day_"
WEEKLY_PREFIX   = "dbfile_backup_week_"
MONTHLY_PREFIX  = "dbfile_backup_month_"
DAILY_KEEP      = 7    # 每日備份保留份數（最近一週逐日）
WEEKLY_KEEP     = 4    # 每週備份保留份數（約一個月）
MONTHLY_KEEP    = 12   # 每月備份保留份數（約一年）

_DAILY_RE   = re.compile(r"^dbfile_backup_day_(\d{8})\.db$")
_WEEKLY_RE  = re.compile(r"^dbfile_backup_week_(\d{8})\.db$")
_MONTHLY_RE = re.compile(r"^dbfile_backup_month_(\d{8})\.db$")


# ── 路徑 / 檔名 ─────────────────────────────────────────────────
def backup_dir(db_path):
    """備份子夾：與 dbfile.db 同資料夾下的 backups/。"""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), BACKUP_DIR_NAME)


def daily_filename(d):
    return f"{DAILY_PREFIX}{d.strftime('%Y%m%d')}.db"


def weekly_filename(d):
    return f"{WEEKLY_PREFIX}{d.strftime('%Y%m%d')}.db"


def monthly_filename(d):
    return f"{MONTHLY_PREFIX}{d.strftime('%Y%m%d')}.db"


# ── 純邏輯（可單測）────────────────────────────────────────────
def _parse_dates(regex, filenames):
    out = []
    for name in filenames:
        m = regex.match(name)
        if not m:
            continue
        try:
            out.append(datetime.strptime(m.group(1), "%Y%m%d").date())
        except ValueError:
            pass
    return out


def parse_daily_dates(filenames):
    """從檔名清單解析出所有每日備份的日期。"""
    return _parse_dates(_DAILY_RE, filenames)


def parse_weekly_dates(filenames):
    """從檔名清單解析出所有每週備份的日期。"""
    return _parse_dates(_WEEKLY_RE, filenames)


def parse_monthly_dates(filenames):
    """從檔名清單解析出所有每月備份的日期。"""
    return _parse_dates(_MONTHLY_RE, filenames)


def is_daily_due(existing_dates, today):
    """每日備份是否到期：今天尚未備份過。"""
    return today not in existing_dates


def is_weekly_due(existing_dates, today):
    """每週備份是否到期：既有週檔中無任一落在 today 的同一 ISO 週。"""
    wk = today.isocalendar()[:2]   # (ISO 年, ISO 週)
    return not any(d.isocalendar()[:2] == wk for d in existing_dates)


def is_monthly_due(existing_dates, today):
    """每月備份是否到期：既有月檔中無任一落在 today 的同一（年, 月）。"""
    ym = (today.year, today.month)
    return not any((d.year, d.month) == ym for d in existing_dates)


def prune_targets(dates, keep):
    """回傳該刪除的日期（保留最近 keep 份，其餘較舊者刪）。"""
    if keep is None or len(dates) <= keep:
        return []
    return sorted(dates)[:-keep]


# ── I/O（失敗靜默）─────────────────────────────────────────────
def do_backup(db_path, dest):
    """以 sqlite3 backup API 做一致性快照；先寫 .tmp 再原子 replace。

    成功回 True、失敗回 False（並記 error.log）；不拋例外。
    """
    tmp = dest + ".tmp"
    try:
        src = sqlite3.connect(db_path)
        try:
            dst = sqlite3.connect(tmp)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        os.replace(tmp, dest)
        return True
    except Exception:
        logging.error("自動備份寫入失敗：%s", dest, exc_info=True)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False


def _prune(bdir, prefix, dates, keep):
    """刪除超出保留份數的舊備份；失敗靜默。"""
    for d in prune_targets(dates, keep):
        try:
            os.remove(os.path.join(bdir, f"{prefix}{d.strftime('%Y%m%d')}.db"))
        except OSError:
            pass


def _run_gfs(db_path, bdir, today):
    """對單一備份資料夾跑一輪每日＋每週＋每月 GFS 輪替修剪。"""
    os.makedirs(bdir, exist_ok=True)

    # 每日
    daily = parse_daily_dates(os.listdir(bdir))
    if is_daily_due(daily, today):
        if do_backup(db_path, os.path.join(bdir, daily_filename(today))):
            daily.append(today)
    _prune(bdir, DAILY_PREFIX, daily, DAILY_KEEP)

    # 每週
    weekly = parse_weekly_dates(os.listdir(bdir))
    if is_weekly_due(weekly, today):
        if do_backup(db_path, os.path.join(bdir, weekly_filename(today))):
            weekly.append(today)
    _prune(bdir, WEEKLY_PREFIX, weekly, WEEKLY_KEEP)

    # 每月
    monthly = parse_monthly_dates(os.listdir(bdir))
    if is_monthly_due(monthly, today):
        if do_backup(db_path, os.path.join(bdir, monthly_filename(today))):
            monthly.append(today)
    _prune(bdir, MONTHLY_PREFIX, monthly, MONTHLY_KEEP)


def run_auto_backup(db_path, now=None, extra_dirs=None):
    """啟動時呼叫：主備份（db 旁 backups/）＋可選異地副本（extra_dirs 各一份），
    每處各自跑每日／每週輪替修剪。全程靜默，絕不阻擋開程式。

    extra_dirs：絕對路徑清單（第二備份位置），由呼叫端讀設定後傳入。每處各自
    獨立 try——某處失敗（如網路碟斷線、權限不足）不影響其他處，也不擋開程式。
    """
    today = (now or datetime.now()).date()
    dirs = [backup_dir(db_path)]
    for d in (extra_dirs or []):
        if d and d.strip():
            dirs.append(d.strip())
    for bdir in dirs:
        try:
            _run_gfs(db_path, bdir, today)
        except Exception:
            logging.error("自動備份程序異常：%s", bdir, exc_info=True)


def latest_backup_date(bdir):
    """該資料夾中最新一份備份（每日或每週）的日期；讀不到／無備份回 None。
    供系統設定「自動備份」面板顯示異地副本最近時間、判斷是否過舊。"""
    try:
        names = os.listdir(bdir)
    except OSError:
        return None
    dates = (parse_daily_dates(names) + parse_weekly_dates(names)
             + parse_monthly_dates(names))
    return max(dates) if dates else None


def quick_check(db_path):
    """對 DB 跑 PRAGMA quick_check 偵測「檔案層級損毀」（頁面毀損／malformed）。

    回 True＝完好、或無法判定（檔案不存在、鎖定、權限不足）——一律不擋開程式；
    回 False＝明確偵測到損毀（須警示並跳過當日備份，避免壞檔擠掉好備份）。

    ⚠️ 判定順序：OperationalError（鎖定／忙線）是 DatabaseError 的子類，須先攔並
    當「無法判定」放行，否則會把「資料庫忙線中」誤判成損毀。
    """
    if not os.path.exists(db_path):
        return True   # 新裝／空殼由建表流程處理，非損毀
    try:
        conn = sqlite3.connect(db_path, timeout=2)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError:
        logging.error("quick_check 無法執行（鎖定／忙線，非損毀判定）：%s",
                      db_path, exc_info=True)
        return True
    except sqlite3.DatabaseError:
        logging.error("quick_check 開啟／執行失敗（疑似損毀）：%s",
                      db_path, exc_info=True)
        return False
    except Exception:
        logging.error("quick_check 未預期例外（非損毀判定）：%s",
                      db_path, exc_info=True)
        return True
    ok = (len(rows) == 1 and rows[0][0] == "ok")
    if not ok:
        logging.error("quick_check 偵測到資料庫異常：%s / %s", db_path, rows)
    return ok


# ── 備份還原（列舉候選／驗檔／筆數預覽／覆蓋還原）────────────────────
# 重置留底：tab_settings._doReset 產於 db 同目錄 dbfile_backup_YYYYMMDD_HHMMSS.db
# 還原前留底：restore_backup 覆蓋前另存 dbfile_prerestore_YYYYMMDD_HHMMSS.db
_RESET_RE      = re.compile(r"^dbfile_backup_(\d{8})_(\d{6})\.db$")
_PRERESTORE_RE = re.compile(r"^dbfile_prerestore_(\d{8})_(\d{6})\.db$")
PRERESTORE_PREFIX = "dbfile_prerestore_"
RESET_PREFIX      = "dbfile_backup_"          # 重置留底（帶時間戳，與 GFS 每日/每週不同）

PRERESTORE_KEEP = 3   # 還原前留底保留份數（只為選錯份備退路，不需多）
RESET_KEEP      = 3   # 跨年度重置留底保留份數（約 3 季；每年一次，3 份涵蓋近 3 年）


def _prune_timestamped(db_dir, regex, prefix, keep):
    """修剪帶時間戳的留底檔（_RESET_RE / _PRERESTORE_RE 格式），保留最新 keep 份。
    失敗靜默——留底修剪不能反過來阻擋主操作。"""
    entries = []
    try:
        for nm in os.listdir(db_dir):
            m = regex.match(nm)
            if m:
                entries.append((nm, _to_dt(m.group(1), m.group(2))))
    except OSError:
        return
    entries.sort(key=lambda x: x[1], reverse=True)   # 最新在前
    for nm, _ in entries[keep:]:
        try:
            os.remove(os.path.join(db_dir, nm))
        except OSError:
            pass


def _to_dt(ymd, hms=None):
    try:
        return datetime.strptime(ymd + (hms or ""),
                                 "%Y%m%d%H%M%S" if hms else "%Y%m%d")
    except ValueError:
        return datetime.min


def _entry(path, source, kind, when):
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    return {"path": path, "name": os.path.basename(path),
            "source": source, "kind": kind, "when": when, "size": size}


def list_backups(db_path, extra_dirs=None):
    """彙整所有可還原備份，最新在前。來源三類：
       - 主備份：db 旁 backups/（每日／每週）
       - 異地副本：extra_dirs 各資料夾（每日／每週）
       - 重置／還原留底：db 同目錄的 dbfile_backup_*_*.db／dbfile_prerestore_*.db
    每筆 dict：{path,name,source,kind,when(datetime),size}。讀不到的資料夾靜默略過。"""
    out = []

    def scan_gfs(bdir, source):
        try:
            names = os.listdir(bdir)
        except OSError:
            return
        for nm in names:
            m = _DAILY_RE.match(nm)
            if m:
                out.append(_entry(os.path.join(bdir, nm), source, "每日",
                                  _to_dt(m.group(1))))
                continue
            m = _WEEKLY_RE.match(nm)
            if m:
                out.append(_entry(os.path.join(bdir, nm), source, "每週",
                                  _to_dt(m.group(1))))
                continue
            m = _MONTHLY_RE.match(nm)
            if m:
                out.append(_entry(os.path.join(bdir, nm), source, "每月",
                                  _to_dt(m.group(1))))

    scan_gfs(backup_dir(db_path), "主備份")
    for d in (extra_dirs or []):
        if d and d.strip():
            scan_gfs(d.strip(), "異地副本")

    db_dir = os.path.dirname(os.path.abspath(db_path))
    try:
        names = os.listdir(db_dir)
    except OSError:
        names = []
    for nm in names:
        m = _RESET_RE.match(nm)
        if m:
            out.append(_entry(os.path.join(db_dir, nm), "重置留底", "留底",
                              _to_dt(m.group(1), m.group(2))))
            continue
        m = _PRERESTORE_RE.match(nm)
        if m:
            out.append(_entry(os.path.join(db_dir, nm), "還原前留底", "留底",
                              _to_dt(m.group(1), m.group(2))))

    out.sort(key=lambda e: e["when"], reverse=True)
    return out


def verify_backup(path):
    """還原前驗檔：檔案存在、是有效 SQLite 且 quick_check 過。回 (ok, 訊息)。
    ⚠️ 防止把損毀檔／非資料庫檔蓋到本體上。"""
    if not path or not os.path.exists(path):
        return False, "檔案不存在。"
    if not quick_check(path):
        return False, "此檔案可能損毀或非有效的資料庫，不予還原。"
    return True, ""


def backup_doc_counts(path):
    """讀備份內主表未刪除筆數（供還原前預覽、確認選對份）。
    回 {task,crim,gen,reward}（值可能為 None＝該表讀不到）或 None（整檔開不了）。
    唯讀、吞例外。"""
    try:
        conn = sqlite3.connect(path, timeout=2)
        try:
            def cnt(sql):
                try:
                    return conn.execute(sql).fetchone()[0]
                except Exception:
                    return None
            return {
                "task": cnt("SELECT COUNT(*) FROM Document_Task "
                            "WHERE receive_date IS NOT NULL"),
                "crim": cnt("SELECT COUNT(*) FROM Document_Criminal "
                            "WHERE report_date IS NOT NULL"),
                "gen":  cnt("SELECT COUNT(*) FROM Document_General "
                            "WHERE report_date IS NOT NULL"),
                "reward": cnt("SELECT COUNT(*) FROM Document_Reward "
                              "WHERE register_date IS NOT NULL"),
            }
        finally:
            conn.close()
    except Exception:
        return None


def formatDocCounts(counts, prefix="", suffix=""):
    """主表筆數摘要（備份內容／重置預覽共用）。None 值顯示「—」。"""
    def s(value):
        return "—" if value is None else str(value)
    return (
        f"{prefix}交辦 {s(counts['task'])} 筆、"
        f"刑案 {s(counts['crim'])} 筆、一般 {s(counts['gen'])} 筆、"
        f"敘獎 {s(counts['reward'])} 筆{suffix}"
    )


def find_latest_usable_backup(db_path, extra_dirs=None):
    """從所有候選備份（最新在前）逐份 quick_check，回第一份完好的 entry；無則 None。
    給開機救援「自動挑最新可還原的備份」用——最新那份也壞就自動跳下一份。"""
    for e in list_backups(db_path, extra_dirs=extra_dirs):
        ok, _ = verify_backup(e["path"])
        if ok:
            return e
    return None


# 預設管理者密碼（同 db_seed 種子；備份缺 hash 列時的退路，見 verify_admin_password）
_DEFAULT_ADMIN_PW = "admin"


def verify_admin_password(backup_path, password):
    """對某份備份 DB 內的 admin_password_hash 驗證管理者密碼。回 True/False，吞例外。

    開機救援專用：本體 DB 已損毀、驗不了密碼，故改驗「將要還原的那份備份」內的 hash
    （備份是完好 SQLite，內含當時的密碼）。若選到改密碼前的舊備份，要輸的是當時的密碼。

    ⚠️ 備份缺 admin_password_hash 列時（極舊備份／異常空殼）退回「預設密碼」比對——
    否則任何密碼都驗不過、admin 被鎖在還原之外。使用者仍須輸入預設密碼（非直接放行）。
    """
    import hashlib
    try:
        from lib.auth_manager import _hash_eq
        h = hashlib.sha256(password.encode()).hexdigest()
        conn = sqlite3.connect(backup_path, timeout=2)
        try:
            row = conn.execute(
                "SELECT value FROM App_Settings WHERE key='admin_password_hash'"
            ).fetchone()
        finally:
            conn.close()
        stored = row[0] if row else None
        if stored is None:
            stored = hashlib.sha256(_DEFAULT_ADMIN_PW.encode()).hexdigest()
        return _hash_eq(stored, h)
    except Exception:
        return False


def restore_backup(db_path, src_path, now=None):
    """以 src_path 覆蓋 db_path（還原）。覆蓋前先把現有 db 另存
    dbfile_prerestore_YYYYMMDD_HHMMSS.db 留底（失敗即中止、不動本體）。
    回 (ok, 訊息)。⚠️ 呼叫端須已 verify_backup 通過、且已擋掉他機使用中。"""
    import shutil
    if not os.path.exists(src_path):
        return False, "來源備份不存在。"
    db_dir = os.path.dirname(os.path.abspath(db_path))
    ts = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    # 1. 現有 db 留底（若存在）
    try:
        if os.path.exists(db_path):
            backup_here = os.path.join(db_dir, f"{PRERESTORE_PREFIX}{ts}.db")
            shutil.copy2(db_path, backup_here)
    except Exception:
        logging.error("還原前留底失敗，已中止還原", exc_info=True)
        return False, "無法建立還原前的備份，已中止還原（本體資料未變動）。"
    # 2. 覆蓋（先寫 .tmp 再原子 replace，中途失敗不毀本體）
    tmp = db_path + ".restore.tmp"
    try:
        shutil.copy2(src_path, tmp)
        os.replace(tmp, db_path)
    except Exception:
        logging.error("還原覆蓋失敗", exc_info=True)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return False, "還原覆蓋失敗，本體資料未變動。"
    # 3. 修剪舊 prerestore 留底（保留最新 PRERESTORE_KEEP 份）
    _prune_timestamped(db_dir, _PRERESTORE_RE, PRERESTORE_PREFIX, PRERESTORE_KEEP)
    return True, ""
