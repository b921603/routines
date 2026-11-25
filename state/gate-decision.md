# Gate 決策過程 2026-11-25 14:35:42

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
- HOLD：未進入決策層（先清坑位債＋patrol 連綠）

## 3.2 LLM 節點明細（每節點 output＋生成模型）

| 節點 | 模型 | 結果 | 延遲 | output（節錄） |
|---|---|---|---|---|
| N1_screen | `gemini-3.5-flash-lite` | ✅ | 4774ms | {"shortlist": [1484511465, 256580326, 1612090432], "note": "優先選擇高學習價值、 |
| N2_deep | `gemini-3.5-flash-lite` | ❌ http503 | 728ms |  |
| decision | `gemini-3.5-flash-lite` | ❌ http503 | 1518ms |  |
| decision | `gemini-3.5-flash-lite` | ❌ http503 | 1230ms |  |
| model_probe | `gemini-4-argon` | ❌ http429 | 171ms |  |
| model_probe | `gemini-4-carbon` | ❌ http429 | 147ms |  |
| model_probe | `gemini-4-hydrogen` | ❌ http503 | 520ms |  |
| model_probe | `gemini-4-neon` | ❌ http429 | 161ms |  |
| model_probe | `gemini-3.8-flash` | ❌ http503 | 490ms |  |
| model_probe | `gemini-3.7-flash` | ❌ http503 | 521ms |  |
| model_probe | `gemini-3.6-flash` | ❌ http503 | 837ms |  |
| model_probe | `gemini-3.5-flash` | ❌ http503 | 690ms |  |
| model_probe | `gemini-3.5-flash-lite` | ✅ | 8832ms | {"model": "gpt-4o", "ok": true} |
| decision | `gemini-3.5-flash-lite` | ❌ http503 | 1229ms |  |
| decision | `gemini-3.5-flash-lite` | ❌ http503 | 3795ms |  |
| model_probe | `gemini-4-argon` | ❌ http429 | 186ms |  |
| model_probe | `gemini-4-carbon` | ❌ http429 | 142ms |  |
| model_probe | `gemini-4-hydrogen` | ❌ http503 | 636ms |  |
| model_probe | `gemini-4-neon` | ❌ http429 | 143ms |  |
| model_probe | `gemini-3.8-flash` | ❌ http503 | 428ms |  |
| model_probe | `gemini-3.7-flash` | ❌ http503 | 1294ms |  |
| model_probe | `gemini-3.6-flash` | ❌ http429 | 174ms |  |
| model_probe | `gemini-3.5-flash` | ❌ http503 | 772ms |  |
| model_probe | `gemini-3.5-flash-lite` | ✅ | 963ms | {
  "model": "gpt-4o",
  "ok": true
} |
| decision | `gemini-3.5-flash-lite` | ❌ http503 | 895ms |  |
| decision | `gemini-3.5-flash-lite` | ❌ http503 | 880ms |  |
| model_probe | `gemini-4-argon` | ❌ http429 | 170ms |  |
| model_probe | `gemini-4-carbon` | ❌ http429 | 134ms |  |
| model_probe | `gemini-4-hydrogen` | ❌ http503 | 510ms |  |
| model_probe | `gemini-4-neon` | ❌ http429 | 131ms |  |
| model_probe | `gemini-3.8-flash` | ❌ http429 | 196ms |  |
| model_probe | `gemini-3.7-flash` | ❌ http503 | 493ms |  |
| model_probe | `gemini-3.6-flash` | ❌ http429 | 129ms |  |
| model_probe | `gemini-3.5-flash` | ❌ http503 | 802ms |  |
| model_probe | `gemini-3.5-flash-lite` | ✅ | 803ms | {
  "model": "gpt-4o",
  "ok": true
} |

## 4. 近期核准日誌（autonomy=full；人類否決通道＝對話說「停更 <名>」）
（本月尚無核准）
