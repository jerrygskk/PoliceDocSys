# -*- coding: utf-8 -*-
"""敘獎 lost-update SQL 契約；只用 stdlib，可在沒有 PySide6 時執行。"""

import ast
import sqlite3
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _literal_assignment(path, name):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(target, ast.Name) and target.id == name
                   for target in targets):
                expression = compile(
                    ast.Expression(node.value), filename=str(path), mode="eval")
                return eval(
                    expression,
                    {"__builtins__": {}},
                    {"REWARD_ACTIVE_SQL": "register_date IS NOT NULL",
                     "LAST_MODIFIED_CAS_SQL": "last_modified IS ?"},
                )
    raise AssertionError(f"{path.name} 缺少 {name}")


def _function_from_source(path, name, globals_dict=None):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    node = next(
        (item for item in tree.body
         if isinstance(item, ast.FunctionDef) and item.name == name),
        None,
    )
    if node is None:
        raise AssertionError(f"{path.name} 缺少 {name}")
    namespace = dict(globals_dict or {})
    exec(compile(ast.Module(body=[node], type_ignores=[]),
                 filename=str(path), mode="exec"), namespace)
    return namespace[name]


class TestRewardLostUpdateSql(unittest.TestCase):
    """⚠️ 2026-08-07 起樂觀鎖由「比對四個欄位原值」改為「比對 `last_modified`」，
    與罰單／交辦／刑案／一般共用同一套（見 db_utils.LAST_MODIFIED_CAS_SQL）。
    本檔的斷言隨之反轉，不是放寬——新機制涵蓋整列而非四個欄位。"""

    _SNAPSHOT = "2026-08-07 10:00:00"

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE Document_Reward("
            "doc_id TEXT PRIMARY KEY, register_date TEXT, sender_id TEXT, "
            "reason TEXT, recipients TEXT, last_modified TEXT)"
        )
        self.conn.execute(
            "INSERT INTO Document_Reward VALUES('1','',NULL,'原事由','原人員',?)",
            (self._SNAPSHOT,),
        )

    def tearDown(self):
        self.conn.close()

    def _touch(self, last_modified="2026-08-07 10:00:05"):
        """模擬他機異動：trigger 會把 last_modified 換掉。"""
        self.conn.execute(
            "UPDATE Document_Reward SET last_modified=? WHERE doc_id='1'",
            (last_modified,))

    def _row(self):
        return self.conn.execute(
            "SELECT register_date,sender_id,reason,recipients "
            "FROM Document_Reward WHERE doc_id='1'").fetchone()

    def test_edit_writes_when_snapshot_matches(self):
        sql = _literal_assignment(
            ROOT / "ui_utils" / "reward_dialog.py", "_REWARD_EDIT_UPDATE_SQL")
        changed = self.conn.execute(
            sql, ("本機事由", "本機人員", "1", self._SNAPSHOT))
        self.assertEqual(changed.rowcount, 1)
        self.assertEqual(self._row(), ("", None, "本機事由", "本機人員"))

    def test_edit_blocked_when_row_changed_elsewhere(self):
        sql = _literal_assignment(
            ROOT / "ui_utils" / "reward_dialog.py", "_REWARD_EDIT_UPDATE_SQL")
        # 他機把這筆結算發文了（register_date/sender 變動 → last_modified 換掉）
        self.conn.execute(
            "UPDATE Document_Reward SET register_date='2026-07-29',"
            "sender_id='P02' WHERE doc_id='1'")
        self._touch()
        blocked = self.conn.execute(
            sql, ("不應寫入", "不應寫入", "1", self._SNAPSHOT))
        self.assertEqual(blocked.rowcount, 0)
        self.assertEqual(self._row(), ("2026-07-29", "P02", "原事由", "原人員"))

    def test_edit_blocked_even_when_values_were_changed_back(self):
        """⚠️ 這條是換成 `last_modified` 才擋得住的情境：他機把值改成 B 又改回 A。

        舊的四欄比對只看「值一不一樣」，改回來就形同沒改過、照樣放行；
        `last_modified` 記的是「有沒有被動過」，故仍然擋下。
        """
        sql = _literal_assignment(
            ROOT / "ui_utils" / "reward_dialog.py", "_REWARD_EDIT_UPDATE_SQL")
        self.conn.execute(
            "UPDATE Document_Reward SET reason='他機事由' WHERE doc_id='1'")
        self.conn.execute(
            "UPDATE Document_Reward SET reason='原事由' WHERE doc_id='1'")
        self._touch()
        blocked = self.conn.execute(
            sql, ("本機事由", "本機人員", "1", self._SNAPSHOT))
        self.assertEqual(blocked.rowcount, 0)
        self.assertEqual(self._row(), ("", None, "原事由", "原人員"))

    def test_edit_blocked_when_row_soft_deleted(self):
        """軟刪除（register_date=NULL）仍由 REWARD_ACTIVE_SQL 擋下，與樂觀鎖無關。"""
        sql = _literal_assignment(
            ROOT / "ui_utils" / "reward_dialog.py", "_REWARD_EDIT_UPDATE_SQL")
        self.conn.execute(
            "UPDATE Document_Reward SET register_date=NULL WHERE doc_id='1'")
        blocked = self.conn.execute(
            sql, ("本機事由", "本機人員", "1", self._SNAPSHOT))
        self.assertEqual(blocked.rowcount, 0)

    def test_browse_updates_all_fields_only_when_snapshot_matches(self):
        sql = _literal_assignment(
            ROOT / "ui_utils" / "reward_dialog.py", "_REWARD_BROWSE_UPDATE_SQL")
        updated = self.conn.execute(
            sql,
            ("2026-07-29", "P01", "新事由", "新人員", "1", self._SNAPSHOT))
        self.assertEqual(updated.rowcount, 1)
        self._touch()
        blocked = self.conn.execute(
            sql,
            ("", None, "過期本機值", "過期本機值", "1", self._SNAPSHOT))
        self.assertEqual(blocked.rowcount, 0)
        self.assertEqual(self._row(),
                         ("2026-07-29", "P01", "新事由", "新人員"))

    def test_edit_miss_releases_writer_before_fresh_classification_read(self):
        classify = _function_from_source(
            ROOT / "ui_utils" / "reward_dialog.py",
            "_classify_reward_update_miss",
            {"REWARD_ACTIVE_SQL": "register_date IS NOT NULL"},
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "reward-lock.db")
            setup = sqlite3.connect(db_path)
            setup.execute(
                "CREATE TABLE Document_Reward("
                "doc_id TEXT PRIMARY KEY, register_date TEXT)")
            setup.execute("INSERT INTO Document_Reward VALUES('1','')")
            setup.commit()
            setup.close()

            writer = sqlite3.connect(db_path, timeout=0.05)
            missed = writer.execute(
                "UPDATE Document_Reward SET register_date='x' "
                "WHERE doc_id='missing'")
            self.assertEqual(missed.rowcount, 0)
            self.assertTrue(writer.in_transaction)

            active = classify(writer, sqlite3.connect, db_path, "1")
            self.assertTrue(active)
            self.assertFalse(writer.in_transaction)

            second_writer = sqlite3.connect(db_path, timeout=0.05)
            try:
                second_writer.execute(
                    "UPDATE Document_Reward SET register_date='2026-07-29' "
                    "WHERE doc_id='1'")
                second_writer.commit()
            finally:
                second_writer.close()
                writer.close()


if __name__ == "__main__":
    unittest.main()
