# 依角色隱藏主功能 TAB Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 依 `user`、`archive`、`admin` 角色隱藏無權限的大 TAB，讓剩餘 TAB 向左遞補，同時保留完整主選單、登入續接與正確 HELP 對應。

**Architecture:** `lib/app_profile.py` 提供不依賴 GUI 的角色可見矩陣，`DocumentManager` 只以 `QTabWidget.setTabVisible()` 套用可見性，保留 Profile 建立後的固定 index。主選單仍回傳原功能 key；`DocumentManager` 判斷受限目標並導向設定登入，登入成功後由既有 `role_changed` signal 重套矩陣並續接目標。

**Tech Stack:** Python 3、PySide6／Qt `QTabWidget`、pytest-qt、unittest、現有 `AuthManager` signal、現有 HELP／QUICKSTART。

## Global Constraints

- 目標環境為 Windows、顯示縮放 125%、全域字體 14pt。
- 所有中文文字檔明確以 UTF-8 讀寫。
- `AppProfile` 仍是產品版本能力邊界；角色不得顯示 Profile 未包含的 TAB。
- 角色切換只能使用 `setTabVisible()`；不得以 `removeTab()`／`insertTab()` 重排執行中 TAB。
- 一般使用者顯示 9 個 TAB，隱藏「檔案歸檔、操作紀錄」。
- 歸檔管理員顯示 10 個 TAB，只隱藏「操作紀錄」。
- 管理者顯示全部 11 個 TAB。
- 一般使用者必須看得到「交辦單發文」、「敘獎發文」與「資料庫設定」。
- 主選單保留 Profile 原有全部 icon；受限入口不跳訊息框，直接導向設定登入頁。
- 不新增角色、不改各 TAB 內部版面、不縮減既有操作權限 guard。
- HELP 固定內容 ID 與固定 index mapping 不重新編號。
- README 與 DEVELOPER.md 只依專案文件規則更新；不修改 `lib/version.py`。

---

## File Structure

- Modify: `lib/app_profile.py` — 集中定義角色隱藏集合與 Profile 交集後的可見 key。
- Modify: `main.py` — 套用 TAB 可見性、處理角色變更、主選單受限入口與登入後續接。
- Modify: `tabs/tab_settings.py` — 在既有登入卡片顯示受限功能的登入引導，並於一般登出時重設。
- Modify: `tests/test_app_profile.py` — 純邏輯矩陣與 Profile 邊界測試。
- Modify: `tests/test_standalone_shell.py` — 真實 Qt TAB 顯隱、索引、主選單導向與角色切換測試。
- Modify: `tests/test_dialog_smoke.py` — 動態隱藏後 HELP key／內容頁 mapping 回歸。
- Modify: `ui_utils/help_content.py` — 共用 HELP 與 QUICKSTART 加入角色可見性和登入導向說明。
- Modify: `tests/test_reward_integration.py` — 固定 HELP／QUICKSTART 內容 ID 與新增說明的整合斷言。
- Modify: `DEVELOPER.md` — 更新架構、跨功能影響表、HELP 說明與權限矩陣。
- Review, modify only if §9 criteria require: `README.md` — 使用者需要知道的 TAB 顯隱與登入操作。

---

### Task 1: 建立角色可見矩陣的純邏輯

**Files:**
- Modify: `lib/app_profile.py`
- Test: `tests/test_app_profile.py`

**Interfaces:**
- Consumes: `AppProfile.tab_keys: tuple[str, ...]`
- Produces: `visibleTabKeys(role: str, profile: AppProfile) -> tuple[str, ...]`
- Produces: `_ROLE_HIDDEN_TAB_KEYS: Mapping[str, frozenset[str]]`

- [ ] **Step 1: 先寫三角色與 Profile 邊界的失敗測試**

在 `tests/test_app_profile.py` 加入：

```python
from lib.app_profile import (
    ENTRY_PROFILE,
    FULL_PROFILE,
    visibleTabKeys,
)


def test_full_profile_visible_tabs_follow_role_matrix():
    assert visibleTabKeys("user", FULL_PROFILE) == (
        "assignment_issue", "assignment_receive", "report", "reward",
        "reward_issue", "ticket", "print", "browse", "settings",
    )
    assert visibleTabKeys("archive", FULL_PROFILE) == (
        "assignment_issue", "assignment_receive", "report", "reward",
        "reward_issue", "ticket", "print", "browse", "archive", "settings",
    )
    assert visibleTabKeys("admin", FULL_PROFILE) == FULL_PROFILE.tab_keys


def test_entry_profile_role_matrix_never_adds_full_only_tabs():
    for role in ("user", "archive", "admin"):
        assert visibleTabKeys(role, ENTRY_PROFILE) == ENTRY_PROFILE.tab_keys


def test_unknown_role_uses_least_privileged_visibility():
    assert visibleTabKeys("unexpected", FULL_PROFILE) == visibleTabKeys(
        "user", FULL_PROFILE
    )


def test_general_user_keeps_both_issue_tabs_and_settings():
    visible = set(visibleTabKeys("user", FULL_PROFILE))
    assert {"assignment_issue", "reward_issue", "settings"} <= visible
    assert {"archive", "audit"}.isdisjoint(visible)
```

- [ ] **Step 2: 執行測試並確認因介面尚未存在而失敗**

Run:

```powershell
python -m pytest tests/test_app_profile.py -q
```

Expected: collection error or import failure mentioning `visibleTabKeys`.

- [ ] **Step 3: 實作最小矩陣與安全 fallback**

在 `lib/app_profile.py` 的 `AppProfile` 定義後加入：

```python
_ROLE_HIDDEN_TAB_KEYS = MappingProxyType({
    "user": frozenset({"archive", "audit"}),
    "archive": frozenset({"audit"}),
    "admin": frozenset(),
})


def visibleTabKeys(role: str, profile: AppProfile) -> tuple[str, ...]:
    """依角色隱藏 Profile 既有 Tab；未知角色採一般使用者最小權限。"""
    hidden = _ROLE_HIDDEN_TAB_KEYS.get(
        role, _ROLE_HIDDEN_TAB_KEYS["user"]
    )
    return tuple(key for key in profile.tab_keys if key not in hidden)
```

矩陣只做 Profile 既有 key 的過濾，不得從 `FULL_PROFILE` 補 key。

- [ ] **Step 4: 執行純邏輯測試**

Run:

```powershell
python -m pytest tests/test_app_profile.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交純邏輯矩陣**

```powershell
git add -- lib/app_profile.py tests/test_app_profile.py
git commit -m "feat: define role tab visibility matrix"
```

---

### Task 2: 讓主視窗動態隱藏 TAB 且保留固定索引

**Files:**
- Modify: `main.py:147-221`
- Modify: `main.py:362-425`
- Test: `tests/test_standalone_shell.py`

**Interfaces:**
- Consumes: `visibleTabKeys(role, profile) -> tuple[str, ...]`
- Produces: `DocumentManager._visibleTabKeys(role: str | None = None) -> tuple[str, ...]`
- Produces: `DocumentManager._isTabVisible(key: str, role: str | None = None) -> bool`
- Produces: `DocumentManager._applyTabVisibility(role: str) -> None`
- Produces: `DocumentManager._onRoleChanged(role: str) -> None`

- [ ] **Step 1: 寫真實 QTabWidget 顯隱與索引不變的失敗測試**

在 `tests/test_standalone_shell.py` 加入：

```python
def _visible_tab_keys(manager):
    return tuple(
        key for key, index in manager.tab_index_by_key.items()
        if manager.tab_widget.isTabVisible(index)
    )


def test_full_manager_initial_user_visibility_hides_archive_and_audit(
        qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    assert _visible_tab_keys(manager) == (
        "assignment_issue", "assignment_receive", "report", "reward",
        "reward_issue", "ticket", "print", "browse", "settings",
    )
    assert manager.tab_widget.count() == 11
    assert manager.tab_index("settings") == 9
    assert manager.tab_index("audit") == 10


def test_role_change_updates_visibility_without_reindexing(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    original_mapping = dict(manager.tab_index_by_key)

    manager._applyTabVisibility("archive")
    assert _visible_tab_keys(manager) == tuple(
        key for key in FULL_PROFILE.tab_keys if key != "audit"
    )

    manager._applyTabVisibility("admin")
    assert _visible_tab_keys(manager) == FULL_PROFILE.tab_keys
    assert manager.tab_index_by_key == original_mapping
    assert manager.tab_widget.count() == 11


def test_entry_manager_visibility_never_adds_removed_tabs(qtbot, shell_db):
    manager = DocumentManager(profile=ENTRY_PROFILE)
    qtbot.addWidget(manager.window)
    manager._applyTabVisibility("admin")
    assert _visible_tab_keys(manager) == ENTRY_PROFILE.tab_keys
    assert manager.tab_widget.count() == 4
```

更新既有 `test_full_manager_keeps_all_current_tab_keys`：保留 `count() == 11` 與 mapping 斷言，但不要再把「QTabWidget 內存在」誤解為「一般使用者全部可見」。

- [ ] **Step 2: 執行 Qt shell 測試確認失敗**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_standalone_shell.py -q
```

Expected: FAIL，因 `_applyTabVisibility` 尚不存在，且初始 user 尚未隱藏兩頁。

- [ ] **Step 3: 在 DocumentManager 實作可見性 helper**

於 `main.py` 匯入 `visibleTabKeys`，並在 `tab_index()` 附近加入：

```python
def _visibleTabKeys(self, role=None):
    role = role or AuthManager.instance().current_role
    return visibleTabKeys(role, self.profile)

def _isTabVisible(self, key, role=None):
    return key in self._visibleTabKeys(role)

def _applyTabVisibility(self, role):
    visible = set(self._visibleTabKeys(role))
    current = self.tab_widget.currentIndex()
    current_key = next(
        (key for key, index in self.tab_index_by_key.items()
         if index == current),
        None,
    )

    if current_key not in visible:
        fallback = self._IDX_SETTINGS
        if fallback is not None:
            self.tab_widget.setCurrentIndex(fallback)

    for key, index in self.tab_index_by_key.items():
        self.tab_widget.setTabVisible(index, key in visible)

    self._prev_tab_index = self.tab_widget.currentIndex()
```

初始化時在 `_prev_tab_index` 建立且 HELP 掛載完成後，以目前 `AuthManager.current_role` 呼叫 `_applyTabVisibility()`；再將 `role_changed` 連到 `_onRoleChanged`。

```python
def _onRoleChanged(self, role):
    self._applyTabVisibility(role)
```

`_updateTitle` 的既有 signal 連線保留。若目前頁將被隱藏，必須先切到設定，再隱藏目標，避免 Qt 自行選到不可預期頁面。

- [ ] **Step 4: 驗證三角色、固定 index 與獨立版**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_standalone_shell.py -q
```

Expected: PASS。

- [ ] **Step 5: 提交 TAB 顯隱**

```powershell
git add -- main.py tests/test_standalone_shell.py
git commit -m "feat: hide tabs by active role"
```

---

### Task 3: 保留完整主選單並將受限入口導向登入

**Files:**
- Modify: `main.py:430-545`
- Modify: `main.py:700-738`
- Modify: `tabs/tab_settings.py:258-267`
- Modify: `tabs/tab_settings.py:638-659`
- Modify: `tabs/tab_settings.py:723-735`
- Test: `tests/test_standalone_shell.py`

**Interfaces:**
- Consumes: `DocumentManager._isTabVisible(key, role=None) -> bool`
- Produces: `DocumentManager.requestTab(key: str, role: str | None = None) -> bool`
- Produces: `DocumentManager._pending_tab_key: str | None`
- Produces: `TabSettings.showLoginPrompt(target_label: str | None = None) -> None`
- Produces: `TabSettings.clearLoginPrompt() -> None`

- [ ] **Step 1: 寫受限入口、登入提示與續接的失敗測試**

在 `tests/test_standalone_shell.py` 加入：

```python
def test_request_hidden_tab_routes_user_to_settings_login(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)

    assert manager.requestTab("archive") is False
    assert manager.tab_widget.currentIndex() == manager.tab_index("settings")
    assert manager._prev_tab_index == manager.tab_index("settings")
    assert manager._pending_tab_key == "archive"

    settings = manager.tabs[manager.tab_index("settings")]
    assert settings._outer_stack.currentIndex() == 0
    assert "檔案歸檔" in settings._lbl_login_ttl.text()


def test_request_visible_tab_opens_it_without_pending_login(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)

    assert manager.requestTab("reward_issue") is True
    assert manager.tab_widget.currentIndex() == manager.tab_index("reward_issue")
    assert manager._pending_tab_key is None


def test_archive_login_continues_archive_but_not_audit(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)

    manager.requestTab("archive")
    manager._onRoleChanged("archive")
    assert manager.tab_widget.currentIndex() == manager.tab_index("archive")
    assert manager._pending_tab_key is None

    manager._applyTabVisibility("user")
    manager.requestTab("audit")
    manager._onRoleChanged("archive")
    assert manager.tab_widget.currentIndex() == manager.tab_index("settings")
    assert manager._pending_tab_key is None


def test_admin_login_continues_audit_target(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)

    manager.requestTab("audit")
    manager._onRoleChanged("admin")
    assert manager.tab_widget.currentIndex() == manager.tab_index("audit")
    assert manager._pending_tab_key is None


def test_unknown_key_clears_older_pending_target(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)

    manager.requestTab("audit")
    assert manager._pending_tab_key == "audit"

    assert manager.requestTab("not-a-tab") is False
    assert manager._pending_tab_key is None
```

另加一支設定提示重設測試：

```python
def test_login_prompt_resets_when_returning_to_user(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    settings = manager.tabs[manager.tab_index("settings")]

    settings.showLoginPrompt("操作紀錄")
    assert "操作紀錄" in settings._lbl_login_ttl.text()
    settings._onRoleChanged("user")
    assert settings._lbl_login_ttl.text() == "管理者驗證"
```

- [ ] **Step 2: 執行目標測試並確認介面尚未存在**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_standalone_shell.py -q
```

Expected: FAIL，缺少 `requestTab()` 與登入提示方法。

- [ ] **Step 3: 在設定 Tab 實作登入卡片內引導**

於 `tabs/tab_settings.py` 加入：

```python
def showLoginPrompt(self, target_label=None):
    self._outer_stack.setCurrentIndex(0)
    if target_label:
        self._lbl_login_ttl.setText(f"請登入以使用「{target_label}」")
    else:
        self._lbl_login_ttl.setText("管理者驗證")
    self.lbl_login_err.setText("")
    self.w_password.setFocus()

def clearLoginPrompt(self):
    self._lbl_login_ttl.setText("管理者驗證")
```

在 `_onRoleChanged("user")` 分支呼叫 `clearLoginPrompt()`；登入失敗仍只更新既有 `lbl_login_err`，不另開訊息框。不要修改 `Layout7.ui` 或新增登入頁元件。

- [ ] **Step 4: 在 DocumentManager 實作統一目標請求與 pending 續接**

初始化 `_pending_tab_key = None`。在 `DocumentManager` 加入：

```python
def requestTab(self, key, role=None):
    index = self.tab_index(key)
    if index is None:
        self._pending_tab_key = None
        return False

    if self._isTabVisible(key, role):
        self._pending_tab_key = None
        self.tab_widget.setCurrentIndex(index)
        self._prev_tab_index = index
        return True

    self._pending_tab_key = key
    settings = self.tabs.get(self._IDX_SETTINGS)
    label = self.profile.menu_labels.get(key, key)
    if settings and hasattr(settings, "showLoginPrompt"):
        settings.showLoginPrompt(label)
    self.tab_widget.setCurrentIndex(self._IDX_SETTINGS)
    self._prev_tab_index = self._IDX_SETTINGS
    return False
```

擴充 `_onRoleChanged()`：

```python
def _onRoleChanged(self, role):
    self._applyTabVisibility(role)
    pending = self._pending_tab_key
    if not pending:
        return
    self._pending_tab_key = None
    if self._isTabVisible(pending, role):
        self.requestTab(pending, role)
```

權限仍不足時 pending 必須清除並停留設定頁。

- [ ] **Step 5: 將啟動主選單選擇交給 requestTab**

保留 `MainMenu` 的 Profile icon 顯示與 `selected_tab_key`。在 `runApplication()` 中以 key 處理選擇：

```python
if menu.ui.exec() != QDialog.Accepted or not menu.selected_tab_key:
    sys.exit(0)

mgr.requestTab(menu.selected_tab_key)
```

移除現有直接以 `selected_tab` 靜默 `setCurrentIndex()` 的 724–726 行，以及只為該靜默切頁補做的 738 行。若啟動效能實測仍要求延後 activation，改為：

```python
selected_index = mgr.tab_widget.currentIndex()
QTimer.singleShot(50, lambda: mgr._onTabChanged(selected_index))
```

但不得在未同步 `_prev_tab_index` 的情況下以 `blockSignals(True)` 切頁。`MainMenu._onSelect()` 不新增權限判斷，因它只負責回傳 key；角色判斷集中於 `DocumentManager.requestTab()`。

- [ ] **Step 6: 測試設定未儲存離頁語意沒有因導向登入而失效**

加入：

```python
def test_restricted_route_tracks_settings_as_previous_tab(
        qtbot, shell_db, monkeypatch):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    settings = manager.tabs[manager.tab_index("settings")]
    calls = []
    monkeypatch.setattr(
        settings, "_promptUnsaved",
        lambda context: calls.append(context),
    )

    manager.requestTab("archive")
    manager.requestTab("browse")

    assert calls == ["leave"]
```

若 `requestTab("browse")` 在實際 signal 順序下已由 `_onTabChanged()` 更新 `_prev_tab_index`，不得額外手動呼叫 `_onTabChanged()` 造成雙提示。

- [ ] **Step 7: 執行主選單與登入流程測試**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_standalone_shell.py -q
```

Expected: PASS，且既有 `test_full_menu_still_shows_all_eleven_actions`、`test_entry_menu_has_exactly_four_visible_actions` 保持通過。

- [ ] **Step 8: 提交登入導向流程**

```powershell
git add -- main.py tabs/tab_settings.py tests/test_standalone_shell.py
git commit -m "feat: route restricted tabs through login"
```

---

### Task 4: 驗證登出、閒置登出與 signal 邊界

**Files:**
- Modify: `main.py:218-231`
- Modify: `main.py:320-349`
- Modify: `tests/test_standalone_shell.py`
- Modify: `tests/test_auth_manager.py:70-76`

**Interfaces:**
- Consumes: `AuthManager.role_changed(str)`
- Consumes: `DocumentManager._onRoleChanged(role: str) -> None`
- Consumes: `DocumentManager.requestTab(key: str) -> bool`

- [ ] **Step 1: 寫角色降低時 fallback 的失敗測試**

加入：

```python
def test_logout_from_admin_only_tab_falls_back_to_settings(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    manager._onRoleChanged("admin")
    manager.requestTab("audit", role="admin")
    assert manager.tab_widget.currentIndex() == manager.tab_index("audit")

    manager._onRoleChanged("user")

    assert manager.tab_widget.currentIndex() == manager.tab_index("settings")
    assert not manager.tab_widget.isTabVisible(manager.tab_index("audit"))
    assert manager._prev_tab_index == manager.tab_index("settings")


def test_logout_keeps_current_business_tab_when_still_visible(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    manager._onRoleChanged("admin")
    manager.requestTab("reward_issue", role="admin")

    manager._onRoleChanged("user")

    assert manager.tab_widget.currentIndex() == manager.tab_index("reward_issue")
    assert manager.tab_widget.isTabVisible(manager.tab_index("reward_issue"))
```

- [ ] **Step 2: 執行測試確認目前 fallback 邊界**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_standalone_shell.py -q
```

Expected: 第一支測試在 Task 2/3 尚未正確處理角色降低時 FAIL；第二支不得被過度 fallback 破壞。

- [ ] **Step 3: 補真實 logout signal 與閒置登出整合測試**

在 `tests/test_standalone_shell.py` 加入：

```python
def _enter_admin_audit(manager):
    auth = AuthManager.instance()
    auth._role = "admin"
    auth.role_changed.emit("admin")
    manager.requestTab("audit", role="admin")
    assert manager.tab_widget.currentIndex() == manager.tab_index("audit")
    return auth


def test_real_logout_signal_falls_back_and_hides_audit(qtbot, shell_db):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    auth = _enter_admin_audit(manager)

    auth.logout()

    assert auth.current_role == "user"
    assert manager.tab_widget.currentIndex() == manager.tab_index("settings")
    assert not manager.tab_widget.isTabVisible(manager.tab_index("audit"))
    assert manager._prev_tab_index == manager.tab_index("settings")


def test_idle_timeout_uses_logout_signal_and_falls_back(
        qtbot, shell_db, monkeypatch):
    manager = DocumentManager(profile=FULL_PROFILE)
    qtbot.addWidget(manager.window)
    auth = _enter_admin_audit(manager)
    notices = []
    monkeypatch.setattr(
        main_module, "msgInfo",
        lambda title, text, parent=None: notices.append((title, text)),
    )

    manager._onIdleTimeout()

    assert auth.current_role == "user"
    assert manager.tab_widget.currentIndex() == manager.tab_index("settings")
    assert not manager.tab_widget.isTabVisible(manager.tab_index("audit"))
    assert manager._prev_tab_index == manager.tab_index("settings")
    assert notices and notices[0][0] == "自動登出"
```

測試直接設定 singleton 的 `_role` 只用於建立已登入前置狀態；被測行為必須呼叫真實
`AuthManager.logout()`／`DocumentManager._onIdleTimeout()` 並由
`role_changed("user")` 驅動主視窗，不得直接呼叫 manager 的登出後 slot 取代整合路徑。
現有 autouse fixture 會在每支測試後拆除 singleton signal 連線。

- [ ] **Step 4: 收斂 _applyTabVisibility 的 fallback**

確認 `_applyTabVisibility(role)` 只在「目前 key 不屬於新角色 visible set」時切設定。切頁順序固定為：

```python
if current_key not in visible and self._IDX_SETTINGS is not None:
    self.tab_widget.setCurrentIndex(self._IDX_SETTINGS)
    self._prev_tab_index = self._IDX_SETTINGS

for key, index in self.tab_index_by_key.items():
    self.tab_widget.setTabVisible(index, key in visible)
```

若目前業務 TAB 對新角色仍可見，不得改變 current index。主動登出與 `_onIdleTimeout()` 均沿用 `AuthManager.logout()` 發出的 `role_changed("user")`，不得另寫第二套 TAB fallback。

- [ ] **Step 5: 驗證 AuthManager 登出 signal**

擴充既有 `TestLogin.test_logout`：

```python
def test_logout(self):
    seen = []
    self.auth.role_changed.connect(seen.append)
    self.auth.login("admin", self.db_path)
    seen.clear()

    self.auth.logout()

    self.assertEqual(self.auth.current_role, "user")
    self.assertFalse(self.auth.is_manager())
    self.assertEqual(seen, ["user"])
```

- [ ] **Step 6: 執行角色與 GUI 回歸**

Run:

```powershell
python -m unittest tests.test_auth_manager
$env:QT_QPA_PLATFORM = 'offscreen'
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_standalone_shell.py -q
```

Expected: PASS。

- [ ] **Step 7: 提交登出邊界**

```powershell
git add -- main.py tests/test_standalone_shell.py tests/test_auth_manager.py
git commit -m "test: cover role tab fallback"
```

---

### Task 5: 保護 HELP 固定 mapping 並更新共用說明

**Files:**
- Modify: `ui_utils/help_content.py:77-682`
- Modify: `ui_utils/help_content.py:736-末尾`
- Modify: `tests/test_dialog_smoke.py:921-附近`
- Modify: `tests/test_reward_integration.py:211-附近`

**Interfaces:**
- Consumes: `attachHelpButton(..., tab_keys=profile.tab_keys)`
- Consumes: `resolveHelpPage(tab_index, tab_keys)` 的既有固定 key→完整版頁碼 mapping
- Produces: 共用角色可見矩陣與受限入口登入導向說明

- [ ] **Step 1: 寫隱藏 TAB 後 HELP mapping 的失敗／回歸測試**

在 `tests/test_dialog_smoke.py` 的既有 HELP mapping 測試旁加入純 mapping 測試：

```python
def test_help_mapping_keeps_full_profile_index_for_each_role(self):
    from lib.app_profile import FULL_PROFILE, visibleTabKeys
    from ui_utils.help_dialog import helpPageIndex

    for role in ("user", "archive", "admin"):
        for key in visibleTabKeys(role, FULL_PROFILE):
            fixed_index = FULL_PROFILE.tab_keys.index(key)
            self.assertEqual(
                helpPageIndex(fixed_index, FULL_PROFILE.tab_keys),
                fixed_index,
            )
```

不得另建以「可見 TAB 的畫面順序」為輸入的 mapping。真實
`QTabWidget.isTabVisible()` 與固定 index 不變已由 Task 2 的
`tests/test_standalone_shell.py` 覆蓋。

- [ ] **Step 2: 寫共用 HELP／QUICKSTART 必含角色說明的測試**

在 `tests/test_reward_integration.py` 加入不依賴完整句子標點的關鍵詞斷言：

```python
def test_help_and_quickstart_explain_role_based_tabs():
    help_text = "\n".join(str(value) for value in HELP_PAGES.values())
    quickstart_text = "\n".join(str(value) for value in QUICKSTART.values())
    for text in (help_text, quickstart_text):
        assert "一般使用者" in text
        assert "歸檔管理員" in text
        assert "操作紀錄" in text
        assert "資料庫設定" in text
```

沿用該檔目前對 `HELP_PAGES`／`QUICKSTART` 的 import 與資料型別展開方式，避免把 HTML list 直接錯當純字串。

- [ ] **Step 3: 執行 HELP 測試確認新增說明尚未存在**

Run:

```powershell
python -m unittest tests.test_dialog_smoke tests.test_reward_integration
```

Expected: mapping 舊測試 PASS；角色說明新測試 FAIL。

- [ ] **Step 4: 更新共用 HELP 與 QUICKSTART 母本**

在 `ui_utils/help_content.py` 的系統導覽／設定相關 HELP 與 `QUICKSTART` 開頭加入同一組事實：

```text
一般使用者：顯示業務登錄、簽收單列印、資料庫瀏覽與資料庫設定；
歸檔管理員：另顯示檔案歸檔；
管理者：再顯示操作紀錄。
資料庫設定永遠保留作為登入入口。從主選單選擇目前隱藏的功能時，
系統會直接前往資料庫設定；登入後身分可使用該功能才會自動開啟。
```

依現有 HELP HTML／QUICKSTART 結構套用既有標籤格式，不新增新的固定數字 key，不重排 `HELP_TITLES`、`HELP_PAGES`、`HELP_TIPS` 或 `QUICKSTART` 的既有 key。

- [ ] **Step 5: 執行 HELP 與速查卡測試**

Run:

```powershell
python -m unittest tests.test_dialog_smoke tests.test_reward_integration
```

Expected: PASS。

- [ ] **Step 6: 提交 HELP 更新**

```powershell
git add -- ui_utils/help_content.py tests/test_dialog_smoke.py tests/test_reward_integration.py
git commit -m "docs: explain role-based tab visibility"
```

---

### Task 6: 同步技術文件與使用者門面

**Files:**
- Modify: `DEVELOPER.md:44`
- Modify: `DEVELOPER.md:68-91`
- Modify: `DEVELOPER.md:324-相關 HELP 章節`
- Modify: `DEVELOPER.md:652-676`
- Review and modify only if §9 requires: `README.md:32-主要功能`
- Review and modify only if §9 requires: `README.md:102-初次設定／登入`
- Review and modify only if §9 requires: `README.md:176-閒置登出`

**Interfaces:**
- Consumes: 核准 spec 的三角色 9／10／11 TAB 矩陣
- Produces: 與程式、HELP、QUICKSTART 一致的長期文件

- [ ] **Step 1: 先寫文件一致性測試**

在 `tests/test_app_profile.py` 加入以精確表格列為主的斷言：

```python
def test_developer_documents_role_tab_visibility():
    text = Path("DEVELOPER.md").read_text(encoding="utf-8")
    assert "一般使用者" in text
    assert "歸檔管理員" in text
    assert "setTabVisible" in text
    assert "操作紀錄" in text
    assert "資料庫設定" in text
```

於檔案頂端加入 `from pathlib import Path`。此測試只防整段規則遺失；矩陣正確性仍由 Task 1 的純邏輯測試負責。

- [ ] **Step 2: 執行測試確認文件尚未描述新機制**

Run:

```powershell
python -m pytest tests/test_app_profile.py -q
```

Expected: FAIL，至少缺少 `setTabVisible` 或新的角色顯隱說明。

- [ ] **Step 3: 更新 DEVELOPER.md**

精確更新：

- §1：說明啟動期 Profile 可 `removeTab()`，執行期角色切換只可 `setTabVisible()`，兩者不可混用。
- §2 跨功能影響表：加入「角色 TAB 顯隱」列，右欄列出主選單、登入、閒置登出、HELP、QUICKSTART、權限矩陣與測試。
- §5 HELP：記錄 HELP 以固定 Profile index 映射內容 ID，不以可見位置編號。
- §10 權限矩陣：把 user／archive 的操作紀錄從「顯示遮罩」更新為「TAB 隱藏；主選單入口導向設定登入」；加入 9／10／11 可見 TAB 清單。
- 清楚記錄資料庫設定對 user 仍顯示，因其兼作登入入口。

- [ ] **Step 4: 依 README §9 定義作一次明確判斷**

檢查 `DEVELOPER.md` §9。若「角色登入後 TAB 會出現／消失」屬於使用者操作必須知道的行為，在 README 的主要功能或登入段落加入一小段；若 §9 定義排除這類細節，不修改 README，並在 commit 訊息前的執行紀錄註明「已檢查，依 §9 不需更新」。

若需更新，內容只描述使用者行為：

```text
系統會依目前登入身分精簡上方分頁；資料庫設定分頁永遠保留作為登入入口。
從主選單選擇目前隱藏的管理功能時，會直接前往登入畫面。
```

不要在 README 寫 `setTabVisible`、index 或函式名稱。

- [ ] **Step 5: 執行文件一致性與個資檢查**

Run:

```powershell
python -m pytest tests/test_app_profile.py -q
python -m unittest tests.test_no_pii
```

Expected: PASS。

- [ ] **Step 6: 提交文件同步**

若 README 依 §9 需要更新：

```powershell
git add -- DEVELOPER.md README.md tests/test_app_profile.py
git commit -m "docs: document role-based tabs"
```

若 README 不需更新：

```powershell
git add -- DEVELOPER.md tests/test_app_profile.py
git commit -m "docs: document role-based tabs"
```

---

### Task 7: 完整驗證與上機驗收清單

**Files:**
- Modify only if failures reveal a scoped defect: files already listed in Tasks 1–6
- No new production interface

**Interfaces:**
- Consumes: Tasks 1–6 的完成結果
- Produces: 可交付且有完整驗證證據的功能

- [ ] **Step 1: 語法驗證**

Run:

```powershell
python -m py_compile main.py lib/app_profile.py tabs/tab_settings.py ui_utils/help_content.py
```

Expected: exit code 0，無輸出。

- [ ] **Step 2: 執行相關 unittest／純邏輯測試**

Run:

```powershell
python -m unittest tests.test_auth_manager tests.test_dialog_smoke tests.test_reward_integration tests.test_no_pii
python -m pytest tests/test_app_profile.py -q
```

Expected: PASS，無 error／failure。

- [ ] **Step 3: 執行 Qt shell 測試**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_standalone_shell.py -q
```

Expected: PASS。

- [ ] **Step 4: 執行完整既有 suite**

Run:

```powershell
python -m unittest discover -s tests
```

Expected: PASS；若環境無 pytest，兩支 pilot 依既有規則 skip，不視為失敗。

- [ ] **Step 5: 執行核准的 GUI pilot**

Run:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_pytest_qt_runtime.py tests/test_reward_gui_pilot.py -q
```

Expected: PASS。

- [ ] **Step 6: 檢查工作樹與差異**

Run:

```powershell
git diff --check
git status --short
git log --oneline -7
```

Expected: `git diff --check` 無輸出；只保留使用者原有未追蹤 `.claude/`，本功能檔案均已逐檔提交；不得加入 `dbfile.db`、根目錄 `fix_*.py` 或 `seed_*.py`。

- [ ] **Step 7: Windows 上機驗收**

在 Windows 125% 顯示縮放與全域 14pt 字體逐項確認：

1. 未登入：9 個 TAB；「檔案歸檔、操作紀錄」完全不見、不占空位，其餘向左遞補。
2. 未登入仍看得到交辦單發文、敘獎發文與資料庫設定。
3. 主選單維持 Profile 的完整 icon 與原排列。
4. 主選單點「檔案歸檔」不跳訊息框，直接到設定登入頁，頁內顯示目標名稱。
5. 以歸檔管理員登入後自動開啟檔案歸檔，TAB 總可見數為 10。
6. 主選單點「操作紀錄」後以歸檔管理員登入，停留設定頁且操作紀錄仍隱藏。
7. 主選單點「操作紀錄」後以管理者登入，自動開啟操作紀錄，TAB 總可見數為 11。
8. 管理者／歸檔管理員登出時，若目前為即將隱藏的頁面，回到設定登入頁。
9. 登出時若停在一般業務頁，不強制切換頁面。
10. 每個可見 TAB 的 `?` HELP 都顯示正確功能內容。
11. 設定頁有未儲存排序時，經受限入口導向後第一次離頁仍執行既有提示。
