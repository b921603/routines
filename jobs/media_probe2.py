#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""media_probe2 — dragBox 形狀比對＋edit 頁 script 區音訊 URL 獵蹤。"""
import re, sys, html
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[mp2] {m}", flush=True)

OB.login()
cid = OB.channel_id()
MIDS = {"0a12fb2f": "Volf基線", "4bbac3f3": "Zoloth疑壞", "717a3ade": "Evang正本疑壞"}
boxes = []
for pg in range(4):
    rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    boxes += re.split(r'<div class="dragBox">', rr.text or "")[1:]
for want, tag in MIDS.items():
    b = next((b for b in boxes if want in b), None)
    if b is None:
        log(f"{tag}: 清單找不到（隱形？）"); continue
    b1 = re.sub(r"\s+", " ", b)
    log(f"═══ {tag} dragBox ({len(b)}B) ═══")
    log(f"  {html.unescape(b1)[:520]}")
for want, tag in MIDS.items():
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={want}&itemType=0", timeout=45).text or ""
    urls = sorted(set(re.findall(r'["\']([^"\']*\.(?:mp3|m4a|aac)[^"\']*)["\']', ep)))
    log(f"── {tag} edit頁音訊URL {len(urls)} 條 ──")
    for u in urls[:4]:
        log(f"    {u[:110]}")
    jf = re.findall(r'(?:fileId|file_id|mediaFileId)\s*[:=]\s*["\']([^"\']{8,})["\']', ep)
    log(f"    fileId 形狀: {jf[:3]}")
