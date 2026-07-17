import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLineEdit

from ui_utils import (
    RecipientLineEditController,
    format_recipient_names,
    parse_recipient_names,
    sort_reward_personnel,
)


class RecipientNameTests(unittest.TestCase):
    def test_parse_normalizes_separators_strips_and_deduplicates_in_order(self):
        self.assertEqual(
            parse_recipient_names(" 王小明， 李小華、王小明,, 名單外姓名， "),
            ["王小明", "李小華", "名單外姓名"],
        )

    def test_format_distinguishes_storage_and_editing_forms(self):
        names = ["王小明", "李小華"]
        self.assertEqual(format_recipient_names(names), "王小明, 李小華")
        self.assertEqual(
            format_recipient_names(names, trailing=True), "王小明, 李小華, "
        )
        self.assertEqual(parse_recipient_names("王小明, 李小華, "), names)

    def test_sort_counts_complete_tokens_and_uses_stable_fallbacks(self):
        personnel = [
            (4, "林大同", None),
            (2, "王小明", 10),
            (3, "王小", 10),
            (1, "李小華", 5),
            (5, "陳新進", None),
        ]
        history = ["王小明, 李小華", "王小明、王小", "林大同，王小明"]
        self.assertEqual(
            sort_reward_personnel(personnel, history),
            [
                (2, "王小明", 10),
                (1, "李小華", 5),
                (3, "王小", 10),
                (4, "林大同", None),
                (5, "陳新進", None),
            ],
        )


class RecipientControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_candidates_store_formal_name_and_add_person_has_no_trailing_comma(self):
        edit = QLineEdit()
        controller = RecipientLineEditController(
            edit,
            [(1, "王小明"), (2, "李小華")],
            {"王小明": ["小明"]},
        )
        roles = [
            controller.model.item(row).data(Qt.UserRole)
            for row in range(controller.model.rowCount())
        ]
        self.assertEqual(roles, ["王小明", "李小華", "王小明"])

        controller.add_person(" 王小明 ")
        controller.add_person("王小明")
        controller.add_person("名單外姓名")
        self.assertEqual(edit.text(), "王小明, 名單外姓名")
        self.assertEqual(edit.cursorPosition(), len(edit.text()))

    def test_candidate_add_replaces_last_unfinished_fragment(self):
        edit = QLineEdit("王小明, 小")
        controller = RecipientLineEditController(edit, [(1, "王小明"), (2, "李小華")])
        controller.add_person("李小華", replace_current=True)
        self.assertEqual(edit.text(), "王小明, 李小華")

    def test_candidate_add_replaces_cursor_fragment_without_changing_later_names(self):
        edit = QLineEdit("王小明, 小, 名單外姓名, ")
        controller = RecipientLineEditController(edit, [(1, "王小明"), (2, "李小華")])
        edit.setCursorPosition(edit.text().index("小, 名單") + 1)
        controller.add_person("李小華", replace_current=True)
        self.assertEqual(edit.text(), "王小明, 李小華, 名單外姓名")

    def test_alias_completer_activation_replaces_fragment_with_formal_name(self):
        edit = QLineEdit("名單外姓名, 小明")
        controller = RecipientLineEditController(
            edit, [(1, "王小明")], {"王小明": ["小明"]}
        )
        edit.setCursorPosition(len(edit.text()))
        from PySide6.QtCore import QModelIndex
        controller.completer.activated[QModelIndex].emit(controller.model.index(1, 0))
        self.app.processEvents()
        self.assertEqual(edit.text(), "名單外姓名, 王小明")


if __name__ == "__main__":
    unittest.main()
