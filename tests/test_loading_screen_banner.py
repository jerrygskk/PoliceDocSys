import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from lib.app_profile import ENTRY_PROFILE, FULL_PROFILE
from lib.db_utils import getResourcePath
from lib.loading_screen import LoadingScreen


_app = QApplication.instance() or QApplication([])


def test_loading_screen_renders_the_profile_banner(monkeypatch):
    monkeypatch.setattr(LoadingScreen, "_start_worker", lambda self: None)

    for profile in (FULL_PROFILE, ENTRY_PROFILE):
        loading = LoadingScreen("unused.db", banner_path=profile.banner_path)
        expected = QPixmap(getResourcePath(profile.banner_path)).scaled(
            loading.WIN_W,
            279,
            Qt.IgnoreAspectRatio,
            Qt.SmoothTransformation,
        )

        actual = loading.banner_label.pixmap()
        assert actual is not None
        assert actual.toImage() == expected.toImage()
        loading.close()


def test_loading_screen_fallback_uses_profile_product_name(monkeypatch):
    monkeypatch.setattr(LoadingScreen, "_start_worker", lambda self: None)

    loading = LoadingScreen("unused.db", banner_path="missing-banner.png",
                            product_name=ENTRY_PROFILE.product_name)

    assert loading.banner_label.text() == ENTRY_PROFILE.product_name
    loading.close()
