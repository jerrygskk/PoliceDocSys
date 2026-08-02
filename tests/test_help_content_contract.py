# tests/test_help_content_contract.py
"""程式內 HELP（`ui_utils/help_content.py`）與速查卡的內容契約。

從 `test_reward_integration.py` 原樣搬出：那支同時檢查敘獎程式契約、HELP、
速查卡與 DEVELOPER.md 四件事，紅燈只會顯示「敘獎整合測試失敗」，看不出到底
哪裡出事。**斷言內容一字未改**，只是換到名副其實的檔案裡。
DEVELOPER.md 的部分在 `test_release_documentation_contract.py`。

⚠️ 這些斷言刻意逐字比對 HELP 文案：改了說明文字就會紅，這是提醒「HELP 要跟著
功能一起更新」的機制（發版前歷來最常漏的兩處之一）。紅了就照著改斷言，
不要為了讓它不紅而把比對放寬。
"""
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HelpContentContractTests(unittest.TestCase):
    def test_help_and_quickstart_indexes(self):
        from ui_utils.help_content import (HELP_PAGES, HELP_TIPS, HELP_TITLES,
                                           QUICKSTART, render_review_text)
        self.assertEqual(set(HELP_TITLES), set(range(10)))
        self.assertEqual(set(HELP_PAGES), set(range(10)))
        self.assertEqual(set(HELP_TIPS), set(range(10)))
        self.assertEqual(HELP_TITLES[3], "敘獎登錄")
        self.assertEqual(HELP_TITLES[4], "罰單登錄")
        self.assertEqual(HELP_TITLES[5], "簽收單列印")
        self.assertEqual(set(QUICKSTART), set(range(9)))
        source = (ROOT / "tools" / "gen_quickstart.py").read_text(encoding="utf-8")
        self.assertIn("PAGE1 = [0, 1, 2]", source)
        self.assertIn("PAGE2 = [3, 4, 5]", source)
        self.assertIn("PAGE3 = [6, 7, 8]", source)
        self.assertIn("九個分頁速查", source)
        reward_help = render_review_text(3)
        ticket_help = render_review_text(4)
        report_help = render_review_text(2)
        print_help = render_review_text(5)
        browse_help = render_review_text(6)
        settings_help = render_review_text(8)
        self.assertIn("登錄日期由系統自動填入今天", reward_help)
        self.assertIn("自助取號模式", reward_help)
        self.assertIn("送文者輸入模式", reward_help)
        self.assertNotIn("敘獎發文", reward_help)
        # 模式名稱必須與設定頁 radio 的字面一致（使用者要照著去設定頁找選項），
        # 不可自創「發文者登錄模式」之類的同義詞。
        self.assertIn("送文者輸入模式", ticket_help)
        self.assertIn("自助取號模式", ticket_help)
        self.assertIn("開立人員", ticket_help)
        self.assertIn("取代", ticket_help)
        self.assertIn("清空", ticket_help)
        self.assertIn("罰單編號僅接受半形英文字母與數字", ticket_help)
        self.assertIn("不可還原", ticket_help)
        self.assertIn("文號（doc_id）直接作廢、不會再被使用；原罰單編號仍可重新登錄", ticket_help)
        ticket_quickstart = "\n".join(QUICKSTART[4][1] + QUICKSTART[4][2])
        self.assertIn("文號（doc_id）作廢不可再用，原罰單編號仍可重新登錄", ticket_quickstart)
        self.assertIn("本頁不設身分限制", ticket_help)
        self.assertIn("登錄日期＝取得文號日", report_help)
        self.assertIn("陳報日期＝實際發文日", report_help)
        self.assertIn("未發文的刑案／一般／敘獎／罰單案件", print_help)
        self.assertIn("結算發文只補上發文日期，不會變更登錄日期", print_help)
        self.assertIn("四項皆為送文者輸入模式但仍有未發文殘留資料時", print_help)
        self.assertIn("四項皆為送文者輸入模式但仍有未發文殘留資料時",
                      QUICKSTART[5][2])
        self.assertEqual(set(HELP_TIPS[3]), {
            "btn_reward_submit", "btn_reward_clear", "reward_personnel_list",
        })
        self.assertEqual(set(HELP_TIPS[4]), {
            "ticket_add", "ticket_clear_issuer", "ticket_candidates_list",
        })
        # 罰單與敘獎同受陳報模式影響，說明不可再宣稱「只影響刑案與一般」
        self.assertIn(
            "自助取號模式影響刑案與一般陳報，以及敘獎登錄與罰單登錄", settings_help)
        self.assertNotIn("敘獎登錄與敘獎發文不受陳報模式影響", settings_help)
        self.assertNotIn("一併於結算時補齊", settings_help)
        self.assertIn("罰單簽收歸屬日一律依發文日期", settings_help)
        self.assertIn("與目前採送文者輸入模式或自助取號模式無關", settings_help)
        self.assertNotIn("歷史單據的列印結果會隨目前模式而不同", settings_help)
        self.assertIn("一般使用者唯讀", browse_help)
        self.assertIn("歸檔管理可修改、不可刪除", browse_help)
        self.assertIn("管理者可修改、可刪除", browse_help)

        from pypdf import PdfReader
        # docs/ 為 gitignored 產物（發版前 gen_quickstart 重產再上傳，見 DEVELOPER §7）；
        # 缺檔環境（fresh clone／CI）不驗頁數，避免依賴未入庫產物而 error。
        pdf_path = ROOT / "docs" / "Quick_Start.pdf"
        if pdf_path.exists():
            self.assertEqual(len(PdfReader(pdf_path).pages), 3)

    def test_help_and_quickstart_explain_role_based_tabs(self):
        from ui_utils.help_content import HELP_PAGES, QUICKSTART

        def text_values(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                return [
                    text
                    for item in value.values()
                    for text in text_values(item)
                ]
            if isinstance(value, (list, tuple)):
                return [text for item in value for text in text_values(item)]
            return [str(value)]

        help_text = "\n".join(text_values(HELP_PAGES))
        quickstart_text = "\n".join(text_values(QUICKSTART))
        for text in (help_text, quickstart_text):
            self.assertIn("一般使用者", text)
            self.assertIn("歸檔管理員", text)
            self.assertIn("操作紀錄", text)
            self.assertIn("資料庫設定", text)


if __name__ == "__main__":
    unittest.main()
