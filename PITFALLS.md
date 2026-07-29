# 踩雷速查表（Pitfalls）

依主題分組；每條為「**症狀** → 解法（必要時括註原因）」。寫過的雷再踩會被點名。本檔自 DEVELOPER.md §2 拆出；任務對照索引見 CLAUDE.md。

#### UI：`.ui` 載入
- **UI-1**: **`Unable to open/read ui device`** → margin 改用 `leftMargin`/`topMargin`/`rightMargin`/`bottomMargin` 四獨立 property，勿用 `contentsMargins`+`<rect>`。
- **UI-2**: **`centralWidget()` 回 None** → central widget 物件名必須全小寫 `centralwidget`。

#### QSS：Qt 樣式／顏色
- **QSS-1**: **狀態色（紅/橘/綠）、停用灰字失效** → `QTableWidget::item` 只設 padding/border，文字色一律交 `setForeground()`（`::item{color}` 優先級會蓋過它；`:selected` 的 color 可留）。⚠ 動表格樣式前先查這條。
- **QSS-2**: **顏色被 stylesheet 蓋掉** → 用 `QColor("#hex")`，勿用 `Qt.red` 等列舉。
- **QSS-3**: **新 Dialog/Widget 文字看不見（深色底）** → 每個新 `QDialog`/`QWidget` 明設背景+文字色（繼承全域深色所致，範例見 DEVELOPER §5）。
- **QSS-4**: **`setEnabled(False)` 按鈕沒變灰** → 該按鈕的 stylesheet 要含 `QPushButton:disabled { ... }`。
- **QSS-5**: **設灰字連月曆／下拉清單也變灰** → 用型別選擇器 `QDateEdit { color: ... }` / `QComboBox { color: ... }`，避免裸 `color:` 繼承到子元件。
- **QSS-6**: **表格滑過（mouseover）整格反白** → Windows 原生 style 對 item 的**預設行為**，刪 hover 規則無效；要明寫 `QTableWidget::item:hover { background-color: transparent; }` 壓掉（tab_archive／backup_restore_panel 皆如此處理）。
- **QSS-7**: **tooltip 整塊黑（未解，勿再嘗試已證無效的招）** → Windows 系統深色模式下（PySide6 6.11／windows11 原生 style），QToolTip 底板整塊黑。**四招皆實測無效**：①theme.py QSS `QToolTip { … }`（規則保留但壓不掉）②app palette ToolTipBase/Text ③`QToolTip.setPalette` ④`app.styleHints().setColorScheme(Qt.ColorScheme.Light)`。2026-07 議定**迴避**：新功能勿依賴 tooltip 傳達資訊（已存在的 HELP_TIPS tooltip 同樣受影響，僅深色模式使用者看不到）。要再挑戰先查 Qt 上游 windows11 style tooltip 相關 bug 是否已修。

#### QTW：Qt 元件行為
- **QTW-1**: **`clicked` callback 首參變成 `False`** → lambda 吃掉 Qt 多塞的 `checked`：`lambda _=False, k=key: ...`（否則 `dict[False]` KeyError）。
- **QTW-2**: **`QTableWidget`/`QAbstractScrollArea` 滾輪攔不到** → 滾輪事件在 `viewport()`：於 `table.viewport()` `installEventFilter` 攔 `QEvent.Wheel`，filter 存成屬性防 GC（覆寫 `wheelEvent` 無效）。
- **QTW-3**: **confirmBox 確認/取消鈕被左右調換** → 兩鈕都用 `ActionRole`（`AcceptRole`/`RejectRole` 會依 OS 慣例調換），手動 `setDefaultButton`+`setEscapeButton`。
- **QTW-4**: **`QDateEdit` 月曆打開停在 1752／空白哨兵相關亂象** → minimumDate 哨兵所致。**必填**日期欄（預設今天、不需空白）用 `setupDateEditToToday` 捲到今月即可。**可留空又要手打的欄位千萬別用 QDateEdit**——拿分段遮罩 spinbox 當可空白欄會反覆出包（空白時鍵盤打不動、亂點冒 `1752/1753` 殘值、整格清空後手打半成品被 fixup 還原）。改用 `NullableDateEdit`（QLineEdit 子類，治本，見 DEVELOPER §5「可空白日期框」）。
- **QTW-5**: **表格內用 `QStyledItemDelegate.createEditor()` 塞 `QLineEdit` 編輯框，固定列高裡數字下緣被裁切** → 全域 `theme.py` 對所有 `QLineEdit` 套 `padding: 6px 10px`，疊上編輯時 focus 的 2px 邊框，固定列高（如 36px）扣一扣空間就不夠。editor 要顯式歸零 `padding`/`margin`（border 不覆寫，沿用 theme.py 原值）。⚠️ 容器內離線量測（無真實 GUI、無 Windows 125% 縮放）這類問題會失準，算出來「應該塞得下」不代表實機真的塞得下，**這類視覺裁切問題最終仍要上機才能定案**，別只憑 `QFontMetrics`/`sizeHint` 的數字就回報「修好了」。
- **QTW-6**: **`QRadioButton` 文字在 125% 縮放下被切字（label 尾字吃掉）** → 圓點指示器＋14pt label 的 `sizeHint` 在 125% 下算不準、寬度不足即截斷。逐顆 `setMinimumWidth`（如 65，比照 `Layout3.ui`）鎖最小寬。⚠️ 容器離線量不出（無 125% 縮放），切字與否**上機才能定案**，別憑 `sizeHint` 數字回報修好（見 `convert_dialog._radio_row`／陳報頁 `Layout3.ui`）。
- **QTW-7**: **可打字 combo 的提示字點入不消失、打字黏進內容（如「輸入或下拉選擇私」）** → `setItemText(0, hint)` 是第 0 項的**真實文字**、非 placeholder，Qt 不會自動清。用 `ui_utils.attachComboHint(combo, hint)`（focus-in 清空／focus-out 未選未打字則還原）。⚠️ event filter 要 **combo 本體＋lineEdit 兩邊都裝**——editable combo 的 `focusProxy` 不一定是 lineEdit，FocusIn 可能送 combo 本體，只裝 lineEdit 會漏接（案類欄實際踩過）。
- **QTW-8**: **completer 打字完全不彈候選（換自建 model 後）** → `QCompleter` 搭 `QStandardItemModel` 時 model **必須掛 parent**（如 `QStandardItemModel(combo)`）；區域變數無 parent 會被 PySide 端 GC 回收，completer 靜默啞掉。離線單測測不出（測試裡物件還活著），症狀只在真機出現。
- **QTW-9**: **completer `activated[QModelIndex]` 讀 UserRole 拿到「別列」的資料（靜默選錯、不報錯）** → 自訂 handler 的 connect 必須在 `combo.setCompleter()` **之前**：setCompleter 內部也連了 activated，內部 slot 先跑會改 lineEdit → completionModel 重新過濾 → 傳進 handler 的 index 已過期、`data()` 讀到別列（實測選「私行拘禁 → 302妨害自由」回填成 319 案類）。同一 handler 若要 `findData` 回填，記得 combo 項目可能已被打字過濾濾掉目標，先重建完整清單再找（見 `widgets.setupFilterCombo` 內註解）。
- **QTW-10**: **彈窗「可空白日期」用 `QDateEdit`＋`specialValueText`／`minimumDate` 哨兵硬撐 → 空白打不動／亂點冒 1752 殘值／fixup 還原，停用欄位又衍生流程限制** → 一律改用 `ui_utils.widgets.NullableDateEdit`（見 DEVELOPER「可空白日期框」；範例 reward_dialog 發文日期、crim／gen 編輯彈窗陳報日期）。
- **QTW-11**: **editable combo「下拉選取＝附加而非取代」的欄位，混用 completer 選字後再點下拉，先前選的人名被洗掉** → Qt 選取下拉項時會先把整欄換成選中文字，handler 需先還原快照再附加；快照若靠 `textEdited` 維護會漏接 completer／程式 `setText`（`textEdited` 只在使用者打字時發出）。正解：覆寫 `showPopup()` 於**張開下拉瞬間**抓快照（那一刻欄位值必然最新），見 `reward_dialog._RecipientCombo`。
- **QTW-12**: **可打字 combo 的提示灰字，使用者「自己打的字也是灰的」（改過兩三次還是回來）** → 顏色掛在 `currentIndexChanged` 上，但 `setupFilterCombo` 的 `_onTextChanged` 重建清單時做了 `combo.blockSignals(True)`、且重建後 index 恆為 0 → **打字期間該訊號結構上不可能觸發**，handler 根本沒被呼叫。所以改 handler 內的判斷式、換顏色值一律無效，只會再犯一次。正解：顏色由 `attachComboHint` 內部負責，判斷依據是**「目前是否正在顯示提示文字」**（`currentData() is None and currentText() == hint`），驅動來源為 `lineEdit().textEdited` ＋ FocusIn／FocusOut，**不得用 index 判斷**；focus 事件內要 `QTimer.singleShot(0, ...)` 延後重繪，順序才會落在既有 `clearEditText`／`setEditText` 之後。提示灰一律用 `theme` 的 token（`#aeaeb2`，與 `QLineEdit::placeholder` 同色），勿在呼叫端自行 `setStyleSheet` 寫死色碼（`tab_report` 曾寫死 `#a0a0a0`，與全域 placeholder 不同色）。⚠️ 別為了「統一」就把提示改成 Qt 原生 placeholder：原生 placeholder **游標進入不會消失、要打字才消失**，與本專案「點一下提示字就消失」的既定行為不符（維護者明確要求保留）；實測「原生 placeholder ＋ focus 時清 placeholder」的混搭，焦點事件在 combo 本體與 lineEdit 間的送達順序不穩，會出現離開欄位後提示沒還原。相關：QTW-7（同一函式的 focus 清空行為與 event filter 兩邊都要裝）。
- **QTW-13**: **日期框滑鼠滾輪意外改日期** → 所有 `QDateEdit` 一律由 `ui_utils.installDateEditWheelGuard(app)` 在 `QApplication` 建立後統一攔截，不得逐欄安裝 filter；guard 會涵蓋 `.ui` 載入、程式動態建立與內部 spin 子元件。`QCalendarWidget` 月曆 popup 是例外，保留月份捲動；`NullableDateEdit` 本來不是 `QDateEdit`，不受影響。

#### LAY：版面／模式切換抖動（多見於 tab_report._switchFormType）
- **LAY-1**: **隱藏列幽靈間距、兩模式下方表格高度不一** → `verticalSpacing=0`、列距改 `setRowMinimumHeight`；兩模式 form 總高設成相同固定值（如刑案 4×45、一般 3×60＝180）。
- **LAY-2**: **show/hide 時整排左右跳、同欄兩模式寬度不同** → `setColumnMinimumWidth` 鎖結構性欄寬；col0 寬取最寬標籤 `sizeHint().width()`（勿寫死）。QGridLayout 欄寬只按當前可見 widget 算。
- **LAY-3**: **切 tab 共用列上的按鈕上下跳** → 共用列兩模式設相同 row min height。
- **LAY-4**: **`setupPreviewTable` 的 200ms autoResize 覆蓋手設欄寬** → 要自控欄寬就別用它；彈性欄 `QHeaderView.Stretch`、固定欄 `Fixed`+`setColumnWidth`。
- **LAY-5**: **浮貼按鈕（絕對定位）在非當前頁重複/錯位** → 改放 GroupBox 內 HBox 標題列走正規 layout（非可見頁 layout 寬=0 所致）。
- **LAY-6**: **同類輸入元件（`QDateEdit`／`QComboBox`）跨頁高度不一致** → 只設 `minimumSize` 高、沒設 `maximumSize` 者會渲染成 `sizeHint` 自然高（14pt 字型＋theme.py padding 略高於 36），比鎖了 max 的同類高一點。要跨頁同高就 `minimumSize` 與 `maximumSize` 給同一個高（如 `220×36`，`.ui` 裡兩個 property 都要寫）。⚠️ **只鎖高、別把寬度的 `maximumSize` 也設成與 `minimumSize` 同值**——那會讓輸入欄卡死不隨視窗拉伸（罰單登錄三個輸入欄踩過，`min=max=220`）。要能拉伸就把寬的 max 留 `16777215`（比照 `Layout9.ui` 敘獎登錄）。
- **LAY-7**: **預覽表加伸縮欄後整張表被拉成整個視窗寬、右側固定面板被擠爛（踩過）** → 伸縮欄**必須是最右側的空標題欄**，不可把「罰單編號」這類資料欄設成伸縮欄。伸縮的語意是「吸收表格內部的剩餘寬度」，不是「讓表格去跟版面要更多寬度」：右側面板（如候選人員 `min=max=240`）與外層 QHBoxLayout 的 `stretch="1,0"` 都不能動。固定欄寬加總要留餘裕給伸縮欄，否則 `autoResizeTable` 會走「空間不足」分支（伸縮欄停在最小寬、表格右緣留白），或反過來冒水平捲軸。⚠️ 本專案的「stretch」**不是** `QHeaderView.Stretch`，是 `ui_utils/table.py:autoResizeTable` 用 `setColumnWidth` 模擬的（`stretchLastSection()` 為 False，兩者同時開會打架）；另注意 `fixed_overrides` 以**欄位名稱字串**當 key，表內若有兩個空標題欄（第 0 欄 ✕ 鈕、末欄伸縮）不會撞名，因為 `""` 不是 key、且第 0 欄在讀標題前就被 `col == 0 and columnWidth(0) <= 32` 特判攔下。**改欄位配置時務必連同釘住配置的測試一起看**（`tests/test_ticket_tab.py` 的 `test_preview_stretch_*`）——這區曾經改壞而全套件無人擋。
- **LAY-8**: **離線測欄寬／版面寬度得到假結果** → `autoResizeTable` 讀的是 `viewport().width()`，而**沒有 `show()` 過的 widget 量不到真實寬度**（實測少約 500px，直接誤走「空間不足」分支，量到的欄寬全是最小值）。這類測試必須 `widget.show()` ＋ `QApplication.processEvents()` 之後再 resize、再量。⚠️ 即使量到數字，**125% 縮放下的實際視覺仍要上機定案**（同 QTW-5／QTW-6）。

#### TAB：Tab 切換攔截
- **TAB-1**: **從設定 Tab 切走時攔不住「未存」** → `currentChanged` 是切換後才觸發：大 Tab 只能切過去後補跳提示；子頁切換（按鈕觸發）才攔得住、可「取消＝回原狀」。

#### SVG：SVG／icon
- **SVG-1**: **Material icon 白邊太多／在按鈕裡偏一邊** → 裁 viewBox 到圖案實際 bounding box 並置中、移除非對稱裝飾，width/height 統一 512px（`0 -960 960 960` 圖案只佔中央 70%）。
- **SVG-2**: **HELP 新增按鈕顯示破圖佔位符** → `tools/gen_buttons.py` 只產 SVG、**不會自動登記 qrc**；新增 key 後須手動在 `res/resources.qrc` 補 `<file alias="btn/<key>.svg">buttons/<key>.svg</file>` 再 `pyside6-rcc res/resources.qrc -o res/resources_rc.py` 重編。
- **SVG-3**: **HELP 要放截圖／圖片** → 用 `help_content.py` 的 `img` block（`("img", ":/help/xxx.png", 寬, 高)`，寬高＝邏輯像素＝125% 截圖尺寸 ÷1.25）；圖放 `res/img/`、qrc 補 `help/` 別名並重編（**不可**引用 `docs/img/`——已 gitignore、不進 exe）。純文字校稿檔自動略過 img。
- **SVG-4**: **速查卡 PDF 產生失敗「字型缺字形（會變豆腐）」** → 微軟正黑體缺 `⇄`(U+21C4)、`⚠`(U+26A0) 等符號，`gen_quickstart.py` 的 `_check_glyphs` 直接 sys.exit 擋下；QUICKSTART 母本文字勿用特殊符號（HELP_PAGES 是 Qt 渲染、可以用）。

#### SQL：資料／SQL
- **SQL-1**: **`ORDER BY sort_order` 新項跑到最前** → 新增時給 `sort_order = MIN(sort_order)-1`（空表 fallback 1）；NULL 會被 SQLite 排最前。
- **SQL-2**: **軟刪除空殼出現在待歸檔清單** → `_queryUnarchived`/`_tableSignature` 排除底層案由欄為 NULL 者；**任何「待處理」查詢都要排除軟刪除空殼**。
- **SQL-3**: **可空下拉的 NULL 舊資料被靜默改成清單第一項** → 建檔可為 NULL 的下拉，建時與編輯時都 `addItem("", None)` 空白哨兵（見 `edit_dialog.py`）；否則 `_set_combo_value(None)` 停在第一項、存回真 id 連必填都騙過。
- **SQL-4**: **編號欄超連結＋純文字重疊** → `setDocIdLinkCell` 切換前互清：連結分支先 `takeItem`、純文字分支先 `removeCellWidget`（item 與 cellWidget 兩套獨立儲存）。
- **SQL-5**: **瀏覽頁搜尋整個沒反應／取到錯列** → ① `_allRows[key]`／`_docorder[key]` 必須與表格列嚴格 1:1（`_diffUpdate` 每次 pop/append 兩者同步維護）；② `_applyRowVisibility`／歸檔 `_rematch` 的 `setUpdatesEnabled(False…True)` **必用 try/finally**（中途丟例外會把表格卡在不更新＝所有 `setRowHidden` 失效，持續到下次整表重建）。
- **SQL-6**: **參照表 rename 後瀏覽／歸檔頁不更新** → 指紋只看公文表 `last_modified`，碰不到參照改名；rename 必走 `_ref_changed` 旗標路徑（`_refreshRefCells`／重載小清單），不能靠指紋偵測。
- **SQL-7**: **同一秒內的兩次異動可能被指紋漏掉（已知限制，勿當新 bug 修）** → 瀏覽／歸檔頁的 `(COUNT, MAX(last_modified))` 指紋只有**秒精度**（trigger 用 `datetime('now','localtime')`），且 `COUNT` 對「筆數不變的 UPDATE」無感。故當「指紋快照」剛好落在同一秒的兩次異動之間（例：登錄一筆罰單／敘獎後，於**同一秒內**切到瀏覽頁取快照、再回去結算發文），切回瀏覽頁不會刷新，要按「重載」鈕或等下次異動。2026-07 實測 ticket 與 reward 行為完全一致（`insert 後=(1,'…10:10')`／`settle 後=(1,'…10:10')`），是**全專案共通的既有設計取捨**，非個別功能缺陷：指紋只在 `on_activated`／`buildInitial` 取，一條龍結算不經瀏覽頁，人工幾乎命中不了，逃生口是手動「重載」。要治本（`last_modified` 帶毫秒或加 rowversion）＝動五張主表 trigger 與所有指紋比較點，**須另立經核可的全域計畫**，不要在功能分支裡順手改。相關：SQL-6（參照改名同樣碰不到指紋，走 `_ref_changed` 旗標）。

#### ARC：歸檔檔名解析（lib/archive_text.py）
- **ARC-1**: **動斷詞／日期／主旨解析前** → 三條解析雷（斷詞漏字、PK 1xx 日期、無 `-` 主旨）詳述在 **DEVELOPER §10「歸檔檔名解析的雷」**，動 `archive_text.py` 前先翻。

#### PKG：打包／重啟
- **PKG-1**: **重置後重啟、打包版跳 `Failed to load Python DLL`／`unicodedata` 缺** → 啟動新程序前設 `PYINSTALLER_RESET_ENVIRONMENT=1`（新程序沿用舊 `_MEI` 所致；見 `tab_settings._restartApp()`，別用 cmd ping 延遲歪招）。
- **PKG-2**: **C 槽空間不足時 onefile 解壓階段失敗（已知無法攔截）** → onefile 開機會先把整包解壓到 C 槽 `%TEMP%`（實測峰值約 216~250MB，視 exe 大小而定），這發生在 `main.py` 任何程式碼執行**之前**（PyInstaller bootloader 階段），我們自己的 `error.log` 機制與 2026-07 加的開機磁碟空間檢查（`lib/db_utils.diskSpaceThreshold` + `main.py` 開頭 `confirmBox`）都攔不到、也留不下紀錄。已與維護者議定不處理（不想為此動 `--runtime-tmpdir` 改打包設定），剩餘風險留給維護者自行注意 C 槽可用空間。執行期間（`main.py` 已開始跑之後）的磁碟空間不足，已用上述檢查＋`LoadWorker` try/except＋`friendlyErrorMessage` 的 `isDiskFullError` 專屬訊息攔住。
- **PKG-3**: **打包版點到某分頁才炸、啟動時完全正常、原始碼跑得動測試也抓不到** → 分頁類別已改動態載入（`tabs/__init__.py` PEP 562＋`main.py` `_resolve_tab_class` 建立當下才 `importlib`），PyInstaller 靜態分析掃不到 `tabs.tab_*` 模組。新增／調整分頁時，兩份 spec（大程式、獨立版）的 `hiddenimports` 都要補對應 `tabs.tab_xxx`；獨立版只補屬於 `ENTRY_PROFILE.tab_keys` 的分頁（見 DEVELOPER §5、§7）。
- **PKG-4**: **打包版在載入畫面階段 `ImportError`、進不了主選單** → 載入畫面預熱模組（`LoadingScreen`/`LoadWorker` 的 `preheat_modules`）由 `AppProfile.preheat_keys` 決定，若寫死或誤填不屬於該 profile 打包範圍的分頁，該分頁模組不在這支 exe 裡、預熱階段就地炸掉。`preheat_keys` 必須是自己 `profile.tab_keys` 的子集（本案獨立版曾誤填完整版三頁）。
- **PKG-5**: **打包瘦身砍掉某個 binary／模組後，打包版開機或點到某功能就炸，但 build 成功、原始碼跑得動、單元測試也全過** → 判斷「這東西能不能砍」不能靠「原始碼有沒有 import 這個名字」，真正決定的是**間接相依**，而且分兩層、兩層都看不出來：①**DLL 連結期**——`QtUiTools.pyd`（`loadUi` 的 `QUiLoader`）→ `Qt6UiTools.dll` → `Qt6OpenGLWidgets.dll` → `Qt6OpenGL.dll` 是硬相依，跟程式有沒有用到 OpenGL 完全無關，砍掉開機就 `ImportError: DLL load failed while importing QtUiTools`；②**第三方套件的 module 層 import**——`matplotlib/colors.py` 開頭就 `from PIL import Image`，所以 `--exclude-module PIL` 會讓列印頁一載入就 `ModuleNotFoundError: No module named 'PIL'`。**動排除清單後一律跑 `python tools/check_excludes.py`（Python 層，不需 build）與 `python tools/check_bundle_deps.py`（DLL 層，build 後）**，別拿打包版當測試場。反例對照：`opengl32sw.dll` 不在任何連結期相依鏈上（只有執行期軟體 OpenGL 後備才動態載入），砍掉是安全的。
- **PKG-6**: **打包版莫名多出 `libcrypto-3-x64.dll`／`libssl-3-x64.dll`（未壓縮約 6.5MB）** → 打包機器 PATH 上有 Git for Windows 時，PyInstaller 會從 `C:\Program Files\Git\mingw64\bin` 撿到那份 OpenSSL 混進來（Python 自己的 `libcrypto-3.dll` 是另一份、才是 `ssl` 模組要用的）。已由 `tools/pyi_prune.py` 依來源路徑濾掉，**不要改成「build 前記得清 PATH」**——那種靠人記得的做法換台機器就失效。

#### TST：測試技巧（本案各踩一次）
- **TST-1**: **`patch.object(Cls, "_method")` 攔不到已連上 signal 的 bound method** → Qt signal 的 `connect()` 記的是連線當下那個 bound method 物件，事後 patch 類別上的方法不會反映到已連線的那個。改攔它內部會開啟的 Dialog／子物件類別，而不是攔外層被 connect 掉的方法。
- **TST-2**: **`patch("mod.Dialog")` 換不掉已經存進 dict 的類別參考**（如 `TABLE_META[key]["dialog"] = SomeDialog`，模組載入時就把類別存進去了）→ 一般 `patch` 換的是模組屬性，dict 裡存的是舊參考不會跟著變；改用 `patch.dict` 直接換 dict 裡那個 key 的值。
- **TST-3**: **`@dataclass(frozen=True)` 擋不住巢狀可變內容**（`profile.menu_labels["k"] = "v"` 能直接改成功，污染全域共用的 `FULL_PROFILE`/`ENTRY_PROFILE`）→ `frozen=True` 只擋「重新指定欄位」，擋不住欄位內容本身是可變物件（dict／list）時的就地修改；欄位型別改用 `types.MappingProxyType`（`lib/app_profile.py` 的 `menu_labels`）從根本擋寫入。
- **TST-4**: **離線測試誤觸大程式 modal 流程會永遠卡住**（本案 `ResetDialog` 卡住約 20 分鐘才發現）→ Qt modal `exec()` 在無人互動的離線環境會無限等待，測試看起來像掛住而非報錯。用 `faulthandler.dump_traceback_later(45, exit=True)` 設一個上限，逾時自動印出當下呼叫堆疊並結束程序，用來定位卡在哪一行；別乾等超時。
- **TST-5**: **`tests/test_standalone_shell.py` 整檔連跑約 20% 機率 native 崩潰或卡死（不是程式 bug，勿當回歸追）** → 2026-07 實測 10 輪：8 輪 29 passed、1 輪 access violation（`0xC0000005`）、1 輪卡死。**崩點每次不同**（罰單頁 `setupFilterCombo`、`test_ui_load` 的 `loadUi`、shell 測試自己），且都落在本來就穩定的既有程式碼上；換 Python runtime 一樣會發生，`python -m unittest discover -s tests`（790）則從未重現。成因判讀：該檔會**在同一個 process 內反覆建立多個 `DocumentManager`**，但測試只把 `manager.window` 交給 `qtbot`，manager 本身沒有 owner、結束即落入 GC；它底下卻有部分東西掛在比它長壽的宿主上（`AuthManager` 單例的 signal、`QApplication` 層的滾輪 guard／hover filter、各 combo 的 completer model 與 viewport event filter），回收時機不確定，於是崩在「下一次大量配置 Qt 物件」的隨機位置。⚠️ **正式程式不受影響**：一輩子只建一個 `DocumentManager` 並活到程式結束，這個生命週期情境不存在。檔內 autouse fixture 拆 `role_changed` 時噴的 `Failed to disconnect (None)` warning 是「清理範圍不完整」的徵兆、不是崩潰原因。**遇到就重跑**；要壓低機率可把該檔單獨開一個 pytest process 跑（`python -m pytest tests/test_standalone_shell.py -q` 再跑其餘），這是純執行方式的迴避、不動任何程式。真要治本＝改測試架構讓每支測試確實拆掉 manager 的所有長壽掛載，**須另立經核可的計畫**，不要為了單一測試在產品程式上動刀。
