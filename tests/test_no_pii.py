"""個資防呆：push 前確認 git 追蹤/已提交的內容不含真實人名。

設計重點：
  - 只掃「git 追蹤」的文字內容，不掃工作樹的本機真實資料（你的髒 dbfile.db）。
    dbfile.db 自此不入庫（schema/種子改為程式碼唯一來源），故改為
    「臨時產一份乾淨空殼」(tools/gen_shell_db) 掃其位元組，驗證 db_seed 不含真名。
  - 比對清單 tests/pii_denylist.local.txt 為本機檔（已 gitignore，不入庫，
    才不會把真名又帶進 repo）；清單不存在時自動 skip（別人 clone/CI 不會壞）。
  - 命中即 fail，並列出檔名與名字，提醒「替換後才能 push」。

執行：專案根目錄下 `python -m unittest tests.test_no_pii`
"""
import os
import subprocess
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DENYLIST = os.path.join(_ROOT, "tests", "pii_denylist.local.txt")
# 只掃會帶字串個資的文字類追蹤檔；二進位 dbfile.db 另以 blob bytes 掃。
_TEXT_EXT = (".py", ".md", ".txt", ".ui", ".qrc", ".sql", ".json")


def _git(*args):
    return subprocess.run(["git", "-C", _ROOT, *args],
                          capture_output=True).stdout


def _load_denylist():
    if not os.path.exists(_DENYLIST):
        return []
    names = []
    with open(_DENYLIST, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#"):
                names.append(s)
    return names


class TestNoPII(unittest.TestCase):
    def setUp(self):
        self.deny = _load_denylist()
        if not self.deny:
            self.skipTest(f"找不到 {os.path.relpath(_DENYLIST, _ROOT)}，跳過個資掃描")

    def test_tracked_text_files_clean(self):
        """所有 git 追蹤的文字檔不得含 denylist 真名。"""
        tracked = _git("ls-files", "-z").split(b"\x00")
        hits = []
        for rel in (p.decode("utf-8") for p in tracked if p):
            if not rel.lower().endswith(_TEXT_EXT):
                continue
            blob = _git("show", f"HEAD:{rel}")
            try:
                text = blob.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for name in self.deny:
                if name in text:
                    hits.append(f"{rel}：{name}")
        self.assertEqual(
            hits, [],
            "git 追蹤檔含真實人名，替換後才能 push：\n  " + "\n  ".join(hits))

    def test_generated_shell_clean(self):
        """臨時產一份乾淨空殼（schema＋db_seed），其位元組不得含 denylist 真名。
        驗證 db_seed 的種子資料（佔位人員等）皆為虛構名，不會把真名帶進發版空殼。"""
        import sys, tempfile
        sys.path.insert(0, _ROOT)
        from tools import gen_shell_db
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        os.remove(tmp)   # build 會自行建立
        try:
            gen_shell_db.build(tmp)
            with open(tmp, "rb") as f:
                blob = f.read()
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        hits = [name for name in self.deny if name.encode("utf-8") in blob]
        self.assertEqual(
            hits, [],
            "產生的空殼含真實人名（db_seed 種子資料有真名），替換為虛構佔位名："
            "\n  " + "\n  ".join(hits))


if __name__ == "__main__":
    unittest.main()
