# 2026-07-22 pytest-qt Pilot 結果

## Runtime

- Python command: `C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest`
- Environment: `QT_QPA_PLATFORM=offscreen`（AI offscreen）；Windows 本機 Python，Python prefix 為空
- Runtime packages: PySide6 6.11.1、matplotlib 3.11.1、pytest 9.1.1、pytest-qt 4.5.0
- Minimal spike: `tests/test_pytest_qt_runtime.py` 與 `tests/test_reward_gui_pilot.py` 最終合跑為 `2 passed in 1.52s`

## Gate Evidence

- Single run: `tests/test_reward_gui_pilot.py::test_reward_lifecycle_pilot` 為 `1 passed in 1.34s`（process wall time 2.2983359 秒）
- Ten runs: `10/10` 通過，未剔除任何 run

| Run | Seconds |
|---:|---:|
| 1 | 2.2104025 |
| 2 | 2.3138298 |
| 3 | 2.3095677 |
| 4 | 2.3308221 |
| 5 | 2.3349116 |
| 6 | 2.3330484 |
| 7 | 2.2778285 |
| 8 | 2.2274926 |
| 9 | 2.3047309 |
| 10 | 2.2666031 |

- Slowest run: 2.3349116 秒（gate: <=120 秒）
- Total: 22.9092372 秒（gate: <=1200 秒）
- Residue: `none`；`reward-pilot.db`、`*.db-journal`、`*.db-wal`、`*.db-shm` 均未留在 repository
- Controlled 發文 mutation: 暫時把 `issue_button` 從 `btn_reward_issue` 改為 `btn_reward_issue_missing`；pytest 在 `tests/test_reward_gui_pilot.py:97` 以 `AssertionError: 發文: 找不到發文按鈕` 失敗（`1 failed in 1.69s`），位置在任何登錄／DB mutation 之前。精確還原後為 `1 passed in 1.60s`，且 `git diff --exit-code -- tests/test_reward_gui_pilot.py` exit 0
- Selector change locations: 4 個 selector 值皆只在單一 pilot 的 `SELECTORS` 各出現一次：`reward_tableWidget` 行 22、`btn_reward_submit` 行 24、`btn_reward_input` 行 29、`btn_reward_issue` 行 30
- Production seams: 0；未建立 driver，未修改 production selector abstraction
- UI-only wiring defect detection: controlled mutation 使實際 `findChild(QPushButton, ...)` 回傳 `None`，並在發文按鈕 assertion 紅燈；還原後相同 lifecycle 綠燈
- Full unittest baseline: `Ran 470 tests in 34.644s`，`FAILED (failures=1, errors=1, skipped=2)`；與既知基線相同，failure 僅 SVG compiled/source 的 CRLF 差異，error 僅缺少 `docs/Quick_Start.pdf`
- Final pytest: `2 passed in 1.52s`

## Decision

`擴充候選—等待使用者核准`

理由：10/10 通過，最慢與總耗時均大幅低於 gate；受控 UI selector 破壞能在 DB mutation 前被精確攔截；無 repository residue，也不需要 production seam。是否值得為其他 GUI 流程另立計畫，仍須由使用者依維護成本與覆蓋價值核准。

本文件不核准其餘五條 GUI 流程，也不核准 driver、版本調升、發布或 push。
