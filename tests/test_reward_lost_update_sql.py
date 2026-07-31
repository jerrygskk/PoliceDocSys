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
                    {"REWARD_ACTIVE_SQL": "register_date IS NOT NULL"},
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
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.execute(
            "CREATE TABLE Document_Reward("
            "doc_id TEXT PRIMARY KEY, register_date TEXT, sender_id TEXT, "
            "reason TEXT, recipients TEXT)"
        )
        self.conn.execute(
            "INSERT INTO Document_Reward VALUES('1','',NULL,'原事由','原人員')"
        )

    def tearDown(self):
        self.conn.close()

    def test_edit_compare_accepts_null_sender_and_rejects_changed_issue_fields(self):
        sql = _literal_assignment(
            ROOT / "ui_utils" / "reward_dialog.py", "_REWARD_EDIT_UPDATE_SQL")

        changed = self.conn.execute(
            sql,
            ("本機事由", "本機人員", "1", "", None, "原事由", "原人員"),
        )
        self.assertEqual(changed.rowcount, 1)

        self.conn.execute(
            "UPDATE Document_Reward SET register_date='2026-07-29',"
            "sender_id='P02' WHERE doc_id='1'")
        blocked = self.conn.execute(
            sql,
            ("不應寫入", "不應寫入", "1", "", None, "本機事由", "本機人員"),
        )
        self.assertEqual(blocked.rowcount, 0)
        self.assertEqual(
            self.conn.execute(
                "SELECT register_date,sender_id,reason,recipients "
                "FROM Document_Reward WHERE doc_id='1'").fetchone(),
            ("2026-07-29", "P02", "本機事由", "本機人員"),
        )

    def test_edit_compare_rejects_each_changed_original_field(self):
        sql = _literal_assignment(
            ROOT / "ui_utils" / "reward_dialog.py", "_REWARD_EDIT_UPDATE_SQL")
        changed_values = (
            ("register_date", "2026-07-29"),
            ("sender_id", "P02"),
            ("reason", "他機事由"),
            ("recipients", "他機人員"),
        )
        for column, external_value in changed_values:
            with self.subTest(column=column):
                self.conn.execute(
                    "UPDATE Document_Reward SET register_date='',sender_id=NULL,"
                    "reason='原事由',recipients='原人員' WHERE doc_id='1'")
                self.conn.execute(
                    f"UPDATE Document_Reward SET {column}=? WHERE doc_id='1'",
                    (external_value,),
                )
                blocked = self.conn.execute(
                    sql,
                    ("本機事由", "本機人員", "1", "", None, "原事由", "原人員"),
                )
                self.assertEqual(blocked.rowcount, 0)
                actual = self.conn.execute(
                    f"SELECT {column} FROM Document_Reward WHERE doc_id='1'"
                ).fetchone()[0]
                self.assertEqual(actual, external_value)

    def test_browse_compare_updates_all_fields_only_when_snapshot_matches(self):
        sql = _literal_assignment(
            ROOT / "ui_utils" / "reward_dialog.py", "_REWARD_BROWSE_UPDATE_SQL")
        updated = self.conn.execute(
            sql,
            ("2026-07-29", "P01", "新事由", "新人員",
             "1", "", None, "原事由", "原人員"),
        )
        self.assertEqual(updated.rowcount, 1)
        blocked = self.conn.execute(
            sql,
            ("", None, "過期本機值", "過期本機值",
             "1", "", None, "原事由", "原人員"),
        )
        self.assertEqual(blocked.rowcount, 0)
        self.assertEqual(
            self.conn.execute(
                "SELECT register_date,sender_id,reason,recipients "
                "FROM Document_Reward WHERE doc_id='1'").fetchone(),
            ("2026-07-29", "P01", "新事由", "新人員"),
        )

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
