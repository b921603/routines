# Onboarding Kit SOP — AI 自動裁決新坑的標準流程（T-080）

> 2026-11-26 用戶裁定：gate 全權裁斷後，新節目搬運引擎**不得第三次複製貼上**。
> tfs_engine（894 集戰錘）＋ob_update（iter-1~8 除錯史）的模式已固化為
> `podcast/engine_kit.py`（機制正典）＋`podcast/covers.py`（封面 SOP）。
> 本文件＝work order 落地的檢查清單；每步機制由 kit 結構保證，不靠記憶。

## 1. 觸發鏈（自動）

```
gate 裁決網絡（N1→N4）核准
  → gate_autonomy=full：state/pit-work-order.json
      {itunes_id, name, channel_name, feed_url, genre, median_min, eps_week,
       approved_by, nodes, human_veto}
  → onboarding 引擎（T-080）消費 work order → 以下 checklist
```

人類否決通道（全程有效）：對話說「停更 <名>」→ 帳本凍結＋policies paused（Bulwark 先例）。

## 2. Checklist（每坑一輪，順序固定）

### A. ShowConfig（~15 欄，唯一的新代碼）

```python
cfg = ShowConfig(key="<short>", itunes_id=<id>, name="<名>",
                 feed_url="<https feed>", channel_names=["<名>", "<備選1>", "<備選2>"],
                 group_name="<分組名>",
                 description="<一句話定位>", seg_seconds=3600,
                 ai_sub_single=True, ai_sub_multi=False,
                 backfill_max=12, days_window=4, max_per_run=2,
                 channel_art="rss_or_generate", episode_art="when_available",
                 accent="#<主色>")
```

- `seg_seconds`：median_min>60 → 必分段（SEG 3600）
- `ai_sub_single/multi`：平台約束——分段（i/n）集一律拒字幕
- 排程參數對照吞吐數學：`986×~13MB ÷ (MAX×36/週)`

### B. 薄殼 runner（~10 行）

`podcast/show_<short>.py`：import engine_kit＋covers，跑 `kit.run_show(cfg)` 主循環。
**禁止**在本檔出現任何機制代碼（機制只在 kit——發現缺機制＝改 kit＋加 preflight 測試）。

### C. Workflow 例化（範本＝ob-backfill.yml）

- preflight step（**部署門檻**）＋backfill（MAX 環境變數）＋commit trail＋notify on failure
- concurrency guard（同款 group）＋schedule 錯峰（現有 tick 表見 Runbook）

### D. 封面政策（covers.py，端看頻道特性）

| 特性 | channel_art | episode_art |
|---|---|---|
| RSS 有頻道插畫 | `rss_only` | 任選 |
| RSS 無插畫／新獨立節目 | `rss_or_generate`（生成封面 accent=品牌色） | `when_available` |
| 封面極簡純音訊長節目 | `never` | `never` |
| per-episode 插畫豐富 | 任選 | `when_available`（URL-hash 快取防孤兒） |

孤兒防線：同封面（頻道級或 per-ep hash 命中）**永不重複上傳**。

### E. 註冊（三處，缺一即 SOP 未完成）

1. `dedup.yml` 的 `DEDUP_EXTRA_CIDS` += 新 cid（去重覆蓋）
2. `policies/policies.json` pits += `{"<key>": {"mode":"backlog","wip":1}}`（gate 補完前提）
3. `patrol.py` PIT_REPORTS += key（艦隊巡檢）

### F. 驗收（preflight 九測＋新坑測試全綠＋首枚上傳實證）

- dispatch 前本地 `python3 podcast/preflight.py` 全綠（紅燈禁發——11-26 違規記錄在案）
- 首輪 run：**首枚 slot claim≤15min**（UploadTingFile 健康訊號）＋帳本首條 mids
- 之後 dedup patrol 每小時掃新頻道；gate 補完條件自動納入新 pit

## 3. 模式清單（kit 內建，逐項對應來源教訓）

| # | 模式 | 來源教訓 |
|---|---|---|
| ① | UploadTingFile 兩步式 | iter-7：multipart 直砸 uploadprivatemedia＝500 風暴 |
| ② | AuthError＋mid-run relogin | 繼承審計 A：cookie 死→大規模重複 |
| ③ | GAP=2.4s 全局節流 | B：WAF 風險 |
| ④ | thumb 快取（run 級/hash 級） | C：逐集重傳＝浪費＋孤兒 |
| ⑤ | per-part ledger＋mids 入帳 | G：用戶裁定必須繼承 |
| ⑥ | 頻道＋分組冪等（缺綁才 POST） | F：分組重排事故 |
| ⑦ | 冪等掃描（guid∪標題，50 頁） | 頁深缺口 E |
| ⑧ | heal（頻道既有→帳本補記） | tfs norm(title) |
| ⑨ | zero-sync exit 1＋TOTAL FAIL ntfy | 11-25「success」掩蓋 0/12 |
| ⑩ | kill-safe 帳本＋每集增量 git commit | tfs git-as-queue |
| ⑪ | ntfy 分級（OK3/PARTIAL4/FAIL4） | 艦隊慣例 |
