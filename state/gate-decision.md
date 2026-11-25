# Gate 決策過程 2026-11-25 14:59:42

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

## 3.2 LLM 節點明細（每節點 output＋請求模型＋伺服器回聲版本）

| 節點 | 請求模型 | server modelVersion | 結果 | 延遲 | output（節錄） |
|---|---|---|---|---|---|
| N1_screen | `gemini-3.5-flash-lite` | gemini-3.5-flash-lite | ✅ | 1440ms | {
  "shortlist": [1484511465, 256580326, 1612090432],
  "note": "排除日更與 |
| N2_deep | `gemini-3.5-flash-lite` | — | ❌ http503 | 1017ms |  |
| N2_deep | `gemini-3.5-flash-lite` | — | ❌ http503 | 853ms |  |
| N2_deep | `gemini-3.5-flash-lite` | — | ❌ http503 | 949ms |  |
| decision | `gemini-3.5-flash-lite` | — | ❌ http503 | 1367ms |  |
| decision | `gemini-3.5-flash-lite` | — | ❌ http503 | 859ms |  |
| model_probe | `gemini-4-argon` | — | ❌ http429 | 159ms |  |
| model_probe | `gemini-4-carbon` | — | ❌ http429 | 195ms |  |
| model_probe | `gemini-4-hydrogen` | — | ❌ http503 | 563ms |  |
| model_probe | `gemini-4-neon` | — | ❌ http429 | 120ms |  |
| model_probe | `gemini-3.8-flash` | — | ❌ http503 | 579ms |  |
| model_probe | `gemini-3.7-flash` | — | ❌ http503 | 428ms |  |
| model_probe | `gemini-3.6-flash` | — | ❌ http503 | 401ms |  |
| model_probe | `gemini-3.5-flash` | — | ❌ http503 | 390ms |  |
| model_probe | `gemini-3.5-flash-lite` | gemini-3.5-flash-lite | ✅ | 646ms | {"model": "gpt-4o", "ok": true} |
| decision | `gemini-3.5-flash-lite` | — | ❌ http503 | 1581ms |  |
| decision | `gemini-3.5-flash-lite` | — | ❌ http503 | 1252ms |  |
| model_probe | `gemini-4-argon` | — | ❌ http429 | 167ms |  |
| model_probe | `gemini-4-carbon` | — | ❌ http429 | 126ms |  |
| model_probe | `gemini-4-hydrogen` | — | ❌ http503 | 669ms |  |
| model_probe | `gemini-4-neon` | — | ❌ http429 | 155ms |  |
| model_probe | `gemini-3.8-flash` | — | ❌ http503 | 1133ms |  |
| model_probe | `gemini-3.7-flash` | — | ❌ http503 | 451ms |  |
| model_probe | `gemini-3.6-flash` | — | ❌ http429 | 90ms |  |
| model_probe | `gemini-3.5-flash` | — | ❌ http503 | 378ms |  |
| model_probe | `gemini-3.5-flash-lite` | gemini-3.5-flash-lite | ✅ | 1511ms | {
  "ok": true
  } |
| decision | `gemini-3.5-flash-lite` | — | ❌ http503 | 1256ms |  |
| decision | `gemini-3.5-flash-lite` | — | ❌ http503 | 1203ms |  |
| model_probe | `gemini-4-argon` | — | ❌ http429 | 115ms |  |
| model_probe | `gemini-4-carbon` | — | ❌ http429 | 154ms |  |
| model_probe | `gemini-4-hydrogen` | — | ❌ http503 | 733ms |  |
| model_probe | `gemini-4-neon` | — | ❌ http429 | 102ms |  |
| model_probe | `gemini-3.8-flash` | — | ❌ http503 | 380ms |  |
| model_probe | `gemini-3.7-flash` | — | ❌ http503 | 410ms |  |
| model_probe | `gemini-3.6-flash` | — | ❌ http503 | 508ms |  |
| model_probe | `gemini-3.5-flash` | — | ❌ http429 | 105ms |  |
| model_probe | `gemini-3.5-flash-lite` | — | ❌ http503 | 732ms |  |
| model_probe | `gemini-3.1-pro-preview` | — | ❌ http429 | 121ms |  |
| model_probe | `gemini-4-argon` | — | ❌ http429 | 168ms |  |
| model_probe | `gemini-4-carbon` | — | ❌ http429 | 156ms |  |
| model_probe | `gemini-4-hydrogen` | — | ❌ http503 | 353ms |  |
| model_probe | `gemini-4-neon` | — | ❌ http429 | 159ms |  |
| model_probe | `gemini-3.8-flash` | — | ❌ http503 | 395ms |  |
| model_probe | `gemini-3.7-flash` | — | ❌ http503 | 438ms |  |
| model_probe | `gemini-3.6-flash` | — | ❌ http503 | 387ms |  |
| model_probe | `gemini-3.5-flash` | — | ❌ http503 | 844ms |  |
| model_probe | `gemini-3.5-flash-lite` | — | ❌ http503 | 462ms |  |
| model_probe | `gemini-3.1-pro-preview` | — | ❌ http429 | 126ms |  |
| model_probe | `gemini-4-argon` | — | ❌ http429 | 161ms |  |
| model_probe | `gemini-4-carbon` | — | ❌ http429 | 188ms |  |
| model_probe | `gemini-4-hydrogen` | — | ❌ http503 | 441ms |  |
| model_probe | `gemini-4-neon` | — | ❌ http429 | 92ms |  |
| model_probe | `gemini-3.8-flash` | — | ❌ http429 | 96ms |  |
| model_probe | `gemini-3.7-flash` | — | ❌ http503 | 368ms |  |
| model_probe | `gemini-3.6-flash` | — | ❌ http503 | 771ms |  |
| model_probe | `gemini-3.5-flash` | — | ❌ http429 | 93ms |  |
| model_probe | `gemini-3.5-flash-lite` | gemini-3.5-flash-lite | ✅ | 697ms | {"ok": true} |

## 3.3 本輪提示詞（各節點實際發送的 prompt 節錄；全文在 gate-llm-trace.json）
### N1_screen（請求模型 `gemini-3.5-flash-lite`）

```
你是播客開坑管線的初篩節點。策展核心＝雋永的亮點（5 年後還值得聽）。
任務：挑出值得深評的 4-6 個（排除：時事耗品、與既有坑位語義重疊、純娛樂無學習價值）。
既有坑位語義：TFF＝英語學習主坑（起點錨定、劇集長壽命）；HTF＝失敗美學／情感共鳴（名人訪談）；Bulwark＝時事評論（日更、法律 major 風源）。用戶優先級：比賽展示第一、完成度債優先清償、維護預算保守。平台現實：歐路免費帳號每頻道資源上限小、上傳帶寬有限→新坑日更成本高，週更/長錄製節目優於日更（Bulwark 類時事坑除外，已有專線）。
候選：[{"id": 1484511465, "name": "Cautionary Tales with Tim Harford", "v2": 85.6, "perennial": 12, "learning": 13, "legal": "independent", "ep_wk": 1.1, "min": 38.7, "desc": ""}, {"id": 256580326, "name": "HistoryExtra podcast", "v2": 84.6, "perennial": 13, "learning": 15, "legal": "independent", "ep_wk": 4.2, "min": 40.2, "desc": ""}, {"id": 1704806594, "name": "Rosebud with Gyles Brandreth", "v2": 81.4, "perennial": 10, "learning": 9, "
```

### N2_deep（請求模型 `gemini-3.5-flash-lite`）

```
你是開坑管線的深評節點。對每個候選論證：學習價值（英語學習者獲得什麼）、雋永論證（5 年後為何還值得聽——必須引用 perennial 分與節目型態）、風險。按價值排序。
既有坑位語義：TFF＝英語學習主坑（起點錨定、劇集長壽命）；HTF＝失敗美學／情感共鳴（名人訪談）；Bulwark＝時事評論（日更、法律 major 風源）。用戶優先級：比賽展示第一、完成度債優先清償、維護預算保守。平台現實：歐路免費帳號每頻道資源上限小、上傳帶寬有限→新坑日更成本高，週更/長錄製節目優於日更（Bulwark 類時事坑除外，已有專線）。
候選：[{"id": 1484511465, "name": "Cautionary Tales with Tim Harford", "v2": 85.6, "perennial": 12, "learning": 13, "legal": "independent", "ep_wk": 1.1, "min": 38.7, "transcript": true, "desc": ""}, {"id": 256580326, "name": "HistoryExtra podcast", "v2": 84.6, "perennial": 13, "learning": 15, "legal": "independent", "ep_wk": 4.2, "min": 40.2, "transcript": false, "desc": ""}, {"id": 1612090432, "name": "Betwixt The Sheets: The History
```

### decision（請求模型 `gemini-3.5-flash-lite`）

```
你是播客搬運管線的開坑審核官。政策數字已由代碼驗證（WIP 上限/月預算/既有坑位補完=complete，可補完性制約）——你只在合格候選中挑選或建議觀望，

【策展核心＝雋永的亮點（用戶 2026-11-25，源於 Tools of Titans 初心）】
推薦前必須回答：『5 年後這檔還值得聽嗎？』
- perennial 維度（0-15）是硬證據：≥10 才推薦；<6 除非人類例外
- 時事/新聞/政治類：須證明珍珠層（恆久內容占比≥30%，如深度專家訪談）且提供語言浸潤價值，否則 recommend=0 並註明 reason
- 優先：心智/科學/歷史/哲學/意義/失敗與復原類
- 受眾是英語學習者：發音清晰度與敘事品質是加分項（評估不可及時標 unknown）無權放寬任何約束（政策否決權屬於代碼與人類）。
既有坑位語義：TFF＝英語學習主坑（起點錨定、劇集長壽命）；HTF＝失敗美學／情感共鳴（名人訪談）；Bulwark＝時事評論（日更、法律 major 風源）。用戶優先級：比賽展示第一、完成度債優先清償、維護預算保守。平台現實：歐路免費帳號每頻道資源上限小、上傳帶寬有限→新坑日更成本高，週更/長錄製節目優於日更（Bulwark 類時事坑除外，已有專線）。
現有坑位：[{"family": "tff", "mode": "backlog", "platform": 1925, "source": "engine", "completion": 1.001, "status": "complete", "official_total": 893, "official_av
```

### model_probe（請求模型 `gemini-4-argon`）

```
回覆 JSON：{"ok": true, "model": "你的型號"}
```


## 4. 近期核准日誌（autonomy=full；人類否決通道＝對話說「停更 <名>」）
（本月尚無核准）
