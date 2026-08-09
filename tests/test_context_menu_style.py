# -*- coding: utf-8 -*-
"""標準文字編輯右鍵選單必須套用公版樣式與 Qt 繁中翻譯。"""
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QLibraryInfo
from PySide6.QtWidgets import QApplication, QLineEdit

import main
from lib.theme import APPLE_STYLE


_app = QApplication.instance() or QApplication([])
STYLE_RULES = re.sub(r"/\*.*?\*/", "", APPLE_STYLE, flags=re.S)


def _is_near_white(color):
    return min(color.red(), color.green(), color.blue()) >= 235


def _is_dark(color):
    return max(color.red(), color.green(), color.blue()) <= 100


class _FakeTranslator:
    """只替換 Qt 的檔案解析邊界；app 安裝流程仍走正式函式。"""

    loadable_paths = set()
    attempted_paths = []
    constructor_effects = []
    load_effects = {}

    def __init__(self, parent=None):
        if self.constructor_effects:
            effect = self.constructor_effects.pop(0)
            if isinstance(effect, Exception):
                raise effect
        self.parent = parent

    def load(self, path):
        normalized = os.path.normpath(path)
        self.attempted_paths.append(normalized)
        effect = self.load_effects.get(normalized)
        if isinstance(effect, Exception):
            raise effect
        if effect is not None:
            return effect
        return normalized in self.loadable_paths


class _RecordingApp:
    def __init__(self):
        self.installed = []
        self.install_attempts = []
        self.install_effects = []

    def installTranslator(self, translator):
        self.install_attempts.append(translator)
        effect = self.install_effects.pop(0) if self.install_effects else True
        if isinstance(effect, Exception):
            raise effect
        if effect:
            self.installed.append(translator)
        return effect


class TestContextMenuTheme(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._previous_style = _app.styleSheet()
        _app.setStyleSheet(APPLE_STYLE)

    @classmethod
    def tearDownClass(cls):
        _app.setStyleSheet(cls._previous_style)

    def test_global_theme_contains_complete_menu_rules(self):
        expected_rules = (
            "QMenu {",
            "QMenu::item",
            "QMenu::item:selected",
            "QMenu::item:disabled",
            "QMenu::separator",
        )
        for selector in expected_rules:
            with self.subTest(selector=selector):
                self.assertIn(selector, STYLE_RULES)
        self.assertRegex(
            STYLE_RULES,
            r"QMenu\s*\{[^}]*background-color:\s*#ffffff",
        )
        self.assertRegex(
            STYLE_RULES,
            r"QMenu::item:selected\s*\{[^}]*background-color:\s*#6e8fac",
        )

    def test_standard_menu_renders_with_light_background_and_dark_text(self):
        editor = QLineEdit("可編輯文字")
        menu = editor.createStandardContextMenu()

        def _close_menu():
            menu.close()
            editor.close()
            _app.processEvents()
            menu.deleteLater()
            editor.deleteLater()
            _app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            _app.processEvents()

        self.addCleanup(_close_menu)

        menu.show()
        _app.processEvents()
        image = menu.grab().toImage()
        self.assertGreater(image.width(), 30)
        self.assertGreater(image.height(), 20)

        # 左側留白帶不含文字與快捷鍵，取一整區而非單點，避開圓角、陰影與縮放差異。
        background = [
            image.pixelColor(x, y)
            for y in range(8, max(9, image.height() - 8))
            for x in range(8, min(24, image.width() - 8))
        ]
        near_white = sum(_is_near_white(color) for color in background)
        self.assertGreater(
            near_white / len(background),
            0.70,
            "標準右鍵選單未呈現公版的淺色背景",
        )

        # 排除邊框後掃描文字區；需有一批深色像素，不能是黑底白字的原生選單。
        text_area = [
            image.pixelColor(x, y)
            for y in range(8, image.height() - 8)
            for x in range(24, max(25, image.width() - 8))
        ]
        self.assertGreater(
            sum(_is_dark(color) for color in text_area),
            20,
            "標準右鍵選單找不到公版深色文字",
        )


class TestChineseTranslatorIntegration(unittest.TestCase):
    def test_standard_menu_undo_action_is_translated(self):
        translation_dir = QLibraryInfo.path(
            QLibraryInfo.LibraryPath.TranslationsPath)
        qm_path = Path(translation_dir) / "qtbase_zh_TW.qm"
        if not qm_path.is_file():
            self.skipTest(f"測試環境沒有 Qt 繁中翻譯檔：{qm_path}")

        previous = getattr(_app, "_qtbase_zh_tw_translator", None)
        installed = None
        try:
            self.assertTrue(main._installChineseTranslator(_app))
            installed = getattr(_app, "_qtbase_zh_tw_translator", None)
            editor = QLineEdit("可編輯文字")
            menu = editor.createStandardContextMenu()
            self.addCleanup(editor.deleteLater)
            self.addCleanup(menu.deleteLater)
            first_text = menu.actions()[0].text().replace("&", "")
            self.assertIn("復原", first_text)
        finally:
            if installed is not None and installed is not previous:
                _app.removeTranslator(installed)
            if previous is None:
                try:
                    delattr(_app, "_qtbase_zh_tw_translator")
                except AttributeError:
                    pass
            else:
                _app._qtbase_zh_tw_translator = previous


class TestChineseTranslatorLoading(unittest.TestCase):
    def setUp(self):
        _FakeTranslator.loadable_paths = set()
        _FakeTranslator.attempted_paths = []
        _FakeTranslator.constructor_effects = []
        _FakeTranslator.load_effects = {}
        self.app = _RecordingApp()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def _create_qm(self, directory):
        path = Path(directory) / "qtbase_zh_TW.qm"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        _FakeTranslator.loadable_paths.add(os.path.normpath(str(path)))
        return path

    def _install(self, official_dir, bundled_dir):
        resource_path = patch.object(
            main, "getResourcePath", return_value=str(bundled_dir))
        with (
            patch("PySide6.QtCore.QLibraryInfo.path", return_value=str(official_dir)),
            patch("PySide6.QtCore.QTranslator", _FakeTranslator),
            resource_path as self.get_resource_path,
        ):
            return main._installChineseTranslator(self.app)

    def test_loads_from_qt_official_translation_directory(self):
        official_dir = self.root / "qt-translations"
        qm_path = self._create_qm(official_dir)

        self.assertTrue(self._install(official_dir, self.root / "bundle"))
        self.assertEqual(_FakeTranslator.attempted_paths,
                         [os.path.normpath(str(qm_path))])
        self.assertEqual(len(self.app.installed), 1)
        self.assertIs(self.app._qtbase_zh_tw_translator, self.app.installed[0])

    def test_falls_back_to_pyinstaller_translation_directory(self):
        official_dir = self.root / "missing-qt-translations"
        bundled_dir = self.root / "bundle" / "PySide6" / "translations"
        qm_path = self._create_qm(bundled_dir)

        self.assertTrue(self._install(official_dir, bundled_dir))
        self.get_resource_path.assert_called_once_with("PySide6/translations")
        self.assertEqual(_FakeTranslator.attempted_paths,
                         [os.path.normpath(str(qm_path))])
        self.assertEqual(len(self.app.installed), 1)
        self.assertIs(self.app._qtbase_zh_tw_translator, self.app.installed[0])

    def test_missing_translation_files_is_silent_and_installs_nothing(self):
        result = self._install(
            self.root / "missing-qt-translations",
            self.root / "missing-bundle-translations",
        )

        self.assertFalse(result)
        self.assertEqual(self.app.installed, [])
        self.assertFalse(hasattr(self.app, "_qtbase_zh_tw_translator"))

    def test_failed_official_load_falls_back_to_bundle(self):
        official_dir = self.root / "qt-translations"
        bundled_dir = self.root / "bundle-translations"
        official_qm = self._create_qm(official_dir)
        bundled_qm = self._create_qm(bundled_dir)
        _FakeTranslator.loadable_paths.remove(os.path.normpath(str(official_qm)))

        self.assertTrue(self._install(official_dir, bundled_dir))
        self.assertEqual(
            _FakeTranslator.attempted_paths,
            [os.path.normpath(str(official_qm)), os.path.normpath(str(bundled_qm))],
        )
        self.assertEqual(len(self.app.installed), 1)
        self.assertIs(self.app._qtbase_zh_tw_translator, self.app.installed[0])

    def test_load_error_falls_back_to_bundle(self):
        official_dir = self.root / "qt-translations"
        bundled_dir = self.root / "bundle-translations"
        official_qm = self._create_qm(official_dir)
        bundled_qm = self._create_qm(bundled_dir)
        _FakeTranslator.load_effects[os.path.normpath(str(official_qm))] = \
            RuntimeError("cannot parse qm")

        self.assertTrue(self._install(official_dir, bundled_dir))
        self.assertEqual(
            _FakeTranslator.attempted_paths,
            [os.path.normpath(str(official_qm)), os.path.normpath(str(bundled_qm))],
        )
        self.assertIs(self.app._qtbase_zh_tw_translator, self.app.installed[0])

    def test_all_load_failures_are_silent(self):
        official_dir = self.root / "qt-translations"
        bundled_dir = self.root / "bundle-translations"
        official_qm = self._create_qm(official_dir)
        bundled_qm = self._create_qm(bundled_dir)
        _FakeTranslator.load_effects[os.path.normpath(str(official_qm))] = \
            RuntimeError("cannot parse qm")
        _FakeTranslator.loadable_paths.remove(os.path.normpath(str(bundled_qm)))

        self.assertFalse(self._install(official_dir, bundled_dir))
        self.assertEqual(self.app.installed, [])
        self.assertFalse(hasattr(self.app, "_qtbase_zh_tw_translator"))

    def test_install_error_falls_back_without_retaining_failed_translator(self):
        official_dir = self.root / "qt-translations"
        bundled_dir = self.root / "bundle-translations"
        self._create_qm(official_dir)
        self._create_qm(bundled_dir)
        self.app.install_effects = [RuntimeError("install failed"), True]

        self.assertTrue(self._install(official_dir, bundled_dir))
        self.assertEqual(len(self.app.install_attempts), 2)
        self.assertEqual(len(self.app.installed), 1)
        self.assertIs(self.app._qtbase_zh_tw_translator, self.app.installed[0])
        self.assertIsNot(self.app._qtbase_zh_tw_translator,
                         self.app.install_attempts[0])

    def test_install_false_falls_back_without_retaining_failed_translator(self):
        official_dir = self.root / "qt-translations"
        bundled_dir = self.root / "bundle-translations"
        self._create_qm(official_dir)
        self._create_qm(bundled_dir)
        self.app.install_effects = [False, True]

        self.assertTrue(self._install(official_dir, bundled_dir))
        self.assertEqual(len(self.app.install_attempts), 2)
        self.assertEqual(len(self.app.installed), 1)
        self.assertIs(self.app._qtbase_zh_tw_translator, self.app.installed[0])
        self.assertIsNot(self.app._qtbase_zh_tw_translator,
                         self.app.install_attempts[0])

    def test_constructor_error_falls_back_without_escaping(self):
        official_dir = self.root / "qt-translations"
        bundled_dir = self.root / "bundle-translations"
        self._create_qm(official_dir)
        bundled_qm = self._create_qm(bundled_dir)
        _FakeTranslator.constructor_effects = [RuntimeError("cannot construct"), None]

        self.assertTrue(self._install(official_dir, bundled_dir))
        self.assertEqual(_FakeTranslator.attempted_paths,
                         [os.path.normpath(str(bundled_qm))])
        self.assertEqual(len(self.app.installed), 1)
        self.assertIs(self.app._qtbase_zh_tw_translator, self.app.installed[0])


if __name__ == "__main__":
    unittest.main()
