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

from matplotlib.patches import FancyBboxPatch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib import db_schema, db_seed, db_utils
from lib.print_canvas import LineOp, RecordingCanvas, RectOp, TextOp
from lib.ticket_utils import createTicket
from ui_utils.settle_dialog import settle_selected

import tabs.tab_print as tab_print
from tabs.tab_print import (
    TICKET_BODY_H, TICKET_ROWS_PER_BAND, TICKET_ROW_H, TICKET_SUB_HEADERS,
    TICKET_SUMMARY_H, TicketCell, TicketPage, ROW_H, _TICKET_SUB_RATIOS,
    buildTicketGrid, drawTicketPage, paginateTicketRows, queryTicketPrintRows,
    sortTicketRows,
)

def _paginate_rows(rows):
    return paginateTicketRows(rows)


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
        page = _paginate_rows(rows)[0]
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

    def test_sort_uses_shared_natural_ticket_number_order(self):
        rows = self._rows(
            "王小明", ["A10B10", "A2", "A01", "A1", "A10B2", "A10"])
        cells = sortTicketRows(rows)
        self.assertEqual(
            [cell.ticket_no for cell in cells],
            ["A1", "A01", "A2", "A10", "A10B2", "A10B10"],
        )

    def test_capacity_boundaries_and_every_page_summary_counts(self):
        cases = {
            0: [],
            1: [1],
            59: [59],
            60: [60],
            61: [60, 1],
            120: [60, 60],
            121: [60, 60, 1],
        }
        for count, expected_sizes in cases.items():
            with self.subTest(count=count):
                rows = self._rows(
                    "王小明", [f"A{i:03}" for i in range(count)])
                pages = _paginate_rows(rows)
                self.assertEqual([len(page.items) for page in pages],
                                 expected_sizes)
                self.assertTrue(all(page.show_summary for page in pages))
                self.assertTrue(all(page.total_count == count for page in pages))

    def test_zero_rows_returns_empty_page_list(self):
        # 0 筆：回空清單（比照既有 _build_sections「查無資料不產生 section」
        # 慣例），呼叫端應以 `if ticket_rows:` 才呼叫，不會印出空白簽收頁。
        self.assertEqual(_paginate_rows([]), [])

    def test_single_row(self):
        pages = _paginate_rows(self._rows("王小明", ["A1"]))
        self.assertEqual(len(pages), 1)
        self.assertTrue(pages[0].show_summary)
        self.assertEqual(pages[0].total_count, 1)


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
        pages = _paginate_rows(
            self._rows("王小明", [f"A{i}" for i in range(61)]))
        self.assertEqual(len(pages), 2)
        grid1 = buildTicketGrid(
            pages[0].items, body_rows=TICKET_ROWS_PER_BAND)
        grid2 = buildTicketGrid(
            pages[1].items, body_rows=TICKET_ROWS_PER_BAND)
        self.assertEqual(grid1[0][0].issuer_rowspan, TICKET_ROWS_PER_BAND)
        self.assertEqual(grid2[0][0].issuer_rowspan, 1)
        self.assertEqual(grid2[0][0].issuer_name, "王小明")

    def test_irregular_groups_split_at_band_boundary_and_repeat_name(self):
        counts = [5, 10, 13, 3, 1, 8, 2, 7, 6, 5]
        rows = []
        for person_index, count in enumerate(counts, start=1):
            rows.extend(self._rows(
                f"人員{person_index:02}", [
                    f"T{person_index:02}-{ticket_index:02}"
                    for ticket_index in range(1, count + 1)
                ],
                sort_order=person_index,
                issuer_id=f"P{person_index:02}",
            ))

        page = _paginate_rows(rows)[0]
        grid = buildTicketGrid(
            page.items, body_rows=TICKET_ROWS_PER_BAND)

        self.assertEqual([len(band) for band in grid], [20, 20, 20])
        self.assertEqual(
            [cell.ticket_no for cell in grid[0][-5:]],
            [f"T03-{i:02}" for i in range(1, 6)])
        self.assertEqual(
            [cell.ticket_no for cell in grid[1][:8]],
            [f"T03-{i:02}" for i in range(6, 14)])
        self.assertEqual(grid[0][-5].issuer_name, "人員03")
        self.assertEqual(grid[0][-5].issuer_rowspan, 5)
        self.assertEqual(grid[1][0].issuer_name, "人員03")
        self.assertEqual(grid[1][0].issuer_rowspan, 8)
        one_row_group = next(
            cell for band in grid for cell in band
            if cell.issuer_name == "人員05")
        self.assertEqual(one_row_group.issuer_rowspan, 1)

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
# ⚠️ 階段 3：`canvas` 改為必填，`drawTicketPage()` 本身不再建立／回傳
# matplotlib Figure（見 tabs/tab_print.py 檔頭與 STAGE3-BRIEF §2）。需要
# 真實 Figure 的測試改用 `tools/mpl_canvas.py::new_mpl_page()` 自行建立
# 一頁、傳入 `canvas=`，再對呼叫端自己持有的 `fig` 斷言——與原本「呼叫
# drawTicketPage() 拿到 fig」等價，只是 fig 的來源從回傳值改成呼叫端
# 自建（型別相關寫法變動，斷言強度不變：兩者都是驗證「真的用 matplotlib
# 畫出一個有效 Figure，過程不拋例外」）。
class TestDrawTicketPage(TicketPrintTestCase):
    # 階段 3：產品預設量測器改用 Qt（見 tabs/tab_print.py::_qt_text_width_pt），
    # `_wrap_clamp()`／`_fit_font()` 在 `drawTicketPage()` 內部一律會呼叫到，
    # 不論最終畫在哪種 canvas 上——`QFontDatabase` 需要先有 QGuiApplication
    # 實例才能用（見 lib/print_canvas.py::_load_font_family()），否則直接
    # RuntimeError。比照 tests/test_reward_print.py 既有作法補上。
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_draws_without_error_and_returns_figure(self):
        import matplotlib.figure
        import matplotlib.pyplot as plt
        from tools.mpl_canvas import new_mpl_page
        rows = self._rows("王小明", ["A1", "A2", "A3"])
        grid = buildTicketGrid(rows, body_rows=2)
        fig, cv = new_mpl_page(tab_print.fp)
        try:
            drawTicketPage(
                grid, table_title="○○分局罰單簽收表",
                print_date="2026/07/25", disp_date="2026/07/25",
                body_rows=2, page_num=1, total_pages=1,
                show_summary=True, total_count=3, canvas=cv)
            self.assertIsInstance(fig, matplotlib.figure.Figure)
        finally:
            plt.close(fig)

    def test_draws_empty_grid_without_error(self):
        import matplotlib.pyplot as plt
        from tools.mpl_canvas import new_mpl_page
        fig, cv = new_mpl_page(tab_print.fp)
        try:
            drawTicketPage(
                [[], [], []], table_title="○○分局罰單簽收表",
                print_date="2026/07/25", disp_date="2026/07/25",
                body_rows=2, page_num=1, total_pages=1, canvas=cv)
        finally:
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

    def test_ticket_geometry_has_twenty_rows_and_one_standard_summary_row(self):
        from tabs.tab_print import BOT, DATE_H, HDR_H, TITLE_H, TOP

        self.assertEqual(TICKET_ROWS_PER_BAND, 20)
        self.assertEqual(TICKET_SUMMARY_H, ROW_H)
        self.assertAlmostEqual(
            TICKET_BODY_H,
            TOP - DATE_H - TITLE_H - HDR_H - BOT - TICKET_SUMMARY_H)
        self.assertAlmostEqual(
            TICKET_ROW_H, TICKET_BODY_H / TICKET_ROWS_PER_BAND)

    def test_capacity_constants_are_fixed_renderer_constants(self):
        from tabs.tab_print import BOT, DATE_H, HDR_H, TITLE_H, TOP

        bottom = (TOP - DATE_H - TITLE_H - HDR_H
                  - TICKET_ROW_H * TICKET_ROWS_PER_BAND
                  - TICKET_SUMMARY_H)
        self.assertAlmostEqual(bottom, BOT)

    def test_summary_shows_page_count_daily_total_and_no_signature_underline(self):
        from tabs.tab_print import BOT

        rows = self._rows("王小明", ["A1"])
        grid = buildTicketGrid(rows, body_rows=TICKET_ROWS_PER_BAND)
        cv = RecordingCanvas()
        drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=TICKET_ROWS_PER_BAND, page_num=2, total_pages=2,
            show_summary=True, total_count=61, canvas=cv)
        texts = [op.s for op in cv.ops if isinstance(op, TextOp)]
        self.assertIn("本頁共 1 筆，本日總計 61 筆", texts)
        self.assertIn("簽收人：", texts)

        summary_bottom = BOT
        summary_top = BOT + TICKET_SUMMARY_H
        right_half_horizontal_lines = [
            op for op in cv.ops
            if isinstance(op, LineOp)
            and abs(op.y0 - op.y1) < 1e-9
            and summary_bottom < op.y0 < summary_top
            and min(op.x0, op.x1) >= 0.5
        ]
        self.assertEqual(right_half_horizontal_lines, [])

    def test_outer_box_starts_at_header_and_leaves_title_outside(self):
        # Task 6：唯一粗外框只包「欄名列頂端～簽收格底端」；
        # 標題與日期都在框外，頁面四周也不得另加 frame。
        from tabs.tab_print import DATE_H, HDR_H, TITLE_H, TOP

        title_top = TOP - DATE_H
        header_top = title_top - TITLE_H
        table_top = header_top - HDR_H

        rows = self._rows("王小明", ["A1", "A2"], issuer_id="P1")
        grid = buildTicketGrid(rows, body_rows=2)

        cv = RecordingCanvas()
        drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=2, page_num=1, total_pages=1, canvas=cv)
        outer_boxes = [
            op for op in cv.ops
            if isinstance(op, RectOp)
            and op.linewidth and op.linewidth >= 1.0
            and (op.edgecolor or '').lower() != "#ffffff"
        ]
        self.assertEqual(len(outer_boxes), 1, "應恰有一個粗單線表格外框")
        box = outer_boxes[0]
        box_top_y = box.y + box.h
        self.assertAlmostEqual(
            box_top_y, header_top, places=3,
            msg="外框上緣只能到欄名列頂端，標題必須留在框外")
        self.assertGreater(box_top_y, table_top)
        self.assertLess(box_top_y, title_top)

        # 5 條內部直線（2 條組間分隔線＋3 條組內子欄分隔線）須穿過欄名列，
        # 上緣須到達 header_top（標題帶不分欄，欄名列須分欄）。
        vlines = [
            op for op in cv.ops
            if isinstance(op, LineOp)
            and abs(op.x0 - op.x1) < 1e-9 and abs(op.y0 - op.y1) > 1e-9
        ]
        touching_header = [
            l for l in vlines
            if abs(max(l.y0, l.y1) - header_top) < 1e-3
        ]
        self.assertEqual(
            len(touching_header), 5,
            "欄名列高度範圍內應有 5 條內部直線（六個欄名各自有邊界）")

    def test_ticket_palette_and_flat_single_line_artists(self):
        # 色碼改回既有四表藍色、明細恢復斑馬紋，或 renderer 再使用
        # FancyBboxPatch 模擬立體框，本測試都必須失敗。
        import matplotlib.pyplot as plt
        from tools.mpl_canvas import new_mpl_page
        from tabs.tab_print import DATE_H, HDR_H, TABLE_L, TABLE_W, TITLE_H, TOP

        expected_palette = {
            "TICKET_HEADER_BG": "#B9858E",
            "TICKET_HEADER_TEXT": "#FFFFFF",
            "TICKET_OUTER_BORDER": "#743A46",
            "TICKET_GROUP_BORDER": "#A56B76",
            "TICKET_GRID_BORDER": "#D7C4C8",
            "TICKET_SUMMARY_BG": "#F5EAEC",
        }
        self.assertEqual(
            {name: getattr(tab_print, name, None) for name in expected_palette},
            expected_palette)

        rows = (self._rows("王小明", ["A1", "A2", "A3"], issuer_id="P1")
                + self._rows("李大華", ["B1"], issuer_id="P2"))
        grid = buildTicketGrid(rows, body_rows=4)

        # 結構不變性（不得再用 FancyBboxPatch 模擬立體框）：
        # MatplotlibCanvas.rect() 一律只產生平面 Rectangle，用實際渲染的
        # fig 驗證這個不變性（RecordingCanvas 的 op 不帶 artist 類別資訊，
        # 測不到這一項）；fig 改由呼叫端經 `new_mpl_page()` 自建，
        # `drawTicketPage()` 本身不再回傳 figure（STAGE3-BRIEF §2）。
        fig, cv_mpl = new_mpl_page(tab_print.fp)
        try:
            drawTicketPage(
                grid, table_title="○○分局罰單簽收表",
                print_date="2026/07/25", disp_date="2026/07/25",
                body_rows=4, page_num=1, total_pages=1,
                show_summary=True, total_count=4, canvas=cv_mpl)
            ax = fig.axes[0]
            self.assertFalse(
                any(isinstance(p, FancyBboxPatch) for p in ax.patches),
                "罰單 renderer 只能使用平面 Rectangle，不得有 FancyBbox 外觀")
        finally:
            plt.close(fig)

        # 其餘配色／填色／外框／表頭文字：改對 RecordingCanvas.ops 斷言，
        # 等價於原本對 ax.patches／ax.texts 顏色、位置、欄數的檢查。
        cv = RecordingCanvas()
        drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=4, page_num=1, total_pages=1,
            show_summary=True, total_count=4, canvas=cv)
        rect_ops = [op for op in cv.ops if isinstance(op, RectOp)]
        fills = [op.facecolor.lower() for op in rect_ops if op.facecolor]
        self.assertIn("#b9858e", fills, "欄名列必須是酒紅底")
        self.assertIn("#f5eaec", fills, "簽收格必須是淡酒紅底")
        self.assertNotIn("#eaf0f7", fills, "不得沿用舊藍色斑馬底")

        body_top = TOP - DATE_H - TITLE_H - HDR_H
        body_bottom = body_top - TICKET_ROW_H * 4
        body_fills = [
            op.facecolor.lower() for op in rect_ops
            if op.facecolor
            and op.y < body_top
            and op.y + op.h > body_bottom
        ]
        self.assertEqual(set(body_fills), {"#ffffff"},
                         "罰單明細必須全部純白，不得斑馬紋")

        header_texts = [
            op for op in cv.ops
            if isinstance(op, TextOp) and op.s in TICKET_SUB_HEADERS
        ]
        self.assertEqual(len(header_texts), 6)
        self.assertTrue(all(
            op.color.lower() == "#ffffff" for op in header_texts))

        outer = [
            op for op in rect_ops
            if op.edgecolor and op.edgecolor.lower() == "#743a46"
            and op.linewidth >= 1.0
        ]
        self.assertEqual(len(outer), 1, "只能有一個酒紅粗單線表格外框")
        self.assertAlmostEqual(outer[0].x, TABLE_L)
        self.assertAlmostEqual(outer[0].w, TABLE_W)

    def test_group_boundaries_are_single_medium_lines(self):
        # 王小明 rowspan=3：r1/r2 的人員合併格內不得有橫線；r3 群組結束
        # 應以一條 GROUP 色／中線寬跨完整直欄，不能同時疊一條 GRID 細線。
        from tabs.tab_print import DATE_H, HDR_H, TABLE_L, TABLE_W, TITLE_H, TOP

        rows = (self._rows("王小明", ["A1", "A2", "A3"], issuer_id="P1")
                + self._rows("李大華", ["B1", "B2"], issuer_id="P2"))
        grid = buildTicketGrid(rows, body_rows=5)
        cv = RecordingCanvas()
        drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=5, show_summary=True, total_count=5, canvas=cv)
        band_w = TABLE_W / 3
        table_top = TOP - DATE_H - TITLE_H - HDR_H
        issuer_end = TABLE_L + band_w * _TICKET_SUB_RATIOS[0]

        def lines_at(y):
            return [
                op for op in cv.ops
                if isinstance(op, LineOp)
                and abs(op.y0 - op.y1) < 1e-8
                and abs(op.y0 - y) < 1e-8
            ]

        for ridx in (1, 2):
            y = table_top - TICKET_ROW_H * ridx
            issuer_lines = [
                op for op in lines_at(y)
                if min(op.x0, op.x1) < issuer_end - 1e-8
            ]
            self.assertEqual(
                issuer_lines, [],
                f"r{ridx} 是合併格內部，不得畫開立人員橫線")

        group_y = table_top - TICKET_ROW_H * 3
        full_band_lines = [
            op for op in lines_at(group_y)
            if abs(min(op.x0, op.x1) - TABLE_L) < 1e-8
            and abs(max(op.x0, op.x1) - (TABLE_L + band_w)) < 1e-8
        ]
        self.assertEqual(len(full_band_lines), 1, "群組共享邊界只能畫一次")
        self.assertEqual(full_band_lines[0].color.lower(), "#a56b76")
        self.assertGreater(full_band_lines[0].linewidth, 0.4)

    def test_long_ticket_no_is_clipped_not_bleeding_into_neighbor(self):
        # F2 regression：超長罰單編號（20 字元）在 min_size=8pt 觸底時仍可能
        # 比格寬還寬，text 必須被裁在自己格子的 bbox 內，不得沒有裁切
        # （沒裁切＝會畫出跨過欄線壓到鄰欄的字）。
        import matplotlib.pyplot as plt
        from tools.mpl_canvas import new_mpl_page
        from tabs.tab_print import TABLE_L, TABLE_W, _TICKET_SUB_RATIOS as ratios

        long_no = "A" * 20
        rows = self._rows("王小明", [long_no], issuer_id="P1")
        grid = buildTicketGrid(rows, body_rows=1)

        cv = RecordingCanvas()
        drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=1, page_num=1, total_pages=1, canvas=cv)
        band_w = TABLE_W / 3
        no_x0 = TABLE_L + band_w * ratios[0]
        no_x1 = TABLE_L + band_w

        no_ops = [op for op in cv.ops
                  if isinstance(op, TextOp) and op.s == long_no]
        self.assertEqual(len(no_ops), 1, "應找到罰單編號文字物件")
        clip_rect = no_ops[0].clip_rect
        self.assertIsNotNone(clip_rect, "超長編號必須有明確的裁切範圍")
        cx0, _cy0, cx1, _cy1 = clip_rect
        self.assertAlmostEqual(min(cx0, cx1), no_x0, places=3)
        self.assertAlmostEqual(max(cx0, cx1), no_x1, places=3)

        # 裁切是否真的套到 matplotlib artist 上（不能只驗 op 本身）：
        # 用真實 fig 驗證 Text artist 的 clip_on／clip_box（fig 改由呼叫端
        # 經 `new_mpl_page()` 自建，`drawTicketPage()` 本身不再回傳 figure）。
        fig2, cv_mpl = new_mpl_page(tab_print.fp)
        try:
            drawTicketPage(
                grid, table_title="○○分局罰單簽收表",
                print_date="2026/07/25", disp_date="2026/07/25",
                body_rows=1, page_num=1, total_pages=1, canvas=cv_mpl)
            ax = fig2.axes[0]
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
            plt.close(fig2)

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

        from tabs.tab_print import DATE_H, HDR_H, TABLE_L, TABLE_W, TITLE_H, TOP

        cv = RecordingCanvas()
        drawTicketPage(
            grid, table_title="○○分局罰單簽收表",
            print_date="2026/07/25", disp_date="2026/07/25",
            body_rows=6, page_num=1, total_pages=1, canvas=cv)
        band_w = TABLE_W / 3
        table_top = TOP - DATE_H - TITLE_H - HDR_H

        def _boundary_y(ridx):
            return table_top - TICKET_ROW_H * ridx

        def _has_line(x0, x1, y):
            for op in cv.ops:
                if not isinstance(op, LineOp):
                    continue
                if abs(op.y0 - op.y1) > 1e-6:
                    continue
                if abs(op.y0 - y) > 1e-6:
                    continue
                if (abs(min(op.x0, op.x1) - x0) < 1e-6
                        and abs(max(op.x0, op.x1) - x1) < 1e-6):
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

        def _covering_lines(x0, x1, y):
            return [
                op for op in cv.ops
                if isinstance(op, LineOp)
                and abs(op.y0 - op.y1) < 1e-6
                and abs(op.y0 - y) < 1e-6
                and min(op.x0, op.x1) <= x0 + 1e-6
                and max(op.x0, op.x1) >= x1 - 1e-6
            ]

        # r3（A/B 交界）、r5（B/C 交界）：共享邊界應各用一條中階線
        # 跨完整直欄；不得再拆 issuer／number 兩段或疊畫細線。
        for ridx in (3, 5):
            ry = _boundary_y(ridx)
            group_lines = _covering_lines(band0_left, band0_left + band_w, ry)
            self.assertEqual(
                len(group_lines), 1,
                f"r{ridx}（群組交界）只能有一條跨完整直欄的共享邊界")
            self.assertEqual(group_lines[0].color.lower(), "#a56b76")

        # number 子欄水平線：每張罰單編號各占一格；群組內是細線，
        # 群組交界則由跨完整直欄的中階共享邊界涵蓋。
        for ridx in range(1, 6):
            ry = _boundary_y(ridx)
            self.assertTrue(
                bool(_covering_lines(number_x0, number_x1, ry)),
                f"r{ridx} number 子欄水平線必須保留")


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

    def test_ticket_settled_to_selected_past_date_prints_on_that_date(self):
        """結算選定日期必須直接成為罰單簽收表的查詢日期。"""
        conn = sqlite3.connect(self.db_path)
        try:
            doc_id = createTicket(
                conn, issuer_id="P1", ticket_no="SELECTED20260709", self_service=True,
                sender_id=None, create_date="2026-07-20", role="user")
            conn.commit()
            self.assertEqual(
                settle_selected(conn, {"crim": [], "gen": [], "ticket": [doc_id]},
                                "2026-07-09", "P1"),
                1,
            )
        finally:
            conn.close()

        selected_rows = queryTicketPrintRows(self.db_path, "2026-07-09")
        self.assertIn("SELECTED20260709", [r["ticket_no"] for r in selected_rows])

    def test_issued_rows_exclude_unissued_and_keep_ticket_sort_order(self):
        rows = queryTicketPrintRows(self.db_path, "2026-07-23")
        ticket_nos = [row["ticket_no"] for row in rows]
        self.assertNotIn("UNISSUED001", ticket_nos)
        self.assertEqual(ticket_nos, ["A1234567", "D4RD15263"])

    def test_query_results_are_naturally_sorted_after_sql_filtering(self):
        conn = sqlite3.connect(self.db_path)
        try:
            for doc_id, ticket_no in enumerate(
                    ("A10B10", "A2", "A01", "A1", "A10B2"), start=9100):
                conn.execute(
                    "INSERT INTO Document_Ticket"
                    "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
                    "VALUES(?, '2026-07-24', '2026-07-24', 'P1', 'P1', ?)",
                    (str(doc_id), ticket_no),
                )
            conn.commit()
        finally:
            conn.close()

        rows = queryTicketPrintRows(self.db_path, "2026-07-24")
        self.assertEqual(
            [row["ticket_no"] for row in rows],
            ["A1", "A01", "A2", "A10B2", "A10B10"],
        )

    def test_query_sort_accepts_legacy_missing_issuer_names(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA ignore_check_constraints=ON")
            conn.execute(
                "INSERT INTO Document_Ticket"
                "(doc_id,create_date,register_date,issuer_id,ticket_no) "
                "VALUES('9201','2026-07-25','2026-07-25',NULL,'A10')")
            conn.execute(
                "INSERT INTO Document_Ticket"
                "(doc_id,create_date,register_date,issuer_id,ticket_no) "
                "VALUES('9202','2026-07-25','2026-07-25','P404','A2')")
            conn.execute("PRAGMA ignore_check_constraints=OFF")
            conn.commit()
        finally:
            conn.close()

        rows = queryTicketPrintRows(self.db_path, "2026-07-25")
        self.assertEqual([row["ticket_no"] for row in rows], ["A10", "A2"])

    def test_no_data_returns_empty_list(self):
        self._set_self_service(True)
        self.assertEqual(queryTicketPrintRows(self.db_path, "2099-01-01"), [])



if __name__ == "__main__":
    unittest.main()
