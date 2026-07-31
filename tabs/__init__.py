"""
延遲載入（PEP 562 module-level __getattr__）：只在實際存取某個 Tab 類別時，
才 import 對應子模組。

目的：`tabs/tab_print.py` 於模組層引入 matplotlib（全專案唯一重量級 import
來源，未壓縮約 49MB／耗時約 1 秒）。獨立版（ENTRY_PROFILE）不含列印頁，
不應為了 import 套件而連帶付出這筆成本；大程式（FULL_PROFILE）仍會在建立
列印頁時觸發載入，行為不變。

對外寫法完全相容：`from tabs import TabReward`、`import tabs; tabs.TabPrint`
皆可照舊使用；差別只在於「未被存取的分頁模組不會被 import」。
"""
import importlib
import sys

__all__ = [
    "TabDispatch", "TabReceive", "TabReport", "TabReward",
    "TabTicket", "TabPrint",
    "TabDBBrowse", "TabArchive", "TabSettings", "TabAudit",
]

# 類別名 → 子模組名（同套件內，相對匯入）
_TAB_MODULES = {
    "TabDispatch":    "tab_dispatch",
    "TabReceive":     "tab_receive",
    "TabReport":      "tab_report",
    "TabReward":      "tab_reward",
    "TabTicket":      "tab_ticket",
    "TabPrint":       "tab_print",
    "TabDBBrowse":    "tab_dbbrowse",
    "TabArchive":     "tab_archive",
    "TabSettings":    "tab_settings",
    "TabAudit":       "tab_audit",
}


def __getattr__(name):
    module_name = _TAB_MODULES.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    setattr(sys.modules[__name__], name, value)  # 快取，之後直接取屬性不再進 __getattr__
    return value
