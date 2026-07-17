"""參照表排序「指定位置」純邏輯測試：既有列序號驗證、Add 對話框順序驗證。"""
import unittest

from ui_utils.settings_dialogs import _parseSeqMoveTarget, _parseAddPosition


class TestParseSeqMoveTarget(unittest.TestCase):
    """既有列「序號」欄編輯驗證，清單共 5 筆（row_count=5）。"""

    def test_valid_middle(self):
        self.assertEqual(_parseSeqMoveTarget("3", 5), 2)

    def test_valid_first(self):
        self.assertEqual(_parseSeqMoveTarget("1", 5), 0)

    def test_valid_last(self):
        self.assertEqual(_parseSeqMoveTarget("5", 5), 4)

    def test_zero_invalid(self):
        self.assertIsNone(_parseSeqMoveTarget("0", 5))

    def test_negative_invalid(self):
        self.assertIsNone(_parseSeqMoveTarget("-1", 5))

    def test_over_range_invalid(self):
        self.assertIsNone(_parseSeqMoveTarget("6", 5))

    def test_non_numeric_invalid(self):
        self.assertIsNone(_parseSeqMoveTarget("abc", 5))

    def test_empty_invalid(self):
        self.assertIsNone(_parseSeqMoveTarget("", 5))
        self.assertIsNone(_parseSeqMoveTarget(None, 5))

    def test_decimal_invalid(self):
        self.assertIsNone(_parseSeqMoveTarget("2.5", 5))

    def test_whitespace_trimmed(self):
        self.assertEqual(_parseSeqMoveTarget("  3  ", 5), 2)


class TestParseAddPosition(unittest.TestCase):
    """Add 對話框「順序」欄驗證，新增前清單共 5 筆（existing_count=5，合法上限 6）。"""

    def test_blank_is_valid_none(self):
        self.assertEqual(_parseAddPosition("", 5), (True, None))
        self.assertEqual(_parseAddPosition("   ", 5), (True, None))
        self.assertEqual(_parseAddPosition(None, 5), (True, None))

    def test_valid_middle(self):
        self.assertEqual(_parseAddPosition("3", 5), (True, 2))

    def test_valid_first(self):
        self.assertEqual(_parseAddPosition("1", 5), (True, 0))

    def test_valid_at_count_plus_one(self):
        # 新增後變 6 筆，可以排在第 6（最後）
        self.assertEqual(_parseAddPosition("6", 5), (True, 5))

    def test_over_range_invalid(self):
        self.assertEqual(_parseAddPosition("7", 5), (False, None))

    def test_zero_invalid(self):
        self.assertEqual(_parseAddPosition("0", 5), (False, None))

    def test_non_numeric_invalid(self):
        self.assertEqual(_parseAddPosition("abc", 5), (False, None))

    def test_empty_list_count_zero(self):
        # 清單目前 0 筆，新增後變 1 筆，只能填 1
        self.assertEqual(_parseAddPosition("1", 0), (True, 0))
        self.assertEqual(_parseAddPosition("2", 0), (False, None))


if __name__ == "__main__":
    unittest.main()
