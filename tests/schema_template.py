"""測試用的建表捷徑：與 `lib.db_schema.applySchema` 同名同用法，結果相同、快很多。

正式 `applySchema` 逐句 DDL 各自 commit，檔案庫每句都等硬碟 fsync，一份庫約 1 秒；
測試逐項建庫累積下來是整輪 gate 的大頭。這裡改成每個行程只在記憶體裡跑一次正式
`applySchema` 當範本，之後各測試用 SQLite backup API 整份複製過去（一次寫入），
並把該連線設 `synchronous=OFF`，後續種子資料也不再逐筆等硬碟。

範本就是正式 DDL 的產物，不是另刻一份 schema，所以結構與正式永遠一致。
⚠️ 專門測建表／升級／備份還原的測試（`test_db_schema`、`test_casetype_alias`、
`test_db_backup`、`test_db_utils`）刻意不用本捷徑，照舊走正式 `applySchema`／
`ensureSchema` 從零建立。
"""
import sqlite3

from lib import db_schema

_template = None


def _templateConn():
    global _template
    if _template is None:
        conn = sqlite3.connect(":memory:", check_same_thread=False)
        db_schema.applySchema(conn)
        conn.commit()
        _template = conn
    return _template


def applySchema(conn):
    """把正式結構複製進 `conn`（須為剛開的空庫，檔案或 :memory: 皆可）。"""
    conn.execute("PRAGMA synchronous=OFF")
    _templateConn().backup(conn)
