# -*- coding: utf-8 -*-
"""罰單簽收表（tabs/tab_print.py）純邏輯層：排序、六欄（三直欄）分組、分頁。

只測 sortTicketRows／paginateTicketRows／buildTicketGrid／drawTicketPage
四個不依賴 DB／不彈視窗的函式，不驗證實際視覺（不產生／不目視 PDF）。

⚠️ 與 brief 範例程式碼索引的偏離（已在交付報告說明）：buildTicketGrid 的
回傳為「三個直欄」（`grid[band_index]`，band 0=左／1=中／2=右），而非
「每列三欄」。brief 範例中 `page[0][2]` 在 body_rows=2、共 4 筆同人資料時
無法成立——3 欄依序（左→中→右）各裝滿 body_rows 才會換下一欄，4 筆只夠
裝滿左欄（2 筆）與中欄（2 筆），右欄（index 2）必然是空清單，不可能還有
第 3 筆資料可供斷言 rowspan。故改用 `grid[1][0]`（中欄第一列）驗證同一件
事：跨欄必須重建群組、重新顯示姓名，並另外用 6 筆資料驗證右欄（index 2）
也一樣重建群組（覆蓋 body_rows=2×3 欄的滿版情境）。
"""
import os
import sqlite3
import sys
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import db_schema, db_seed, db_utils
from lib.ticket_utils import createTicket
from ui_utils.settle_dialog import settle_selected

import tabs.tab_print as tab_print_module
from tabs.tab_print import (
    TICKET_FINAL_ROWS, TICKET_FULL_ROWS, TICKET_SUB_HEADERS, TICKET_SUMMARY_H,
    TicketCell, TicketPage, ROW_H, _TICKET_SUB_RATIOS,
    buildTicketGrid, drawTicketPage, paginateTicketRows, queryTicketPrintRows,
    sortTicketRows,
)


def _row(issuer_sort_order, issuer_name, ticket_no, issuer_id=None, doc_id=None):
    return {
        "doc_id": doc_id or ticket_no,
        "ticket_no": ticket_no,
        "issuer_id": issuer_id or issuer_name,
        "issuer_name": issuer_name,
        "issuer_sort_order": issuer_sort_order,
    }


class TicketPrintTestCase(unittest.TestCase):
    def _rows(self, name, ticket_nos, sort_order=1, issuer_id=None):
        return [_row(sort_order, name, no, issuer_id=issuer_id) for no in ticket_nos]


# ── sortTicketRows／paginateTicketRows ──────────────────────
class TestTicketSortAndPaginate(TicketPrintTestCase):
    def test_ticket_sort_and_column_fill(self):
        rows = [
            {"issuer_sort_order": 2, "issuer_name": "李大華", "ticket_no": "B2"},
            {"issuer_sort_order": 1, "issuer_name": "王小明", "ticket_no": "A2"},
            {"issuer_sort_order": 1, "issuer_name": "王小明", "ticket_no": "A1"},
        ]
        page = paginateTicketRows(rows, full_rows=2, final_rows=1)[0]
        self.assertEqual(page.items[0].ticket_no, "A1")
        self.assertEqual(page.items[1].ticket_no, "A2")
        self.assertEqual(page.items[2].ticket_no, "B2")

    def test_sort_key_ignores_ticket_no_case(self):
        # "a1" vs "B1"：ASCII 原始排序（無 .upper()）會是 B1 在前（'B'=66
        # < 'a'=97）；正規化為大寫後排序則是 a1（大寫 A1）在前。兩者結果
        # 不同，才能有效斷住「排序 key 有沒有做 .upper()」。
        rows = [
            {"issuer_sort_order": 1, "issuer_name": "王小明", "ticket_no": "a1"},
            {"issuer_sort_order": 1, "issuer_name": "王小明", "ticket_no": "B1"},
        ]
        cells = sortTicketRows(rows)
        self.assertEqual([c.ticket_no for c in cells], ["a1", "B1"])

    def test_only_final_page_has_summary(self):
        pages = paginateTicketRows(
            self._rows("王小明", [f"A{i:02}" for i in range(20)]),
            full_rows=3, final_rows=2)
        self.assertTrue(all(not p.show_summary for p in pages[:-1]))
        self.assertTrue(pages[-1].show_summary)
        self.assertEqual(pages[-1].total_count, 20)

    def test_zero_rows_returns_empty_page_list(self):
        # 0 筆：回空清單（比照既有 _build_sections「查無資料不產生 section」
        # 慣例），呼叫端應以 `if ticket_rows:` 才呼叫，不會印出空白簽收頁。
        self.assertEqual(paginateTicketRows([], full_rows=2, final_rows=1), [])

    def test_single_row(self):
        pages = paginateTicketRows(self._rows("王小明", ["A1"]),
                                    full_rows=2, final_rows=1)
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].show_summary)
        self.assertEqual(pages[0].total_count, 1)

    def test_exactly_final_capacity(self):
        # 剛好等於末頁容量（final_rows=1 → 3 筆）：單頁即可，全部有 summary。
        pages = paginateTicketRows(self._rows("王小明", ["A1", "A2", "A3"]),
                                    full_rows=2, final_rows=1)
        self.assertEqual(len(pages), 1)
        self.assertEqual(len(pages[0].items), 3)
        self.assertTrue(pages[0].show_summary)

    def test_final_capacity_plus_one(self):
        # 末頁容量 +1（final_rows=1 → 3 筆 +1 = 4 筆）：必須拆成 2 頁，
        # 且末頁不得為 0 筆（brief 虛擬碼會在此情境把末頁吃成空頁）。
        pages = paginateTicketRows(self._rows("王小明", [f"A{i}" for i in range(4)]),
                                    full_rows=3, final_rows=1)
        self.assertEqual(len(pages), 2)
        self.assertFalse(pages[0].show_summary)
        self.assertTrue(pages[1].show_summary)
        self.assertGreater(len(pages[1].items), 0)
        self.assertLessEqual(len(pages[1].items), 3)
        self.assertEqual(sum(len(p.items) for p in pages), 4)

    def test_full_capacity_plus_final_capacity_splits_cleanly(self):
        # full_capacity(9) + final_capacity(6) = 15：應恰好切成 [9, 6] 兩頁。
        pages = paginateTicketRows(
            self._rows("王小明", [f"A{i:02}" for i in range(15)]),
            full_rows=3, final_rows=2)
        self.assertEqual([len(p.items) for p in pages], [9, 6])
        self.assertFalse(pages[0].show_summary)
        self.assertTrue(pages[1].show_summary)

    def test_non_final_pages_fill_greedily(self):
        # 貼近真實容量：full_rows=15（capacity 45）、final_rows=13
        # （capacity 39）。非末頁應盡量填滿（每頁 45 筆），不得像舊公式
        # 「只取剛好留給末頁的量」導致非末頁大量留白（例如舊版 total=100
        # 會產生 [45, 16, 39]，第 2 頁只用 16/45）。
        pages = paginateTicketRows(
            self._rows("王小明", [f"A{i:03}" for i in range(100)]),
            full_rows=15, final_rows=13)
        sizes = [len(p.items) for p in pages]
        self.assertEqual(sizes, [45, 45, 10])
        self.assertEqual(sum(sizes), 100)
        self.assertTrue(all(not p.show_summary for p in pages[:-1]))
        self.assertTrue(pages[-1].show_summary)

    def test_invalid_capacity_raises_instead_of_hanging(self):
        # full_rows/final_rows 非正整數：必須明確拋例外，不得造成
        # `full_rows*3==0` 時的無窮迴圈。
        with self.assertRaises(ValueError):
            paginateTicketRows(self._rows("王小明", ["A1"]), full_rows=0, final_rows=1)
        with self.assertRaises(ValueError):
            paginateTicketRows(self._rows("王小明", ["A1"]), full_rows=1, final_rows=0)


# ── buildTicketGrid（群組限於「欄內」，跨欄／跨頁必重建）──────
class TestTicketGridRowspan(TicketPrintTestCase):
    def test_single_column_group_gets_local_rowspan(self):
        rows = self._rows("王小明", ["A1", "A2"])
        grid = buildTicketGrid(rows, body_rows=2)
        self.assertEqual(grid[0][0].issuer_rowspan, 2)
        self.assertEqual(grid[0][0].issuer_name, "王小明")
        # 群組內非起始列：rowspan=0、姓名清空（renderer 不重覆畫姓名）
        self.assertEqual(grid[0][1].issuer_rowspan, 0)
        self.assertEqual(grid[0][1].issuer_name, "")

    def test_same_person_merges_per_vertical_group_only(self):
        # 4 筆同一人、body_rows=2：左欄裝滿 2 筆（A1,A2）、中欄裝滿 2 筆
        # （A3,A4）、右欄空。驗證「同一人」在左右兩欄各自形成獨立群組，
        # 不會被合併成跨欄的一個 rowspan=4。
        rows = self._rows("王小明", ["A1", "A2", "A3", "A4"])
        grid = buildTicketGrid(rows, body_rows=2)
        self.assertEqual(grid[0][0].issuer_rowspan, 2)
        self.assertEqual(grid[0][0].ticket_no, "A1")
        # 跨欄重建群組＋重新顯示姓名：中欄第一列雖是同一人，仍是新群組起點
        self.assertEqual(grid[1][0].issuer_name, "王小明")
        self.assertEqual(grid[1][0].issuer_rowspan, 2)
        self.assertEqual(grid[1][0].ticket_no, "A3")
        self.assertEqual(grid[2], [])

    def test_same_person_spans_all_three_columns_independently(self):
        # 6 筆同一人、body_rows=2：三欄各裝滿 2 筆，三個獨立群組。
        rows = self._rows("王小明", [f"A{i}" for i in range(1, 7)])
        grid = buildTicketGrid(rows, body_rows=2)
        for band in grid:
            self.assertEqual(len(band), 2)
            self.assertEqual(band[0].issuer_rowspan, 2)
            self.assertEqual(band[0].issuer_name, "王小明")
            self.assertEqual(band[1].issuer_rowspan, 0)

    def test_different_person_does_not_merge(self):
        rows = (self._rows("王小明", ["A1"], issuer_id="P1")
                + self._rows("李大華", ["A2"], issuer_id="P2"))
        grid = buildTicketGrid(rows, body_rows=2)
        self.assertEqual(grid[0][0].issuer_rowspan, 1)
        self.assertEqual(grid[0][1].issuer_rowspan, 1)
        self.assertEqual(grid[0][1].issuer_name, "李大華")

    def test_cross_page_does_not_merge(self):
        # 跨頁：同一人剛好卡在分頁邊界，兩頁各自呼叫 buildTicketGrid，
        # 群組互不相通（不會有「上一頁最後一列」影響「下一頁第一列」）。
        pages = paginateTicketRows(self._rows("王小明", [f"A{i}" for i in range(4)]),
                                    full_rows=1, final_rows=1)
        self.assertEqual(len(pages), 2)
        grid1 = buildTicketGrid(pages[0].items, body_rows=1)
        grid2 = buildTicketGrid(pages[1].items, body_rows=1)
        self.assertEqual(grid1[0][0].issuer_rowspan, 1)
        self.assertEqual(grid2[0][0].issuer_rowspan, 1)
        self.assertEqual(grid2[0][0].issuer_name, "王小明")

    def test_zero_rows_grid_is_three_empty_bands(self):
        grid = buildTicketGrid([], body_rows=2)
        self.assertEqual(grid, [[], [], []])

    def test_over_capacity_raises(self):
        rows = self._rows("王小明", [f"A{i}" for i in range(7)])
        with self.assertRaises(ValueError):
            buildTicketGrid(rows, body_rows=2)   # 容量 6，給 7 筆

    def test_invalid_body_rows_raises(self):
        with self.assertRaises(ValueError):
            buildTicketGrid(self._rows("王小明", ["A1"]), body_rows=0)


# ── drawTicketPage（renderer：只消費已整理好的資料，不得再做決策）──
class TestDrawTicketPage(TicketPrintTestCase):
    def test_draws_without_error_and_returns_figure(self):
        import matplotlib.figure
        rows = self._rows("王小明", ["A1", "A2", "A3"])
        grid = buildTicketGrid(rows, body_rows=2)
        fig = drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=2, page_num=1, total_pages=1,
            show_summary=True, total_count=3)
        try:
            self.assertIsInstance(fig, matplotlib.figure.Figure)
        finally:
            import matplotlib.pyplot as plt
            plt.close(fig)

    def test_draws_empty_grid_without_error(self):
        import matplotlib.pyplot as plt
        fig = drawTicketPage(
            [[], [], []], table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=2, page_num=1, total_pages=1)
        plt.close(fig)

    def test_six_columns_no_signature_subcolumn(self):
        # C1：spec §11.1 每頁三組並排、共六欄（開立人員｜罰單編號 ×3）；
        # Task 8 骨架多出的逐列「簽收」子欄已移除。
        self.assertEqual(TICKET_SUB_HEADERS, ("開立人員", "罰單編號"))
        full_headers = TICKET_SUB_HEADERS * 3
        self.assertEqual(len(full_headers), 6)
        self.assertNotIn("簽收", full_headers)

    def test_issuer_column_narrower_than_number_column(self):
        # C2：spec §11.1「開立人員欄略窄，罰單編號欄略寬」。
        self.assertEqual(len(_TICKET_SUB_RATIOS), 2)
        issuer_ratio, number_ratio = _TICKET_SUB_RATIOS
        self.assertLess(issuer_ratio, number_ratio)
        self.assertAlmostEqual(issuer_ratio + number_ratio, 1.0)

    def test_summary_area_is_at_least_two_row_heights(self):
        # I3／mutation guard：末頁簽收人區高度至少為一般明細列的兩倍。
        self.assertGreaterEqual(TICKET_SUMMARY_H, 2 * ROW_H)

    def test_capacity_constants_are_fixed_renderer_constants(self):
        # M1：容量固定為 renderer 常數，不依電腦環境變動；並防呆不衝出版面
        # （既有 ROW_H=0.052、可用高約 0.802 → 上限約 15 列）。
        from tabs.tab_print import (
            BOT, DATE_H, HDR_H, TITLE_H, TOP, TICKET_SUMMARY_H as _SUM_H,
        )
        self.assertIsInstance(TICKET_FULL_ROWS, int)
        self.assertIsInstance(TICKET_FINAL_ROWS, int)
        self.assertGreaterEqual(TICKET_FULL_ROWS, 1)
        self.assertLessEqual(TICKET_FULL_ROWS, 15)
        self.assertGreater(TICKET_FULL_ROWS, TICKET_FINAL_ROWS)

        # 推導式本身：可用高度＝TOP-DATE_H-TITLE_H-HDR_H-BOT，末頁再扣一次
        # TICKET_SUMMARY_H；容量＝可用高度整除 ROW_H（無條件捨去）。
        avail = TOP - DATE_H - TITLE_H - HDR_H - BOT
        self.assertEqual(TICKET_FULL_ROWS, min(15, int(avail / ROW_H)))
        self.assertEqual(TICKET_FINAL_ROWS,
                          min(15, int((avail - _SUM_H) / ROW_H)))

        # 表格底部不得低於 BOT（非末頁明細填滿 TICKET_FULL_ROWS 列時）。
        table_bottom = TOP - DATE_H - TITLE_H - HDR_H - ROW_H * TICKET_FULL_ROWS
        self.assertGreaterEqual(table_bottom, BOT)
        # 末頁：明細 + summary 區底部同樣不得低於 BOT。
        final_bottom = (TOP - DATE_H - TITLE_H - HDR_H
                         - ROW_H * TICKET_FINAL_ROWS - _SUM_H)
        self.assertGreaterEqual(final_bottom, BOT)

    def test_header_and_title_are_inside_outer_box(self):
        # F1 regression：外框須涵蓋標題帶與欄名列，直欄線須穿過欄名列
        # （穿到 header_top），不能像舊版只從欄名列下緣（table_top）開始，
        # 否則標題帶／欄名列會被畫在外框之外、六個欄名之間沒有分隔線。
        from tabs.tab_print import DATE_H, TITLE_H, TOP

        title_top = TOP - DATE_H
        header_top = title_top - TITLE_H

        rows = self._rows("王小明", ["A1", "A2"], issuer_id="P1")
        grid = buildTicketGrid(rows, body_rows=2)

        import matplotlib.pyplot as plt
        fig = drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=2, page_num=1, total_pages=1)
        try:
            ax = fig.axes[0]

            outer_boxes = [
                p for p in ax.patches
                if getattr(p, 'get_linewidth', None)
                and abs(p.get_linewidth() - 1.2) < 1e-6
            ]
            self.assertEqual(len(outer_boxes), 1, "應恰有一個外框")
            box = outer_boxes[0]
            box_top_y = box.get_y() + box.get_height()
            self.assertAlmostEqual(
                box_top_y, title_top, places=3,
                msg="外框上緣須涵蓋標題帶，不能只從欄名列下緣（table_top）開始")

            # 5 條內部直線（2 條組間分隔線＋3 條組內子欄分隔線）須穿過欄名列，
            # 上緣須到達 header_top（標題帶不分欄，欄名列須分欄）。
            vlines = [
                l for l in ax.lines
                if len(l.get_xdata()) == 2 and len(set(l.get_xdata())) == 1
                and len(set(round(y, 6) for y in l.get_ydata())) == 2
            ]
            touching_header = [
                l for l in vlines
                if abs(max(l.get_ydata()) - header_top) < 1e-3
            ]
            self.assertEqual(
                len(touching_header), 5,
                "欄名列高度範圍內應有 5 條內部直線（六個欄名各自有邊界）")
        finally:
            plt.close(fig)

    def test_long_ticket_no_is_clipped_not_bleeding_into_neighbor(self):
        # F2 regression：超長罰單編號（20 字元）在 min_size=8pt 觸底時仍可能
        # 比格寬還寬，text 必須被裁在自己格子的 bbox 內，不得沒有裁切
        # （沒裁切＝會畫出跨過欄線壓到鄰欄的字）。
        from tabs.tab_print import TABLE_L, TABLE_W, _TICKET_SUB_RATIOS as ratios

        long_no = "A" * 20
        rows = self._rows("王小明", [long_no], issuer_id="P1")
        grid = buildTicketGrid(rows, body_rows=1)

        import matplotlib.pyplot as plt
        fig = drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=1, page_num=1, total_pages=1)
        try:
            ax = fig.axes[0]
            band_w = TABLE_W / 3
            no_x0 = TABLE_L + band_w * ratios[0]
            no_x1 = TABLE_L + band_w

            no_texts = [t for t in ax.texts if t.get_text() == long_no]
            self.assertEqual(len(no_texts), 1, "應找到罰單編號文字物件")
            txt = no_texts[0]
            self.assertTrue(txt.get_clip_on(), "超長編號必須開啟裁切，避免溢出鄰欄")
            clip_box = txt.get_clip_box()
            self.assertIsNotNone(clip_box, "超長編號必須有明確的裁切範圍")
            # clip_box 以 display 座標儲存，轉回 axes 座標比對格子邊界。
            inv = ax.transAxes.inverted()
            (cx0, _cy0), (cx1, _cy1) = inv.transform(clip_box.get_points())
            self.assertAlmostEqual(min(cx0, cx1), no_x0, places=3)
            self.assertAlmostEqual(max(cx0, cx1), no_x1, places=3)
        finally:
            plt.close(fig)

    def test_merged_issuer_group_skips_only_internal_issuer_line(self):
        # I2／F3：issuer 合併區只移除合併內部的 issuer 水平線，保留 number
        # 格水平線。用 rowspan=3（列0-2）＋rowspan=2（列3-4）＋rowspan=1
        # （列5）、body_rows=6，確保能抓到 rowspan≥3 的回歸（body_rows=2
        # 時 row_boundary_ys[0] 是恆真、抓不到這類問題）。
        rows = (self._rows("王小明", ["A1", "A2", "A3"], issuer_id="P1")
                + self._rows("李大華", ["B1", "B2"], issuer_id="P2")
                + self._rows("陳小美", ["C1"], issuer_id="P3"))
        grid = buildTicketGrid(rows, body_rows=6)
        self.assertEqual(grid[0][0].issuer_rowspan, 3)
        self.assertEqual(grid[0][1].issuer_rowspan, 0)
        self.assertEqual(grid[0][2].issuer_rowspan, 0)
        self.assertEqual(grid[0][3].issuer_rowspan, 2)
        self.assertEqual(grid[0][4].issuer_rowspan, 0)
        self.assertEqual(grid[0][5].issuer_rowspan, 1)

        import matplotlib.pyplot as plt
        from tabs.tab_print import DATE_H, HDR_H, TABLE_L, TABLE_W, TITLE_H, TOP

        fig = drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=6, page_num=1, total_pages=1)
        try:
            ax = fig.axes[0]
            band_w = TABLE_W / 3
            table_top = TOP - DATE_H - TITLE_H - HDR_H

            def _boundary_y(ridx):
                return table_top - ROW_H * ridx

            def _has_line(x0, x1, y):
                for l in ax.lines:
                    xs, ys = l.get_xdata(), l.get_ydata()
                    if len(xs) != 2 or len(set(ys)) != 1:
                        continue
                    if abs(ys[0] - y) > 1e-6:
                        continue
                    if abs(min(xs) - x0) < 1e-6 and abs(max(xs) - x1) < 1e-6:
                        return True
                return False

            issuer_ratio, number_ratio = _TICKET_SUB_RATIOS
            band0_left = TABLE_L
            issuer_x0, issuer_x1 = band0_left, band0_left + band_w * issuer_ratio
            number_x0, number_x1 = issuer_x1, band0_left + band_w

            # r1、r2（群組 A 內部）、r4（群組 B 內部）：不應有 issuer 線。
            for ridx in (1, 2, 4):
                ry = _boundary_y(ridx)
                self.assertFalse(
                    _has_line(issuer_x0, issuer_x1, ry),
                    f"r{ridx}（合併群組內部）不應保留 issuer 水平線")

            # r3（A/B 交界）、r5（B/C 交界）：群組起點，應有 issuer 線。
            for ridx in (3, 5):
                ry = _boundary_y(ridx)
                self.assertTrue(
                    _has_line(issuer_x0, issuer_x1, ry),
                    f"r{ridx}（群組交界）應保留 issuer 水平線")

            # number 子欄水平線：每張罰單編號各占一格，r1-r5 全部都要在。
            for ridx in range(1, 6):
                ry = _boundary_y(ridx)
                self.assertTrue(
                    _has_line(number_x0, number_x1, ry),
                    f"r{ridx} number 子欄水平線必須保留")
        finally:
            plt.close(fig)


# ── queryTicketPrintRows（簽收日固定為 register_date）─────────
class TestQueryTicketPrintRows(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        db_schema.applySchema(conn)
        db_seed.seedFreshDb(conn)
        conn.execute(
            "INSERT OR REPLACE INTO Ref_Personnel"
            "(staff_id,staff_name,is_active,sort_order) VALUES('P1','王小明',1,1)")
        # create_date（登錄日）與 register_date（發文／取號日）刻意不同，
        # 才能實際驗到「用哪個欄名查」而非兩者剛好同值時的假綠。
        conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES('9001','2026-07-20','2026-07-23','P1','P1','D4RD15263')")
        conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES('9002','2026-07-23','','P1','P1','UNISSUED001')")
        # 發文者登錄模式：register_date=create_date（同 ticket_utils.createTicket
        # 非自助分支的寫入語意）。
        conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES('9003','2026-07-23','2026-07-23','P1','P1','A1234567')")
        conn.commit()
        conn.close()

    def tearDown(self):
        os.remove(self.db_path)

    def _set_self_service(self, on):
        db_utils.setSetting(self.db_path, db_utils.REPORT_MODE_KEYS["ticket"],
                             "1" if on else "0")

    def test_self_service_ticket_settled_after_mode_switch_prints_by_register_date(self):
        """自助建立後切回送文者模式，隔日結算仍以資料本身的簽收日列印。"""
        self._set_self_service(True)
        conn = sqlite3.connect(self.db_path)
        try:
            doc_id = createTicket(
                conn, issuer_id="P1", ticket_no="SELF20260720", self_service=True,
                sender_id=None, create_date="2026-07-20", role="user")
            conn.commit()
        finally:
            conn.close()

        self._set_self_service(False)
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(
                settle_selected(conn, {"crim": [], "gen": [], "ticket": [doc_id]},
                                "2026-07-21", "P1"),
                1,
            )
        finally:
            conn.close()

        settled_rows = queryTicketPrintRows(self.db_path, "2026-07-21")
        self.assertIn("SELF20260720", [r["ticket_no"] for r in settled_rows])
        created_rows = queryTicketPrintRows(self.db_path, "2026-07-20")
        self.assertNotIn("SELF20260720", [r["ticket_no"] for r in created_rows])

    def test_issued_rows_exclude_unissued_and_keep_ticket_sort_order(self):
        rows = queryTicketPrintRows(self.db_path, "2026-07-23")
        ticket_nos = [row["ticket_no"] for row in rows]
        self.assertNotIn("UNISSUED001", ticket_nos)
        self.assertEqual(ticket_nos, ["A1234567", "D4RD15263"])

    def test_no_data_returns_empty_list(self):
        self._set_self_service(True)
        self.assertEqual(queryTicketPrintRows(self.db_path, "2099-01-01"), [])



if __name__ == "__main__":
    unittest.main()
