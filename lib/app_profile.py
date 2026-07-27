"""集中式應用 Profile：完整版與獨立版（警政快速登錄系統）能力設定唯一來源。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AppProfile:
    key: str
    product_name: str
    exe_name: str
    tab_keys: tuple[str, ...]
    menu_keys: tuple[str, ...]
    menu_labels: dict[str, str]
    browse_keys: tuple[str, ...]
    preload_keys: tuple[str, ...]
    settings_pages: tuple[str, ...]
    system_panels: tuple[str, ...]
    input_lock_flows: tuple[str, ...]
    input_mode_flows: tuple[str, ...]

    def allows_tab(self, key: str) -> bool:
        return key in self.tab_keys

    def allows_browse(self, key: str) -> bool:
        return key in self.browse_keys

    def allows_setting(self, key: str) -> bool:
        return key in self.settings_pages


FULL_PROFILE = AppProfile(
    key="full",
    product_name="公文管理系統",
    exe_name="Police-Document-Manager.exe",
    tab_keys=(
        "assignment_issue", "assignment_receive", "report", "reward",
        "reward_issue", "ticket", "print", "browse", "archive",
        "settings", "audit",
    ),
    menu_keys=(
        "assignment_issue", "assignment_receive", "report", "reward",
        "reward_issue", "ticket", "print", "browse", "archive",
        "settings", "audit",
    ),
    menu_labels={
        "assignment_issue": "交辦單發文",
        "assignment_receive": "交辦單收文",
        "report": "公文陳報",
        "reward": "敘獎登錄",
        "reward_issue": "敘獎發文",
        "ticket": "罰單登錄",
        "print": "簽收單列印",
        "browse": "資料庫瀏覽",
        "archive": "檔案歸檔",
        "settings": "資料庫設定",
        "audit": "操作紀錄",
    },
    browse_keys=("task", "crim", "gen", "reward", "ticket"),
    preload_keys=("task", "crim", "gen"),
    settings_pages=("personnel", "dept", "casetype", "system", "trash", "backup"),
    system_panels=(
        "archive_root", "print_title", "idle", "input_lock", "backup", "input_mode",
    ),
    input_lock_flows=(
        "dispatch", "task", "crim", "gen", "ticket", "reward", "reward_issue",
    ),
    input_mode_flows=("crim", "gen", "ticket"),
)


ENTRY_PROFILE = AppProfile(
    key="entry",
    product_name="警政快速登錄系統",
    exe_name="Police-Entry-Manager.exe",
    tab_keys=("reward", "ticket", "browse", "settings"),
    menu_keys=("reward", "ticket", "browse", "settings"),
    menu_labels={
        "reward": "敘獎登錄",
        "ticket": "罰單登錄",
        "browse": "資料庫瀏覽",
        "settings": "系統設定",
    },
    browse_keys=("reward", "ticket"),
    preload_keys=(),
    settings_pages=("personnel", "system"),
    system_panels=("idle", "input_lock", "input_mode"),
    input_lock_flows=("reward", "ticket"),
    input_mode_flows=("ticket",),
)
