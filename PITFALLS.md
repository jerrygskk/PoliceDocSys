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

#### LAY：版面／模式切換抖動（多見於 tab_report._switchFormType）
- **LAY-1**: **隱藏列幽靈間距、兩模式下方表格高度不一** → `verticalSpacing=0`、列距改 `setRowMinimumHeight`；兩模式 form 總高設成相同固定值（如刑案 4×45、一般 3×60＝180）。
- **LAY-2**: **show/hide 時整排左右跳、同欄兩模式寬度不同** → `setColumnMinimumWidth` 鎖結構性欄寬；col0 寬取最寬標籤 `sizeHint().width()`（勿寫死）。QGridLayout 欄寬只按當前可見 widget 算。
- **LAY-3**: **切 tab 共用列上的按鈕上下跳** → 共用列兩模式設相同 row min height。
- **LAY-4**: **`setupPreviewTable` 的 200ms autoResize 覆蓋手設欄寬** → 要自控欄寬就別用它；彈性欄 `QHeaderView.Stretch`、固定欄 `Fixed`+`setColumnWidth`。
- **LAY-5**: **浮貼按鈕（絕對定位）在非當前頁重複/錯位** → 改放 GroupBox 內 HBox 標題列走正規 layout（非可見頁 layout 寬=0 所致）。
- **LAY-6**: **同類輸入元件（`QDateEdit`／`QComboBox`）跨頁高度不一致** → 只設 `minimumSize` 高、沒設 `maximumSize` 者會渲染成 `sizeHint` 自然高（14pt 字型＋theme.py padding 略高於 36），比鎖了 max 的同類高一點。要跨頁同高就 `minimumSize` 與 `maximumSize` 給同一個高（如 `220×36`，`.ui` 裡兩個 property 都要寫）。

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

#### ARC：歸檔檔名解析（lib/archive_text.py）
- **ARC-1**: **動斷詞／日期／主旨解析前** → 三條解析雷（斷詞漏字、PK 1xx 日期、無 `-` 主旨）詳述在 **DEVELOPER §10「歸檔檔名解析的雷」**，動 `archive_text.py` 前先翻。

#### PKG：打包／重啟
- **PKG-1**: **重置後重啟、打包版跳 `Failed to load Python DLL`／`unicodedata` 缺** → 啟動新程序前設 `PYINSTALLER_RESET_ENVIRONMENT=1`（新程序沿用舊 `_MEI` 所致；見 `tab_settings._restartApp()`，別用 cmd ping 延遲歪招）。
- **PKG-2**: **C 槽空間不足時 onefile 解壓階段失敗（已知無法攔截）** → onefile 開機會先把整包解壓到 C 槽 `%TEMP%`（實測峰值約 216~250MB，視 exe 大小而定），這發生在 `main.py` 任何程式碼執行**之前**（PyInstaller bootloader 階段），我們自己的 `error.log` 機制與 2026-07 加的開機磁碟空間檢查（`lib/db_utils.diskSpaceThreshold` + `main.py` 開頭 `confirmBox`）都攔不到、也留不下紀錄。已與維護者議定不處理（不想為此動 `--runtime-tmpdir` 改打包設定），剩餘風險留給維護者自行注意 C 槽可用空間。執行期間（`main.py` 已開始跑之後）的磁碟空間不足，已用上述檢查＋`LoadWorker` try/except＋`friendlyErrorMessage` 的 `isDiskFullError` 專屬訊息攔住。
