#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sys, html
sys.path.insert(0, "podcast")
import ob_update as OB
import ob_face_maint as FM

def log(m): print(f"[rv] {m}", flush=True)

OB.login()
cid = OB.channel_id()
boxes = []
for pg in range(10):
    r = OB.req("GET", f"{OB.BASE}/ting/GetPrivateMedias?sortby=0&page={pg}&channelId={cid}", timeout=45)
    boxes += re.split(r'<div class="dragBox">', r.text or "")[1:]
log(f"listing {len(boxes)} boxes")

TARGETS = [
    ("Anchee Min With Krista", "改寫①（[Unedited] Mao→Turbulent）"),
    ("Surviving a Turbulent Era", "改寫②（Mao→Turbulent）"),
    ("Same-Sex Marriage", "改寫③（Gay→Same-Sex）"),
    ("Genetic Duplication", "改寫④（Cloning→Genetic）"),
    ("Spirit of Defiance", "對照組（正常）"),
    ("Religion and Violence", "Volf（資源處理中）"),
]
for key, tag in TARGETS:
    x = next((x for x in boxes if key.lower() in html.unescape(
        (re.search(r'rl-title"[^>]*title="([^"]*)"', x) or re.match(r"$^","")).group(1)).lower()
        if re.search(r'rl-title"', x)), None)
    if x is None:
        log(f"── [{tag}] {key!r} 不在清單")
        continue
    tm = re.search(r'rl-title"[^>]*title="([^"]*)"', x)
    mid = re.search(r'media_id"[^>]*data="([^"]+)"', x)
    title = html.unescape(tm.group(1))
    log(f"── [{tag}] {title[:56]}")
    ep = OB.req("GET", f"{OB.BASE}/Ting/upload?channelid={cid}&mediaid={mid.group(1)}&itemType=0", timeout=45).text or ""
    info = FM.parse_edit_page(ep)
    log(f"    title 欄位: {(info.get('title') or '')[:56]!r}")
    desc = (info.get("desc") or "")
    low = desc.lower()
    hits = [w for w in ("mao", "gay", "clon", "同姓", "克隆", "毛泽东") if w in low]
    log(f"    desc {len(desc)}B｜敏感詞殘留: {hits or '無'}")
    if hits:
        for w in hits:
            i = low.index(w)
            log(f"      …{desc[max(0,i-60):i+80]}…")
    # 審核狀態標記（表單外全文）
    flat = re.sub(r"\s+", " ", ep)
    for kw in ("未顯示", "審核", "审核", "狀態", "状态", "資源處理", "资源处理", "正在處理", "正在处理"):
        i = flat.find(kw)
        if i >= 0:
            log(f"    ★頁面含 {kw!r}: …{flat[max(0,i-100):i+140]}…")
    # 媒體資源處理狀態（Volf 用）：dragBox 的處理標記
    if "Volf" in tag:
        for kw in ("资源处理", "資源處理", "正在", "processing"):
            i = x.lower().find(kw.lower())
            if i >= 0:
                log(f"    ★dragBox 含 {kw!r}: …{re.sub(chr(92)+'s+',' ',x[max(0,i-120):i+160])}…")
