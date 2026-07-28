import os
import sys
import subprocess
import textwrap
from types import SimpleNamespace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

import main
from lib.app_profile import ENTRY_PROFILE


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_document_manager_failure_closes_loading_reports_and_exits(monkeypatch):
    """主視窗建構失敗時，不能留下 loading 視窗或繼續進入主選單。"""
    class Loading:
        def __init__(self):
            self.closed = False

        def finishAndClose(self):
            self.closed = True

        def setStep(self, *_args):
            pass

    loading = Loading()
    reported = {}

    monkeypatch.setattr(main, "DocumentManager",
                        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(main.logging, "error",
                        lambda message: reported.setdefault("log", message))
    import ui_utils
    monkeypatch.setattr(ui_utils, "msgCritical",
                        lambda title, text: reported.update(title=title, text=text))

    with pytest.raises(SystemExit) as exited:
        main._buildDocumentManagerOrExit(
            loading, results={}, profile=ENTRY_PROFILE, cleanup_lock=lambda: None)

    assert exited.value.code == 1
    assert loading.closed is True
    assert "RuntimeError: boom" in reported["log"]
    assert reported["title"] == "系統錯誤"


def test_error_handler_uses_profile_product_name_for_windows_event_source(monkeypatch):
    """獨立版未捕捉例外不得在事件檢視器標成完整版產品。"""
    reported = {}
    import ui_utils
    monkeypatch.setattr(main.logging, "error", lambda _message: None)
    monkeypatch.setattr(ui_utils, "msgCritical", lambda *_args, **_kwargs: None)
    monkeypatch.setitem(sys.modules, "win32evtlog",
                        SimpleNamespace(EVENTLOG_ERROR_TYPE="error"))
    monkeypatch.setitem(
        sys.modules, "win32evtlogutil",
        SimpleNamespace(ReportEvent=lambda source, *_args, **_kwargs:
                        reported.setdefault("source", source)),
    )

    previous_hook = sys.excepthook
    try:
        main._setup_error_handler(ENTRY_PROFILE.product_name)
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            sys.excepthook(type(exc), exc, exc.__traceback__)

        assert reported["source"] == ENTRY_PROFILE.product_name
    finally:
        sys.excepthook = previous_hook


def test_standalone_import_installs_entry_error_source_before_runner_starts():
    """standalone_main 匯入 main 期間安裝的 handler 就必須是獨立版名稱。"""
    script = textwrap.dedent("""
        import sys
        from types import SimpleNamespace

        seen = {}
        sys.modules["win32evtlog"] = SimpleNamespace(EVENTLOG_ERROR_TYPE="error")
        sys.modules["win32evtlogutil"] = SimpleNamespace(
            ReportEvent=lambda source, *_args, **_kwargs: seen.setdefault("source", source))

        import standalone_main
        import main
        main.logging.error = lambda _message: None
        try:
            raise RuntimeError("import-seam")
        except RuntimeError as exc:
            sys.excepthook(type(exc), exc, exc.__traceback__)
        print(seen["source"])
    """)
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=REPO_ROOT,
        capture_output=True, text=True, encoding="utf-8", timeout=30,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == ENTRY_PROFILE.product_name
