import ast
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QFile
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication


ROOT = Path(__file__).resolve().parents[1]


def _document_manager_tab_width_violations(source):
    """找出把 TabBar 尺寸資料回寫到主視窗寬度的資料流。"""
    tree = ast.parse(source)
    manager = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DocumentManager"
    )
    sinks = {"setMinimumWidth", "setFixedWidth", "resize"}
    metric_methods = {"tabBar", "tabSizeHint", "sizeHint"}
    violations = []

    def is_tab_metric(node, tainted):
        if isinstance(node, ast.Name):
            return node.id in tainted
        if isinstance(node, ast.Call):
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr in metric_methods):
                return is_tab_metric(node.func.value, tainted) or node.func.attr == "tabBar"
            return (is_tab_metric(node.func, tainted)
                    or any(is_tab_metric(arg, tainted) for arg in node.args)
                    or any(is_tab_metric(keyword.value, tainted)
                           for keyword in node.keywords))
        if isinstance(node, ast.Attribute):
            return is_tab_metric(node.value, tainted)
        if isinstance(node, ast.BinOp):
            return is_tab_metric(node.left, tainted) or is_tab_metric(node.right, tainted)
        if isinstance(node, (ast.Tuple, ast.List)):
            return any(is_tab_metric(item, tainted) for item in node.elts)
        return False

    def is_window_sink(call):
        func = call.func
        return (isinstance(func, ast.Attribute)
                and func.attr in sinks
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "window"
                and isinstance(func.value.value, ast.Name)
                and func.value.value.id == "self")

    for method in (node for node in manager.body if isinstance(node, ast.FunctionDef)):
        tainted = set()
        for node in ast.walk(method):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if is_tab_metric(value, tainted):
                    tainted.update(target.id for target in targets if isinstance(target, ast.Name))
            elif isinstance(node, ast.Call) and is_window_sink(node):
                if any(is_tab_metric(arg, tainted) for arg in node.args):
                    violations.append(method.name)
    return violations


class RewardIntegrationTests(unittest.TestCase):
    def test_document_tab_and_menu_mappings_are_complete(self):
        from lib.app_profile import FULL_PROFILE
        from main import DocumentManager, MainMenu

        # TAB_CLASSES 語意已改為「key → (模組路徑, 類別名)」座標，不再是類別物件本身
        # ——避免檔頭一次 import 全部 11 個分頁（見 tabs/__init__.py 延遲載入）。
        expected_tabs = {
            "assignment_issue": ("tabs.tab_dispatch", "TabDispatch"),
            "assignment_receive": ("tabs.tab_receive", "TabReceive"),
            "report": ("tabs.tab_report", "TabReport"),
            "reward": ("tabs.tab_reward", "TabReward"),
            "reward_issue": ("tabs.tab_reward_issue", "TabRewardIssue"),
            "ticket": ("tabs.tab_ticket", "TabTicket"),
            "print": ("tabs.tab_print", "TabPrint"),
            "browse": ("tabs.tab_dbbrowse", "TabDBBrowse"),
            "archive": ("tabs.tab_archive", "TabArchive"),
            "settings": ("tabs.tab_settings", "TabSettings"),
            "audit": ("tabs.tab_audit", "TabAudit"),
        }
        # 固定索引契約改以 FULL_PROFILE 驗證相同順序：完整版仍是同樣 11 個 Tab、同樣順序。
        self.assertEqual(DocumentManager.TAB_CLASSES, expected_tabs)
        self.assertEqual(tuple(DocumentManager.TAB_CLASSES), FULL_PROFILE.tab_keys)
        self.assertEqual(set(MainMenu.MENU_BUTTONS), set(FULL_PROFILE.menu_keys))
        self.assertEqual(MainMenu.MENU_BUTTONS["reward"], "btn_reward")
        self.assertEqual(MainMenu.MENU_BUTTONS["reward_issue"], "btn_reward_issue")
        self.assertEqual(MainMenu.MENU_BUTTONS["ticket"], "btn_ticket")
        self.assertEqual(MainMenu.ICON_MAP["reward"], ":/menu/reward.svg")
        self.assertEqual(MainMenu.ICON_MAP["reward_issue"], ":/menu/reward_issue.svg")
        self.assertEqual(MainMenu.ICON_MAP["ticket"], ":/menu/ticket.svg")

    def _menu_button_positions(self):
        menu = (ROOT / "layouts" / "main_menu.ui").read_text(encoding="utf-8")
        cells = re.findall(
            r'<item row="(\d+)" column="(\d+)">\s*<widget class="QToolButton" name="(btn_[^"]+)"',
            menu)
        return [(int(r), int(c), name) for r, c, name in cells]

    def test_ui_order_and_menu_grid(self):
        layout = (ROOT / "layouts" / "Layout1.ui").read_text(encoding="utf-8")
        names = re.findall(r'<widget class="QWidget" name="(tab_[^"]+)"', layout)
        self.assertEqual(names, [
            "tab_dispatch", "tab_receive", "tab_report", "tab_reward",
            "tab_reward_issue", "tab_ticket", "tab_print", "tab_dbbrowse",
            "tab_archive", "tab_settings", "tab_audit",
        ])

        positions = self._menu_button_positions()
        self.assertEqual(len(positions), 11)
        self.assertEqual(
            {(row, col) for row, col, _ in positions},
            {(0, c) for c in range(4)} | {(1, c) for c in range(4)} | {(2, c) for c in range(3)},
        )

        menu = (ROOT / "layouts" / "main_menu.ui").read_text(encoding="utf-8")
        for name in ("btn_reward", "btn_reward_issue", "btn_ticket"):
            block = re.search(rf'<widget class="QToolButton" name="{name}">(.*?)</widget>', menu, re.S).group(1)
            self.assertNotIn('name="icon"', block)

    def test_svg_resources_and_geometry(self):
        expected = {
            "menu_reward.svg": [
                'd="M6 3h8l4 4v13a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z"',
                'd="M14 3v4h4"',
                'd="M11.5 9l1.05 2.12 2.34.34-1.7 1.66.4 2.35-2.09-1.1-2.1 1.1.4-2.35-1.7-1.66 2.35-.34L11.5 9z"',
                'd="M8 18.5h7"',
            ],
        }
        for filename, fragments in expected.items():
            svg = (ROOT / "res" / "buttons" / filename).read_text(encoding="utf-8")
            self.assertNotIn("<text", svg)
            self.assertIn('viewBox="0 0 24 24"', svg)
            self.assertIn('fill="none"', svg)
            self.assertIn('stroke="#4977b1"', svg)
            self.assertIn('stroke-width="1.7"', svg)
            self.assertIn('stroke-linecap="round"', svg)
            self.assertIn('stroke-linejoin="round"', svg)
            for fragment in fragments:
                self.assertIn(fragment, svg)

        ticket_svg = (ROOT / "res" / "buttons" / "menu_reward_issue.svg").read_text(
            encoding="utf-8")
        self.assertIn('width="512" height="512" viewBox="0 0 512 512"', ticket_svg)
        self.assertIn('stroke="#4977b1"', ticket_svg)
        self.assertIn('stroke-width="36"', ticket_svg)
        self.assertIn('id="reward-glyph"', ticket_svg)
        self.assertIn('id="outbound-arrow"', ticket_svg)

        for filename in ("menu_ticket.svg",):
            svg = (ROOT / "res" / "buttons" / filename).read_text(encoding="utf-8")
            self.assertIn('viewBox="0 0 24 24"', svg)
            self.assertIn('fill="none"', svg)
            self.assertIn('stroke="#4977b1"', svg)
            self.assertIn('stroke-width="1.7"', svg)
            self.assertIn('stroke-linecap="round"', svg)
            self.assertIn('stroke-linejoin="round"', svg)

        from res import resources_rc  # noqa: F401
        for path in (":/menu/reward.svg", ":/menu/reward_issue.svg", ":/tab/reward.svg",
                     ":/menu/ticket.svg"):
            f = QFile(path)
            self.assertTrue(f.exists(), path)
            self.assertTrue(f.open(QFile.ReadOnly), path)
            self.assertGreater(f.size(), 0)
            self.assertFalse(QIcon(path).isNull(), path)

    def test_tab_overflow_default_width_1440_resizable_and_uses_qt_fallback(self):
        from ui_utils import loadUi

        app = QApplication.instance() or QApplication([])
        window = loadUi(str(ROOT / "layouts" / "Layout1.ui"))
        tab_widget = window.tabWidget
        self.assertEqual(window.width(), 1440)
        window.show()
        QApplication.processEvents()
        tab_widget.resize(200, tab_widget.height())
        bar = tab_widget.tabBar()
        required = max(bar.sizeHint().width(),
                       sum(bar.tabSizeHint(i).width() for i in range(bar.count())))
        self.assertGreater(required, tab_widget.width())
        self.assertTrue(bar.usesScrollButtons())

        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertEqual(_document_manager_tab_width_violations(source), [])

        mutated = source.replace(
            "\nclass MainMenu:",
            "\n\n    def _future_bad_tab_width(self):\n"
            "        bar = self.tab_widget.tabBar()\n"
            "        ideal_width = bar.sizeHint().width()\n"
            "        self.window.setMinimumWidth(bar.sizeHint().width())\n"
            "        self.window.setFixedWidth(ideal_width)\n"
            "        self.window.resize(ideal_width, 768)\n"
            "\nclass MainMenu:",
        )
        self.assertEqual(_document_manager_tab_width_violations(mutated),
                         ["_future_bad_tab_width"] * 3)
        window.close()
        del app

    def test_help_and_quickstart_indexes(self):
        from ui_utils.help_content import (HELP_PAGES, HELP_TIPS, HELP_TITLES,
                                           QUICKSTART, render_review_text)
        self.assertEqual(set(HELP_TITLES), set(range(11)))
        self.assertEqual(set(HELP_PAGES), set(range(11)))
        self.assertEqual(set(HELP_TIPS), set(range(11)))
        self.assertEqual(HELP_TITLES[4], "敘獎發文")
        self.assertEqual(HELP_TITLES[5], "罰單登錄")
        self.assertEqual(set(QUICKSTART), set(range(10)))
        source = (ROOT / "tools" / "gen_quickstart.py").read_text(encoding="utf-8")
        self.assertIn("PAGE1 = [0, 1, 2]", source)
        self.assertIn("PAGE2 = [3, 4, 5, 6]", source)
        self.assertIn("PAGE3 = [7, 8, 9]", source)
        self.assertIn("十個分頁速查", source)
        reward_help = render_review_text(3)
        issue_help = render_review_text(4)
        ticket_help = render_review_text(5)
        print_help = render_review_text(6)
        browse_help = render_review_text(7)
        settings_help = render_review_text(9)
        self.assertIn("登錄日期由系統自動填入今天", reward_help)
        self.assertNotIn("選擇發文日期", reward_help)
        self.assertNotIn("自助取號模式", reward_help)
        self.assertIn("請由「敘獎發文」頁", reward_help)
        self.assertIn("文號輸入框輸入編號", issue_help)
        self.assertIn("Enter", issue_help)
        self.assertIn("或按「輸入」", issue_help)
        self.assertNotIn("加入清單", issue_help)
        self.assertIn("輸入不存在的編號時，系統會提示找不到編號", issue_help)
        self.assertIn("輸入已刪除的編號時，系統會提示已被刪除", issue_help)
        self.assertIn("已發文", issue_help)
        self.assertIn("覆蓋", issue_help)
        self.assertIn("發文前已被刪除", issue_help)
        reward_issue_quickstart = "\n".join(QUICKSTART[4][1])
        self.assertIn("或「輸入」", reward_issue_quickstart)
        self.assertNotIn("加入清單", reward_issue_quickstart)
        # 模式名稱必須與設定頁 radio 的字面一致（使用者要照著去設定頁找選項），
        # 不可自創「發文者登錄模式」之類的同義詞。
        self.assertIn("送文者輸入模式", ticket_help)
        self.assertIn("自助取號模式", ticket_help)
        self.assertIn("開立人員", ticket_help)
        self.assertIn("取代", ticket_help)
        self.assertIn("清空", ticket_help)
        self.assertIn("罰單編號僅接受半形英文字母與數字", ticket_help)
        self.assertIn("不可還原", ticket_help)
        self.assertIn("文號（doc_id）直接作廢、不會再被使用；原罰單編號仍可重新登錄", ticket_help)
        ticket_quickstart = "\n".join(QUICKSTART[5][1] + QUICKSTART[5][2])
        self.assertIn("文號（doc_id）作廢不可再用，原罰單編號仍可重新登錄", ticket_quickstart)
        self.assertIn("本頁不設身分限制", ticket_help)
        self.assertIn("未發文的刑案／一般／罰單案件", print_help)
        self.assertNotIn("未發文的刑案／一般／敘獎案件", print_help)
        self.assertIn("三項皆為送文者輸入模式但仍有未發文殘留資料時", print_help)
        self.assertIn("三項皆為送文者輸入模式但仍有未發文殘留資料時",
                      QUICKSTART[6][2])
        self.assertEqual(set(HELP_TIPS[3]), {
            "btn_reward_submit", "btn_reward_clear", "reward_personnel_list",
        })
        self.assertNotIn("日期", HELP_TIPS[3]["btn_reward_submit"])
        self.assertEqual(set(HELP_TIPS[4]), {
            "btn_reward_input", "btn_reward_issue", "btn_reward_issue_clear",
        })
        self.assertEqual(set(HELP_TIPS[5]), {
            "ticket_add", "ticket_clear_issuer", "ticket_candidates_list",
        })
        # 罰單登錄同受陳報模式影響（Task 5 起），說明不可再宣稱「只影響刑案與一般」
        self.assertIn("自助取號模式影響刑案與一般陳報，以及罰單登錄", settings_help)
        self.assertIn("敘獎登錄與敘獎發文不受陳報模式影響", settings_help)
        self.assertNotIn("此模式同時涵蓋敘獎登錄", settings_help)
        self.assertNotIn("一併於結算時補齊", settings_help)
        self.assertIn("罰單簽收歸屬日一律依發文日期", settings_help)
        self.assertIn("與目前採送文者輸入模式或自助取號模式無關", settings_help)
        self.assertNotIn("歷史單據的列印結果會隨目前模式而不同", settings_help)
        self.assertIn("一般使用者唯讀", browse_help)
        self.assertIn("歸檔管理可修改、不可刪除", browse_help)
        self.assertIn("管理者可修改、可刪除", browse_help)

        from pypdf import PdfReader
        # docs/ 為 gitignored 產物（發版前 gen_quickstart 重產再上傳，見 DEVELOPER §7）；
        # 缺檔環境（fresh clone／CI）不驗頁數，避免依賴未入庫產物而 error。
        pdf_path = ROOT / "docs" / "Quick_Start.pdf"
        if pdf_path.exists():
            self.assertEqual(len(PdfReader(pdf_path).pages), 3)

        developer = (ROOT / "DEVELOPER.md").read_text(encoding="utf-8")
        self.assertNotIn("新 Tab 若有日期／發文欄位要接自助取號模式", developer)
        self.assertIn("只有陳報類輸入頁才依需求接 `report_input_mode`", developer)
        self.assertNotIn("SETTLE_META` reward", developer)
        self.assertNotIn("並對有 `reward_data_dirty` 屬性的 tab 設 True", developer)
        self.assertIn("成員為刑案／一般／罰單", developer)
        self.assertIn("罰單 meta 帶 `strict=True`，任一衝突即整批 rollback", developer)
        self.assertIn(
            "`input_lock_reward`／`input_lock_reward_issue`／`input_lock_ticket`",
            developer)
        self.assertIn(
            "`tab_reward_issue.handleIssue`(reward_issue／UPDATE)", developer)
        self.assertIn("`print_title_ticket`", developer)
        self.assertIn("| **罰單登錄**（`Document_Ticket`／`print_title_ticket`）", developer)
        self.assertIn("所有 CRUD 寫入唯一走 `lib/ticket_utils.py`；結算發文由 `SETTLE_META` 在共用 transaction 更新", developer)
        self.assertIn("五張公文主表", developer)
        release_section = developer.split("### 發布流程", 1)[1].split(
            "### 打包（spec 檔", 1)[0]
        gate_pos = release_section.index("**推送前完整 gate**")
        push_pos = release_section.index("**版號進版並推上去**")
        self.assertLess(gate_pos, push_pos)
        self.assertIn("三項全部通過後才可推送與建立 tag", release_section)
        self.assertIn("python -m unittest discover -s tests", release_section[:push_pos])
        self.assertIn("python -m pytest tests -q", release_section[:push_pos])
        self.assertIn("python -m unittest tests.test_no_pii", release_section[:push_pos])
        self.assertIn("刪除既有 `build/`／`dist/`", release_section)
        fresh_build_pos = release_section.index("**兩支 exe 都要重建**")
        checker_pos = release_section.index(
            "兩支 fresh build 完成後立即於同次執行")
        self.assertLess(fresh_build_pos, checker_pos)
        self.assertIn("兩支 fresh build 完成後立即於同次執行",
                      release_section)
        self.assertIn("不得沿用舊 `build/` 或 `PKG-00.toc`", release_section)
        self.assertIn(
            "python tools/check_bundle_deps.py Police-Document-Manager Police-Entry-Manager",
            release_section[checker_pos:])
        self.assertIn("候選 PE 只要來源缺失或無法解析即 **fail-closed**", developer)
        self.assertIn("唯一依 `Document_Ticket.register_date`", developer)
        views_section = developer.split("### Views", 1)[1].split("\n---\n", 1)[0]
        for view_name in ("View_Task_Full", "View_Criminal_Full",
                          "View_General_Full", "Document_Ticket_Full"):
            self.assertIn(view_name, views_section)
        self.assertIn("`idx_task/crim/gen/reward/ticket_lastmod`", developer)

    def test_quickstart_build_renders_only_approved_indexes(self):
        from reportlab.platypus import Spacer
        from tools import gen_quickstart

        rendered = []

        def record_section(index):
            rendered.append(index)
            return Spacer(1, 1)

        class FakeDocument:
            def __init__(self, *args, **kwargs):
                pass

            def build(self, story, **kwargs):
                self.story = story

        with (patch.object(gen_quickstart, "_section", side_effect=record_section),
              patch.object(gen_quickstart, "SimpleDocTemplate", FakeDocument)):
            gen_quickstart.build(str(ROOT / "docs" / "_test_quick_start.pdf"))

        self.assertEqual(rendered, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
        self.assertNotIn(10, rendered)


class TestThemeTicketAddButton(unittest.TestCase):
    """`ticket_add`（罰單登錄「新增」鈕）須與其餘送出鈕同套墨藍樣式，
    三段（base／:hover／:pressed）皆須列在白名單內，缺一段就退回預設灰。"""

    def test_ticket_add_in_submit_button_palette(self):
        theme_src = (ROOT / "lib" / "theme.py").read_text(encoding="utf-8")
        start = theme_src.index("送出按鈕")
        end = theme_src.index("只歸紙本禁用態", start)
        block = theme_src[start:end]
        for selector in ("QPushButton#ticket_add,",
                         "QPushButton#ticket_add:hover,",
                         "QPushButton#ticket_add:pressed,"):
            self.assertIn(selector, block)


if __name__ == "__main__":
    unittest.main()
