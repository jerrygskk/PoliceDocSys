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
        from tabs import TabReward, TabTicketPlaceholder

        self.assertEqual(list(DocumentManager.TAB_CLASSES), list(range(10)))
        self.assertIs(DocumentManager.TAB_CLASSES[3], TabReward)
        self.assertIs(DocumentManager.TAB_CLASSES[4], TabTicketPlaceholder)
        self.assertEqual(DocumentManager._IDX_DBBROWSE, 6)
        self.assertEqual(DocumentManager._IDX_SETTINGS, 8)
        self.assertEqual(set(MainMenu.BTN_MAP.values()), set(range(10)))
        self.assertEqual(MainMenu.BTN_MAP["btn_reward"], 3)
        self.assertEqual(MainMenu.BTN_MAP["btn_ticket"], 4)
        self.assertEqual(MainMenu.ICON_MAP["btn_reward"], ":/menu/reward.svg")
        self.assertEqual(MainMenu.ICON_MAP["btn_ticket"], ":/menu/ticket.svg")

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
            "menu_ticket.svg": [
                'd="M4 4h16a1 1 0 0 1 1 1v14a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1z"',
                'd="M3 12.7h18"', 'd="M7 9.8h10l-1.2-3H8.2L7 9.8z"',
                '<circle cx="8.5" cy="10.9" r="0.7" fill="#4977b1" stroke="none"/>',
                '<circle cx="15.5" cy="10.9" r="0.7" fill="#4977b1" stroke="none"/>',
                'd="M5.5 14.9v1.8"', 'd="M5.5 18.2h.01"', 'd="M9 15.4h9"', 'd="M9 17.9h7"',
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

        from res import resources_rc  # noqa: F401
        for path in (":/menu/reward.svg", ":/menu/ticket.svg", ":/tab/reward.svg"):
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
        self.assertEqual(set(QUICKSTART), {0, 1, 2, 3, 5, 6, 7, 8})
        source = (ROOT / "tools" / "gen_quickstart.py").read_text(encoding="utf-8")
        self.assertIn("PAGE1 = [0, 1, 2, 3]", source)
        self.assertIn("PAGE2 = [5, 6, 7, 8]", source)
        self.assertIn("八個分頁速查", source)
        self.assertNotIn("七個分頁速查", source)
        reward_help = render_review_text(3)
        browse_help = render_review_text(6)
        self.assertIn("本次預覽三種身分皆可修改、刪除", reward_help)
        self.assertIn("一般使用者唯讀", browse_help)
        self.assertIn("歸檔管理可修改、不可刪除", browse_help)
        self.assertIn("管理者可修改、可刪除", browse_help)

        from pypdf import PdfReader
        self.assertEqual(len(PdfReader(ROOT / "docs" / "Quick_Start.pdf").pages), 2)

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

        self.assertEqual(rendered, [0, 1, 2, 3, 5, 6, 7, 8])
        self.assertNotIn(4, rendered)
        self.assertNotIn(9, rendered)


if __name__ == "__main__":
    unittest.main()
