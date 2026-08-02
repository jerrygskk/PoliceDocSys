# 簽收單列印（tab_print.py／print_canvas.py）

自 DEVELOPER.md §5 拆出。**動列印頁、繪圖層或簽收表版面前先讀完本檔**；
其餘技術主題仍在 [DEVELOPER.md](DEVELOPER.md)，踩雷速查在 [PITFALLS.md](PITFALLS.md)。

涵蓋範圍：繪圖引擎、三個出口、五張簽收表的版面決策、罰單專用 renderer、
以及三層驗收網與基準重建流程。**簽收表標題自訂**（六個 `print_title_*` key）
牽涉設定頁面板，留在 DEVELOPER §5，不在本檔。

---

## 1. 繪圖引擎：Qt 原生（v1.2.9 起，已脫離 matplotlib）

三個出口共用 `lib/print_canvas.py` 的 `Canvas` 介面（`text`／`rect`／`line`，normalized
座標、y 向上）：預覽出 `QImage`、儲存 PDF 走 `QPdfWriter`、列印走 `QPrinter`
**向量直印**（不再點陣化）。產品端一律 `QtCanvas`（QPainter）；matplotlib 版
`MatplotlibCanvas` 降級搬到 `tools/mpl_canvas.py`，只當比對基準、不進打包。
完整版 exe 因此 55.5 → 30.1 MB。

⚠️ **維護這塊必須知道的三件事**（每一條都是踩過才寫的）：

1. **版面決策與繪製裝置解耦**：換行／字級只用固定 1200dpi 基準算一次，三個出口
   照同一組結果畫，**不得各自依自己的 dpi 重算**——Qt 會把字寬取整到整數 device
   px，96dpi 下誤差大到讓螢幕預覽與紙本換行不同。
2. **粗體必須明確 `setBold()`**，不可靠 family 名區分：本機 `msjh.ttc` 與
   `msjhbd.ttc` 回傳的 family 名**完全相同**，靠名字切字重會靜默失效（整頁標題
   與欄名曾整批變成一般字重）。
3. **垂直置中沿用 matplotlib 的 `"lp"` 參考字串規則**，不是墨跡框置中、也不是 Qt
   的 `AlignVCenter`——純 CJK 差 1.7pt。

第四件事是驗收網，見本檔 §4。

---

## 2. 三個出口與版面規則

- ⚠️ **簽收表產生走前景＋modal「產生中」popup**（`runWithBusy`），非背景執行緒：
  `generate_pages` 一律主執行緒同步畫（單機 1～2 秒可接受）。QPainter／QPdfWriter
  同樣不應在背景 `QThread` 與主執行緒搶用
- 用 **`QPrintPreviewDialog`** 跳原生預覽＋列印選項；不碰 PDF 檔案關聯（避 WinError 1155）
- 跨版本相容：`setPageSize` 用 `QPageSize` 物件、頁面範圍用 `painter.viewport()`（避 6.x enum 命名空間差異）
- **預設彩色＋長邊雙面**：開預覽前對 `QPrinter` 設 `setColorMode(Color)`＋`setDuplex(DuplexLongSide)`，使用者仍可改（實際支援取決於印表機）
- **欄內換行用真實字型度量**（`_text_width_pt`，dpi=72 `RendererAgg`）：`_wrap_clamp` 不再用「中文當滿格＋0.86 係數」估算（偏窄，會害欄寬還夠的主旨／案類提早折行）。可用寬＝欄寬扣約 1.2×PAD。⚠️ 編號欄 `_fit_font` 仍用舊估算（單行縮字、影響小）
- **刑案類型欄固定 10pt**（`_draw_page` 中 `is_crim and cidx==2`）：案類名長短不一，固定避免參差又壓迫。一般「業務單位」與交辦不受影響、維持 12→10 自動縮

---

## 3. 罰單簽收表版面（`drawTicketPage`，與其他四張不同 renderer）

每頁三組並排、共六欄（開立人員｜罰單編號 ×3），每組固定 20 列，末頁下方一次性
「本頁／本日總計＋簽收人」區。開立人員依 `TicketCell.issuer_rowspan` 合併儲存格。

- **v1.2.9 起標題包在粗外框內**：粗外框從標題帶頂端包到簽收格底端，本表上邊界因此
  與其他四張齊平（先前標題浮在框外，上邊界低一個 `TITLE_H`≈14.8mm）。列印日期與
  發文日期仍在框外
- **兩層網底**：標題帶 `TICKET_TITLE_BG`（重色白字）→ 欄名列 `TICKET_HEADER_BG`
  （＝總計區同色的淡粉底、深字）→ 明細純白。⚠️ **欄名列不用白字**：淺底白字在
  雷射列印會糊，筆畫多的中文尤其明顯
- 明細整塊鋪白底再畫線，不逐列 patch（避免斑馬紋與相鄰邊界疊畫）
- 配色與框線位置由 `tests/test_ticket_print.py` 釘住，改色或改框請一併更新該檔
- 排序一律走 `lib/ticket_utils.py` 的 `ticketSortKey()`（人員順序→姓名→編號自然序）；
  查詢端排過之後，`paginateTicketRows(rows, presorted=True)` 不再重排一次

---

## 4. 驗收網三層，缺一不可

| 工具 | 驗什麼 |
|------|--------|
| `tools/print_baseline.py --check` | 目前 **101 個比對項目**（100 張 PNG＋1 個查無資料哨兵），逐位元組鎖住基準版面沒位移 |
| `tools/render_diff.py` | Qt vs matplotlib 感知級比對，附 `--selftest` 自我驗證這張網還活著 |
| `tools/check_no_matplotlib.py` | 靜態 AST 掃描＋執行期 import 攔截雙軌，證明產品路徑無 matplotlib |

⚠️ `tools/engine_diff.py` 只驗「打算畫什麼」，對繪製正確性零保證——§1 的第 2、3 條它照樣全綠。

### 基準的組成與重建

可版控雜湊放 `tests/print_baseline_manifest.json`，頂層 `environment` 記錄一般／粗體字型檔
與版本、matplotlib／Qt／PySide6 版本及 Windows 顯示縮放；`--check` 失敗會把記錄值與目前值
並排列出，先辨別環境漂移或程式回歸。PNG 放 `docs/print_baseline/`（未入庫、用完即棄），
資料由 `tools/seed_print_baseline.py` 以 `tools/fake_seed_data.py` 的全虛構人員與公文產生，
**完全不讀取正式 `dbfile.db`**。從專案根依序執行：

```powershell
python tools/seed_print_baseline.py tmp/print-baseline
python tools/print_baseline.py --db-dir tmp/print-baseline --save --force
python tools/print_baseline.py --db-dir tmp/print-baseline --check
```

- 輸出資料夾已有資料庫時 seed 會拒絕覆寫，請另選空的暫存資料夾。
- 只有 manifest、沒有 PNG 的乾淨 clone 也能直接 `--check`（雜湊比對不需要舊圖，
  只有要輸出差異圖時才建立資料夾）。
- 每次 run 使用獨立的暫存 `MPLCONFIGDIR`，避免全機共用的 matplotlib 字型快取讓
  同一份輸入產生不同結果（踩過：同機同資料連跑三次得到三種比對結果）。
- 換機器時應在新機重建基準當新起點，不要拿舊雜湊硬比（字型／matplotlib／Qt／PySide6／
  縮放任一變動，雜湊可能全滅）。

### 版本 pin 與人工核准

`requirements-dev.txt` 固定 **matplotlib 3.11.1**；2026-08-02 已在指定 Python 實際安裝該版、
重建現行 101 項 manifest 並重跑重現性驗證（連續三輪 `--check` 皆 101/101）。
這個 pin 是**重現已驗證環境、不是永久禁止升版**；升版須重建 manifest、三輪比對並重新人工目視。

⚠️ **雜湊全綠只證明前後一致，不證明圖面正確**：粗體全滅與垂直置中偏移兩次都是人眼抓到的，
op log 比對與雜湊比對當時全綠。重建候選一律須由維護者逐張目視確認後才視為基準，
offscreen 自動檢查不能替代這道人工核准。驗證網是否活著，用「故意改一個版面常數
（如 `TICKET_ROWS_PER_BAND`）後 `--check` 必須變紅」來確認。
