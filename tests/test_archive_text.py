"""lib/archive_text.py 純文字/檔名工具單元測試（無 Qt、無 DB）。

涵蓋 README 踩雷表登記過的歸檔檔名解析案例：
  - 黏連日期＋主旨檔名（1150101李美華竊盜案）
  - PK 為 1xx 時不被誤判成民國年
  - 承辦人去後綴（半形/全形連字號）
執行：專案根目錄下 `python -m unittest tests.test_archive_text`

註：以下檔名／人名皆為虛構範例（依真實檔名格式自編），不含任何真實個資。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from lib.archive_text import (
    _trimName, _tokenize, _parseDate, _sanitize, _pkOf,
    _resolveNames, _parseSubject, _stripStaffParen,
)


def _make_name_dict(*full_names):
    """模擬 tab_archive._loadNameDict 產出：{全名: 全名, 去姓2字: 全名}。
    人名皆為虛構，不含真實個資。"""
    d = {}
    for full in full_names:
        d[full] = full
        if len(full) >= 3:
            d[full[1:]] = full   # 去姓(後2字)→全名
    return d


class TestTrimName(unittest.TestCase):
    def test_half_width_suffix(self):
        self.assertEqual(_trimName("王小明-01"), "王小明")

    def test_full_width_suffix(self):
        self.assertEqual(_trimName("李美華－19.06"), "李美華")

    def test_dotted_suffix(self):
        self.assertEqual(_trimName("李美華-19.06"), "李美華")

    def test_no_suffix(self):
        self.assertEqual(_trimName("陳志明"), "陳志明")

    def test_empty_and_none(self):
        self.assertEqual(_trimName(""), "")
        self.assertEqual(_trimName(None), "")

    def test_strips_whitespace(self):
        self.assertEqual(_trimName(" 王小明 -01"), "王小明")


class TestTokenize(unittest.TestCase):
    def test_glued_date_subject_name(self):
        # 踩雷表：日期黏主旨檔名，整串中文段須抽得出來並做 2 字滑動
        toks = _tokenize("1150101李美華竊盜案")
        # 整段中文（數字前綴已被排除）
        self.assertIn("李美華竊盜案", toks)
        # 2 字滑動片段（跨人名與主旨皆涵蓋）
        for bigram in ("李美", "美華", "華竊", "竊盜", "盜案"):
            self.assertIn(bigram, toks)

    def test_separators_split(self):
        toks = _tokenize("王小明-竊盜-1150101")
        self.assertIn("王小明", toks)
        self.assertIn("竊盜", toks)

    def test_single_char_dropped(self):
        # 長度 < 2 的片段不入集合
        self.assertNotIn("王", _tokenize("王 竊盜"))

    def test_full_width_brackets(self):
        toks = _tokenize("竊盜案（王小明）")
        self.assertIn("竊盜案", toks)
        self.assertIn("王小明", toks)

    def test_empty(self):
        self.assertEqual(_tokenize(""), set())


class TestParseDate(unittest.TestCase):
    def test_minguo_compact(self):
        self.assertEqual(_parseDate("1150612李美華.pdf"), "1150612")

    def test_glued_subject(self):
        # 格式(2)：日期黏主旨
        self.assertEqual(_parseDate("1150101林淑芬竊盜案-黃文雄.pdf"), "1150101")

    # ── PK 撞號（README 踩雷表 / 檔名格式）──────────────────
    # 正規檔名「PK-日期-主旨-承辦」開頭 PK 也是 1xx，日期須前後不接數字才不被
    # PK 咬走。以下為依真實檔名格式自編的虛構範例。
    def test_pk_prefix_not_swallowed(self):
        self.assertEqual(
            _parseDate("103-1150120-周大年遭詐欺案-吳國華.pdf"), "1150120")
        self.assertEqual(
            _parseDate("109-1140109-鄭明德詐欺案-許家豪.pdf"), "1140109")
        self.assertEqual(
            _parseDate("116-1150102-楊志偉遭侵占遺失物案-黃文雄.pdf"), "1150102")

    def test_multi_pk_prefix(self):
        # 多編號合併「268-269-1150227-…」：兩段 PK 後才是日期
        self.assertEqual(
            _parseDate("268-269-1150227-蔡俊傑公共危險案-馮長生.pdf"), "1150227")
        self.assertEqual(
            _parseDate("120、224-1150125-王安違反保護令-馮長生.pdf"), "1150125")

    def test_first_invalid_run_skipped(self):
        # 第一個 7 碼湊出不合理月日要跳過，往後找合理的
        # 1159999: 月99日99不合理 → 應抓後方 1150101
        self.assertEqual(_parseDate("1159999-x-1150101案.pdf"), "1150101")

    # ── 畸形 / 無日期：不可誤判 ────────────────────────────
    def test_malformed_rejected(self):
        # 8 碼黏連、6 碼短日期、140 非有效民國年 → 一律抓不到（寧空白）
        self.assertEqual(_parseDate("11506110趙天明詐欺案-孫文山.pdf"), "")
        self.assertEqual(_parseDate("140-110205-高大同家暴通報-范振國.pdf"), "")

    def test_invalid_month_rejected(self):
        self.assertEqual(_parseDate("1151301.pdf"), "")   # 13 月

    def test_western_compact(self):
        self.assertEqual(_parseDate("20240612報告.pdf"), "20240612")

    def test_no_date(self):
        self.assertEqual(_parseDate("葉永福竊盜案.pdf"), "")
        self.assertEqual(_parseDate("林良遭詐騙案-阿福.pdf"), "")


class TestSanitize(unittest.TestCase):
    def test_removes_windows_illegal(self):
        self.assertEqual(_sanitize('a/b:c*d?e"f<g>h|i\\j'), "abcdefghij")

    def test_keeps_chinese(self):
        self.assertEqual(_sanitize("竊盜案 王小明"), "竊盜案 王小明")

    def test_none(self):
        self.assertEqual(_sanitize(None), "")


class TestPkOf(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(_pkOf("103-1150612-竊盜案.pdf"), "103")

    def test_full_width_dash(self):
        self.assertEqual(_pkOf("CT01－主旨.pdf"), "CT01")

    def test_with_path(self):
        self.assertEqual(_pkOf(r"D:\歸檔\刑案\103-1150612.pdf"), "103")

    def test_no_dash(self):
        self.assertEqual(_pkOf("整串無分隔.pdf"), "整串無分隔")

    def test_multi_pk_takes_first(self):
        # 多編號合併取首段（第一個 - 之前）
        self.assertEqual(
            _pkOf("268-269-1150227-蔡俊傑公共危險案-馮長生.pdf"), "268")

    def test_format2_no_pk(self):
        # 格式(2)「日期主旨-承辦」無 PK 段 → 取到日期黏主旨的首段（呼叫端只在
        # 已格式化檔名上用 _pkOf，這裡僅記錄無 PK 時的實際行為）
        self.assertEqual(
            _pkOf("1150101林淑芬竊盜案-黃文雄.pdf"), "1150101林淑芬竊盜案")


class TestResolveNames(unittest.TestCase):
    """承辦人解析：只收對得到人名字典者，案由詞/報案人不誤收。
    人名皆虛構。"""
    def setUp(self):
        # 承辦人：王測乙、王測甲、游瑛媛、歐陽建國(4字測長名仍可對)
        self.nd = _make_name_dict("王測乙", "王測甲", "游瑛媛", "歐陽建國")

    def test_multi_dash_processors(self):
        # 多個 - 分隔承辦人都要收；案由「竊盜案」、報案人「王小華」不可收
        self.assertEqual(
            _resolveNames("1150611-林大明(王小華)竊盜案-王測乙-王測甲.pdf", self.nd),
            ["王測乙", "王測甲"])

    def test_dunhao_processors_with_short_name(self):
        # 頓號多人 + 去姓2字（測甲→王測甲、測乙→王測乙）
        self.assertEqual(
            _resolveNames("1150620-高大同竊盜案-測甲、測乙.pdf", self.nd),
            ["王測甲", "王測乙"])

    def test_case_word_not_treated_as_name(self):
        # 回歸：「竊盜案」3字但非人名，不得混入承辦人
        names = _resolveNames("1150611-林大明竊盜案-王測乙.pdf", self.nd)
        self.assertEqual(names, ["王測乙"])
        self.assertNotIn("竊盜案", names)

    def test_long_name_in_dict_collected(self):
        # 4字全名在字典 → 仍收
        self.assertEqual(
            _resolveNames("1150611-林大明竊盜案-歐陽建國.pdf", self.nd),
            ["歐陽建國"])

    def test_single_processor(self):
        self.assertEqual(
            _resolveNames("103-1150612-林大明竊盜案-游瑛媛.pdf", self.nd),
            ["游瑛媛"])


class TestParseSubjectWithDict(unittest.TestCase):
    """主旨解析：剝乾淨承辦人、保留報案人括號。人名皆虛構。"""
    def setUp(self):
        self.nd = _make_name_dict("王測乙", "王測甲", "游瑛媛")

    def test_multi_dash_processors_stripped(self):
        # 多個 - 承辦人全剝除；報案人括號保留
        self.assertEqual(
            _parseSubject("1150611-林大明(王小華)竊盜案-王測乙-王測甲.pdf", self.nd),
            "林大明(王小華)竊盜案")

    def test_dunhao_processor_segment_stripped(self):
        self.assertEqual(
            _parseSubject("1150620-高大同竊盜案-測甲、測乙.pdf", self.nd),
            "高大同竊盜案")

    def test_keeps_reporter_paren(self):
        # 報案人(王小華)不在承辦字典 → 主旨保留括號
        self.assertEqual(
            _parseSubject("1150611-林大明(王小華)竊盜案-游瑛媛.pdf", self.nd),
            "林大明(王小華)竊盜案")

    def test_strips_trailing_staff_paren(self):
        # 尾端括號內為承辦人 → 整組去掉
        self.assertEqual(
            _parseSubject("1150611-林大明竊盜案(游瑛媛).pdf", self.nd),
            "林大明竊盜案")

    def test_format2_space_separated(self):
        # 無 - 格式：日期黏主旨、空白分承辦人
        self.assertEqual(
            _parseSubject("1150101林大明竊盜案 游瑛媛.pdf", self.nd),
            "林大明竊盜案")

    def test_subject_never_emptied(self):
        # 全是承辦人段時至少保留主旨段，不砍成空
        out = _parseSubject("1150611-林大明竊盜案-王測乙-王測甲.pdf", self.nd)
        self.assertTrue(out)


class TestRealWorldCorpus(unittest.TestCase):
    """取自真實檔名語料（已去識別化為虛構人名）的回歸案例。
    good_* 為應正確解析；edge_* 為低頻邊緣格式，記錄目前行為（已知限制、不修），
    若日後改動解析邏輯，這些斷言會提醒行為變化。"""
    def setUp(self):
        self.nd = _make_name_dict("王志強", "陳測甲", "王測丁")

    # ── 應正確 ──────────────────────────────────────────
    def test_good_dunhao(self):
        s, n = self._run("107-1150123-林大明竊盜案-王志強、陳測甲.pdf")
        self.assertEqual(s, "林大明竊盜案")
        self.assertEqual(n, ["王志強", "陳測甲"])

    def test_good_paren_reporter(self):
        # 報案人(王測丙)非承辦 → 主旨保留括號、不混入承辦人
        s, n = self._run("114-1150124-周建宏(王測丙)詐欺案-陳測甲、王測丁、王志強.pdf")
        self.assertEqual(s, "周建宏(王測丙)詐欺案")
        self.assertEqual(n, ["陳測甲", "王測丁", "王志強"])

    def test_good_quxing_glued_date(self):
        # 日期黏主旨於首段 + 去姓2字承辦（志強→王志強）
        s, n = self._run("1150107林淑芬肇事逃逸兼過失傷害案-志強.pdf")
        self.assertEqual(s, "林淑芬肇事逃逸兼過失傷害案")
        self.assertEqual(n, ["王志強"])

    def test_good_multi_dash_processors(self):
        # 多個 - 分隔的承辦人全數剝除/收集
        s, n = self._run("467-1150411-嶺東竊盜案-王志強-王測丁-陳測甲.pdf")
        self.assertEqual(s, "嶺東竊盜案")
        self.assertEqual(n, ["王志強", "王測丁", "陳測甲"])

    # ── 邊緣格式：記錄現況（已知限制，不修）─────────────────
    def test_edge_duplicate_marker(self):
        # 承辦人後接 (2) 重複註記 → (2) 含純數字使承辦區提早中止
        s, n = self._run("434-1150317-林大明侵入住宅案-王志強 (2).pdf")
        self.assertEqual(s, "林大明侵入住宅案、王志強 (2)")
        self.assertEqual(n, [])

    def test_edge_role_paren(self):
        # 承辦人帶角色括號(普仁單窗) → 角色非人名，承辦區提早中止
        s, n = self._run("28-1150106-林大明詐欺案-王測丁(普仁單窗).pdf")
        self.assertEqual(s, "林大明詐欺案、王測丁(普仁單窗)")
        self.assertEqual(n, [])

    def test_edge_dash_role(self):
        # 承辦人後接 -單窗 角色標記 → 同上
        s, n = self._run("729-1150607-林大明所報詐欺案-王志強-單窗.pdf")
        self.assertEqual(s, "林大明所報詐欺案、王志強、單窗")
        self.assertEqual(n, [])

    def test_edge_mazuo_prefix(self):
        # 「馬佐」職稱黏承辦名、無分隔 → 整串對不到字典
        s, n = self._run("382-1150326林大明竊盜通緝-馬佐志強.pdf")
        self.assertEqual(s, "林大明竊盜通緝、馬佐志強")
        self.assertEqual(n, [])

    def _run(self, fn):
        return _parseSubject(fn, self.nd), _resolveNames(fn, self.nd)


class TestStripStaffParen(unittest.TestCase):
    def test_strips_when_all_staff(self):
        nd = _make_name_dict("游瑛媛", "王測乙")
        self.assertEqual(_stripStaffParen("竊盜案(游瑛媛、王測乙)", nd), "竊盜案")

    def test_keeps_when_not_staff(self):
        nd = _make_name_dict("游瑛媛")
        # 王小華非承辦 → 保留
        self.assertEqual(_stripStaffParen("竊盜案(王小華)", nd), "竊盜案(王小華)")


if __name__ == "__main__":
    unittest.main()
