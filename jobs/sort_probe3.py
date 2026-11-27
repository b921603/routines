#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sort_probe3 — index 頁 inline script：reSortByChannel/dragSort 儲存邏輯全 dump。"""
import re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[sp3] {m}", flush=True)

OB.login()
cid = OB.channel_id()
idx = OB.req("GET", f"{OB.BASE}/ting/index?channelid={cid}", timeout=45).text or ""
inlines = re.findall(r"<script(?![^>]*src)[^>]*>(.*?)</script>", idx, re.S)
log(f"inline scripts {len(inlines)} 個")
blob = "\n".join(inlines)
log(f"共 {len(blob)}B")
for kw in ("reSortByChannel", "dragStart", "SaveSort", "saveSort", "SortMedia",
           "sortmedia", "UpdateSort", "mediaSort", "/ting/"):
    for m in list(re.finditer(re.escape(kw), blob))[:6]:
        seg = re.sub(r"\s+", " ", blob[max(0, m.start()-150):m.end()+420])
        log(f"═══ {kw} ═══")
        log(f"  …{seg}…")
