"""APP 層軟性互斥：開啟時偵測「是否已有人在用」。

把 DB 放在網路磁碟機給多台機器同時跑時，SQLite 的檔案鎖不保證跨機器生效，
真同時寫入可能造成資料毀損。本模組在 `dbfile.db` 旁維護一個鎖檔（`dbfile.lock`），
開啟時讀它判斷是否已有人在用，**純勸導**：仍可選擇「仍要開啟」。
不做唯讀模式、不擋 DB 寫入（那層由 SQLite 自身的忙線鎖處理）。

純邏輯（parse/format/is_stale/is_mine）可單測；I/O 為薄包裝、失敗一律靜默退讓
（讀不到/寫不了鎖檔時不阻擋使用者開程式）。
"""
import json
import os
import socket
import getpass
from datetime import datetime

STALE_SECONDS = 5 * 60        # 心跳超過 5 分鐘沒更新＝視為當機殘留，可接管
HEARTBEAT_MS  = 60 * 1000     # 心跳更新間隔（毫秒）
LOCK_NAME     = "dbfile.lock"


def lock_file_path(db_path):
    """鎖檔路徑：與 dbfile.db 同資料夾。"""
    return os.path.join(os.path.dirname(os.path.abspath(db_path)), LOCK_NAME)


def current_identity():
    """回 (機器名, 使用者名, PID)。取不到時給佔位字串，不拋例外。"""
    machine = os.environ.get("COMPUTERNAME") or socket.gethostname() or "未知電腦"
    try:
        user = getpass.getuser()
    except Exception:
        user = os.environ.get("USERNAME") or "未知使用者"
    return machine, user, os.getpid()


def format_lock(machine, user, opened_iso, heartbeat_iso, pid):
    return json.dumps({
        "machine": machine,
        "user": user,
        "opened": opened_iso,
        "heartbeat": heartbeat_iso,
        "pid": pid,
    }, ensure_ascii=False)


def parse_lock(text):
    """解析鎖檔內容為 dict；壞掉/非 dict 回 None。"""
    try:
        d = json.loads(text)
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def is_stale(heartbeat_iso, now_iso, stale_seconds=STALE_SECONDS):
    """心跳是否已失效（過舊或時間戳壞掉）。失效＝可接管。"""
    try:
        hb = datetime.fromisoformat(heartbeat_iso)
        now = datetime.fromisoformat(now_iso)
    except Exception:
        return True
    return (now - hb).total_seconds() > stale_seconds


def is_mine(info, machine, pid):
    """鎖檔是否屬於本實例（機器名＋PID 相符）。"""
    return bool(info) and info.get("machine") == machine and info.get("pid") == pid


# ── I/O 薄包裝（失敗一律靜默，不阻擋使用者）──────────────────────
def read_lock(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return parse_lock(f.read())
    except Exception:
        return None


def write_lock(path, machine, user, opened_iso, heartbeat_iso, pid):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(format_lock(machine, user, opened_iso, heartbeat_iso, pid))
        return True
    except Exception:
        return False


def remove_lock(path, machine=None, pid=None):
    """刪鎖檔。給了 machine/pid 則只在鎖檔屬於本實例時才刪（避免刪掉別人的）。"""
    try:
        if machine is not None or pid is not None:
            if not is_mine(read_lock(path), machine, pid):
                return
        os.remove(path)
    except Exception:
        pass
