# ui_utils/__init__.py
# 統一對外介面：外部永遠只寫 `from ui_utils import xxx`
# 不論內部如何拆分，這裡都不需要改動外部呼叫端

from .ui_common import (
    msgInfo, msgWarning, msgCritical, reportError, confirmBox, loadUi,
    BTN_CONFIRM, BTN_DANGER, BTN_CANCEL,
)
from .status  import calcOverdue, colorForStatus
from .sticky_scroll import attachStickyScroll
from .widgets import (
    setupFilterCombo, setupDateEditToToday, setupDateEditCalendarOnly,
    setupNullableDateEdit, NullableDateEdit,
    normalizeDateText, classifyNullableDate,
    refreshFilterCombo, runWithBusy, preserveScroll, attachComboHint,
    RowHoverFilter, RowHoverDelegate, LinkCursorFilter, TwoLineElideLabel,
    parse_recipient_names, format_recipient_names, sort_reward_personnel,
    count_recipient_names, sort_personnel_by_counts,
    RecipientLineEditController, setupRecipientLineEdit,
)
from .table   import (
    setupPreviewTable,
    autoResizeTable,
    makeDeleteBtn,
    refreshDeleteBtns,
    setDocIdLinkCell,
    applyLinkStyle,
    LINK_COLOR,
    FIXED_COL_WIDTHS,
)

from .help_dialog import helpDialog, attachHelpButton
from .edit_dialog import TaskEditDialog, CriminalEditDialog, GeneralEditDialog
from .reward_dialog import RewardEditDialog
from .convert_dialog import ConvertDialog
from .settings_dialogs import (
    RefItemDialog, REF_PERSONNEL, REF_DEPT, REF_CASETYPE,
    ChangePasswordDialog, ResetDialog,
)
from .settings_panels import (ArchiveRootPanel, PrintTitlePanel, IdleTimeoutPanel,
                              InputLockPanel, BackupPanel, InputModePanel)

__all__ = [
    "msgInfo", "msgWarning", "msgCritical", "reportError", "confirmBox", "loadUi",
    "BTN_CONFIRM", "BTN_DANGER", "BTN_CANCEL",
    "calcOverdue",
    "colorForStatus",
    "attachStickyScroll",
    "setupFilterCombo",
    "refreshFilterCombo",
    "attachComboHint",
    "setupDateEditToToday",
    "setupDateEditCalendarOnly",
    "setupNullableDateEdit",
    "NullableDateEdit",
    "normalizeDateText",
    "classifyNullableDate",
    "runWithBusy",
    "preserveScroll",
    "RowHoverFilter",
    "RowHoverDelegate",
    "LinkCursorFilter",
    "TwoLineElideLabel",
    "parse_recipient_names",
    "format_recipient_names",
    "sort_reward_personnel",
    "count_recipient_names",
    "sort_personnel_by_counts",
    "RecipientLineEditController",
    "setupRecipientLineEdit",
    "setupPreviewTable",
    "autoResizeTable",
    "makeDeleteBtn",
    "refreshDeleteBtns",
    "setDocIdLinkCell",
    "applyLinkStyle",
    "LINK_COLOR",
    "helpDialog",
    "attachHelpButton",
    "TaskEditDialog",
    "CriminalEditDialog",
    "GeneralEditDialog",
    "RewardEditDialog",
    "ConvertDialog",
    "FIXED_COL_WIDTHS",
    "RefItemDialog", "REF_PERSONNEL", "REF_DEPT", "REF_CASETYPE",
    "ChangePasswordDialog", "ResetDialog",
    "ArchiveRootPanel", "PrintTitlePanel", "IdleTimeoutPanel", "InputLockPanel",
    "BackupPanel", "InputModePanel",
]
