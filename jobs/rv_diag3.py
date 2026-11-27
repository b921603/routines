#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rv_diag3 — 字幕假說對照：殭屍 11 集（heal 組）的 lrc/subtitle method 全面盤點
＋Volf 現況。假說：face-maint 的 needAISubtitle=false 重貼殺了字幕任務→lrc 空→未顯示。"""
import os, re, sys, html
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

def log(m): print(f"[rv3] {m}", flush=True)

OB.login()
cid = OB.channel_id()
boxes = []
for pg in range(10):
    rr = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    boxes += re.split(r'<div class="dragBox">', rr.text or "")[1:]
log(f"listing {len(boxes)}")

HEAL_11 = ["Where Was God", "Jean Bethke", "Robert Coles", "Robert Pollack",
           "Khaled Abou El Fadl", "Parker Palmer", "Thomas Moore", "Mario Cuomo",
           "Peter J. Gomes", "Bruce Feiler", "Sharon Salzberg", "David Fox",
           "Anchee Min", "Genetic Duplication", "Religion and Violence"]
seen = set()
for b in boxes:
    tm = re.search(r'rl-title"[^>]*title="([^"]*)"', b)
    mid = re.search(r'media_id"[^>]*data="([^"]+)"', b)
    if not (tm and mid):
        continue
    title = html.unescape(tm.group(1))
    key = None
    for h in HEAL_11:
        if h.lower() in title.lower():
            key = h; break
    if key is None or mid.group(1) in seen:
        continue
    seen.add(mid.group(1))
    bm = re.search(r'<span class="badge[^"]*">([^<]*)</span>', re.sub(r"\s+", " ", b))
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid.group(1)}&itemType=0", timeout=45).text or ""
    info = FM.parse_edit_page(ep)
    sam = re.search(r'name="subtitle_upload_method"[^>]*value="([^"]*)"', ep)
    log(f"[{key[:24]:24}] badge={bm.group(1) if bm else '?':14} lrc={'✓' if (info.get('lrc') or '').strip() else '✗空'} method={sam.group(1) if sam else '?'} | {title[:40]}")
