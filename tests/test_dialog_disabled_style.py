# -*- coding: utf-8 -*-
"""編輯彈窗裡「被停用的輸入欄」必須看得出來是反灰的（以實際算繪的像素驗證）。

## 為什麼要用算繪像素驗，而不是讀 styleSheet 字串

這條雷的本質是 **Qt 樣式表的覆蓋順序**：彈窗自帶的區域 QSS 會蓋掉全域公版
`lib/theme.py` 的 `:disabled` 規則。讀字串只能看到「有沒有寫這條規則」，
看不到「最後誰贏」——而輸掉的那一方正是 bug 的成因。故本檔一律 `grab()` 成
影像後取樣像素，問的是使用者眼睛真正看到的顏色。

## 背景（2026-08-07）

現場回報：發文結算模式下，一般使用者開刑案／一般陳報的修改視窗，陳報日期與
發文人員**確實被鎖住了，但長得跟可編輯的欄位一模一樣**。根因是彈窗自帶的
`_CRIMGEN_QSS` 又寫了一份輸入元件樣式（沒有 `:disabled` 變體），把公版的反灰
整個蓋掉；`TaskEditDialog` 還有第二份同樣的複製品。

⚠️ 修正過程中踩到第二層：光刪掉輸入元件那段還不夠，那份區域樣式同時用
`QWidget` 這種寬選擇器把彈窗內**所有容器**塗白；一拿掉，容器就變成一塊一塊的
灰、白底彈窗上到處是色塊（維護者截圖回報「醜爆了」）。故最後整份移除，彈窗
底色回歸公版的 `#f2f2f7`，與程式其他視窗一致。

⚠️ **這支測試同時釘兩件事**：①停用欄位看得出反灰 ②彈窗內不會出現色塊。
第二件是上一版漏掉的——當時只驗欄位顏色，測試全綠但畫面是壞的。
紅了請去改 `lib/theme.py`，**不要在彈窗內補區域樣式**。
"""
import os
import re
import sqlite3
import tempfile
import unittest
from collections import Counter

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QDialog

from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from lib.db_seed import seedFreshDb
from lib.theme import APPLE_STYLE

# 比對規則時要先去掉 CSS 註解：註解裡會提到「不要把某條加回來」的選擇器名稱，
# 直接對整份字串做 assertNotIn 會被自己的說明文字誤判。
STYLE_RULES = re.sub(r"/\*.*?\*/", "", APPLE_STYLE, flags=re.S)
from ui_utils.edit_dialog import (
    CriminalEditDialog, GeneralEditDialog, TaskEditDialog,
)

_app = QApplication.instance() or QApplication([])

# 公版 `lib/theme.py` 的停用色（灰底）。⚠️ 不要在本檔另寫一組色碼——
# 這裡刻意從 theme 的實際值抄一份常數只是為了斷言可讀，改色時兩邊要一起改，
# 由 test_matches_theme_tokens 釘住兩者一致。
THEME_WINDOW_BG = (0xF2, 0xF2, 0xF7)   # 公版的主視窗／訊息框底色
DIALOG_BG = (0xFF, 0xFF, 0xFF)         # 公版「彈窗公版」區塊的彈窗底色
DISABLED_BG = (0xE5, 0xE5, 0xEA)
ENABLED_BG = (0xFF, 0xFF, 0xFF)
NORMAL_TEXT = (0x1C, 0x1C, 0x1E)
DISABLED_TEXT = (0xAE, 0xAE, 0xB2)
DANGER_ENABLED = (0xE7, 0x4C, 0x3C)    # 救援視窗還原鈕（#danger）可用時的紅


def _corner_color(widget):
    """取彈窗左上角內縮 3px 的像素＝真正的「底色」。

    ⚠️ 底色不能用眾數判斷：彈窗裡有六個白色輸入框，面積加起來可能超過背景，
    眾數會變成白的。角落落在版面邊距內，必定是背景。
    """
    image = widget.grab().toImage()
    c = image.pixelColor(3, 3)
    return (c.red(), c.green(), c.blue())


def _dominant_color(widget):
    """算繪該元件並回傳面積最大的顏色（RGB tuple）。

    取眾數而非單點：單點可能落在文字、邊框或下拉箭頭上。停用與否的差別是
    **整片底色**，眾數最穩。
    """
    image = widget.grab().toImage()
    counter = Counter()
    for y in range(0, image.height()):
        for x in range(0, image.width()):
            c = image.pixelColor(x, y)
            counter[(c.red(), c.green(), c.blue())] += 1
    return counter.most_common(1)[0][0]


class _DisabledStyleBase(unittest.TestCase):
    """⚠️ 測試環境必須套上全域公版樣式。

    正式程式在 `main.py:707` 對 `QApplication` 套 `APPLE_STYLE`；測試的
    `QApplication` 預設沒有樣式表，不套的話公版的 `:disabled` 根本不存在，
    這支測試會變成永遠綠的假保證。
    """

    @classmethod
    def setUpClass(cls):
        cls._prev_style = _app.styleSheet()
        _app.setStyleSheet(APPLE_STYLE)

    @classmethod
    def tearDownClass(cls):
        _app.setStyleSheet(cls._prev_style)

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        seedFreshDb(conn)
        conn.execute(
            "INSERT OR REPLACE INTO Ref_Personnel"
            "(staff_id,staff_name,is_active,sort_order) VALUES('P001','甲員',1,1)")
        self._insertRow(conn)
        conn.commit()
        conn.close()
        AuthManager.instance()._role = "user"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _insertRow(self, conn):
        raise NotImplementedError

    def assertLooksDisabled(self, widget, label):
        widget.setEnabled(False)
        self.assertEqual(
            _dominant_color(widget), DISABLED_BG,
            f"{label}：停用後看起來仍是可編輯的樣子（公版反灰被區域 QSS 蓋掉了）")

    def assertLooksEnabled(self, widget, label):
        widget.setEnabled(True)
        self.assertEqual(
            _dominant_color(widget), ENABLED_BG,
            f"{label}：可編輯狀態的底色不是白的")


class TestThemeTokens(unittest.TestCase):
    def test_matches_theme_tokens(self):
        """本檔的色碼常數必須與公版一致（改色時不會只改一邊）。"""
        self.assertIn("background-color: #e5e5ea", APPLE_STYLE)
        self.assertIn("QLineEdit:disabled", APPLE_STYLE)
        self.assertIn("QComboBox:disabled", APPLE_STYLE)
        self.assertIn("QDateEdit:disabled", APPLE_STYLE)

    def test_edit_dialog_module_has_no_shared_local_qss(self):
        """⚠️ `_CRIMGEN_QSS` 已整份移除，不得復活。"""
        import ui_utils.edit_dialog as ed
        self.assertFalse(
            hasattr(ed, "_CRIMGEN_QSS"),
            "_CRIMGEN_QSS 又回來了；彈窗外觀請改 lib/theme.py（公版唯一來源）")

    def test_window_background_rules_are_in_the_right_order(self):
        """⚠️ 公版裡 `QWidget { transparent }` 必須寫在視窗底色**之前**。

        兩者特異度相同（各一個型別選擇器），Qt 由後者勝。順序寫反的話
        `transparent` 會把 `QDialog` 的底色中和掉，視窗變透明、在 Windows 上
        渲染成整塊黑。2026-08-07 實測踩過。
        """
        widget_rule = APPLE_STYLE.index("QWidget {\n    background-color: transparent;")
        window_rule = APPLE_STYLE.index("QMainWindow, QDialog {")
        self.assertLess(
            widget_rule, window_rule,
            "QWidget 透明那條必須在視窗底色之前，否則視窗底色會被中和成透明（全黑）")

    def test_dialog_template_block_exists(self):
        """⚠️ 彈窗公版區塊：還原 v1.2.10 外觀，但只此一份、且限定 QDialog。

        它取代了六個彈窗各自帶的那份區域 QSS（其中五份漏 `:disabled`，造成
        「欄位鎖住了卻看不出來」）。⚠️ 範圍必須留在 `QDialog`——套到全域會讓
        分頁沒鎖死高度的欄位矮 4px、鎖死的不動，同頁高低不齊（LAY-6）。
        """
        self.assertIn("QDialog QLineEdit", STYLE_RULES)
        self.assertIn("QDialog {\n    background-color: #ffffff;", STYLE_RULES)

    def test_dialog_block_declares_no_disabled_state(self):
        """⚠️ 彈窗公版**不得**宣告停用態。

        `QLineEdit:disabled` 帶偽狀態、特異度高於這裡的兩個型別選擇器，公版的
        反灰本來就生效；在此「補齊」反而會把反灰鎖死成固定值，重演 QSS-8。
        """
        selectors = [sel for sel, _ in
                     re.findall(r"([^{}]+)\{([^{}]*)\}", STYLE_RULES)
                     if "QDialog " in sel]
        self.assertTrue(selectors, "找不到彈窗公版的規則，區塊被刪了？")
        for sel in selectors:
            self.assertNotIn(
                ":disabled", sel,
                f"彈窗公版出現 `{sel.strip()}`；停用態交給全域規則處理")

    def test_message_box_keeps_window_background(self):
        """訊息框是 QDialog 子類，但底色要維持灰（與 v1.2.10 一致）。

        靠的是 `QMessageBox` 規則排在彈窗公版**之後**、同特異度後者勝；
        把彈窗公版往後搬會讓訊息框一起變白。
        """
        self.assertLess(STYLE_RULES.index("QDialog QLineEdit"),
                        STYLE_RULES.index("QMessageBox {"),
                        "彈窗公版必須排在 QMessageBox 之前")

    def test_no_container_patch_rule(self):
        """⚠️ `QDialog > QWidget` 那條補丁不得復活。

        它會連 `QLineEdit`／`QComboBox`／`QDateEdit` 一起匹配（都是 QWidget），
        且特異度高於單獨的 `QLineEdit`，於是輸入框白底被容器灰底蓋掉——
        現場回報的「停用了卻看不出來」就是它的下游症狀。
        """
        self.assertNotIn(
            "QDialog > QWidget", STYLE_RULES,
            "容器補丁又回來了；視窗底色請靠上一條測試釘住的順序解決")


class TestTemplateCoversEveryDisabledState(unittest.TestCase):
    """⚠️ 2026-08-07 全面稽核：區域 QSS 蓋掉公版偽狀態的地方逐一修掉後，
    以真正的程式路徑釘住結果。這幾條都是「停用了卻看不出來」的同一個病。

    紅了不要在區域樣式裡補色碼——先確認公版有沒有那個狀態，沒有就補公版。
    """

    @classmethod
    def setUpClass(cls):
        cls._prev = _app.styleSheet()
        _app.setStyleSheet(APPLE_STYLE)

    @classmethod
    def tearDownClass(cls):
        _app.setStyleSheet(cls._prev)

    def _text_counts(self, w):
        image = w.grab().toImage()
        counter = Counter()
        for y in range(image.height()):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                counter[(c.red(), c.green(), c.blue())] += 1
        return counter

    def test_template_has_generic_disabled_button(self):
        """⚠️ 公版原本**只有** hover／pressed，沒有通用 `QPushButton:disabled`，
        每支自訂按鈕都得自己記得補（PITFALLS QSS-4 長年靠人記得）。已補上。"""
        self.assertIn("QPushButton:disabled", STYLE_RULES)

    def test_plain_button_greys_out(self):
        from PySide6.QtWidgets import QPushButton, QVBoxLayout
        dlg = QDialog(); QVBoxLayout(dlg)
        btn = QPushButton("確認發文"); dlg.layout().addWidget(btn)
        self.addCleanup(dlg.deleteLater)
        dlg.show(); btn.setEnabled(False); _app.processEvents()
        self.assertEqual(_dominant_color(btn), DISABLED_BG,
                         "一般按鈕停用後沒有反灰")

    def test_radio_text_greys_out(self):
        """`RADIO_STYLE` 已移除（與公版逐項相同的複製品，但漏了 `:disabled`）。

        原症狀：唯讀模式下陳報頁「輸入框灰了、按鈕灰了，選項文字還是黑的」。
        """
        from PySide6.QtWidgets import QRadioButton, QVBoxLayout
        dlg = QDialog(); QVBoxLayout(dlg)
        rb = QRadioButton("現行犯"); dlg.layout().addWidget(rb)
        self.addCleanup(dlg.deleteLater)
        dlg.show(); rb.setEnabled(False); _app.processEvents()
        c = self._text_counts(rb)
        self.assertGreater(c[DISABLED_TEXT], c[NORMAL_TEXT],
                           "radio 停用後文字沒有變灰")

    def test_combo_hint_does_not_shadow_disabled_text(self):
        """`attachComboHint` 設在 combo 元件上，必須連 `:disabled` 一起寫。

        原症狀：唯讀模式下陳報頁案類欄的文字不會變灰。
        """
        from PySide6.QtWidgets import QVBoxLayout
        from ui_utils.widgets import attachComboHint
        dlg = QDialog(); QVBoxLayout(dlg)
        combo = QComboBox(); combo.setEditable(True)
        combo.addItem("", None); combo.addItem("302妨害自由", "CT01")
        dlg.layout().addWidget(combo)
        attachComboHint(combo, "輸入或下拉選擇")
        combo.setCurrentIndex(1)
        self.addCleanup(dlg.deleteLater)
        dlg.show(); combo.setEnabled(False); _app.processEvents()
        c = self._text_counts(combo)
        self.assertGreater(c[DISABLED_TEXT], c[NORMAL_TEXT],
                           "案類欄停用後文字沒有變灰")

    def test_rescue_dialog_password_field_greys_out(self):
        """⚠️ 本輪唯一「使用者真的會遇到」的那條。

        救援視窗在資料庫損毀時出現；沒有可用備份時 `_updateButtons` 會停用密碼欄
        與還原鈕。原本該視窗自帶的 QSS 蓋掉公版反灰，密碼欄看起來可用卻打不動
        ——在使用者本來就慌的時機給錯誤提示，代價最高。
        """
        import tempfile
        from ui_utils.rescue_dialog import RescueDialog
        fd, db = tempfile.mkstemp(suffix=".db"); os.close(fd)
        self.addCleanup(lambda: os.remove(db))
        dlg = RescueDialog(db)
        self.addCleanup(dlg.deleteLater)
        dlg.show()
        dlg._path = None          # 明確重現「找不到可用備份」
        dlg._updateButtons()
        _app.processEvents()
        self.assertFalse(dlg.w_pw.isEnabled())
        self.assertEqual(_dominant_color(dlg.w_pw), DISABLED_BG,
                         "救援視窗密碼欄停用後沒有反灰")
        # 還原鈕走自己的 `#danger:disabled`（紅調灰），不是通用灰——這是刻意的
        self.assertNotEqual(_dominant_color(dlg.btn_restore), DANGER_ENABLED,
                            "還原鈕停用後外觀沒有變化")


class TestDialogsCarryNoLocalStyleSheet(_DisabledStyleBase):
    """六個彈窗一律不得自帶 stylesheet（外觀全部交給公版）。"""

    def _insertRow(self, conn):
        conn.execute(
            "INSERT INTO Document_Task"
            "(doc_id,receive_date,receive_id,dept_id,subject,processor_id) "
            "VALUES('1','2026-08-01','P001','D01','原主旨','P001')")

    def test_task_dialog_sets_no_stylesheet(self):
        dlg = TaskEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        self.assertEqual(
            dlg.styleSheet(), "",
            "彈窗又自帶區域樣式了；外觀請改 lib/theme.py")

    def test_no_patchy_containers(self):
        """⚠️ 彈窗內的容器不得與彈窗本身不同色（不能一塊一塊的）。

        上一版就是敗在這裡：拿掉區域樣式裡的輸入元件那段之後，容器改吃公版的
        `#f2f2f7`，在當時仍是白底的彈窗上變成一塊塊灰色。當時的測試只驗欄位
        顏色，全綠但畫面是壞的。

        ⚠️ 這裡整個彈窗算繪一次再看，不逐一 grab 子容器：容器的底色是
        `transparent`（靠父層畫在後面），單獨 grab 會得到純黑，那是取樣手法的
        假象、不是使用者看到的畫面。
        """
        dlg = TaskEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        dlg.show()
        _app.processEvents()

        # 彈窗底色由公版的「彈窗公版」區塊提供（白）；壞掉那版是白底彈窗
        # ＋灰色容器色塊，容器色會讓下面的面積檢查抓到。
        self.assertEqual(
            _corner_color(dlg), DIALOG_BG,
            "彈窗底色不是公版指定的白；八成又自帶區域樣式了")

        # 容器不得與底色不同：把整張影像的顏色分佈拿出來，佔比 >3% 的顏色
        # 只允許是「底色、輸入框白、停用灰」三種。壞掉那版的灰色容器色塊
        # 會讓 #f2f2f7 以外的大面積色出現。
        image = dlg.grab().toImage()
        total = image.width() * image.height()
        counter = Counter()
        for y in range(image.height()):
            for x in range(image.width()):
                c = image.pixelColor(x, y)
                counter[(c.red(), c.green(), c.blue())] += 1
        allowed = {DIALOG_BG, ENABLED_BG, DISABLED_BG}
        big = {col for col, n in counter.items() if n / total > 0.03}
        self.assertTrue(
            big <= allowed,
            f"彈窗出現非預期的大面積色塊：{sorted(big - allowed)}")


class TestCriminalDialogDisabledStyle(_DisabledStyleBase):
    def _insertRow(self, conn):
        conn.execute(
            "INSERT INTO Document_Criminal"
            "(doc_id,create_date,report_date,sender_id,case_type,case_status,"
            " processor_id,subject_summary,occurrence_date) "
            "VALUES('1','2026-08-01',NULL,NULL,'CT01','CS01','P001',"
            "'原案由','2026-07-30')")

    def test_report_fields_look_disabled_in_settle_mode(self):
        """發文結算模式＋一般使用者：陳報日期與發文人員必須看得出被鎖住。

        這正是現場回報的情境（`_lockReportFieldsIfSelfService`）。
        """
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                     "VALUES('report_mode_crim','1')")
        conn.commit()
        conn.close()
        dlg = CriminalEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        dlg.show()

        self.assertFalse(dlg.w_report_date.isEnabled(), "陳報日期應被鎖住")
        self.assertFalse(dlg.w_sender.isEnabled(), "發文人員應被鎖住")
        self.assertEqual(_dominant_color(dlg.w_report_date), DISABLED_BG,
                         "陳報日期鎖住了卻看不出來")
        self.assertEqual(_dominant_color(dlg.w_sender), DISABLED_BG,
                         "發文人員鎖住了卻看不出來")

    def test_enabled_and_disabled_are_visually_different(self):
        """反證：同一個欄位在兩種狀態下算繪出來必須不同色。

        少了這條，上面那些斷言可能只是「兩種狀態剛好都等於灰」。
        """
        dlg = CriminalEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        dlg.show()
        self.assertLooksEnabled(dlg.w_subject, "陳報主旨")
        self.assertLooksDisabled(dlg.w_subject, "陳報主旨")


class TestGeneralDialogDisabledStyle(_DisabledStyleBase):
    def _insertRow(self, conn):
        conn.execute(
            "INSERT INTO Document_General"
            "(doc_id,create_date,report_date,sender_id,dept_id,gen_cat_id,"
            " subject,processor_id) "
            "VALUES('1','2026-08-01',NULL,NULL,'D01','GC01','原主旨','P001')")

    def test_report_fields_look_disabled_in_settle_mode(self):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                     "VALUES('report_mode_gen','1')")
        conn.commit()
        conn.close()
        dlg = GeneralEditDialog(self.db, "1")
        self.addCleanup(dlg.deleteLater)
        dlg.show()

        self.assertFalse(dlg.w_report_date.isEnabled())
        self.assertFalse(dlg.w_sender.isEnabled())
        self.assertEqual(_dominant_color(dlg.w_report_date), DISABLED_BG,
                         "陳報日期鎖住了卻看不出來")
        self.assertEqual(_dominant_color(dlg.w_sender), DISABLED_BG,
                         "發文人員鎖住了卻看不出來")


class TestTaskDialogDisabledStyle(_DisabledStyleBase):
    """交辦單彈窗原本自帶**第二份**同樣的區域 QSS（那份有補 `:disabled`）。

    兩份都移除後改吃公版，行為必須維持不變——這支就是在釘「移除沒改壞它」。
    """

    def _insertRow(self, conn):
        conn.execute(
            "INSERT INTO Document_Task"
            "(doc_id,receive_date,receive_id,dept_id,subject,processor_id) "
            "VALUES('1','2026-08-01','P001','D01','原主旨','P001')")

    def test_restricted_fields_look_disabled(self):
        """一般使用者只能改承辦人，其餘欄位必須看得出被鎖住。"""
        dlg = TaskEditDialog(self.db, "1", restricted=True)
        self.addCleanup(dlg.deleteLater)
        dlg.show()

        self.assertFalse(dlg.w_subject.isEnabled())
        self.assertEqual(_dominant_color(dlg.w_subject), DISABLED_BG,
                         "交辦事由鎖住了卻看不出來")
        self.assertTrue(dlg.w_proc.isEnabled(), "承辦人應維持可改")
        self.assertEqual(_dominant_color(dlg.w_proc), ENABLED_BG,
                         "承辦人不該看起來像被鎖住")


if __name__ == "__main__":
    unittest.main()
