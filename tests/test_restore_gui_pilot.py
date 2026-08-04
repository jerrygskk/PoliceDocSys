"""GUI pilot：備份還原一條龍（列清單 → 選一份 → 驗檔與擋門 → 覆蓋 → 善後）。

還原會**整個覆蓋現有資料庫**，是僅次於跨年度重置的破壞性操作。既有測試只到底層
（`verify_backup`／`restore_backup` 在 `test_db_backup.py`），**面板那層完全沒有
測試**——權限保底、驗檔擋下、他機使用中擋下、確認框、還原後寫稽核、重啟，
全部沒人看過。本檔補的就是這一層。

最要緊的一條是「壞檔不得蓋掉本體」：讓損毀或非資料庫的檔案還原成功，等於資料
直接沒了，而且當下不會有任何錯誤——要等下次開啟才會發現。

替身（其餘全用真的）：確認框與提示框、重啟 callback、選檔的原生視窗。

只建備份還原面板一個元件、不建 `DocumentManager`，故留在 qt 層、不需行程隔離
（PITFALLS TST-5）。
"""

import os
import shutil
import sqlite3
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import pytest
except ModuleNotFoundError as exc:  # 讓 unittest discover 在缺 pytest 時記為「跳過」而非 ImportError
    if exc.name != "pytest":
        raise
    import unittest

    raise unittest.SkipTest("需 pytest/pytest-qt，請以 pytest 執行此檔")

from lib import app_lock
from lib.auth_manager import AuthManager
from lib.db_backup import (
    PRERESTORE_KEEP, PRERESTORE_PREFIX, backup_dir, daily_filename)
from lib.db_schema import applySchema
from lib.db_seed import seedFreshDb
import ui_utils.backup_restore_panel as panel_module
from ui_utils.backup_restore_panel import BackupRestorePanel


LIVE_SUBJECT = "還原前的現有資料"
BACKUP_SUBJECT = "備份裡的舊資料"


@pytest.fixture(scope="session")
def _db_template(tmp_path_factory):
    """套完 schema 與種子的空殼，之後各測試以複製檔案取代重建（本檔每支測試要兩個
    資料庫，重建 schema 是這裡最大的固定成本）。"""
    path = tmp_path_factory.mktemp("template") / "template.db"
    conn = sqlite3.connect(path)
    applySchema(conn)
    seedFreshDb(conn)
    conn.commit()
    conn.close()
    return str(path)


def _make_db(template, path, subject):
    shutil.copy2(template, path)
    conn = sqlite3.connect(path)
    conn.execute(
        "INSERT INTO Document_Criminal"
        "(doc_id,create_date,report_date,processor_id,subject_summary,is_reported)"
        " VALUES(?,?,?,?,?,?)",
        ("1", "2026-08-01", "2026-08-01", "P01", subject, 0))
    conn.commit()
    conn.close()


@pytest.fixture
def env(tmp_path, _db_template):
    """現行資料庫 ＋ backups/ 內一份每日備份，兩者內容刻意不同以便辨認誰覆蓋誰。"""
    db_path = tmp_path / "dbfile.db"
    _make_db(_db_template, db_path, LIVE_SUBJECT)

    bdir = backup_dir(str(db_path))
    os.makedirs(bdir, exist_ok=True)
    daily = os.path.join(bdir, daily_filename(datetime(2026, 8, 1)))
    _make_db(_db_template, daily, BACKUP_SUBJECT)
    return {"db": str(db_path), "dir": str(tmp_path), "daily": daily}


@pytest.fixture(autouse=True)
def _admin_role():
    """還原僅管理身分可為。"""
    AuthManager.instance()._role = "admin"
    yield
    AuthManager.instance()._role = "user"


@pytest.fixture
def quiet_dialogs(monkeypatch):
    """攔掉所有 modal：確認框固定回「確定」，其餘只記標題供斷言。"""
    seen = {"confirm": [], "warning": [], "critical": [], "info": []}
    monkeypatch.setattr(
        panel_module, "confirmBox",
        lambda title, text=None, **kw: (seen["confirm"].append(title), True)[1])
    for name, bucket in (("msgWarning", "warning"), ("msgCritical", "critical"),
                         ("msgInfo", "info")):
        monkeypatch.setattr(
            panel_module, name,
            lambda title, text=None, *a, _b=bucket, **kw: seen[_b].append(title))
    return seen


def _make_panel(qtbot, env):
    restarts = []
    panel = BackupRestorePanel(env["db"], lambda: restarts.append(1))
    qtbot.addWidget(panel)
    return panel, restarts


def _subject(db_path):
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT subject_summary FROM Document_Criminal WHERE doc_id='1'"
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _prerestore_files(env):
    return sorted(f for f in os.listdir(env["dir"])
                  if f.startswith(PRERESTORE_PREFIX) and f.endswith(".db"))


def _audit_actions(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute(
            "SELECT detail FROM Audit_Log WHERE action='CONFIG'").fetchall()]
    finally:
        conn.close()


def _write_foreign_lock(env, *, fresh=True):
    """寫一個「別台電腦持有」的鎖檔；fresh=True 代表心跳仍新（＝真的在用）。"""
    now = datetime.now()
    hb = now if fresh else now - timedelta(days=1)
    app_lock.write_lock(
        app_lock.lock_file_path(env["db"]),
        machine="OTHER-PC", user="別的承辦人",
        opened_iso=now.isoformat(timespec="seconds"),
        heartbeat_iso=hb.isoformat(timespec="seconds"),
        pid=999999)


# ── 測試 ──────────────────────────────────────────────────────

def test_list_shows_every_backup_source_and_previews_selection(qtbot, env):
    """清單要涵蓋三種來源（主備份／重置留底／還原前留底），選取後顯示內容摘要。"""
    with open(os.path.join(env["dir"], "dbfile_backup_20260101_000000.db"), "wb") as fh:
        fh.write(b"x")                       # 重置留底
    with open(os.path.join(env["dir"], "dbfile_prerestore_20260102_000000.db"), "wb") as fh:
        fh.write(b"x")                       # 還原前留底
    panel, _ = _make_panel(qtbot, env)

    sources = {e["source"] for e in panel._entries}
    assert {"主備份", "重置留底", "還原前留底"} <= sources
    assert panel.btn_restore.isEnabled() is False, "未選取前不得可按還原"

    daily_row = next(i for i, e in enumerate(panel._entries)
                     if e["path"] == env["daily"])
    panel.table.selectRow(daily_row)

    assert panel.btn_restore.isEnabled() is True
    assert panel.lbl_preview.text(), "選取後應顯示該份備份的內容摘要"


def test_restore_replaces_db_keeps_prerestore_copy_writes_audit_and_restarts(
        qtbot, env, quiet_dialogs):
    """成功還原：資料庫被換成備份的內容、覆蓋前留底真的產生、寫稽核、重啟一次。"""
    panel, restarts = _make_panel(qtbot, env)
    assert _subject(env["db"]) == LIVE_SUBJECT

    panel._doRestore(env["daily"])

    assert _subject(env["db"]) == BACKUP_SUBJECT, "資料庫應被備份內容取代"
    kept = _prerestore_files(env)
    assert len(kept) == 1, "覆蓋前必須留下一份現有資料庫"
    assert _subject(os.path.join(env["dir"], kept[0])) == LIVE_SUBJECT, \
        "留底內容應是還原前的資料"
    assert any("還原" in d for d in _audit_actions(env["db"]))
    assert quiet_dialogs["confirm"] == ["還原備份"]
    assert quiet_dialogs["info"] == ["還原完成"]
    assert restarts == [1]


def test_corrupt_source_is_rejected_before_touching_anything(
        qtbot, env, quiet_dialogs):
    """損毀／非資料庫檔一律擋下：本體不動、不留底、不重啟。

    這是本檔最要緊的一條——壞檔還原成功等於資料直接沒了，而且當下沒有任何
    錯誤訊息，要等下次開啟才會發現。"""
    bad = os.path.join(env["dir"], "not-a-database.db")
    with open(bad, "wb") as fh:
        fh.write(b"not a sqlite database at all")
    panel, restarts = _make_panel(qtbot, env)

    panel._doRestore(bad)

    assert quiet_dialogs["warning"] == ["無法還原"]
    assert not quiet_dialogs["confirm"], "驗檔未過就不該問使用者"
    assert _subject(env["db"]) == LIVE_SUBJECT
    assert _prerestore_files(env) == []
    assert restarts == []


def test_missing_source_is_rejected(qtbot, env, quiet_dialogs):
    """來源不存在（例如備份被移走）→ 擋下，本體不動。"""
    panel, restarts = _make_panel(qtbot, env)

    panel._doRestore(os.path.join(env["dir"], "不存在的備份.db"))

    assert quiet_dialogs["warning"] == ["無法還原"]
    assert _subject(env["db"]) == LIVE_SUBJECT
    assert restarts == []


def test_other_machine_in_use_blocks_restore(qtbot, env, quiet_dialogs):
    """他機正在使用（鎖檔屬別台且心跳仍新）→ 擋下並提示，本體不動。"""
    _write_foreign_lock(env, fresh=True)
    panel, restarts = _make_panel(qtbot, env)

    panel._doRestore(env["daily"])

    assert quiet_dialogs["warning"] == ["無法還原"]
    assert not quiet_dialogs["confirm"]
    assert _subject(env["db"]) == LIVE_SUBJECT
    assert _prerestore_files(env) == []
    assert restarts == []


def test_stale_lock_does_not_block_restore(qtbot, env, quiet_dialogs):
    """鎖檔心跳已過期（程式沒正常關掉留下的殘骸）→ 不得擋住還原。
    這道判斷只是勸導層，過度嚴格會讓使用者永遠還原不了。"""
    _write_foreign_lock(env, fresh=False)
    panel, restarts = _make_panel(qtbot, env)

    panel._doRestore(env["daily"])

    assert _subject(env["db"]) == BACKUP_SUBJECT
    assert restarts == [1]


def test_cancelling_confirm_does_nothing(qtbot, env, quiet_dialogs, monkeypatch):
    """確認框取消 → 不覆蓋、不留底、不重啟。"""
    monkeypatch.setattr(panel_module, "confirmBox",
                        lambda title, text=None, **kw: False)
    panel, restarts = _make_panel(qtbot, env)

    panel._doRestore(env["daily"])

    assert _subject(env["db"]) == LIVE_SUBJECT
    assert _prerestore_files(env) == []
    assert restarts == []


def test_non_admin_direct_call_has_no_side_effect(qtbot, env, quiet_dialogs):
    """面板僅管理身分可見，但仍要有保底：非管理身分直接呼叫完全無副作用。"""
    panel, restarts = _make_panel(qtbot, env)
    AuthManager.instance()._role = "archive"

    panel._doRestore(env["daily"])

    assert _subject(env["db"]) == LIVE_SUBJECT
    assert _prerestore_files(env) == []
    assert not quiet_dialogs["confirm"] and not quiet_dialogs["warning"]
    assert restarts == []


def test_prerestore_copies_are_pruned_to_keep_limit(qtbot, env, quiet_dialogs):
    """還原前留底只保留最新 PRERESTORE_KEEP 份，最舊的會被修剪。"""
    stale = [f"{PRERESTORE_PREFIX}2020010{i}_000000.db"
             for i in range(1, PRERESTORE_KEEP + 2)]
    for name in stale:
        with open(os.path.join(env["dir"], name), "wb") as fh:
            fh.write(b"old")
    panel, _ = _make_panel(qtbot, env)

    panel._doRestore(env["daily"])

    kept = _prerestore_files(env)
    assert len(kept) == PRERESTORE_KEEP
    assert stale[0] not in kept, "最舊的留底應被修剪"


def test_pick_other_location_goes_through_the_same_restore_path(
        qtbot, env, quiet_dialogs, monkeypatch):
    """「從其他位置選擇備份檔」與清單還原走同一條路（同樣驗檔、同樣留底）。"""
    monkeypatch.setattr(
        panel_module.QFileDialog, "getOpenFileName",
        staticmethod(lambda *a, **kw: (env["daily"], "")))
    panel, restarts = _make_panel(qtbot, env)

    panel._pickOther()

    assert _subject(env["db"]) == BACKUP_SUBJECT
    assert len(_prerestore_files(env)) == 1
    assert restarts == [1]
