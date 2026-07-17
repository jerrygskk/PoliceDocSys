# -*- coding: utf-8 -*-
import ast
import inspect
import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QLabel, QLineEdit, QListWidget,
    QPushButton, QTabWidget, QTableWidget, QToolButton, QWidget,
)

_app = QApplication.instance() or QApplication([])


class TestTicketPlaceholder(unittest.TestCase):
    def setUp(self):
        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "罰單登錄")

    def tearDown(self):
        self.tabs.deleteLater()

    def test_setup_shows_only_approved_placeholder_copy(self):
        from tabs.tab_ticket import TabTicketPlaceholder

        controller = TabTicketPlaceholder(self.tabs, "不存在也不應讀取.db")
        controller.setup(0)

        labels = self.tabs.widget(0).findChildren(QLabel)
        self.assertEqual(
            [label.text() for label in labels],
            ["▲ 罰單登錄", "本功能建置中，將於後續版本提供。"],
        )

    def test_base_tab_contract_is_inert(self):
        from tabs.tab_ticket import TabTicketPlaceholder

        controller = TabTicketPlaceholder(self.tabs, "不存在也不應讀取.db")
        controller.setup(0)

        self.assertEqual(controller.get_tables(), [])
        self.assertIsNone(controller.get_focus_widget())
        self.assertIsNone(controller.on_activated())

    def test_tabs_package_exports_fixed_class_name(self):
        from tabs import TabTicketPlaceholder

        self.assertEqual(TabTicketPlaceholder.__name__, "TabTicketPlaceholder")

    def test_layout_contains_no_interactive_or_fake_form_widgets(self):
        from tabs.tab_ticket import TabTicketPlaceholder

        controller = TabTicketPlaceholder(self.tabs, "不存在也不應讀取.db")
        controller.setup(0)
        page = self.tabs.widget(0)
        forbidden = (
            QPushButton, QToolButton, QLineEdit, QDateEdit, QComboBox,
            QTableWidget, QListWidget,
        )
        for widget_type in forbidden:
            with self.subTest(widget=widget_type.__name__):
                self.assertEqual(page.findChildren(widget_type), [])
        self.assertEqual(len(page.findChildren(QLabel)), 2)

    def test_controller_source_stays_out_of_business_and_permission_layers(self):
        import tabs.tab_ticket as ticket_module

        source = inspect.getsource(ticket_module)
        tree = ast.parse(source)
        identifiers = {
            node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
        } | {
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        }
        forbidden_identifiers = {
            "AuthManager", "is_admin", "is_manager", "role_changed", "getConn",
            "sqlite", "sqlite3", "Audit", "Reset", "print", "browse",
        }
        self.assertTrue(forbidden_identifiers.isdisjoint(identifiers))
        source_lower = source.lower()
        for forbidden_text in (
                "authmanager", "is_admin", "is_manager", "role_changed",
                "getconn", "sqlite", "document_", "audit", "reset",
                "print", "browse"):
            with self.subTest(token=forbidden_text):
                self.assertNotIn(forbidden_text, source_lower)

    def test_setup_does_not_consult_permissions_for_any_role(self):
        from lib.auth_manager import AuthManager
        from tabs.tab_ticket import TabTicketPlaceholder

        for role in ("user", "archive", "admin"):
            with self.subTest(role=role), patch.object(
                    AuthManager, "instance",
                    side_effect=AssertionError(f"{role} 不得查詢權限")):
                tabs = QTabWidget()
                tabs.addTab(QWidget(), "罰單登錄")
                controller = TabTicketPlaceholder(tabs, "不存在也不應讀取.db")
                controller.setup(0)
                self.assertEqual(len(tabs.widget(0).findChildren(QLabel)), 2)
                tabs.deleteLater()


if __name__ == "__main__":
    unittest.main()
