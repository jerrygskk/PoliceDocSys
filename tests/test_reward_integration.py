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
        from main import DocumentManager, MainMenu
        from tabs import TabReward, TabRewardIssue

        self.assertEqual(list(DocumentManager.TAB_CLASSES), list(range(10)))
        self.assertIs(DocumentManager.TAB_CLASSES[3], TabReward)
        self.assertIs(DocumentManager.TAB_CLASSES[4], TabRewardIssue)
        self.assertEqual(DocumentManager._IDX_DBBROWSE, 6)
        self.assertEqual(DocumentManager._IDX_SETTINGS, 8)
        self.assertEqual(set(MainMenu.BTN_MAP.values()), set(range(10)))
        self.assertEqual(MainMenu.BTN_MAP["btn_reward"], 3)
        self.assertEqual(MainMenu.BTN_MAP["btn_ticket"], 4)
        self.assertEqual(MainMenu.ICON_MAP["btn_reward"], ":/menu/reward.svg")
        self.assertEqual(MainMenu.ICON_MAP["btn_ticket"], ":/menu/reward_issue.svg")

    def test_ui_order_and_menu_grid(self):
        layout = (ROOT / "layouts" / "Layout1.ui").read_text(encoding="utf-8")
        names = re.findall(r'<widget class="QWidget" name="(tab_[^"]+)"', layout)
        self.assertEqual(names, [
            "tab_dispatch", "tab_receive", "tab_report", "tab_reward", "tab_ticket",
            "tab_print", "tab_dbbrowse", "tab_archive", "tab_settings", "tab_audit",
        ])

        menu = (ROOT / "layouts" / "main_menu.ui").read_text(encoding="utf-8")
        cells = re.findall(r'<item row="(\d+)" column="(\d+)">\s*<widget class="QToolButton" name="(btn_[^"]+)"', menu)
        self.assertEqual(len(cells), 10)
        self.assertEqual({(int(r), int(c)) for r, c, _ in cells}, {(r, c) for r in range(5) for c in range(2)})
        for name in ("btn_reward", "btn_ticket"):
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

        from res import resources_rc  # noqa: F401
        for path in (":/menu/reward.svg", ":/menu/reward_issue.svg", ":/tab/reward.svg"):
            f = QFile(path)
            self.assertTrue(f.exists(), path)
            self.assertTrue(f.open(QFile.ReadOnly), path)
            self.assertGreater(f.size(), 0)
            self.assertFalse(QIcon(path).isNull(), path)

    def test_tab_overflow_default_width_1320_resizable_and_uses_qt_fallback(self):
        from ui_utils import loadUi

        app = QApplication.instance() or QApplication([])
        window = loadUi(str(ROOT / "layouts" / "Layout1.ui"))
        tab_widget = window.tabWidget
        self.assertEqual(window.width(), 1320)
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
        self.assertEqual(set(HELP_TITLES), set(range(10)))
        self.assertEqual(set(HELP_PAGES), set(range(10)))
        self.assertEqual(set(HELP_TIPS), set(range(10)))
        self.assertEqual(HELP_TITLES[4], "敘獎發文")
        self.assertEqual(set(QUICKSTART), set(range(9)))
        source = (ROOT / "tools" / "gen_quickstart.py").read_text(encoding="utf-8")
        self.assertIn("PAGE1 = [0, 1, 2]", source)
        self.assertIn("PAGE2 = [3, 4, 5]", source)
        self.assertIn("PAGE3 = [6, 7, 8]", source)
        self.assertIn("九個分頁速查", source)
        reward_help = render_review_text(3)
        issue_help = render_review_text(4)
        print_help = render_review_text(5)
        browse_help = render_review_text(6)
        settings_help = render_review_text(8)
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
        self.assertIn("未發文的刑案／一般案件", print_help)
        self.assertNotIn("未發文的刑案／一般／敘獎案件", print_help)
        self.assertEqual(set(HELP_TIPS[3]), {
            "btn_reward_submit", "btn_reward_clear", "reward_personnel_list",
        })
        self.assertNotIn("日期", HELP_TIPS[3]["btn_reward_submit"])
        self.assertEqual(set(HELP_TIPS[4]), {
            "btn_reward_input", "btn_reward_issue", "btn_reward_issue_clear",
        })
        self.assertIn("自助取號模式只影響刑案與一般陳報", settings_help)
        self.assertIn("敘獎登錄與敘獎發文不受陳報模式影響", settings_help)
        self.assertNotIn("此模式同時涵蓋敘獎登錄", settings_help)
        self.assertNotIn("一併於結算時補齊", settings_help)
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
        self.assertIn("`SETTLE_META` 僅含刑案與一般", developer)

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

        self.assertEqual(rendered, [0, 1, 2, 3, 4, 5, 6, 7, 8])
        self.assertNotIn(9, rendered)


if __name__ == "__main__":
    unittest.main()
