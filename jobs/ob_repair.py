#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ob_repair — 壞媒體集刪除（11-27 驗屍結論：fileId 死亡→建檔無音訊→lrc 永空）。
Zoloth 4bbac3f3（平台 500「不存在音频」自認）＋Evangelicals 717a3ade（post 十連
「音频/视频是必须上传的」仍異步建檔 ×10，dedup 已刪 9）。刪後由下一班 drain
重傳新鮮副本（帳本 guid 同步移除——本地 git 另行 surgical edit）。"""
import json, re, sys, time
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[repair] {m}", flush=True)

TARGETS = ["4bbac3f3-6467-47f9-9011-468186ebb173",   # Zoloth
           "717a3ade-8bae-4f00-86fc-797789ec0a17"]   # Evangelicals 正本

OB.login()
cid = OB.channel_id()
for mid in TARGETS:
    r = OB.req("POST", f"{OB.BASE}/ting/DeletePriveteMedia",
               data=json.dumps({"mediaIds": [mid]}),
               headers={"Content-Type": "application/json"}, timeout=60)
    log(f"del {mid[:8]}: HTTP {r.status_code} {(r.text or '')[:120]}")
    time.sleep(3)
# 驗證：全清單掃描，兩 mid 皆應消失
gone = set()
for pg in range(24):
    rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    txt = rr.text or ""
    for mid in TARGETS:
        if mid in txt:
            gone.add(mid)
    if 'dragBox' not in txt:
        break
for mid in TARGETS:
    log(f"verify {mid[:8]}: {'✗ 仍在清單' if mid in gone else '✓ 已刪除'}")
if gone:
    sys.exit(1)
log("repair done")
