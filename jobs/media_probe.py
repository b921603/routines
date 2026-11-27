#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""media_probe — 壞媒體鑑識：Evangelicals 正本 / Zoloth / Volf 基線的 edit 頁音訊形狀。"""
import re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[mp] {m}", flush=True)

TARGETS = [
    ("Volf(健康基線)", "0a12fb2f-156d-49b9-8137-e4bd7ba25925"),
    ("Zoloth(疑壞)",   "4bbac3f3-6467-47f9-9011-468186ebb173"),
    ("Evang正本(疑壞)", "717a3ade-8bae-4f00-86fc-797789ec0a17"),
]
OB.login()
cid = OB.channel_id()
for tag, mid in TARGETS:
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid}&itemType=0", timeout=45).text or ""
    log(f"═══ {tag} mid={mid[:8]} page={len(ep)}B ═══")
    hits = 0
    for kw in ("<audio", ".mp3", "duration", "时长", "media_url", "mediaUrl", "playUrl",
               "source src", "data-fileid", "voiceDiv", "audioPlay"):
        for m in list(re.finditer(re.escape(kw), ep))[:1]:
            ctx = re.sub(r"\s+", " ", ep[max(0, m.start()-100):m.start()+150])
            log(f"  {kw!r}: …{ctx}…")
            hits += 1
    if not hits:
        log("  （音訊形狀零命中——疑似無媒體！）")
