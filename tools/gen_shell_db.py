# -*- coding: utf-8 -*-
"""產生乾淨空殼 dbfile.db（schema 來自 lib/db_schema、種子來自 lib/db_seed）。

發版用：取代「從 git HEAD 取二進位空殼」。schema 與種子的唯一來源都在程式碼，
跑本腳本即得與程式碼一致的空殼，不再手工維護二進位檔。

用法（從專案根目錄執行）：
    python tools/gen_shell_db.py [輸出路徑]

預設輸出 ./_shell/dbfile.db（不碰專案根的真實 dbfile.db）。
為防誤覆蓋真實資料，若輸出路徑已存在，必須加 --force 才覆蓋。
產出後自動 VACUUM（消除 slack space，與發版前置一致）。
"""
import os
import sys
import sqlite3

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from lib import db_schema, db_seed  # noqa: E402


def build(out_path):
    if os.path.exists(out_path):
        os.remove(out_path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    conn = sqlite3.connect(out_path)
    try:
        db_schema.applySchema(conn)   # 全部表/View/Trigger（IF NOT EXISTS）
        db_seed.seedFreshDb(conn)     # 參照資料＋預設密碼＋Seq 歸零
        conn.commit()
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()


def main(argv):
    args = [a for a in argv if a != "--force"]
    force = "--force" in argv
    out_path = args[0] if args else os.path.join(_ROOT, "_shell", "dbfile.db")
    out_path = os.path.abspath(out_path)

    # 嚴防覆蓋專案根的真實 dbfile.db
    real_db = os.path.abspath(os.path.join(_ROOT, "dbfile.db"))
    if out_path == real_db:
        print("拒絕：不可輸出到專案根的 dbfile.db（真實資料）。請指定其他路徑。")
        return 2
    if os.path.exists(out_path) and not force:
        print(f"輸出路徑已存在：{out_path}\n如要覆蓋請加 --force。")
        return 1

    build(out_path)
    print(f"已產生乾淨空殼：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
