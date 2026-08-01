# -*- coding: utf-8 -*-
"""打包排除清單（tools/pyi_prune.py）的規則測試。

重點是釘住 2026-07 踩過的兩條雷：
- `Qt6OpenGL.dll`／`Qt6OpenGLWidgets.dll` **不可**被剔除（`Qt6UiTools.dll` 連結期硬相依）
- 兩份 spec 的 `excludes` 都**不可**含整包 `PIL`（matplotlib module 層就 import 它）
"""

import ast
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pyi_prune  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SPECS = ("Police-Document-Manager.spec", "Police-Entry-Manager.spec")


class _FakeAnalysis:
    def __init__(self, binaries, datas):
        self.binaries = binaries
        self.datas = datas


class TestDropRules(unittest.TestCase):
    def test_drops_software_opengl(self):
        self.assertEqual(pyi_prune._drop(r"PySide6\opengl32sw.dll", "x"), "unused-qt")

    def test_drops_quick_and_qml(self):
        for name in ("Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlModels.dll"):
            self.assertEqual(pyi_prune._drop(rf"PySide6\{name}", "x"), "unused-qt", name)

    def test_keeps_opengl_dlls_required_by_uitools(self):
        """QtUiTools 連結期硬相依，砍掉打包版一開機就 ImportError（踩過）。"""
        for name in ("Qt6OpenGL.dll", "Qt6OpenGLWidgets.dll"):
            self.assertIsNone(pyi_prune._drop(rf"PySide6\{name}", "x"), name)

    def test_keeps_core_qt(self):
        for name in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6UiTools.dll",
                     "Qt6PrintSupport.dll", "Qt6Svg.dll"):
            self.assertIsNone(pyi_prune._drop(rf"PySide6\{name}", "x"), name)

    def test_drops_git_openssl_by_source_path(self):
        got = pyi_prune._drop(
            "libcrypto-3-x64.dll", r"C:\Program Files\Git\mingw64\bin\libcrypto-3-x64.dll")
        self.assertEqual(got, "git-openssl")

    def test_keeps_python_own_openssl(self):
        """預設不砍：完整版的 _ssl.pyd／libssl-3.dll 也吃這份 libcrypto。"""
        got = pyi_prune._drop(
            "libcrypto-3.dll", r"C:\Python312\DLLs\libcrypto-3.dll")
        self.assertIsNone(got)

    def test_drops_openssl_only_when_opted_in(self):
        """獨立版限定：唯一使用者 _hashlib 已由 spec excludes 排掉（見 prune docstring）。"""
        for name in ("libcrypto-3.dll", "libssl-3.dll"):
            self.assertEqual(
                pyi_prune._drop(name, r"C:\Python312\DLLs" + "\\" + name,
                                drop_openssl=True),
                "openssl", name)

    def test_drops_pdf_and_network_cluster(self):
        """qpdf→Qt6Pdf→Qt6Network 整串沒人用；缺砍一支就會留下沒被回收的相依。"""
        for name in ("Qt6Pdf.dll", "Qt6Network.dll"):
            self.assertEqual(pyi_prune._drop(rf"PySide6\{name}", "x"), "unused-qt", name)
        self.assertEqual(
            pyi_prune._drop(r"PySide6\plugins\imageformats\qpdf.dll", "x"), "unused-qt")
        for folder in ("tls", "networkinformation", "generic"):
            self.assertEqual(
                pyi_prune._drop(rf"PySide6\plugins\{folder}\whatever.dll", "x"),
                "unused-qt", folder)

    def test_drops_spare_platform_plugins(self):
        for name in ("qdirect2d.dll", "qoffscreen.dll", "qminimal.dll"):
            self.assertEqual(
                pyi_prune._drop(rf"PySide6\plugins\platforms\{name}", "x"),
                "unused-qt", name)

    def test_keeps_plugins_the_app_actually_needs(self):
        """qwindows＝唯一實際使用的平台外掛；svg 是本專案 icon 的命脈；
        qjpeg 為既定安全網；qico 供視窗圖示。"""
        keep = (
            r"PySide6\plugins\platforms\qwindows.dll",
            r"PySide6\plugins\styles\qmodernwindowsstyle.dll",
            r"PySide6\plugins\imageformats\qsvg.dll",
            r"PySide6\plugins\iconengines\qsvgicon.dll",
            r"PySide6\plugins\imageformats\qjpeg.dll",
            r"PySide6\plugins\imageformats\qico.dll",
            r"PySide6\Qt6Svg.dll",
        )
        for dest in keep:
            self.assertIsNone(pyi_prune._drop(dest, "x"), dest)

    def test_locale_filter_keeps_only_zh_tw(self):
        self.assertIsNone(pyi_prune._drop(r"PySide6\translations\qtbase_zh_TW.qm", "x"))
        for name in ("qtbase_de.qm", "qt_sl.qm", "qtbase_ja.qm"):
            self.assertEqual(
                pyi_prune._drop(rf"PySide6\translations\{name}", "x"), "locale", name)


class TestPruneOnAnalysis(unittest.TestCase):
    def test_prune_filters_in_place_and_reports(self):
        a = _FakeAnalysis(
            binaries=[
                (r"PySide6\opengl32sw.dll", "s", "BINARY"),
                (r"PySide6\Qt6OpenGL.dll", "s", "BINARY"),
                (r"PySide6\Qt6Core.dll", "s", "BINARY"),
            ],
            datas=[
                (r"PySide6\translations\qtbase_de.qm", "s", "DATA"),
                (r"PySide6\translations\qtbase_zh_TW.qm", "s", "DATA"),
            ],
        )
        stats = pyi_prune.prune(a, verbose=False)
        self.assertEqual([x[0] for x in a.binaries],
                         [r"PySide6\Qt6OpenGL.dll", r"PySide6\Qt6Core.dll"])
        self.assertEqual([x[0] for x in a.datas],
                         [r"PySide6\translations\qtbase_zh_TW.qm"])
        self.assertEqual(stats, {"unused-qt": 1, "locale": 1})


class TestSpecFiles(unittest.TestCase):
    """spec 是入庫設定，這裡守住幾條不能退回去的約束。"""

    def _excludes(self, spec):
        path = os.path.join(_ROOT, spec)
        with io.open(path, encoding="utf-8-sig") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "Analysis":
                for kw in node.keywords:
                    if kw.arg == "excludes":
                        return ast.literal_eval(kw.value)
        return []

    def test_specs_exist(self):
        for spec in _SPECS:
            self.assertTrue(os.path.isfile(os.path.join(_ROOT, spec)), spec)

    def test_both_specs_exclude_matplotlib_stack(self):
        """兩支 exe 都不得把 matplotlib／numpy／PIL 打包進去。

        簽收單列印頁自 v1.2.9 起改用 Qt 原生繪圖（`lib/print_canvas.py` 的
        `QtCanvas`），產品路徑已無 matplotlib，這三包連同相依整組排除，
        完整版因此少 25MB。

        ⚠️ 本測試取代了舊的 `test_main_spec_does_not_exclude_whole_pil`
        （當時斷言「完整版**不可**排除 PIL」，理由是 `matplotlib/colors.py`
        在 module 層 `from PIL import Image`）。那條相依隨 matplotlib 一起
        消失，舊斷言已與現實相反——留著會擋住瘦身、改回去會讓 exe 胖回來。

        另一半的保護在 `tools/check_no_matplotlib.py`（靜態掃描＋執行期攔截，
        涵蓋全部 tabs／ui_utils）：這裡只管「有沒有排除」，那裡管「排除了會
        不會炸」，兩邊都要過。
        """
        for spec in _SPECS:
            excludes = self._excludes(spec)
            for mod in ("matplotlib", "numpy", "PIL"):
                self.assertIn(mod, excludes, f"{spec} 應排除 {mod}")

    def test_entry_spec_excludes_rescue_dialog(self):
        """規格禁止獨立版做資料庫還原，這是 profile 之外的第二層保險。"""
        self.assertIn("ui_utils.rescue_dialog", self._excludes("Police-Entry-Manager.spec"))

    def test_both_specs_exclude_qtnetwork_binding(self):
        """Qt6Network.dll 由 prune 砍掉，綁定層必須同時排除，否則留下缺相依的 pyd。"""
        for spec in _SPECS:
            self.assertIn("PySide6.QtNetwork", self._excludes(spec), spec)

    def test_hashlib_excluded_in_entry_spec_only(self):
        """完整版另有 _ssl 吃 libcrypto，排掉 _hashlib 省不到東西又多一份風險。"""
        self.assertIn("_hashlib", self._excludes("Police-Entry-Manager.spec"))
        self.assertNotIn("_hashlib", self._excludes("Police-Document-Manager.spec"))

    def test_no_spec_excludes_uitools_opengl_bindings_dlls(self):
        for spec in _SPECS:
            excludes = self._excludes(spec)
            # Python 綁定層可以排除，但不能連 DLL 一起放進 prune 的黑名單
            self.assertNotIn("Qt6OpenGL.dll", excludes)
        for name in ("qt6opengl.dll", "qt6openglwidgets.dll"):
            self.assertNotIn(name, pyi_prune._DROP_BASENAMES, name)


if __name__ == "__main__":
    unittest.main()
