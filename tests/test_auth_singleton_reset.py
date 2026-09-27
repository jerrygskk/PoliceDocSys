# -*- coding: utf-8 -*-
"""conftest 每支測試後統一拆 AuthManager.role_changed 連線並還原身分（PITFALLS TST-6）。

兩支測試依檔內順序執行：前一支故意留下連線與管理身分，後一支確認已被清乾淨。
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import SIGNAL, QObject

from lib.auth_manager import AuthManager

_SIG = SIGNAL("role_changed(QString)")
_leftover = QObject()


def test_leaves_connection_and_admin_role_behind():
    auth = AuthManager.instance()
    auth.role_changed.connect(_leftover.setObjectName)
    auth._role = "admin"
    assert auth.receivers(_SIG) >= 1


def test_previous_test_state_was_reset():
    auth = AuthManager.instance()
    assert auth.receivers(_SIG) == 0
    assert auth.current_role == "user"
