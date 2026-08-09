# tests/test_reward_integration.py
"""敘獎相關的**程式契約**：分頁／主選單映射、.ui 順序、SVG 與 qrc、TabBar 寬度資料流、
速查卡只渲染核准索引、送出鈕樣式白名單。

⚠️ 本檔原本還兼任 HELP／速查卡／DEVELOPER.md 的**文字契約**（一支測試讀四個來源），
文案潤飾就會紅在「敘獎整合測試」名下。文字契約已拆出：
HELP／速查卡 → `test_help_content_contract.py`；DEVELOPER.md →
`test_release_documentation_contract.py`。**新的文件契約請加到那兩支，不要加回本檔。**
"""
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
        # ——避免檔頭一次 import 全部 10 個分頁（見 tabs/__init__.py 延遲載入）。
        expected_tabs = {
            "assignment_issue": ("tabs.tab_dispatch", "TabDispatch"),
            "assignment_receive": ("tabs.tab_receive", "TabReceive"),
            "report": ("tabs.tab_report", "TabReport"),
            "reward": ("tabs.tab_reward", "TabReward"),
            "ticket": ("tabs.tab_ticket", "TabTicket"),
            "print": ("tabs.tab_print", "TabPrint"),
            "browse": ("tabs.tab_dbbrowse", "TabDBBrowse"),
            "archive": ("tabs.tab_archive", "TabArchive"),
            "settings": ("tabs.tab_settings", "TabSettings"),
            "audit": ("tabs.tab_audit", "TabAudit"),
        }
        # 固定索引契約改以 FULL_PROFILE 驗證相同順序：完整版為 10 個 Tab、固定順序。
        self.assertEqual(DocumentManager.TAB_CLASSES, expected_tabs)
        self.assertEqual(tuple(DocumentManager.TAB_CLASSES), FULL_PROFILE.tab_keys)
        self.assertEqual(set(MainMenu.MENU_BUTTONS), set(FULL_PROFILE.menu_keys))
        self.assertEqual(MainMenu.MENU_BUTTONS["reward"], "btn_reward")
        self.assertEqual(MainMenu.MENU_BUTTONS["ticket"], "btn_ticket")
        self.assertEqual(MainMenu.ICON_MAP["reward"], ":/menu/reward.svg")
        self.assertEqual(MainMenu.ICON_MAP["ticket"], ":/menu/ticket.svg")
        # 敘獎發文頁整頁移除：按鈕與圖示映射都不得殘留
        self.assertNotIn("reward_issue", MainMenu.MENU_BUTTONS)
        self.assertNotIn("reward_issue", MainMenu.ICON_MAP)

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
            "tab_ticket", "tab_print", "tab_dbbrowse",
            "tab_archive", "tab_settings", "tab_audit",
        ])

        # 磚格位置由 MainMenu 依 menu_keys 重排（ceil(sqrt(n)) 欄），.ui 內的
        # row/column 只是設計期擺放；此處只驗按鈕數量與不重複。
        positions = self._menu_button_positions()
        self.assertEqual(len(positions), 10)
        self.assertEqual(len({name for _, _, name in positions}), 10)

        menu = (ROOT / "layouts" / "main_menu.ui").read_text(encoding="utf-8")
        self.assertNotIn('name="btn_reward_issue"', menu)
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

        # 敘獎發文頁移除：圖檔與 qrc 別名都不得殘留
        self.assertFalse((ROOT / "res" / "buttons" / "menu_reward_issue.svg").exists())
        qrc = (ROOT / "res" / "resources.qrc").read_text(encoding="utf-8")
        self.assertNotIn("menu_reward_issue.svg", qrc)

        for filename in ("menu_ticket.svg",):
            svg = (ROOT / "res" / "buttons" / filename).read_text(encoding="utf-8")
            self.assertIn('viewBox="0 0 24 24"', svg)
            self.assertIn('fill="none"', svg)
            self.assertIn('stroke="#4977b1"', svg)
            self.assertIn('stroke-width="1.7"', svg)
            self.assertIn('stroke-linecap="round"', svg)
            self.assertIn('stroke-linejoin="round"', svg)

        from res import resources_rc  # noqa: F401
        for path in (":/menu/reward.svg", ":/tab/reward.svg", ":/menu/ticket.svg"):
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


class TestThemeTicketAddButton(unittest.TestCase):
    """`ticket_add`（罰單登錄「新增」鈕）須與其餘送出鈕同套墨藍樣式，
    三段（base／:hover／:pressed）皆須列在白名單內，缺一段就退回預設灰。"""

    def test_ticket_add_in_submit_button_palette(self):
        theme_src = (ROOT / "lib" / "theme.py").read_text(encoding="utf-8")
        start = theme_src.index("送出按鈕")
        end = theme_src.index("Tab 標籤", start)
        block = theme_src[start:end]
        for selector in ("QPushButton#ticket_add,",
                         "QPushButton#ticket_add:hover,",
                         "QPushButton#ticket_add:pressed,"):
            self.assertIn(selector, block)


if __name__ == "__main__":
    unittest.main()
