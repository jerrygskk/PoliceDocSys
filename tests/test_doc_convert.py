# -*- coding: utf-8 -*-
"""刑案 ↔ 一般 類別互轉純邏輯（lib/doc_convert.py）。

涵蓋：欄位映射、丟失欄清單與顯示名解析、檔名換 PK、convertDoc round-trip
（新號遞增／來源表 Seq 不動／原列成空殼／稽核一筆含雙號與丟失欄／不進回收筒／
失敗 rollback）。

受測模組 import 時會載入 PySide6（db_utils 依賴），故執行環境需裝 PySide6。
"""
import os
import sys
import sqlite3
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib import db_schema
from lib import doc_convert


def _make_db():
    conn = sqlite3.connect(":memory:")
    db_schema.applySchema(conn)          # 正式 DDL：三主表＋triggers＋Seq_DocId
    conn.executescript("""
        INSERT INTO Seq_DocId(table_name,last_id) VALUES('Document_Criminal',5);
        INSERT INTO Seq_DocId(table_name,last_id) VALUES('Document_General',20);
        INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order)
            VALUES('P01','王小明',1,1),('P02','陳志豪',1,2),('P03','林大偉',1,3);
        INSERT INTO Ref_Departments(dept_id,dept_name,is_active,sort_order)
            VALUES('D01','偵查隊',1,1);
        INSERT INTO Ref_CaseTypes(case_type_id,case_type_name,is_active,sort_order)
            VALUES('CT01','竊盜案',1,1);
        INSERT INTO Ref_Case_Status(status_id,status_name)
            VALUES('CS01','現行'),('CS02','到案'),('CS03','未到');
        INSERT INTO Ref_General_Category(gen_cat_id,gen_cat_name)
            VALUES('GC01','業務'),('GC02','相驗'),('GC03','其他');
    """)
    conn.commit()
    return conn


def _insert_gen(conn, doc_id="20", **over):
    row = dict(report_date="2026-06-28", sender_id="P01", dept_id="D01",
               gen_cat_id="GC01", subject="超商竊盜案移送", processor_id="P02",
               is_reported=1, is_electronic="")
    row.update(over)
    conn.execute(
        "INSERT INTO Document_General(doc_id,report_date,sender_id,dept_id,"
        "gen_cat_id,subject,processor_id,is_reported,is_electronic) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (doc_id, row["report_date"], row["sender_id"], row["dept_id"],
         row["gen_cat_id"], row["subject"], row["processor_id"],
         row["is_reported"], row["is_electronic"]))
    conn.commit()


def _insert_crim(conn, doc_id="5", **over):
    row = dict(report_date="2026-06-28", sender_id="P01", case_type="CT01",
               case_status="CS01", processor_id="P02",
               subject_summary="超商竊盜案移送", occurrence_date="2026-06-20",
               reporter_name="張老闆", receiver_id="P03", is_reported=1,
               is_electronic="")
    row.update(over)
    conn.execute(
        "INSERT INTO Document_Criminal(doc_id,report_date,sender_id,case_type,"
        "case_status,processor_id,subject_summary,occurrence_date,reporter_name,"
        "receiver_id,is_reported,is_electronic) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (doc_id, row["report_date"], row["sender_id"], row["case_type"],
         row["case_status"], row["processor_id"], row["subject_summary"],
         row["occurrence_date"], row["reporter_name"], row["receiver_id"],
         row["is_reported"], row["is_electronic"]))
    conn.commit()


class TestMapping(unittest.TestCase):
    def test_gen_to_crim_common(self):
        m = doc_convert.mapGenToCrim(dict(
            report_date="d", sender_id="P01", processor_id="P02",
            subject="主旨X", is_reported=1))
        self.assertEqual(m["subject_summary"], "主旨X")   # 主旨欄名互換
        self.assertEqual(m["processor_id"], "P02")
        self.assertEqual(m["is_reported"], 1)
        self.assertNotIn("case_type", m)                  # 補填欄不在共通映射

    def test_crim_to_gen_common(self):
        m = doc_convert.mapCrimToGen(dict(
            report_date="d", sender_id="P01", processor_id="P02",
            subject_summary="主旨Y", is_reported=0))
        self.assertEqual(m["subject"], "主旨Y")           # 主旨欄名互換
        self.assertNotIn("subject_summary", m)


class TestRenamePk(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(
            doc_convert.renamePdfWithNewPk("37-1150628-主旨-人.pdf", "12"),
            "12-1150628-主旨-人.pdf")

    def test_fullwidth_dash(self):
        self.assertEqual(
            doc_convert.renamePdfWithNewPk("37－1150628－主旨.pdf", "12"),
            "12－1150628－主旨.pdf")

    def test_no_dash(self):
        self.assertEqual(doc_convert.renamePdfWithNewPk("37.pdf", "12"), "12.pdf")

    def test_no_ext(self):
        self.assertEqual(doc_convert.renamePdfWithNewPk("37-abc", "12"), "12-abc")


class TestLostFields(unittest.TestCase):
    def setUp(self):
        self.conn = _make_db()

    def tearDown(self):
        self.conn.close()

    def test_crim_lost_five(self):
        nr = doc_convert.makeNameResolver(self.conn)
        row = dict(case_type="CT01", case_status="CS01",
                   occurrence_date="2026-06-20", receiver_id="P03",
                   reporter_name="張老闆")
        lost = dict(doc_convert.lostFields("crim", row, nr))
        self.assertEqual(lost["案類"], "竊盜案")
        self.assertEqual(lost["發文分類"], "現行")
        self.assertEqual(lost["受理日期"], "2026-06-20")
        self.assertEqual(lost["受理人"], "林大偉")
        self.assertEqual(lost["報案人"], "張老闆")

    def test_gen_lost_two(self):
        nr = doc_convert.makeNameResolver(self.conn)
        row = dict(dept_id="D01", gen_cat_id="GC01")
        lost = dict(doc_convert.lostFields("gen", row, nr))
        self.assertEqual(lost["業務單位"], "偵查隊")
        self.assertEqual(lost["分類"], "業務")

    def test_empty_values_omitted(self):
        nr = doc_convert.makeNameResolver(self.conn)
        row = dict(case_type="CT01", case_status=None, occurrence_date=None,
                   receiver_id=None, reporter_name="")
        lost = dict(doc_convert.lostFields("crim", row, nr))
        self.assertEqual(list(lost.keys()), ["案類"])   # 空值省略


class TestConvertRoundTrip(unittest.TestCase):
    def setUp(self):
        self.conn = _make_db()

    def tearDown(self):
        self.conn.close()

    def _audit(self):
        return self.conn.execute(
            "SELECT role, action, target_table, target_id, operator, detail "
            "FROM Audit_Log ORDER BY log_id DESC LIMIT 1").fetchone()

    def test_gen_to_crim(self):
        _insert_gen(self.conn, doc_id="20")
        nr = doc_convert.makeNameResolver(self.conn)
        new_id, snap = doc_convert.convertDoc(
            self.conn, src_kind="gen", doc_id="20",
            fill_values=dict(case_type="CT01", case_status="CS02",
                             occurrence_date="2026-06-20", receiver_id="P03",
                             reporter_name="張老闆"),
            role="admin", operator="王小明", name_resolver=nr)
        self.conn.commit()

        self.assertEqual(new_id, "6")                     # 目標刑案表 Seq 5+1
        crim = self.conn.execute(
            "SELECT subject_summary,processor_id,case_type,case_status,"
            "occurrence_date,receiver_id,reporter_name,is_reported "
            "FROM Document_Criminal WHERE doc_id='6'").fetchone()
        self.assertEqual(crim[0], "超商竊盜案移送")        # 主旨帶過
        self.assertEqual(crim[1], "P02")                  # 陳報人→承辦人
        self.assertEqual(crim[2], "CT01")                 # 補填
        self.assertEqual(crim[7], 1)                      # is_reported 照搬

        # 來源表 Seq 不動
        seq_gen = self.conn.execute(
            "SELECT last_id FROM Seq_DocId WHERE table_name='Document_General'"
        ).fetchone()[0]
        self.assertEqual(seq_gen, 20)

        # 原列成空殼
        old = self.conn.execute(
            "SELECT subject,report_date,dept_id FROM Document_General "
            "WHERE doc_id='20'").fetchone()
        self.assertEqual(old, (None, None, None))

        # 稽核一筆、含雙號與丟失欄
        a = self._audit()
        self.assertEqual(a[1], "轉換")
        self.assertEqual(a[2], "Document_Criminal")
        self.assertEqual(a[3], "6")
        self.assertIn("一般20→刑案6", a[5])
        self.assertIn("業務單位=偵查隊", a[5])            # 丟失欄顯示名

        # 不進回收筒
        n = self.conn.execute("SELECT COUNT(*) FROM Trash_Documents").fetchone()[0]
        self.assertEqual(n, 0)

    def test_crim_to_gen(self):
        _insert_crim(self.conn, doc_id="5")
        nr = doc_convert.makeNameResolver(self.conn)
        new_id, _ = doc_convert.convertDoc(
            self.conn, src_kind="crim", doc_id="5",
            fill_values=dict(dept_id="D01", gen_cat_id="GC01"),
            role="archive", operator="陳志豪", name_resolver=nr)
        self.conn.commit()

        self.assertEqual(new_id, "21")                    # 一般 Seq 20+1
        gen = self.conn.execute(
            "SELECT subject,dept_id,gen_cat_id,is_reported FROM Document_General "
            "WHERE doc_id='21'").fetchone()
        self.assertEqual(gen[0], "超商竊盜案移送")
        self.assertEqual(gen[1], "D01")
        self.assertEqual(gen[2], "GC01")
        a = self._audit()
        self.assertIn("刑案5→一般21", a[5])
        self.assertIn("受理人=林大偉", a[5])

    def test_is_electronic_param(self):
        _insert_gen(self.conn, doc_id="20", is_electronic="20-old.pdf")
        new_id, _ = doc_convert.convertDoc(
            self.conn, src_kind="gen", doc_id="20",
            fill_values=dict(case_type="CT01", case_status="CS01",
                             occurrence_date="2026-06-20"),
            role="admin", operator="王小明", is_electronic="21-new.pdf")
        self.conn.commit()
        ie = self.conn.execute(
            "SELECT is_electronic FROM Document_Criminal WHERE doc_id=?",
            (new_id,)).fetchone()[0]
        self.assertEqual(ie, "21-new.pdf")

    def test_rollback_on_pk_clash(self):
        # 先佔用目標表下一號 21，使 INSERT 撞 PK → 整個 transaction 回滾
        _insert_gen(self.conn, doc_id="20")
        _insert_crim(self.conn, doc_id="6")              # 佔住刑案下一號 6
        nr = doc_convert.makeNameResolver(self.conn)
        with self.assertRaises(sqlite3.IntegrityError):
            doc_convert.convertDoc(
                self.conn, src_kind="gen", doc_id="20",
                fill_values=dict(case_type="CT01", case_status="CS01",
                                 occurrence_date="2026-06-20"),
                role="admin", operator="王小明", name_resolver=nr)
        self.conn.rollback()
        # 原列不變
        old = self.conn.execute(
            "SELECT subject FROM Document_General WHERE doc_id='20'").fetchone()
        self.assertEqual(old[0], "超商竊盜案移送")


if __name__ == "__main__":
    unittest.main()
