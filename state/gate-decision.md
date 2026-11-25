# Gate 決策過程 2026-11-25 14:26:47

**裁定：⌛ HOLD** ｜ 連綠 streak 0/7 ｜ WIP 3/4 ｜ 月預算 0/1

## 1. 坑位債務判定（補完前提）
- **tff**: ⌛ 未穩 — engine completion 1.001 （缺 0｜lag —）｜streak 0/7
- **htf**: ⌛ 未穩 — engine completion 1.0 （缺 0｜lag -0.1d）｜streak 0/7
- **bulwark**: ✅ steady — paused（用戶裁示 11-25）——不計入補完條件
- **ob**: ⌛ 未穩 — completion None（本地估算）｜streak 0/7

## 2. 合格候選（fresh＋非 major＋非 avoid＋活躍）Top5

| 節目 | v2 總分 | perennial | legal | 更新 | 時長中位 |
|---|---|---|---|---|---|
| Cautionary Tales with Tim Harford | 85.6 | 12 | independent | 1.1ep/週 | 38.7min |
| HistoryExtra podcast | 84.6 | 13 | independent | 4.2ep/週 | 40.2min |
| Rosebud with Gyles Brandreth | 81.4 | 10 | independent | 2.1ep/週 | 65.2min |
| The Bulwark Daily | 81.3 | 5 | independent | 5ep/週 | 58.7min |
| Betwixt The Sheets: The History of Sex, Scandal & Society | 80.6 | 13 | independent | 2ep/週 | 44.9min |

## 3. 決策
- 基座：`gemini-3.5-flash-lite` ｜ recommend：**1484511465** ｜ valid：True ｜ confidence：high ｜ autonomy：**full**
- ⚠ **DEMO 運行**：非裁決（HOLD／已決狀態下的網絡示範；無核准副作用，LLM 額度照計）
- 理由：Cautionary Tales with Tim Harford 符合雋永亮點原則，其 perennial 分數為 12（≥10 的硬證據），learning 分數 13，探討人類行為、決策與失敗歷史，完美契合心智與失敗修復類主題，且每週更新 cadence (1.1) 符合帶寬現實與 independent 法律風險要求。
- 風險：該節目每集平均時長約 38.7 分鐘，需注意上傳頻寬及逐字稿對齊與資源消耗。
- 完成態（done_when）：確認歐路免費帳號空間與上傳頻寬足夠承載每週約 38.7 分鐘的長錄製節目，並完成自動化管線對接。
- 證據引用：[降級 N1_empty] itunes_id: 1484511465, perennial: 12, learning: 13, cadence: 1.1, legal: independent, median_min: 38.7, transcript_tag: true

## 3.2 LLM 節點明細（每節點 output＋生成模型）

| 節點 | 模型 | 結果 | 延遲 | output（節錄） |
|---|---|---|---|---|
| model_probe | `gemini-4-argon` | ❌ http429 | 143ms |  |
| model_probe | `gemini-4-carbon` | ❌ http429 | 135ms |  |
| model_probe | `gemini-4-hydrogen` | ❌ http503 | 923ms |  |
| model_probe | `gemini-4-neon` | ❌ http429 | 113ms |  |
| model_probe | `gemini-3.8-flash` | ❌ http503 | 442ms |  |
| model_probe | `gemini-3.7-flash` | ❌ http503 | 415ms |  |
| model_probe | `gemini-3.6-flash` | ❌ http503 | 288ms |  |
| model_probe | `gemini-3.5-flash` | ❌ http503 | 511ms |  |
| model_probe | `gemini-3.5-flash-lite` | ✅ | 6101ms | {"model": "gpt-4o", "ok": true} |
| N1_screen | `gemini-3.5-flash-lite` | ✅ | 1040ms | {"recommend": 1, "reasons": "Filtered out redundant or high-frequency  |
| decision | `gemini-3.5-flash-lite` | ❌ http503 | 18307ms |  |
| decision | `gemini-3.5-flash-lite` | ❌ http503 | 5040ms |  |
| model_probe | `gemini-4-argon` | ❌ http429 | 127ms |  |
| model_probe | `gemini-4-carbon` | ❌ http429 | 195ms |  |
| model_probe | `gemini-4-hydrogen` | ❌ http503 | 534ms |  |
| model_probe | `gemini-4-neon` | ❌ http429 | 131ms |  |
| model_probe | `gemini-3.8-flash` | ❌ http503 | 1468ms |  |
| model_probe | `gemini-3.7-flash` | ❌ http503 | 544ms |  |
| model_probe | `gemini-3.6-flash` | ❌ http503 | 1066ms |  |
| model_probe | `gemini-3.5-flash` | ❌ http503 | 2782ms |  |
| model_probe | `gemini-3.5-flash-lite` | ✅ | 718ms | {"ok": true} |
| decision | `gemini-3.5-flash-lite` | ✅ | 1773ms | {
  "recommend": 1484511465,
  "reasons": "Cautionary Tales with Tim H |

## 4. 近期核准日誌（autonomy=full；人類否決通道＝對話說「停更 <名>」）
（本月尚無核准）
