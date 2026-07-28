import os

from lib.app_profile import ENTRY_PROFILE

# main.py 在 import 期間即安裝全域 excepthook；先傳入獨立版名稱，避免該時段
# 的未捕捉例外被 Windows 事件檢視器標成完整版。匯入後還原環境，避免污染後續模組。
_ERROR_SOURCE_ENV = "POLICE_DOCSYS_PRODUCT_NAME"
_previous_error_source = os.environ.get(_ERROR_SOURCE_ENV)
os.environ[_ERROR_SOURCE_ENV] = ENTRY_PROFILE.product_name
try:
    from main import runApplication
finally:
    if _previous_error_source is None:
        os.environ.pop(_ERROR_SOURCE_ENV, None)
    else:
        os.environ[_ERROR_SOURCE_ENV] = _previous_error_source


def main() -> int:
    return runApplication(ENTRY_PROFILE)


if __name__ == "__main__":
    raise SystemExit(main())
