"""測試套件。

⚠️ 這裡只做一件事：`unittest` 跑法沒有 `conftest.py`，故在此補上日期防呆的
遮蔽（PITFALLS TST-4）。pytest 跑法由根 `conftest.py` 的 autouse fixture 處理，
兩者共用 `tests/date_guard_shim.py` 這一份實作。沒有這段的話，
`python -m unittest discover -s tests` 會卡在無人可按的確認框上不結束。
"""
import sys

if "pytest" not in sys.modules:          # pytest 有自己的 fixture，不重複安裝
    from tests.date_guard_shim import installAutoConfirm
    installAutoConfirm()
