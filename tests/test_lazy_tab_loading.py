"""
tabs/__init__.py 延遲載入（PEP 562 module-level __getattr__）驗證。

matplotlib 為全專案唯一重量級 import 來源，僅 tabs/tab_print.py 於模組層引入。
獨立版（ENTRY_PROFILE）不含列印頁，理應完全不載入 tabs.tab_print / matplotlib；
大程式（FULL_PROFILE）維持原行為，仍會載入。

由於 sys.modules 快取會因同一行程內其他測試先行 import 而失真，凡涉及
「某模組是否已被載入」的斷言一律以子行程驗證。
"""
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_subprocess_check(script: str, timeout: int = 60) -> str:
    env = {}
    import os
    env.update(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"子行程失敗 (exit={result.returncode})\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result.stdout.strip()


_BUILD_MANAGER_SCRIPT = textwrap.dedent("""
    import sqlite3
    import sys
    import tempfile
    import os

    from lib.db_schema import applySchema
    from lib.app_profile import {profile_name}
    import main as main_module
    from PySide6.QtWidgets import QApplication

    tmp_dir = tempfile.mkdtemp()
    db_path = os.path.join(tmp_dir, "shell.db")
    conn = sqlite3.connect(db_path)
    applySchema(conn)
    conn.commit()
    conn.close()

    real_get_resource_path = main_module.getResourcePath

    def fake_get_resource_path(rel):
        if rel == "dbfile.db":
            return db_path
        return real_get_resource_path(rel)

    main_module.getResourcePath = fake_get_resource_path

    app = QApplication.instance() or QApplication([])
    manager = main_module.DocumentManager(profile={profile_name})

    print("matplotlib_loaded=" + str("matplotlib" in sys.modules))
    print("tab_print_loaded=" + str("tabs.tab_print" in sys.modules))
""")


class LazyTabLoadingSubprocessTests(unittest.TestCase):
    def test_entry_profile_never_loads_tab_print_or_matplotlib(self):
        script = _BUILD_MANAGER_SCRIPT.format(profile_name="ENTRY_PROFILE")
        out = _run_subprocess_check(script)
        lines = dict(line.split("=", 1) for line in out.splitlines())
        self.assertEqual(lines["matplotlib_loaded"], "False")
        self.assertEqual(lines["tab_print_loaded"], "False")

    def test_full_profile_still_loads_tab_print(self):
        script = _BUILD_MANAGER_SCRIPT.format(profile_name="FULL_PROFILE")
        out = _run_subprocess_check(script)
        lines = dict(line.split("=", 1) for line in out.splitlines())
        self.assertEqual(lines["matplotlib_loaded"], "True")
        self.assertEqual(lines["tab_print_loaded"], "True")

    def test_importing_tabs_package_does_not_import_tab_print(self):
        script = textwrap.dedent("""
            import sys
            import tabs
            print("before=" + str("tabs.tab_print" in sys.modules))
            _ = tabs.TabPrint
            print("after=" + str("tabs.tab_print" in sys.modules))
        """)
        out = _run_subprocess_check(script)
        lines = dict(line.split("=", 1) for line in out.splitlines())
        self.assertEqual(lines["before"], "False")
        self.assertEqual(lines["after"], "True")

    def test_all_tab_names_still_resolvable_via_getattr(self):
        script = textwrap.dedent("""
            import tabs
            names = [
                "TabDispatch", "TabReceive", "TabReport", "TabReward",
                "TabRewardIssue", "TabTicket", "TabPrint",
                "TabDBBrowse", "TabArchive", "TabSettings", "TabAudit",
            ]
            for name in names:
                assert getattr(tabs, name) is not None, name
            print("ok=True")
        """)
        out = _run_subprocess_check(script)
        self.assertIn("ok=True", out)


class TestPreheatStaysInsideProfileBundle(unittest.TestCase):
    """⚠️ 打包版特有的雷（已踩過）：載入畫面的「預熱」原本寫死完整版三個分頁，
    原始碼跑得動（模組都在），但獨立版 EXE 只打包自己的四個分頁，打包後會在
    載入步驟 11 ImportError、連主選單都進不去。故預熱範圍必須是該 profile
    tab_keys 的子集——本測試釘住這條不變式，任何 profile 都適用。"""

    def test_every_profile_preheats_only_its_own_tabs(self):
        from lib.app_profile import ENTRY_PROFILE, FULL_PROFILE
        for profile in (FULL_PROFILE, ENTRY_PROFILE):
            with self.subTest(profile=profile.key):
                self.assertTrue(set(profile.preheat_keys) <= set(profile.tab_keys),
                                f"{profile.key} 預熱了不屬於自己的分頁："
                                f"{set(profile.preheat_keys) - set(profile.tab_keys)}")

    def test_full_profile_keeps_existing_preheat_set(self):
        from lib.app_profile import FULL_PROFILE
        self.assertEqual(FULL_PROFILE.preheat_keys,
                         ("assignment_issue", "assignment_receive", "report"))

    def test_entry_preheat_does_not_pull_print_or_archive(self):
        from lib.app_profile import ENTRY_PROFILE
        self.assertNotIn("print", ENTRY_PROFILE.preheat_keys)
        self.assertNotIn("archive", ENTRY_PROFILE.preheat_keys)


if __name__ == "__main__":
    unittest.main()
