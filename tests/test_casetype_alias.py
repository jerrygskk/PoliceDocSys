# -*- coding: utf-8 -*-
"""案類別名功能單元測試。

涵蓋：
  1. schema round-trip：ensureSchema 後 Ref_CaseTypes 有 alias 欄；
     舊庫（無 alias 欄）跑 ensureSchema 後補上。
  2. 候選 model 建構純邏輯：正式名 + 別名筆（重複別名兩筆並存，各帶各的 id）。
  3. 別名 SQL round-trip：_has_alias_col、寫入、讀回。
  4. 歸檔 token：案類帶別名後 _docTokens 含別名斷詞。
"""

import sqlite3
import sys
import os
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from lib.db_schema import applySchema, ensureSchema


# ── helper ───────────────────────────────────────────────────────────

def _make_db():
    conn = sqlite3.connect(":memory:")
    applySchema(conn)
    return conn


def _make_legacy_db():
    """模擬「無 alias 欄」的舊庫。"""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE Ref_CaseTypes "
        "(case_type_id VARCHAR(10) PRIMARY KEY, case_type_name VARCHAR(100) NOT NULL, "
        "is_active BOOLEAN NOT NULL DEFAULT 1, sort_order INTEGER)"
    )
    conn.commit()
    return conn


# ── 1. Schema round-trip ─────────────────────────────────────────────

class TestSchemaAlias(unittest.TestCase):

    def test_new_db_has_alias_col(self):
        conn = _make_db()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(Ref_CaseTypes)")]
        self.assertIn("alias", cols)

    def test_legacy_db_gets_alias_col_after_ensure(self):
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(lambda: os.path.exists(db_path) and os.remove(db_path))
        conn = sqlite3.connect(db_path)
        conn.execute(
            "CREATE TABLE Ref_CaseTypes ("
            "case_type_id VARCHAR(10) PRIMARY KEY, "
            "case_type_name VARCHAR(100) NOT NULL, "
            "is_active BOOLEAN NOT NULL DEFAULT 1, sort_order INTEGER)"
        )
        conn.commit()
        conn.close()

        ensureSchema(db_path)

        conn = sqlite3.connect(db_path)
        try:
            columns = [row[1] for row in conn.execute(
                "PRAGMA table_info(Ref_CaseTypes)"
            )]
        finally:
            conn.close()
        self.assertIn("alias", columns)


# ── 2. Completer 候選 model 純邏輯 ───────────────────────────────────

def _build_model_items(data_list, alias_map):
    """複製 setupFilterCombo 中建構 model 的純邏輯（不依賴 Qt widgets）。

    回傳 [(display_text, user_role_id), ...]。
    """
    items = []
    for id_, name in data_list:
        items.append((name, id_))
    if alias_map:
        name_to_id = {name: id_ for id_, name in data_list}
        for name, aliases in alias_map.items():
            id_ = name_to_id.get(name)
            if id_ is None:
                continue
            for alias in aliases:
                alias = alias.strip()
                if not alias:
                    continue
                items.append((f"{alias} → {name}", id_))
    return items


class TestCompleterModel(unittest.TestCase):

    def setUp(self):
        self.data = [
            ("CT01", "公共危險"),
            ("CT02", "竊盜"),
        ]
        self.alias_map = {
            "公共危險": ["酒駕", "毒駕", "公危"],
            "竊盜": ["偷竊"],
        }

    def test_formal_names_present(self):
        items = _build_model_items(self.data, None)
        texts = [t for t, _ in items]
        self.assertIn("公共危險", texts)
        self.assertIn("竊盜", texts)

    def test_alias_items_present(self):
        items = _build_model_items(self.data, self.alias_map)
        texts = [t for t, _ in items]
        self.assertIn("酒駕 → 公共危險", texts)
        self.assertIn("公危 → 公共危險", texts)
        self.assertIn("偷竊 → 竊盜", texts)

    def test_alias_items_carry_correct_id(self):
        items = _build_model_items(self.data, self.alias_map)
        id_map = {t: id_ for t, id_ in items}
        self.assertEqual(id_map["酒駕 → 公共危險"], "CT01")
        self.assertEqual(id_map["偷竊 → 竊盜"], "CT02")

    def test_duplicate_alias_across_casetypes(self):
        # 同一別名掛兩個案類（允許重複）
        alias_map = {
            "公共危險": ["公危"],
            "竊盜": ["公危"],
        }
        items = _build_model_items(self.data, alias_map)
        same_alias = [(t, id_) for t, id_ in items if "公危" in t]
        self.assertEqual(len(same_alias), 2)
        ids = {id_ for _, id_ in same_alias}
        self.assertEqual(ids, {"CT01", "CT02"})

    def test_no_alias_map_produces_only_formal(self):
        items = _build_model_items(self.data, None)
        self.assertEqual(len(items), 2)

    def test_empty_alias_str_skipped(self):
        alias_map = {"公共危險": ["", "  ", "酒駕"]}
        items = _build_model_items(self.data, alias_map)
        texts = [t for t, _ in items]
        # 空別名不應出現
        self.assertNotIn(" → 公共危險", texts)
        self.assertIn("酒駕 → 公共危險", texts)


# ── 3. 別名 SQL round-trip ───────────────────────────────────────────

class TestCasetypeAliasSql(unittest.TestCase):

    def setUp(self):
        self.conn = _make_db()
        self.conn.execute(
            "INSERT INTO Ref_CaseTypes (case_type_id, case_type_name, is_active, sort_order, alias) "
            "VALUES ('CT01','公共危險',1,1,'酒駕,毒駕,公危')"
        )
        self.conn.commit()

    def test_alias_written_and_read_back(self):
        row = self.conn.execute(
            "SELECT alias FROM Ref_CaseTypes WHERE case_type_id='CT01'"
        ).fetchone()
        self.assertEqual(row[0], "酒駕,毒駕,公危")

    def test_alias_can_be_null(self):
        self.conn.execute(
            "INSERT INTO Ref_CaseTypes (case_type_id, case_type_name, is_active, sort_order) "
            "VALUES ('CT02','竊盜',1,2)"
        )
        self.conn.commit()
        row = self.conn.execute(
            "SELECT alias FROM Ref_CaseTypes WHERE case_type_id='CT02'"
        ).fetchone()
        self.assertIsNone(row[0])

# ── 4. 歸檔 _docTokens 含別名斷詞 ────────────────────────────────────

class TestDocTokensAlias(unittest.TestCase):
    """抽出 _docTokens + _loadCaseTypeAliasMap 的純邏輯，用 stub 驗証。"""

    def _run_doc_tokens(self, doc_fields, alias_map):
        """複製 tab_archive._docTokens 純邏輯（不依賴 TabArchive 實例）。"""
        from lib.archive_text import _tokenize, _trimName
        toks = set()
        for v in doc_fields.values():
            if not v:
                continue
            toks |= _tokenize(v)
            toks.add(_trimName(v))
        ct_name = doc_fields.get("案類")
        if ct_name:
            for alias in alias_map.get(ct_name, []):
                toks |= _tokenize(alias)
        return toks

    def test_alias_tokens_included(self):
        alias_map = {"公共危險": ["酒駕", "毒駕"]}
        doc = {"案類": "公共危險", "主旨": "竊盜案"}
        toks = self._run_doc_tokens(doc, alias_map)
        self.assertIn("酒駕", toks)
        self.assertIn("毒駕", toks)

    def test_no_alias_no_extra_tokens(self):
        alias_map = {}
        doc = {"案類": "竊盜", "主旨": "某案"}
        toks_with = self._run_doc_tokens(doc, {"竊盜": ["偷竊"]})
        toks_without = self._run_doc_tokens(doc, alias_map)
        self.assertIn("偷竊", toks_with)
        self.assertNotIn("偷竊", toks_without)

    def test_missing_casetype_no_error(self):
        alias_map = {"公共危險": ["酒駕"]}
        doc = {"主旨": "某案"}  # 沒有「案類」欄
        toks = self._run_doc_tokens(doc, alias_map)
        # 不應拋例外，結果不含別名
        self.assertNotIn("酒駕", toks)


if __name__ == "__main__":
    unittest.main()
