"""GUI pilot：日期防呆真的接在六個送出點上，而且「取消」會中止寫入。

門檻本身由 `tests/test_date_guard.py` 驗（純邏輯）；本檔驗的是**接線**——防呆是否
真的擋在每個送出點之前、按「返回修正」是否真的一筆都不寫、按「確認無誤」是否照常
寫入，以及「同一欄位同一日期本次只問一次」。

事故背景：2026-08-04 某日發文日期年份被誤改成隔年，當天 12 筆有 8 筆寫成 2027，
簽收表只印得出前 4 筆。連續登錄時日期欄是共用的，錯一次就一路錯下去。

替身：只有確認框（離線 modal 會無限等待，PITFALLS TST-4）。
只建單一分頁、不建 `DocumentManager`，故留在 qt 層、不需行程隔離（PITFALLS TST-5）。
"""

import os
import shutil
import sqlite3

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

try:
    import pytest
except ModuleNotFoundError as exc:  # 讓 unittest discover 在缺 pytest 時記為「跳過」而非 ImportError
    if exc.name != "pytest":
        raise
    import unittest

    raise unittest.SkipTest("需 pytest/pytest-qt，請以 pytest 執行此檔")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QTabWidget, QWidget

from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from lib.db_seed import seedFreshDb
import ui_utils.date_guard as guard_module
from ui_utils.date_guard import resetConfirmedDates
import tabs.tab_report as report_module
import tabs.tab_reward as reward_module
from tabs.tab_report import TabReport
from tabs.tab_reward import TabReward


STAFF_ID = "P01"
BAD_YEAR = QDate.currentDate().addYears(1)      # 事故的形狀：年份被多加一年


@pytest.fixture(scope="session")
def _db_template(tmp_path_factory):
    path = tmp_path_factory.mktemp("guard-template") / "template.db"
    conn = sqlite3.connect(path)
    applySchema(conn)
    seedFreshDb(conn)
    conn.commit()
    conn.close()
    return str(path)


@pytest.fixture
def db_path(tmp_path, _db_template):
    path = tmp_path / "guard-pilot.db"
    shutil.copy2(_db_template, path)
    return str(path)


@pytest.fixture(autouse=True)
def _clean_state():
    """「本次只問一次」是模組層狀態，每支測試前後都要清乾淨，否則測試互相影響。"""
    AuthManager.instance()._role = "admin"
    resetConfirmedDates()
    yield
    resetConfirmedDates()
    AuthManager.instance()._role = "user"


@pytest.fixture
def prompts(monkeypatch):
    """記錄防呆確認框被叫了幾次；回傳值由 `answer` 決定（預設按「返回修正」）。"""
    seen = {"calls": [], "answer": False}

    def _confirm(title, text, **kw):
        seen["calls"].append(text)
        return seen["answer"]

    monkeypatch.setattr(guard_module, "confirmBox", _confirm)
    # 送出流程中其他 modal 一律靜音，避免離線卡住
    for module in (report_module, reward_module):
        for name in ("msgWarning", "msgCritical"):
            if hasattr(module, name):
                monkeypatch.setattr(module, name,
                                    lambda *a, **kw: None)
    return seen


def _host(qtbot):
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "頁")
    qtbot.addWidget(tabs)
    return tabs


def _report_tab(qtbot, db_path, *, report_date, occ_date="2026-08-01"):
    tab = TabReport(_host(qtbot), db_path)
    tab.setup(0)
    tab.type_tabbar.setCurrentIndex(0)
    tab.rpt_date.setDate(report_date)
    tab.rpt_sender.setCurrentIndex(tab.rpt_sender.findData(STAFF_ID))
    tab.crim_casetype.setCurrentIndex(tab.crim_casetype.findData("CT01"))
    tab.crim_processor.setCurrentIndex(tab.crim_processor.findData(STAFF_ID))
    tab.crim_subject.setText("防呆測試案由")
    tab.crim_occdate.setText(occ_date)
    return tab


def _count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


# ── 接線 ──────────────────────────────────────────────────────

def test_year_typo_prompts_and_cancel_writes_nothing(qtbot, db_path, prompts):
    """事故重現：年份被改成隔年 → 跳提示；按「返回修正」一筆都不能寫進去。"""
    tab = _report_tab(qtbot, db_path, report_date=BAD_YEAR)

    tab._submit()

    assert len(prompts["calls"]) == 1, "應跳出一次日期確認"
    assert "發文日期" in prompts["calls"][0]
    assert _count(db_path, "Document_Criminal") == 0, "取消後不得寫入"


def test_confirming_lets_the_submission_through(qtbot, db_path, prompts):
    """按「確認無誤」照常寫入——這是提示不是攔阻，跨年度作業仍要做得下去。"""
    prompts["answer"] = True
    tab = _report_tab(qtbot, db_path, report_date=BAD_YEAR)

    tab._submit()

    assert len(prompts["calls"]) == 1
    assert _count(db_path, "Document_Criminal") == 1


def test_today_does_not_prompt_at_all(qtbot, db_path, prompts):
    """正常情境（今天）完全不打擾。"""
    tab = _report_tab(qtbot, db_path, report_date=QDate.currentDate())

    tab._submit()

    assert prompts["calls"] == []
    assert _count(db_path, "Document_Criminal") == 1


def test_same_date_only_asks_once_across_consecutive_entries(
        qtbot, db_path, prompts):
    """連續登錄十幾筆時每筆都問會被無視，反而失去提醒效果：
    同一欄位＋同一日期本次只問一次。"""
    prompts["answer"] = True
    tab = _report_tab(qtbot, db_path, report_date=BAD_YEAR)

    tab._submit()
    tab.crim_casetype.setCurrentIndex(tab.crim_casetype.findData("CT01"))
    tab.crim_processor.setCurrentIndex(tab.crim_processor.findData(STAFF_ID))
    tab.crim_subject.setText("第二筆")
    tab.crim_occdate.setText("2026-08-01")
    tab._submit()

    assert len(prompts["calls"]) == 1, "同一日期不該問第二次"
    assert _count(db_path, "Document_Criminal") == 2


def test_occurrence_date_in_the_future_prompts(qtbot, db_path, prompts):
    """查獲日期填到未來 → 提示；發文日期是今天，故這次只會為查獲日期問一次。"""
    tab = _report_tab(
        qtbot, db_path, report_date=QDate.currentDate(),
        occ_date=QDate.currentDate().addDays(30).toString("yyyy-MM-dd"))

    tab._submit()

    assert len(prompts["calls"]) == 1
    assert "查獲日期" in prompts["calls"][0]
    assert _count(db_path, "Document_Criminal") == 0


def test_occurrence_date_in_the_past_never_prompts(qtbot, db_path, prompts):
    """案件受理常在數週前，往前不得打擾。"""
    tab = _report_tab(
        qtbot, db_path, report_date=QDate.currentDate(),
        occ_date=QDate.currentDate().addDays(-90).toString("yyyy-MM-dd"))

    tab._submit()

    assert prompts["calls"] == []
    assert _count(db_path, "Document_Criminal") == 1


def test_reward_entry_is_guarded_too(qtbot, db_path, prompts):
    """敘獎登錄同樣是連續登錄共用日期欄，必須一起防。"""
    tab = TabReward(_host(qtbot), db_path)
    tab.setup(0)
    tab.reward_date.setDate(BAD_YEAR)
    tab.reward_sender.setCurrentIndex(tab.reward_sender.findData(STAFF_ID))
    tab.reward_reason.setText("防呆測試事由")
    tab.reward_recipients.setCurrentText("王小明")

    tab._submit()

    assert len(prompts["calls"]) == 1
    assert _count(db_path, "Document_Reward") == 0


def test_every_entry_point_calls_the_guard():
    """六個送出點都要接上——漏接一處就等於那條流程沒有防呆，而且不會有任何徵兆。

    以原始碼比對而非逐條驅動 UI：接線與否是靜態事實，逐條建分頁只是重複成本。"""
    import io
    expected = {
        "tabs/tab_report.py": 3,        # 刑案發文日期＋查獲日期、一般發文日期
        "tabs/tab_reward.py": 1,
        "tabs/tab_receive.py": 1,
        "tabs/tab_dispatch.py": 1,
        "ui_utils/settle_dialog.py": 1,
    }
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel, times in expected.items():
        src = io.open(os.path.join(root, rel), encoding="utf-8").read()
        assert "confirmDateGap" in src, f"{rel} 未匯入日期防呆"
        assert src.count("confirmDateGap(") == times, (
            f"{rel} 的 confirmDateGap 呼叫數應為 {times}")
