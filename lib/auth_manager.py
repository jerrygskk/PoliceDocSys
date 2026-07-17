"""
auth_manager.py — 權限控管

設計說明：
  - 單例模式：AuthManager.instance() 取得全域實例
  - 啟動時 current_role 永遠是 'user'
  - 設定 Tab 呼叫 login(password, db_path) 驗證，成功後升為 'admin'
  - 離開設定 Tab 時呼叫 logout()，降回 'user'
  - 各 Tab 需要判斷權限時，用便捷判斷 is_admin() / is_manager() / is_archive()

使用範例：
    from lib.auth_manager import AuthManager

    def _deleteSomething(self, doc_id):
        if not AuthManager.instance().is_admin():
            msgWarning("權限不足", "請先登入管理者帳號")
            return
        ...

    AuthManager.instance().role_changed.connect(self._onRoleChanged)
"""

import hashlib
import secrets
import sqlite3

from PySide6.QtCore import QObject, Signal


def _hash_eq(stored, candidate_hash: str) -> bool:
    """常數時間比對兩個 hash 字串（防時序攻擊）。

    stored 可能為 None（key 不存在）；以空字串墊底並回 False。
    secrets.compare_digest 兩參數須等長且皆為 str，故先確認 stored 是字串。
    """
    if not isinstance(stored, str):
        return False
    return secrets.compare_digest(stored, candidate_hash)


class AuthManager(QObject):
    """
    全域單例，管理目前登入身份。

    Roles:
        'user'  — 一般使用者（預設）
        'admin' — 管理者，可修刪改所有資料及維護參照表

    Permissions:
        'delete' — 刪除資料
        'edit'   — 修改資料
        'ref'    — 維護參照表（人員、部門、案件類型）
    """

    role_changed = Signal(str)   # 身份變更時 emit，帶新的 role 字串

    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self._role = 'user'

    # ── 查詢 ────────────────────────────────────────────
    @property
    def current_role(self):
        return self._role

    def is_admin(self) -> bool:
        """便捷判斷：當前是否為最高權限管理者。等同 current_role == 'admin'。"""
        return self._role == 'admin'

    def is_archive(self) -> bool:
        """便捷判斷：當前是否為歸檔管理身分。"""
        return self._role == 'archive'

    def is_manager(self) -> bool:
        """便捷判斷：當前是否具管理身分（歸檔管理或最高權限管理者）。
        給「歸檔管理也能做」的功能判斷用（歸檔頁、瀏覽頁編輯、歸檔狀態區塊等）。"""
        return self._role in ('admin', 'archive')

    def actor_name(self) -> str:
        """回傳當前身分的中文名（稽核 log 的 operator 用）。"""
        return {'admin': '管理者', 'archive': '歸檔管理'}.get(self._role, '一般使用者')

    # ── 登入 / 登出（由設定 Tab 呼叫）────────────────────
    def login(self, password: str, db_path: str) -> bool:
        """
        驗證密碼並提升身分。先比對 admin_password_hash（最高權限管理者），
        再比對 archive_password_hash（歸檔管理）；都不中則登入失敗。
        """
        try:
            h    = hashlib.sha256(password.encode()).hexdigest()
            conn = sqlite3.connect(db_path)
            rows = dict(conn.execute(
                "SELECT key, value FROM App_Settings "
                "WHERE key IN ('admin_password_hash','archive_password_hash')"
            ).fetchall())
            conn.close()
            if _hash_eq(rows.get('admin_password_hash'), h):
                self._role = 'admin'
                self.role_changed.emit(self._role)
                return True
            if _hash_eq(rows.get('archive_password_hash'), h):
                self._role = 'archive'
                self.role_changed.emit(self._role)
                return True
        except Exception:
            pass
        return False

    def logout(self):
        """降回一般使用者身份。"""
        if self._role != 'user':
            self._role = 'user'
            self.role_changed.emit(self._role)

    def change_password(self, old_password: str, new_password: str, db_path: str) -> str:
        """
        變更「當前登入身分」那組密碼。
        admin → admin_password_hash、archive → archive_password_hash。
        需先通過舊密碼驗證，且新密碼不得與另一組管理密碼相同
        （login() 先比 admin 再比 archive，兩組同值時 archive 永遠登不進）。

        回傳狀態字串：
            'ok'        — 變更成功
            'wrong_old' — 舊密碼錯誤
            'conflict'  — 新密碼與另一組管理密碼相同
            'error'     — 未登入或讀寫失敗
        """
        key = {'admin': 'admin_password_hash',
               'archive': 'archive_password_hash'}.get(self._role)
        if not key:
            return 'error'
        other_key = ('archive_password_hash' if key == 'admin_password_hash'
                     else 'admin_password_hash')
        try:
            old_h = hashlib.sha256(old_password.encode()).hexdigest()
            conn  = sqlite3.connect(db_path)
            try:
                rows = dict(conn.execute(
                    "SELECT key, value FROM App_Settings "
                    "WHERE key IN ('admin_password_hash','archive_password_hash')"
                ).fetchall())
                if not _hash_eq(rows.get(key), old_h):
                    return 'wrong_old'
                new_h = hashlib.sha256(new_password.encode()).hexdigest()
                if _hash_eq(rows.get(other_key), new_h):
                    return 'conflict'
                conn.execute(
                    "UPDATE App_Settings SET value=? WHERE key=?",
                    (new_h, key)
                )
                conn.commit()
            finally:
                conn.close()
            return 'ok'
        except Exception:
            return 'error'
