# tests/test_environment_contract.py
"""驗證「實際裝的套件版本」與釘住的版本一致，並守住 runtime／dev 兩份清單的分界。

**為什麼有這支**：2026-08-02 matplotlib 曾被降到 3.10.9 又換回 3.11.1，全程沒有
任何機制示警，是靠人工比對 manifest 才發現。列印基準的 101 項雜湊直接綁
matplotlib 版本，版本一漂，比對出來的差異全是假的——當時第一輪就誤判成
繪圖層壞掉。2026-08-03 這支測試第一次跑就再抓到一件：`requirements-dev.txt` 的
pypdf／reportlab 兩行釘的是 Codex runtime（沒有 pytest，跑不了測試）的版本，
與真正跑 gate 的系統 Python 對不上——**兩支直譯器的差異肉眼看不出來**。

**fail-closed**：套件沒裝也算失敗，不 skip。本專案已有教訓（PII gate 的
`OK (skipped=...)` 被當成通過），skip 不等於通過。
"""
import re
import unittest
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_REQUIREMENTS = ROOT / "requirements.txt"
DEV_REQUIREMENTS = ROOT / "requirements-dev.txt"
# 少了任何一項，這支測試就等於沒在保護；缺項本身要紅
CRITICAL_PACKAGES = {"PySide6", "matplotlib", "pytest", "pytest-qt"}
# 只給開發／驗收工具用的套件，不得混進產品 runtime 清單
DEV_ONLY_PACKAGES = {"matplotlib", "pytest", "pytest-qt", "pytest-xdist",
                     "reportlab", "pypdf"}
# 版本綁著驗收產物的套件，訊息要多講一句該連帶更新什麼
BOUND_ARTIFACTS = {
    "matplotlib": "tests/print_baseline_manifest.json（列印基準 101 項雜湊）",
}
_PIN = re.compile(r"^([A-Za-z0-9._-]+)\s*(==|>=|<=|~=|!=|>|<)\s*(.+?)\s*$")


def _requirement_lines(path):
    """讀一份 requirements，`-r` 指向的檔案一併展開（相對於該檔所在目錄）。"""
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith(("-r ", "--requirement ")):
            included = Path(path).parent / line.split(None, 1)[1].strip()
            yield from _requirement_lines(included)
        else:
            yield line


def parse_pins(lines):
    """回傳 {套件名: 版本}；非 `==` 的釘法一律回報，交由測試判失敗。"""
    pins, loose = {}, []
    for line in lines:
        match = _PIN.match(line)
        if match is None:
            loose.append(line)
            continue
        name, operator, pinned = match.groups()
        if operator != "==":
            loose.append(line)
        else:
            pins[name] = pinned
    return pins, loose


class EnvironmentContractTests(unittest.TestCase):
    def setUp(self):
        self.pins, self.loose = parse_pins(_requirement_lines(DEV_REQUIREMENTS))
        self.runtime_pins, _ = parse_pins(_requirement_lines(RUNTIME_REQUIREMENTS))

    def test_every_dependency_is_pinned_to_an_exact_version(self):
        self.assertEqual(
            self.loose, [],
            "requirements 必須逐項釘死版本（`套件==版本`）："
            f"下列寫法無法重現已驗證環境 → {self.loose}")

    def test_critical_packages_are_still_listed(self):
        missing = sorted(CRITICAL_PACKAGES - set(self.pins))
        self.assertEqual(
            missing, [],
            f"requirements-dev.txt 少了關鍵套件 {missing}；"
            "本測試靠這份清單保護環境，缺項等於防線消失")

    def test_dev_requirements_include_the_runtime_file(self):
        # 分層的前提：裝 dev 就一定連 runtime 一起裝，兩份不會各自漂
        raw = DEV_REQUIREMENTS.read_text(encoding="utf-8")
        self.assertIn("-r requirements.txt", raw)
        self.assertTrue(
            set(self.runtime_pins).issubset(set(self.pins)),
            "requirements-dev.txt 應涵蓋 requirements.txt 的每一項")

    def test_runtime_requirements_stay_free_of_dev_only_tools(self):
        # 產品 exe 不 import 這些：PDF 產出走 Qt 的 QPdfWriter／QPrinter，
        # reportlab 只有 tools/gen_quickstart.py 用，matplotlib 只有列印基準工具用
        leaked = sorted(DEV_ONLY_PACKAGES & set(self.runtime_pins))
        self.assertEqual(
            leaked, [],
            f"requirements.txt 混進了只有開發／驗收才需要的套件 {leaked}；"
            "產品 runtime 清單只放 lib/ 或 tabs/ 真的會 import 的東西")

    def test_installed_versions_match_the_pinned_versions(self):
        problems = []
        for name, pinned in sorted(self.pins.items()):
            try:
                installed = version(name)
            except PackageNotFoundError:
                problems.append(
                    f"{name}：釘 {pinned}，但目前環境**沒有安裝**。"
                    f"請執行 `pip install -r requirements-dev.txt`")
                continue
            if installed != pinned:
                note = BOUND_ARTIFACTS.get(name)
                fix = (f"要嘛把 {name} 裝回 {pinned}，"
                       "要嘛確認這是刻意升版並同步更新 requirements 清單")
                if note:
                    fix += f"；{name} 的版本綁著 {note}，升版須連同重建並重新人工目視"
                problems.append(
                    f"{name}：釘住 {pinned}，實際安裝 {installed}。{fix}")
        self.assertEqual(
            problems, [],
            "環境與 requirements 清單不一致，測試結果不可信：\n  "
            + "\n  ".join(problems))


if __name__ == "__main__":
    unittest.main()
