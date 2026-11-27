#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sub_probe — edit 頁 HTML/JS 獵「字幕生成/重新處理」端點（唯讀）。"""
import os, re, sys
sys.path.insert(0, "podcast")
import ob_update as OB

def log(m): print(f"[sp] {m}", flush=True)

OB.login()
cid = OB.channel_id()
MID = "4bbac3f3-6467-47f9-9011-468186ebb173"
ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={MID}&itemType=0", timeout=45).text or ""
log(f"edit page {len(ep)}B")
for kw in ("字幕", "lrc", "Lrc", "subtitle", "Subtitle", "重新", "生成"):
    for m in list(re.finditer(re.escape(kw), ep))[:2]:
        ctx = re.sub(r"\s+", " ", ep[max(0, m.start()-140):m.start()+180])
        log(f"{kw!r}: …{ctx}…")
urls = sorted(set(re.findall(r'["\'](/(?:Ting|ting)/[A-Za-z]+[^"\']*)["\']', ep)))
log("── edit 頁內端點 ──")
for u in urls:
    log(f"    {u[:80]}")
